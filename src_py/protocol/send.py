"""Client side of the LocalSend v2 protocol.

prepare-upload (metadata only) followed by concurrent binary uploads.
Uses only the standard library; HTTPS peers use ``ssl._create_unverified_context()``.
"""

import hashlib
import http.client
import json
import os
import ssl
import uuid as _uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

# LocalSend HTTPS 使用 mTLS（双向证书）：客户端连接对方时必须提供自己的证书。
_CLIENT_CERT_PATHS = None  # (cert_path, key_path)


def set_client_cert_paths(cert_path, key_path):
    """设置 HTTPS 客户端证书（LocalSend mTLS 需要，由 Protocol 启动时调用）。"""
    global _CLIENT_CERT_PATHS
    _CLIENT_CERT_PATHS = (cert_path, key_path)


MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".svg": "image/svg+xml",
}

VALID_DEVICE_TYPES = {"mobile", "desktop", "web", "headless", "server"}

PREPARE_UPLOAD_PATH = "/api/localsend/v2/prepare-upload"
UPLOAD_PATH = "/api/localsend/v2/upload"
REGISTER_PATH = "/api/localsend/v2/register"


def new_uuid():
    return str(_uuid.uuid4())


def guess_mime(file_name):
    ext = os.path.splitext(str(file_name or ""))[1].lower()
    return MIME_BY_EXT.get(ext, "application/octet-stream")


def sha256_file(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def to_wire_info(info):
    """Convert a snake_case public info dict to the camelCase wire object."""
    info = info or {}
    out = {
        "alias": info.get("alias") or "AirFloat",
        "version": info.get("version") or "2.0",
        "deviceType": info.get("device_type") or "desktop",
        "fingerprint": info.get("fingerprint") or "",
        "port": info.get("port") if isinstance(info.get("port"), int) else 53317,
        "protocol": info.get("protocol") if info.get("protocol") == "http" else "https",
        "download": bool(info.get("download", True)),
    }
    if info.get("device_model") is not None:
        out["deviceModel"] = info["device_model"]
    return out


def normalize_peer(obj, ip):
    """Convert a camelCase wire device object to a snake_case public peer."""
    obj = obj or {}
    peer = {
        "alias": obj.get("alias") or "Unknown",
        "version": obj.get("version") or "2.0",
        "device_type": obj.get("deviceType")
        if obj.get("deviceType") in VALID_DEVICE_TYPES
        else "desktop",
        "fingerprint": obj.get("fingerprint"),
        "port": obj.get("port") if isinstance(obj.get("port"), int) else 53317,
        "protocol": obj.get("protocol") if obj.get("protocol") == "http" else "https",
        "download": obj.get("download") is True,
        "ip": ip,
    }
    if obj.get("deviceModel") is not None:
        peer["device_model"] = obj["deviceModel"]
    return peer


def _connection(peer):
    host = peer.get("ip") or "127.0.0.1"
    port = peer.get("port") if isinstance(peer.get("port"), int) else 53317
    if peer.get("protocol") == "http":
        return http.client.HTTPConnection(host, port, timeout=30)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if _CLIENT_CERT_PATHS is not None:
        ctx.load_cert_chain(_CLIENT_CERT_PATHS[0], _CLIENT_CERT_PATHS[1])
    return http.client.HTTPSConnection(host, port, context=ctx, timeout=30)


def request(peer, method, req_path, body=None, headers=None):
    """Single HTTP(S) request; returns ``{"status": int, "body": bytes}``."""
    conn = _connection(peer)
    try:
        hdrs = dict(headers or {})
        data = body
        if data is not None:
            if isinstance(data, str):
                data = data.encode("utf-8")
            if not isinstance(data, (bytes, bytearray)) and not hasattr(data, "read"):
                data = bytes(data)
            if hasattr(data, "__len__"):
                hdrs.setdefault("content-length", str(len(data)))
        conn.request(method, req_path, body=data, headers=hdrs)
        resp = conn.getresponse()
        rbody = resp.read()
        return {"status": resp.status, "body": rbody}
    finally:
        try:
            conn.close()
        except Exception:
            pass


class _ProgressReader:
    """File-like reader that reports per-chunk upload progress."""

    def __init__(self, file_obj, file_name, total_bytes, on_progress):
        self._f = file_obj
        self.file_name = file_name
        self.total_bytes = total_bytes
        self.on_progress = on_progress
        self.sent = 0

    def read(self, n=-1):
        chunk = self._f.read(n)
        if chunk:
            self.sent += len(chunk)
            if self.on_progress is not None:
                try:
                    self.on_progress(
                        {
                            "file_name": self.file_name,
                            "sent_bytes": self.sent,
                            "total_bytes": self.total_bytes,
                        }
                    )
                except Exception:
                    pass
        return chunk

    def __len__(self):
        return self.total_bytes


def upload_file(peer, req_path, file_path, size, file_name, on_progress):
    conn = _connection(peer)
    try:
        with open(file_path, "rb") as f:
            body = _ProgressReader(f, file_name, size, on_progress)
            headers = {"content-length": str(size)}
            conn.request("POST", req_path, body=body, headers=headers)
            resp = conn.getresponse()
            resp.read()
            if resp.status not in (200, 204):
                raise RuntimeError("upload status %d" % resp.status)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _qs(value):
    return quote(str(value), safe="")


def send_files(peer, files, self_info, on_progress):
    """Blocking send: prepare-upload then concurrent uploads."""
    entries = []
    for f in files:
        path = f["path"]
        st = os.stat(path)
        file_name = f.get("file_name") or os.path.basename(path)
        mime = f.get("mime") or guess_mime(file_name)
        fid = new_uuid()
        sha = sha256_file(path)
        entries.append(
            {
                "id": fid,
                "file_name": file_name,
                "size": st.st_size,
                "mime": mime,
                "sha256": sha,
                "path": path,
            }
        )

    files_obj = {}
    for e in entries:
        files_obj[e["id"]] = {
            "id": e["id"],
            "fileName": e["file_name"],
            "size": e["size"],
            "fileType": e["mime"],
            "sha256": e["sha256"],
        }

    body = json.dumps({"info": to_wire_info(self_info), "files": files_obj}).encode("utf-8")
    resp = request(
        peer,
        "POST",
        PREPARE_UPLOAD_PATH,
        body=body,
        headers={"content-type": "application/json"},
    )

    if resp["status"] == 204:
        return
    if resp["status"] != 200:
        raise RuntimeError("prepare-upload status %d" % resp["status"])

    try:
        data = json.loads(resp["body"].decode("utf-8"))
    except Exception:
        raise RuntimeError("invalid prepare-upload response")

    session_id = data.get("sessionId")
    tokens = data.get("files") or {}

    def _upload_one(e):
        token = tokens.get(e["id"])
        if not token:
            raise RuntimeError("missing token for file %s" % e["id"])
        q = "%s?sessionId=%s&fileId=%s&token=%s" % (
            UPLOAD_PATH,
            _qs(session_id),
            _qs(e["id"]),
            _qs(token),
        )
        upload_file(peer, q, e["path"], e["size"], e["file_name"], on_progress)

    workers = max(1, min(len(entries), 8))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_upload_one, entries))
