"""UDP multicast discovery for LocalSend v2: group 224.0.0.167:53317."""

import json
import socket
import struct
import threading
import time

from .send import REGISTER_PATH, normalize_peer, request, to_wire_info

MULTICAST_ADDR = "224.0.0.167"
MULTICAST_PORT = 53317

BROADCAST_INTERVAL = 30.0


class Discovery:
    """Best-effort discovery: broadcast announce, reply to remote announces.

    Never raises out of ``start``; if the multicast socket cannot be set up
    discovery simply stays disabled (server/send still work).
    """

    def __init__(self, self_info, fingerprint, peer_store):
        self.self_info = self_info
        self.fingerprint = fingerprint
        self.peer_store = peer_store
        self.sock = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self.sock is not None or self._thread is not None:
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            except OSError:
                pass
            sock.bind(("", MULTICAST_PORT))
            mreq = struct.pack("4sL", socket.inet_aton(MULTICAST_ADDR), socket.INADDR_ANY)
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError:
                pass
            sock.settimeout(1.0)
        except OSError:
            return  # discovery unavailable, not fatal

        self.sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="discovery")
        self._thread.start()

    def _run(self):
        self._broadcast()
        last_broadcast = time.monotonic()
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
                self._on_message(data, addr)
            except socket.timeout:
                pass
            except OSError:
                break
            if time.monotonic() - last_broadcast >= BROADCAST_INTERVAL:
                self._broadcast()
                last_broadcast = time.monotonic()

    def _broadcast(self):
        if self.sock is None:
            return
        info = dict(to_wire_info(self.self_info()))
        info["announce"] = True
        msg = json.dumps(info).encode("utf-8")
        try:
            self.sock.sendto(msg, (MULTICAST_ADDR, MULTICAST_PORT))
        except OSError:
            pass

    def _on_message(self, data, addr):
        try:
            obj = json.loads(data.decode("utf-8"))
        except Exception:
            return
        if not isinstance(obj, dict) or not obj.get("fingerprint"):
            return
        if obj["fingerprint"] == self.fingerprint:
            return
        peer = normalize_peer(obj, addr[0])
        self.peer_store.upsert(peer)
        if obj.get("announce") is True:
            threading.Thread(
                target=self._reply_register, args=(peer,), daemon=True, name="reply-register"
            ).start()

    def _reply_register(self, peer):
        try:
            body = json.dumps(to_wire_info(self.self_info())).encode("utf-8")
            resp = request(
                peer,
                "POST",
                REGISTER_PATH,
                body=body,
                headers={"content-type": "application/json"},
            )
            if resp["status"] == 200:
                obj = {}
                try:
                    obj = json.loads(resp["body"].decode("utf-8"))
                except Exception:
                    obj = {}
                if obj.get("fingerprint"):
                    self.peer_store.upsert(normalize_peer(obj, peer["ip"]))
        except Exception:
            pass

    def stop(self):
        self._stop.set()
        sock = self.sock
        self.sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
