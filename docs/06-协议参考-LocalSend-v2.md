# 06 · LocalSend v2 协议参考

> 来源：官方 [localsend/protocol](https://github.com/localsend/protocol)（README-zh-CN）。实现协议时以此为准。

## 1. 默认配置

- UDP 组播：组 `224.0.0.167`，端口 `53317`。
- HTTP(TCP) 服务器：端口 `53317`（可改，改动后广播新端口）。

## 2. 指纹 fingerprint

- HTTPS 模式：证书 **DER 的 SHA-256（hex）**。
- HTTP 模式：随机字符串。
- 用途：区分设备 / 信任 / 白名单。

## 3. 设备信息对象

```json
{
  "alias": "Nice Orange",
  "version": "2.0",
  "deviceModel": "Samsung",
  "deviceType": "mobile",
  "fingerprint": "随机字符串",
  "port": 53317,
  "protocol": "https",
  "download": true,
  "announce": true
}
```

- `deviceType` ∈ `mobile | desktop | web | headless | server`（未知值按 desktop）。
- `protocol` ∈ `http | https`。
- `download`：是否激活下载 API（5.2/5.3），可选默认 false。
- `announce`：仅当 true 时触发对方响应。

## 4. 发现

### 4.1 UDP 组播
- 启动时向组播地址发上述 JSON（含 `announce:true`）。
- 收到 `announce:true` 的成员，向其 `POST /api/localsend/v2/register` 返回自身信息。

### 4.2 HTTP 传统模式（组播不可用时）
- 向本网段各 IP `POST /api/localsend/v2/register` 发现设备。

## 5. 发送（HTTP，接收方为服务器）

### 5.1 准备（仅元数据）

`POST /api/localsend/v2/prepare-upload`

请求：
```json
{
  "info": { "alias": "...", "version": "2.0", "deviceModel": "...", "deviceType": "mobile", "fingerprint": "...", "port": 53317, "protocol": "https", "download": true },
  "files": {
    "文件ID": { "id": "文件ID", "fileName": "我的图片.png", "size": 324242, "fileType": "image/jpeg", "sha256": "*哈希*", "preview": "*预览*" }
  }
}
```

响应：
```json
{ "sessionId": "我的会话ID", "files": { "文件ID": "文件Token" } }
```

错误码：`204` 完成（无需传文件）｜`400` 无效请求体｜`403` 拒绝｜`500` 未知错误。

### 5.2 上传文件

`POST /api/localsend/v2/upload?sessionId=会话ID&fileId=文件ID&token=文件Token`（body=二进制，可并发）

错误码：`400` 参数缺失｜`403` 无效令牌或 IP｜`409` 被其他会话阻止｜`500` 未知错误。

### 5.3 取消

`POST /api/localsend/v2/cancel?sessionId=会话ID`

## 6. 反向传输（HTTP，发送方为服务器，浏览器降级用）

- `POST /api/localsend/v2/prepare-download`（无请求体）→ 返回 `{info, sessionId, files:{...}}`。
- `GET /api/localsend/v2/download?sessionId=会话ID&fileId=文件ID` → 二进制。
- 浏览器 URL：`http://<发送者ip>:<发送者端口>`（因浏览器拒绝自签证书，用明文 HTTP）。

## 7. 其他

- `GET /api/localsend/v2/info` → 设备信息（旧发现接口，现仅调试用）。

## 8. 实现注意

- 客户端对接对方自签证书：`rejectUnauthorized:false`。
- `sessionId` / `fileId` / `token` 均由对方在 `prepare-upload` 响应中给出。
- 本项目的实现接口约定见根目录 `CONTRACT.md`（createProtocol 公开 API）。
