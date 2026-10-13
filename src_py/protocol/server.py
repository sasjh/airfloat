"""Receive side of the LocalSend v2 protocol.

A ``http.server.ThreadingHTTPServer`` (optionally wrapped in TLS) serves
``register`` / ``prepare-upload`` / ``upload`` / ``cancel`` / ``info``.
"""

import json
import os
import re
import ssl
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .send import new_uuid, normalize_peer, to_wire_info

BASE = "/api/localsend/v2"

MAX_BODY_BYTES = 50 * 1024 * 1024
SESSION_TTL = 10 * 60  # seconds
SWEEP_INTERVAL = 60.0


def sanitize_file_name(name):
    cleaned = re.sub(r"[\\/\x00-\x1f]", "", str(name or ""))
    cleaned = re.sub(r"^\.+$", "", cleaned)
    return cleaned or "unnamed"


class ReceiveServer:
    def __init__(
        self,
        self_info,
        tls_cert,
        cache_dir,
        get_receive_mode,
        is_trusted,
        on_received,
        peer_store,
        port,
    ):
        self.self_info = self_info
        self.tls_cert = tls_cert  # cert dict or None
        self.cache_dir = cache_dir
        self.get_receive_mode = get_receive_mode
        self.is_trusted = is_trusted
        self.on_received = on_received
        self.peer_store = peer_store
        self.port = port

        self.server = None
        self.sessions = {}
        self.reserved_paths = set()
        self._lock = threading.Lock()
        self._tls_temp_paths = []
        self._sweep_thread = None
        self._sweep_stop = threading.Event()

    # ---- lifecycle -----------------------------------------------------

    def start(self):
        os.makedirs(self.cache_dir, exist_ok=True)

        tls_context = None
        if self.tls_cert is not None:
            tls_context = self._build_tls_context(self.tls_cert)

        parent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                parent._handle(self, "GET")

            def do_POST(self):
                parent._handle(self, "POST")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        server.daemon_threads = True
        if tls_context is not None:
            server.socket = tls_context.wrap_socket(server.socket, server_side=True)
        self.server = server

        threading.Thread(target=server.serve_forever, daemon=True, name="receive-server").start()

        self._sweep_stop.clear()
        self._sweep_thread = threading.Thread(
            target=self._sweep_loop, daemon=True, name="session-sweep"
        )
        self._sweep_thread.start()

    def stop(self):
        self._sweep_stop.set()
        srv = self.server
        self.server = None
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass
            try:
                srv.server_close()
            except Exception:
                pass
        for p in self._tls_temp_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        self._tls_temp_paths = []

    def _build_tls_context(self, cert_obj):
        os.makedirs(self.cache_dir, exist_ok=True)
        fd_cert, cert_path = tempfile.mkstemp(suffix=".pem", prefix="airfloat-cert-", dir=self.cache_dir)
        fd_key, key_path = tempfile.mkstemp(suffix=".pem", prefix="airfloat-key-", dir=self.cache_dir)
        with os.fdopen(fd_cert, "w") as f:
            f.write(cert_obj["pem"])
        with os.fdopen(fd_key, "w") as f:
            f.write(cert_obj["key"])
        self._tls_temp_paths.extend([cert_path, key_path])
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        return ctx

    def _sweep_loop(self):
        while not self._sweep_stop.wait(SWEEP_INTERVAL):
            now = time.time()
            with self._lock:
                for sid in [s for s, v in self.sessions.items() if now - v["created_at"] > SESSION_TTL]:
                    self.sessions.pop(sid, None)

    # ---- routing -------------------------------------------------------

    def _handle(self, handler, method):
        try:
            split = urlsplit(handler.path)
            path = split.path
            qs = parse_qs(split.query)
        except Exception:
            self._json(handler, 400, {})
            return

        if path == BASE + "/info" and method == "GET":
            self._json(handler, 200, to_wire_info(self.self_info()))
            return

        if path == BASE + "/register" and method == "POST":
            self._register(handler)
            return

        if path == BASE + "/prepare-upload" and method == "POST":
            self._prepare_upload(handler)
            return

        if path == BASE + "/upload" and method == "POST":
            self._upload(handler, qs)
            return

        if path == BASE + "/cancel" and method == "POST":
            session_id = qs.get("sessionId", [None])[0]
            if session_id:
                with self._lock:
                    self.sessions.pop(session_id, None)
            handler.send_response(200)
            handler.send_header("content-length", "0")
            handler.end_headers()
            return

        handler.send_response(404)
        handler.send_header("content-length", "0")
        handler.end_headers()

    def _register(self, handler):
        body = self._read_body(handler)
        if body is None:
            return self._json(handler, 400, {})
        obj = self._parse_json(body)
        if isinstance(obj, dict) and obj.get("fingerprint"):
            self.peer_store.upsert(normalize_peer(obj, self._remote_ip(handler)))
        self._json(handler, 200, to_wire_info(self.self_info()))

    def _prepare_upload(self, handler):
        body = self._read_body(handler)
        if body is None:
            return self._json(handler, 400, {})
        obj = self._parse_json(body)
        if not isinstance(obj, dict) or not isinstance(obj.get("files"), dict):
            return self._json(handler, 400, {})

        mode = self.get_receive_mode()
        if mode == "off":
            return self._json(handler, 403, {})

        info = obj.get("info") or {}
        if isinstance(info, dict) and info.get("fingerprint"):
            self.peer_store.upsert(normalize_peer(info, self._remote_ip(handler)))

        if mode == "contacts":
            if not info.get("fingerprint") or not self.is_trusted(info.get("fingerprint")):
                return self._json(handler, 403, {})

        file_ids = list(obj["files"].keys())
        if not file_ids:
            handler.send_response(204)
            handler.send_header("content-length", "0")
            handler.end_headers()
            return

        session_id = new_uuid()
        files = {}
        for fid in file_ids:
            f = obj["files"][fid] or {}
            files[fid] = {
                "id": fid,
                "file_name": sanitize_file_name(f.get("fileName") or fid),
                "size": f.get("size") if isinstance(f.get("size"), int) else 0,
                "mime": f.get("fileType") or "application/octet-stream",
                "sha256": f.get("sha256"),
                "token": new_uuid(),
            }
        with self._lock:
            self.sessions[session_id] = {
                "session_id": session_id,
                "files": files,
                "from": info,
                "created_at": time.time(),
            }

        resp_files = {fid: files[fid]["token"] for fid in files}
        self._json(handler, 200, {"sessionId": session_id, "files": resp_files})

    def _upload(self, handler, qs):
        session_id = qs.get("sessionId", [None])[0]
        file_id = qs.get("fileId", [None])[0]
        token = qs.get("token", [None])[0]
        if not session_id or not file_id or not token:
            return self._json(handler, 400, {})

        with self._lock:
            session = self.sessions.get(session_id)
            f = session["files"].get(file_id) if session else None
        if session is None or f is None or f["token"] != token:
            return self._json(handler, 403, {})

        dest = self._unique_path(f["file_name"])
        try:
            self._write_upload(handler, dest)
        except Exception:
            with self._lock:
                self.reserved_paths.discard(dest)
            return self._json(handler, 500, {})
        finally:
            with self._lock:
                self.reserved_paths.discard(dest)

        f["done"] = True
        item = {
            "id": f["id"],
            "file_name": f["file_name"],
            "file_path": dest,
            "size": f["size"],
            "mime": f["mime"],
            "sha256": f.get("sha256"),
            "from_alias": session["from"].get("alias") if session["from"] else None,
            "from_fingerprint": session["from"].get("fingerprint") if session["from"] else None,
        }
        # Run in the request worker thread (already background); do it before
        # responding so a completed send() guarantees on_received has fired.
        try:
            self.on_received(item)
        except Exception:
            pass

        handler.send_response(200)
        handler.send_header("content-length", "0")
        handler.end_headers()

    def _write_upload(self, handler, dest):
        body = self._read_body(handler)
        if body is None:
            raise ValueError("request body exceeds limit")
        with open(dest, "wb") as out:
            out.write(body)

    def _unique_path(self, file_name):
        base = sanitize_file_name(file_name)
        stem, ext = os.path.splitext(base)
        candidate = os.path.join(self.cache_dir, base)
        n = 1
        with self._lock:
            while os.path.exists(candidate) or candidate in self.reserved_paths:
                candidate = os.path.join(self.cache_dir, "%s (%d)%s" % (stem, n, ext))
                n += 1
            self.reserved_paths.add(candidate)
        return candidate

    # ---- helpers -------------------------------------------------------

    def _remote_ip(self, handler):
        addr = handler.client_address[0] if handler.client_address else ""
        return str(addr).replace("::ffff:", "")

    def _read_body(self, handler):
        """读取请求体，兼容 Content-Length 与 chunked 两种传输编码。"""
        te = (handler.headers.get("transfer-encoding") or "").lower()
        if "chunked" in te:
            return self._read_chunked_body(handler)
        raw = handler.headers.get("content-length") or "0"
        try:
            length = int(raw)
        except ValueError:
            length = 0
        if length <= 0:
            return b""
        if length > MAX_BODY_BYTES:
            return None
        return handler.rfile.read(length)

    def _read_chunked_body(self, handler):
        data = bytearray()
        while True:
            line = handler.rfile.readline()
            size_str = line.split(b";")[0].strip()
            try:
                size = int(size_str, 16)
            except (ValueError, TypeError):
                break
            if size == 0:
                handler.rfile.readline()
                break
            if len(data) + size > MAX_BODY_BYTES:
                return None
            data.extend(handler.rfile.read(size))
            handler.rfile.read(2)
        return bytes(data)

    def _parse_json(self, body):
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return None

    def _json(self, handler, status, obj):
        body = json.dumps(obj).encode("utf-8")
        handler.send_response(status)
        handler.send_header("content-type", "application/json")
        handler.send_header("content-length", str(len(body)))
        handler.end_headers()
        try:
            handler.wfile.write(body)
        except Exception:
            pass
