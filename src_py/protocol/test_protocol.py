"""Self-test for the pure-Python LocalSend v2 protocol.

Two ``Protocol`` instances (protocol='http', different ports, 127.0.0.1)
exchange a temporary file in both directions and assert that the received
bytes are identical. Prints PASS/FAIL and exits 0/1.
"""

import os
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))          # .../src_py/protocol
SRC_PY = os.path.dirname(HERE)                             # .../src_py
ROOT = os.path.dirname(SRC_PY)                             # workspace root
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src_py.protocol import Protocol  # noqa: E402


def _make(alias, port, cache_dir, received, event, progress):
    return Protocol(
        {
            "alias": alias,
            "device_type": "desktop",
            "version": "2.0",
            "port": port,
            "protocol": "http",
            "download": True,
            "cache_dir": cache_dir,
            "get_receive_mode": lambda: "everyone",
            "is_trusted": lambda fp: True,
            "on_peer": lambda p: None,
            "on_peer_lost": lambda fp: None,
            "on_received": lambda item: (received.append(item), event.set()),
            "on_progress": progress,
        }
    )


def main():
    tmp = tempfile.mkdtemp(prefix="airfloat-test-")
    try:
        a_dir = os.path.join(tmp, "a-cache")
        b_dir = os.path.join(tmp, "b-cache")

        # A random file (>1 MiB) so streaming/progress paths are exercised.
        src_path = os.path.join(tmp, "source.bin")
        payload = os.urandom(1024 * 1024 + 123)
        with open(src_path, "wb") as f:
            f.write(payload)

        received_a = []
        received_b = []
        ev_a = threading.Event()
        ev_b = threading.Event()
        progress_events = []
        progress = lambda ev: progress_events.append(ev)  # noqa: E731

        a = _make("A", 53320, a_dir, received_a, ev_a, progress)
        b = _make("B", 53321, b_dir, received_b, ev_b, progress)

        a.start()
        b.start()

        try:
            # A -> B
            peer_b = b.get_self()
            peer = dict(peer_b)
            peer["ip"] = "127.0.0.1"
            a.send(peer, [{"path": src_path}])

            assert ev_b.wait(10), "B did not receive A's file"
            item = received_b[0]
            with open(item["file_path"], "rb") as f:
                got = f.read()
            assert got == payload, "A->B bytes mismatch"
            assert item["file_name"] == "source.bin", "unexpected file_name"
            assert item["from_alias"] == "A", "unexpected from_alias"

            # B -> A
            peer_a = a.get_self()
            peer = dict(peer_a)
            peer["ip"] = "127.0.0.1"
            b.send(peer, [{"path": src_path}])

            assert ev_a.wait(10), "A did not receive B's file"
            item = received_a[0]
            with open(item["file_path"], "rb") as f:
                got = f.read()
            assert got == payload, "B->A bytes mismatch"

            # self/peers sanity
            s = a.get_self()
            assert s["fingerprint"] and s["protocol"] == "http" and s["port"] == 53320
        finally:
            a.stop()
            b.stop()

        print("PASS")
        return 0
    except Exception as exc:
        import traceback

        traceback.print_exc()
        print("FAIL: %s" % exc)
        return 1
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
