"""AirFloat Python protocol module (LocalSend v2), pure Python, no Qt.

Public API: ``Protocol``.
"""

import os
import tempfile
import threading
import time

from . import cert
from .discovery import Discovery
from .send import send_files, set_client_cert_paths
from .server import ReceiveServer

__all__ = ["Protocol"]


class _PeerStore:
    """Peer registry: dedupe by fingerprint, exclude self, stale sweep."""

    _FIELDS = (
        "alias",
        "version",
        "device_type",
        "device_model",
        "port",
        "protocol",
        "download",
        "ip",
    )

    def __init__(self, self_fingerprint, on_peer, on_peer_lost, stale_ms=300000):
        self.self_fingerprint = self_fingerprint
        self.on_peer = on_peer or (lambda p: None)
        self.on_peer_lost = on_peer_lost or (lambda fp: None)
        self.stale_ms = stale_ms
        self._map = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def _to_public(self, p):
        out = {
            "alias": p.get("alias", "Unknown"),
            "version": p.get("version", "2.0"),
            "device_type": p.get("device_type", "desktop"),
            "fingerprint": p.get("fingerprint"),
            "port": p.get("port", 53317),
            "protocol": p.get("protocol", "https"),
            "download": bool(p.get("download", False)),
            "ip": p.get("ip"),
        }
        if p.get("device_model") is not None:
            out["device_model"] = p["device_model"]
        return out

    def upsert(self, peer):
        if not peer or not peer.get("fingerprint"):
            return
        if peer["fingerprint"] == self.self_fingerprint:
            return
        notify = None
        with self._lock:
            now = time.time()
            existing = self._map.get(peer["fingerprint"])
            if existing:
                changed = False
                for k in self._FIELDS:
                    if peer.get(k) is not None and peer.get(k) != existing.get(k):
                        existing[k] = peer[k]
                        changed = True
                existing["last_seen"] = now
                if changed:
                    notify = self._to_public(existing)
            else:
                p = dict(peer)
                p["last_seen"] = now
                self._map[p["fingerprint"]] = p
                notify = self._to_public(p)
        if notify is not None:
            try:
                self.on_peer(notify)
            except Exception:
                pass

    def get_peers(self):
        with self._lock:
            return [self._to_public(p) for p in self._map.values()]

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="peer-sweep")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(5.0):
            lost = []
            now = time.time()
            with self._lock:
                for fp, p in list(self._map.items()):
                    if now - p.get("last_seen", now) > self.stale_ms:
                        del self._map[fp]
                        lost.append(fp)
            for fp in lost:
                try:
                    self.on_peer_lost(fp)
                except Exception:
                    pass


class Protocol:
    """LocalSend v2 protocol instance (server + discovery + send)."""

    def __init__(self, config):
        config = config or {}

        self.alias = config.get("alias") or "AirFloat"
        self.version = config.get("version") or "2.0"
        self.device_type = config.get("device_type") or "desktop"
        self.port = config.get("port") if isinstance(config.get("port"), int) else 53317
        self.protocol = "http" if config.get("protocol") == "http" else "https"
        self.download = bool(config.get("download", True))
        self.device_model = config.get("device_model")

        self.cache_dir = config.get("cache_dir")
        if not self.cache_dir:
            self.cache_dir = os.path.join(tempfile.gettempdir(), "airfloat-cache")

        self.get_receive_mode = (
            config.get("get_receive_mode")
            if callable(config.get("get_receive_mode"))
            else (lambda: "everyone")
        )
        self.is_trusted = (
            config.get("is_trusted") if callable(config.get("is_trusted")) else (lambda fp: False)
        )
        self.on_peer = config.get("on_peer") if callable(config.get("on_peer")) else (lambda p: None)
        self.on_peer_lost = (
            config.get("on_peer_lost")
            if callable(config.get("on_peer_lost"))
            else (lambda fp: None)
        )
        self.on_received = (
            config.get("on_received")
            if callable(config.get("on_received"))
            else (lambda item: None)
        )
        self.on_progress = (
            config.get("on_progress")
            if callable(config.get("on_progress"))
            else (lambda ev: None)
        )

        if self.protocol == "https":
            c = cert.create_self_signed()
            self.fingerprint = c["fingerprint"]
            self._tls_cert = c
            # 写临时文件，供 HTTPS 客户端证书（LocalSend mTLS）使用。
            # 放在 cache_dir（程序旁边、低完整性可写），而非 %TEMP%（低完整性进程写不了）。
            os.makedirs(self.cache_dir, exist_ok=True)
            fd_c, self._cert_file = tempfile.mkstemp(suffix=".pem", prefix="airfloat-c-", dir=self.cache_dir)
            fd_k, self._key_file = tempfile.mkstemp(suffix=".pem", prefix="airfloat-k-", dir=self.cache_dir)
            with os.fdopen(fd_c, "w") as f:
                f.write(c["pem"])
            with os.fdopen(fd_k, "w") as f:
                f.write(c["key"])
            set_client_cert_paths(self._cert_file, self._key_file)
        else:
            self.fingerprint = cert.random_fingerprint()
            self._tls_cert = None

        self._self = {
            "alias": self.alias,
            "version": self.version,
            "device_type": self.device_type,
            "fingerprint": self.fingerprint,
            "port": self.port,
            "protocol": self.protocol,
            "download": self.download,
        }
        if self.device_model is not None:
            self._self["device_model"] = self.device_model

        self._peer_store = _PeerStore(self.fingerprint, self.on_peer, self.on_peer_lost)
        self._server = ReceiveServer(
            self_info=lambda: dict(self._self),
            tls_cert=self._tls_cert,
            cache_dir=self.cache_dir,
            get_receive_mode=self.get_receive_mode,
            is_trusted=self.is_trusted,
            on_received=self.on_received,
            peer_store=self._peer_store,
            port=self.port,
        )
        self._discovery = Discovery(
            self_info=lambda: dict(self._self),
            fingerprint=self.fingerprint,
            peer_store=self._peer_store,
        )

        self._started = False
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        try:
            self._server.start()
        except Exception:
            self._started = False
            raise
        self._discovery.start()
        self._peer_store.start()

    def stop(self):
        with self._lock:
            if not self._started:
                return
            self._started = False
        self._discovery.stop()
        self._peer_store.stop()
        self._server.stop()

    def get_self(self):
        return {
            "alias": self.alias,
            "version": self.version,
            "device_type": self.device_type,
            "fingerprint": self.fingerprint,
            "port": self.port,
            "protocol": self.protocol,
            "download": self.download,
        }

    def get_peers(self):
        return self._peer_store.get_peers()

    def send(self, peer, files):
        return send_files(peer, files, self._self, self.on_progress)
