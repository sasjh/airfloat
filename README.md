# AirFloat

Windows 桌面小浮窗，与 iPhone 上的官方 **LocalSend** App 在同一 WiFi 下**双向互传图片**。

淡蓝主题、iOS 设置页风格、小浮窗尺寸（Win+V 剪贴板那种大小），专为「手机 ↔ 电脑传图」设计，只传图片、不弹保存框。

---

## 功能特性

- 📥 **手机 → 电脑**：手机 LocalSend 发图，图片自动出现在浮窗里（不弹保存框）
- 📤 **电脑 → 手机**：拖图进浮窗 → 点「发送」→ 图片进手机相册
- 🖐️ **拖出缩略图**：浮窗里的缩略图可直接拖到微信 / QQ / 文件夹
- 🎨 **毛玻璃质感**、淡蓝主色、iOS 设置页布局（左侧功能卡片 + 可接收对象菜单，右侧图片口）
- 🪟 **可缩放浮窗**：拖动窗口边 / 角自由放大缩小，大小与位置自动记住
- 🗑️ **可删图片**：每张缩略图右上角带删除键，点一下即移除
- 🖼️ **仅图片**：支持 jpg / png / gif / webp / heic 等常见格式

---

## 使用说明

### 前提条件

1. 电脑和 iPhone 连接**同一个网络**（同一个 WiFi，或手机开热点给电脑连）
2. iPhone 安装官方免费 App：**LocalSend**（App Store 搜索即可）

### 快速开始

1. 双击 `AirFloat.exe` 打开电脑端浮窗
2. 打开手机 LocalSend

#### 手机 → 电脑（接收）

手机 LocalSend 里选择电脑设备 → 发图 → 图片自动出现在电脑浮窗。

#### 电脑 → 手机（发送）

1. 浮窗**左侧列表点一下你的 iPhone**（选中，高亮）
2. 从文件夹**拖一张图到右侧图片口**
3. 点浮窗底部蓝色 **「发送」** 按钮
4. 图片进入手机相册

#### 拖出到微信 / QQ / 文件夹

把浮窗里的**缩略图**按住，直接拖到微信聊天窗口、QQ 或文件夹即可。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.12 |
| GUI | PySide6（Qt6 原生窗口） |
| 传输协议 | LocalSend v2（UDP 组播发现 + HTTPS 双向证书 + REST） |
| HEIC 解码 | pillow-heif |
| 打包 | PyInstaller（onedir） |

---

## 项目结构

```
src_py/
├── main.py                 # 入口（装配协议 + UI）
├── protocol/               # LocalSend v2 协议实现
│   ├── __init__.py         # Protocol 装配
│   ├── cert.py             # 自签证书
│   ├── discovery.py        # UDP 组播发现
│   ├── send.py             # 发送（HTTPS 客户端 + mTLS）
│   └── server.py           # 接收服务器
└── ui/
    ├── main_window.py      # 浮窗界面
    ├── styles.py           # 设计令牌（材质 / 颜色 / 字体 / 间距 / 圆角）+ QSS
    ├── glass.py            # 窗口级亚克力（Windows 真实模糊 + 圆角裁剪）
    ├── glyphs.py           # 单色矢量图标（QPainter 绘制，不用 emoji）
    └── test_ui.py          # UI 自测（离线渲染）
docs/                       # 需求 / 技术 / UI 设计文档
devlog/                     # 开发日志
```

---

## 开发与构建

### 安装依赖

```bash
pip install PySide6 cryptography pillow-heif pyinstaller
# 国内可用清华镜像：
# pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PySide6 cryptography pillow-heif pyinstaller
```

### 本地运行

```bash
python src_py/main.py
```

### 打包 exe

```bash
pyinstaller --clean --noconfirm --windowed --onedir --name AirFloat \
  --collect-all pillow_heif --collect-all PIL --paths src_py src_py/main.py
```

打包产物在 `dist/AirFloat/AirFloat.exe`。

---

## 说明

- 本应用不自研 iOS 端，手机端使用官方免费 App **LocalSend**。
- 数据（收到的图片）保存在程序目录下的 `AirFloat数据/cache` 文件夹。
- 首次使用若手机搜不到电脑，请确认电脑防火墙已放行 `53317` 端口（UDP/TCP）。
