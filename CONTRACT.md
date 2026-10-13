# AirFloat 并行开发契约

所有协作者（协议模块 / UI 模块 / 主进程）**写代码前先读本文件**，严格按这里的接口约定实现，禁止自行改变对外接口。

## 0. 项目定位

Windows 上的 Electron **小浮窗** App，实现 LocalSend v2 协议，与 iPhone 官方 LocalSend App 在同一 WiFi 下**互传图片**。淡蓝主题、iOS 设置页风格、Win+V 剪贴板那种小浮窗尺寸。

## 1. 目录与归属（互斥写范围，勿越界）

- `src/protocol/` —— **纯 Node.js，不得 `require('electron')`**。所有者：协议协作者。
- `src/renderer/` —— 纯 HTML/CSS/JS（渲染进程）。所有者：UI 协作者。
- `src/main/` —— Electron 主进程 + preload。所有者：Lead。
- 其他（`package.json`、`CONTRACT.md`、`README.md`）：Lead。

## 2. LocalSend v2 协议要点（协议协作者必须实现，已核对官方中文文档）

- **发现**：UDP 组播，组 `224.0.0.167`、端口 `53317`；广播设备信息 JSON；收到带 `announce:true` 的消息时，用 `POST /api/localsend/v2/register` 回复自身信息。
- **设备信息对象**：`{ alias, version:"2.0", deviceModel, deviceType, fingerprint, port, protocol, download, announce? }`
  - `deviceType` ∈ `mobile | desktop | web | headless | server`
  - `protocol` ∈ `https | http`
- **指纹 fingerprint**：HTTPS 模式 = 自签证书 **DER 的 SHA-256（hex）**；HTTP 模式 = 随机字符串。
- **接收端点**（我们当 HTTPS/HTTP 服务器）：
  - `POST /api/localsend/v2/register` → 返回自身设备信息
  - `POST /api/localsend/v2/prepare-upload` 入参 `{info, files:{id:{id,fileName,size,fileType,sha256,preview}}}` → 返回 `{sessionId, files:{id:token}}`；拒收返回 `403`
  - `POST /api/localsend/v2/upload?sessionId=&fileId=&token=` 二进制 body → 写文件
  - `POST /api/localsend/v2/cancel?sessionId=`
  - `GET  /api/localsend/v2/info` → 设备信息
- **发送**（我们当客户端，`rejectUnauthorized:false` 对接对方自签证书；若 peer.protocol==='http' 用 http）：
  - 先 `POST` 对方 `/prepare-upload` → 得 `sessionId` + `files{fileId:token}` → 并发 `POST` 对方 `/upload`（body=文件二进制）→ 完成。
- **错误码**：`204` 完成（无需传文件）、`400` 无效请求体、`403` 拒绝/无效令牌或 IP、`409` 被其他会话阻止、`500` 未知错误。

## 3. protocol 模块公开 API（src/protocol/index.js 导出）

```js
module.exports = { createProtocol };

/**
 * createProtocol(config) -> Promise<Api>
 * config:
 *   alias: string
 *   deviceType: 'desktop'
 *   version: '2.0'
 *   port: number            // 服务器端口，默认 53317
 *   protocol: 'https'|'http'// 默认 'https'
 *   download: boolean       // 默认 true
 *   cacheDir: string        // 接收文件保存目录（绝对路径）
 *   getReceiveMode(): 'everyone'|'contacts'|'off'
 *   isTrusted(fingerprint): boolean   // 'contacts' 白名单判定
 *   onPeer(peer): void
 *   onPeerLost(fingerprint): void
 *   onReceived(item): void
 *   onProgress(ev): void    // ev = { fileName, sentBytes, totalBytes }
 *
 * Api:
 *   start(): Promise<void>      // 启动服务器 + 组播发现 + 广播 announce
 *   stop(): Promise<void>
 *   getSelf(): { alias, fingerprint, port, protocol, download, deviceType, version }
 *   getPeers(): Peer[]
 *   send(peer, files): Promise<void>  // files = [{ path, fileName?, mime? }]
 */
```

- `send(peer, files)`：每个文件生成唯一 `fileId`（uuid）；`fileName` 默认 `path.basename`；`mime` 默认按扩展名推断（仅 image/*）；`size` 取 `fs.stat`。先 `prepare-upload`，再并发 `upload`，期间回调 `onProgress`，全部成功才 resolve，出错 reject。
- 发现：启动时向 `224.0.0.167:53317` 广播 `announce:true`；监听组播，收到 `announce:true` 的成员时 `POST /register` 并解析返回；`getPeers()` 按 fingerprint 去重、**排除自身**；peer 约 60s 未见触发 `onPeerLost`。
- 接收：`prepare-upload` 按 `getReceiveMode()` 决定：`off`→403；`everyone`→接受；`contacts`→`isTrusted(info.fingerprint)` 为真才接受，否则 403。`upload` 写文件到 `cacheDir`（重名自动改名），完成后 `onReceived(item)`。

## 4. 数据形状（所有模块共用）

```js
// Peer（协议模块产出）
{ alias, version, deviceModel?, deviceType?, fingerprint, port, protocol, download?, ip }

// ReceivedItem（协议模块产出，onReceived 参数）
{ id, fileName, filePath, size, mime, sha256?, fromAlias, fromFingerprint }

// Device（主进程转给 UI，只含 UI 需要的字段）
{ alias, fingerprint, deviceType, ip }

// State（主进程转给 UI）
{ enabled: boolean, receiveMode: 'everyone'|'contacts'|'off', alias: string, fingerprint: string, ip: string, port: number }
```

## 5. preload / renderer 契约（window.airfloat，由主进程通过 contextBridge 暴露）

```js
window.airfloat = {
  getState(): Promise<State>,
  setEnabled(enabled: boolean): Promise<void>,
  setReceiveMode(mode: 'everyone'|'contacts'|'off'): Promise<void>,
  getDevices(): Promise<Device[]>,
  sendFiles(peerFingerprint: string, paths: string[]): Promise<void>, // 发到指定设备
  dragOut(filePath: string): void,   // 触发系统级文件拖拽（拖给微信/QQ/文件夹）
  revealCache(): Promise<void>,
  onEvent(cb: (ev)=>void): () => void,  // 订阅事件，返回取消函数
};
```

事件（`onEvent` 回调收到的对象）：
```js
{ type:'devices', devices: Device[] }
{ type:'received', item: ReceivedItem }
{ type:'state', state: State }
{ type:'progress', ev: { fileName, sentBytes, totalBytes } }
```

## 6. UI 要求（UI 协作者实现，按用户原话）

- **淡蓝主色**（建议：背景 `#EAF3FB`，主蓝 `#4A90D9`，卡片白底），简洁直观。
- **小浮窗**：约 360×500（Win+V 那种小窗感）。
- **布局**：左侧窄栏 = 设置列表；右侧宽区 = 图片口。
  - 左栏第 1 行：「隔空投送」**开关**（switch）。
  - 左栏第 2 行：「可接收对象」选择（所有人 / 仅联系人 / 接收关闭）。
  - 左栏第 3 行（可扩展）：附近设备列表，点击**选中**一个作为发送目标。
  - 右栏「图片口」：接收到的图片**缩略图网格** + 空态提示"手机发来的图会出现在这里；也可拖图片进来发给手机"。
- **交互**：
  - 开关 → `setEnabled`；接收对象 → `setReceiveMode`。
  - 拖图片文件进右栏 → `sendFiles(选中设备, 文件路径)`。
  - 缩略图可**拖出**：`dragstart` 时调 `airfloat.dragOut(filePath)`。
  - 展示接收进度、数量。
- **兼容**：`window.airfloat` 不存在时（纯浏览器预览）不报错、给出占位提示。

## 7. 主进程 / preload 职责（Lead 实现）

- 无边框、置顶、约 360×500 小窗 + 系统托盘 + 全局快捷键唤出。
- 实例化 `createProtocol`，把 `onPeer`→`devices` 事件、`onReceived`→`received` 事件转发给 renderer。
- `dragOut` 用 `webContents.startDrag({ file, icon })`。
- 配置持久化到 `app.getPath('userData')/config.json`（alias / enabled / receiveMode / whitelist）。
- preload 用 `contextBridge` 暴露第 5 节 API。

## 8. 自测要求

- 协议协作者：`src/protocol/protocol.test.js`，用两个 `createProtocol` 实例（不同端口，`protocol:'http'` 简化即可，host 127.0.0.1）互发一个临时字节文件，断言 `onReceived` 收到且字节一致；打印结果并 `process.exit(0|1)`。运行方式 `npm run test:protocol`。
