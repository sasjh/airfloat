# AirFloat Python 版并行开发契约（原生 GUI，替代 Electron）

> 原因：本机 AMD 锐龙 9 9955HX 上 Electron/Chromium 系统性崩溃（0xc0000005），但原生 GUI（Qt/Tkinter）正常。
> 改用 **Python + PySide6（Qt）** 重写。协议逻辑与 Node 版完全一致（LocalSend v2），界面按 docs/03。

## 0. 目录（互斥写范围）

- `src_py/protocol/` —— 纯 Python 协议（LocalSend v2），不依赖 Qt。所有者：协议协作者。
- `src_py/ui/` —— PySide6 界面。所有者：UI 协作者。
- `src_py/main.py` —— 入口，把协议和 UI 接起来。所有者：Lead。
- 参考：`docs/06-协议参考-LocalSend-v2.md`（协议）、`docs/03-UI设计规范.md`（界面）、`src/protocol/*.js`（Node 版协议逻辑，可移植）。

## 1. 协议公开 API（src_py/protocol/__init__.py 导出）

```python
class Protocol:
    def __init__(self, config: dict):
        # config 键：
        #   alias: str, device_type: str='desktop', version: str='2.0',
        #   port: int=53317, protocol: str='https', download: bool=True,
        #   cache_dir: str,
        #   get_receive_mode: callable()->'everyone'|'contacts'|'off',
        #   is_trusted: callable(fingerprint:str)->bool,
        #   on_peer: callable(peer:dict), on_peer_lost: callable(fingerprint:str),
        #   on_received: callable(item:dict), on_progress: callable(ev:dict)
    def start(self): ...      # 启动 HTTPS 服务器 + UDP 组播发现（后台线程，非阻塞）
    def stop(self): ...
    def get_self(self) -> dict: ...   # {alias,version,device_type,fingerprint,port,protocol,download}
    def get_peers(self) -> list: ...  # [peer,...] 按 fingerprint 去重、排除自身
    def send(self, peer: dict, files: list): ...  # files=[{"path":str,"file_name"?,"mime"?}] 阻塞式，完成后返回
```

## 2. 协议要点（实现 LocalSend v2，同 Node 版）

- 发现：UDP 组播 `224.0.0.167:53317`，启动广播 `announce:true`；收到 `announce:true` 用 `POST /api/localsend/v2/register` 回复。
- 指纹：HTTPS 模式 = 自签证书 DER 的 SHA-256(hex)；HTTP 模式 = 随机字符串。用 `cryptography` 生成 RSA2048 自签证书。
- 接收端点：`register`(POST)、`prepare-upload`(POST, 按 get_receive_mode 决定 200/403/204)、`upload`(POST, 写 cache_dir 自动改名)、`cancel`(POST)、`info`(GET)。
- 发送：先 POST 对方 `/prepare-upload` 拿 sessionId+token，再并发 POST `/upload`（HTTPS 时 `ssl._create_unverified_context()`）。
- 服务器用 `http.server.ThreadingHTTPServer` + `ssl` 包装；发送用 `http.client` 或 `urllib`。
- 回调在后台线程触发，不阻塞。

## 3. 数据形状

```python
# peer = {alias, version, device_model?, device_type?, fingerprint, port, protocol, download?, ip}
# item(收到) = {id, file_name, file_path, size, mime, sha256?, from_alias, from_fingerprint}
# device(给UI) = {alias, fingerprint, device_type, ip}
# progress ev = {file_name, sent_bytes, total_bytes}
```

## 4. UI 要求（PySide6，按 docs/03）

- 无边框小窗约 360×500，淡蓝主题（背景 #EAF3FB、主蓝 #4A90D9、白卡片）。
- 左窄栏：①「隔空投送」开关 ②「可接收对象」三选（所有人/仅联系人/接收关闭）③「附近设备」列表点选。
- 右宽栏「图片口」：缩略图网格 + 空态提示；**支持拖入图片文件发送**（dropEvent）+ **拖出缩略图到微信/QQ/文件夹**（QDrag，`QMimeData().setUrls`）。
- 底部：进度条 + 状态提示 + 已接收数量。
- 通过 Qt 信号把协议回调 marshal 到主线程。

## 5. 自测要求

- 协议协作者写 `src_py/protocol/test_protocol.py`：两个 Protocol 实例（protocol='http'，不同端口，127.0.0.1）互发临时文件，断言 on_received 字节一致，打印 PASS/FAIL 并 exit(0/1)。
