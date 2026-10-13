#!/usr/bin/env python3
"""AirFloat 入口：PySide6 浮窗 + LocalSend v2 协议。"""
import sys
import os

# PyInstaller --windowed 模式下 sys.stdout/stderr 为 None，任何 print/写日志都会崩
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# 单实例保护：防止双击启动多个窗口互相冲突
import ctypes
_kernel32 = ctypes.windll.kernel32
_kernel32.CreateMutexW(None, False, "AirFloat_SingleInstance_Mutex")
if _kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    sys.exit(0)

import json
import socket
import threading

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from protocol import Protocol
from ui.main_window import AirFloatWindow

# 数据目录：放在程序/脚本旁边。原因：工作区 E:\jason de app 被标记为"低完整性级别"，
# 从这里启动的 exe 继承低完整性，无法写 %APPDATA%（普通完整性）；放旁边则是低写低，无权限问题。
_BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
APP_DIR = os.path.join(_BASE_DIR, 'AirFloat数据')
CONFIG_PATH = os.path.join(APP_DIR, 'config.json')
CACHE_DIR = os.path.join(APP_DIR, 'cache')

DEFAULT_CONFIG = {'alias': '我的电脑', 'enabled': True, 'receive_mode': 'everyone', 'whitelist': []}


def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **cfg}
    except Exception:
        return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('223.5.5.5', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


class Bridge(QObject):
    """把协议后台线程的回调 marshal 到 Qt 主线程。"""
    peer_signal = Signal(object)
    peer_lost_signal = Signal(str)
    received_signal = Signal(object)
    progress_signal = Signal(object)


def main():
    cfg = load_config()
    os.makedirs(CACHE_DIR, exist_ok=True)

    app = QApplication(sys.argv)
    bridge = Bridge()
    peers = {}

    win = AirFloatWindow()
    win.on_state({
        'alias': cfg['alias'],
        'enabled': cfg['enabled'],
        'receive_mode': cfg['receive_mode'],
        'ip': local_ip(),
    })

    def refresh_devices():
        win.on_devices([{
            'alias': x['alias'],
            'fingerprint': x['fingerprint'],
            'device_type': x.get('device_type'),
            'ip': x.get('ip'),
        } for x in peers.values()])

    protocol = Protocol({
        'alias': cfg['alias'],
        'device_type': 'desktop',
        'version': '2.0',
        'port': 53317,
        'protocol': 'https',
        'download': True,
        'cache_dir': CACHE_DIR,
        'get_receive_mode': lambda: cfg['receive_mode'] if cfg['enabled'] else 'off',
        'is_trusted': lambda fp: fp in cfg['whitelist'],
        'on_peer': lambda p: bridge.peer_signal.emit(p),
        'on_peer_lost': lambda fp: bridge.peer_lost_signal.emit(fp),
        'on_received': lambda item: bridge.received_signal.emit(item),
        'on_progress': lambda ev: bridge.progress_signal.emit(ev),
    })

    bridge.peer_signal.connect(lambda p: (peers.__setitem__(p['fingerprint'], p), refresh_devices()))
    bridge.peer_lost_signal.connect(lambda fp: (peers.pop(fp, None), refresh_devices()))
    bridge.received_signal.connect(win.on_received_item)
    bridge.progress_signal.connect(win.on_progress)

    win.enabled_changed.connect(lambda v: (cfg.__setitem__('enabled', bool(v)), save_config(cfg)))
    win.receive_mode_changed.connect(lambda m: (cfg.__setitem__('receive_mode', m), save_config(cfg)))
    win.reveal_cache_requested.connect(lambda: os.startfile(CACHE_DIR) if os.name == 'nt' else None)

    def send_files(paths):
        fp = win._selected_fingerprint
        peer = peers.get(fp)
        if not peer:
            win.show_toast('请先在左侧选择要发送的设备', 'error')
            return

        def worker():
            try:
                protocol.send(peer, [{'path': p} for p in paths])
                win.show_toast('已发送 ' + str(len(paths)) + ' 张', 'success')
            except Exception as e:
                win.show_toast('发送失败: ' + str(e), 'error')

        threading.Thread(target=worker, daemon=True).start()

    win.send_files_requested.connect(lambda paths: send_files(paths))
    win.send_pending_requested.connect(lambda paths: send_files(paths))
    win._airfloat_send_handler = send_files

    try:
        protocol.start()
    except Exception as e:
        print('协议启动失败:', e)

    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        _log_path = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'airfloat', 'crash.log')
        try:
            os.makedirs(os.path.dirname(_log_path), exist_ok=True)
            with open(_log_path, 'w', encoding='utf-8') as _f:
                _f.write(traceback.format_exc())
        except Exception:
            pass
        raise
