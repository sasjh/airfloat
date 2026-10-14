# AirFloat

Windows 桌面小浮窗，与 iPhone 上的官方 **LocalSend** App 在同一 WiFi 下**双向互传图片**。

淡蓝主题、iOS 设置页风格、小浮窗尺寸（Win+V 剪贴板那种大小），专为「手机 ↔ 电脑传图」设计，只传图片、不弹保存框。

界面是**真毛玻璃**：抓当前桌面 → 真高斯模糊 → 裁进自己的圆弧四角，指针移到哪、玻璃上的光就从哪来。

---

## 功能特性

- 📥 **手机 → 电脑**：手机 LocalSend 发图，图片自动出现在浮窗里（不弹保存框）
- 📤 **电脑 → 手机**：拖图进浮窗 → 点「发送」→ 图片进手机相册
- 🖐️ **拖出缩略图**：浮窗里的缩略图可直接拖到微信 / QQ / 文件夹
- 🎨 **毛玻璃质感**：背景那层模糊自己抓、自己糊（真高斯）、自己裁圆角 —— 所以四角是真圆弧，
  背后只剩色块与明暗走向，桌面的图标文字不会透过来；指针光、边缘光、那粒小光针都跟着指针走
- 🧊 **淡蓝主色、iOS 设置页布局**（左侧功能卡片 + 可接收对象菜单，右侧图片口）
- 🪟 **可缩放浮窗**：拖动窗口边 / 角自由放大缩小，大小与位置自动记住
- 🗑️ **可删图片**：每张缩略图右上角带删除键，点一下即移除
- 🖼️ **仅图片**：支持 jpg / png / gif / webp / heic 等常见格式

---

## 最近更新（2026-10-14）

- **四角圆弧**：查清「四角有直角」的根因（DWM 的模糊铺在窗口矩形上、不理会窗口区域），
  改成自己抓屏 + 自己模糊 + 自己裁圆角。
- **背景糊到位**：真高斯（Pillow）σ=16 物理像素 —— 之前太清楚（壁纸线条还看得清），
  换成纯 Qt「缩小再放大」又会糊成马赛克，这一档是量出来的。
- **拖动更顺**：抓屏 + 模糊挪进工作线程，拖动时 UI 线程每步从 p95 18ms 降到最大 1.3ms。
- **指针光**：改成临界阻尼弹簧（起步柔、收尾不「咔」），卡片上那粒镜面光针收到 10px。

细节与取舍都写在 `docs/03-UI设计规范.md` 与 `devlog/2026-10-14.md`。

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
| 毛玻璃背景 | 自己抓屏（`BitBlt`，抓的那一瞬间用 `SetWindowDisplayAffinity` 把自己摘出画面）+ Pillow 真高斯，裁进圆角路径；抓与糊都在工作线程 |
| 玻璃光影 | `ui/liquid.py`：指针光、受光边薄光、表面光泽、镜面光针、边缘色差、按下内阴影（参考 [rdev/liquid-glass-react](https://github.com/rdev/liquid-glass-react)） |
| HEIC 解码 | pillow-heif |
| 打包 | PyInstaller（onedir） |

---

## 项目结构

```
├── src_py/
│   ├── main.py                 # 入口（装配协议 + UI）
│   ├── protocol/               # LocalSend v2 协议实现
│   │   ├── __init__.py         # Protocol 装配
│   │   ├── cert.py             # 自签证书
│   │   ├── discovery.py        # UDP 组播发现
│   │   ├── send.py             # 发送（HTTPS 客户端 + mTLS）
│   │   └── server.py           # 接收服务器
│   └── ui/
│       ├── main_window.py      # 浮窗界面
│       ├── styles.py           # 设计令牌（材质 / 颜色 / 字体 / 间距 / 圆角）+ QSS
│       ├── glass.py            # 窗口级材质（亚克力 / 模糊 / 圆角偏好；自绘底时让开）
│       ├── backdrop.py         # 自绘的桌面底：抓屏 → 真高斯 → 交给窗口裁圆角（工作线程里跑）
│       ├── liquid.py           # 液态玻璃光影 + 指针光（临界阻尼弹簧）
│       ├── glyphs.py           # 单色矢量图标（QPainter 绘制，不用 emoji）
│       └── test_ui.py          # UI 自测（离线渲染）
├── scripts/
│   └── build_exe.ps1           # 打包 + 部署（顺手剔掉 PATH 里会污染打包的外来 ICU）
├── docs/                       # 需求 / 技术 / UI 设计文档
└── devlog/                     # 开发日志
```

---

## 开发与构建

### 安装依赖

```bash
pip install PySide6 cryptography Pillow pillow-heif pyinstaller
# 国内可用清华镜像：
# pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PySide6 cryptography Pillow pillow-heif pyinstaller
```

`Pillow` 有两处用途：解码 HEIC（配合 `pillow-heif`），以及毛玻璃背景那层**真高斯模糊**。
没装也能跑 —— 背景会退回纯 Qt 的「缩小再放大」糊法（厚度差不多，但折痕稍明显）。

### 本地运行

```bash
python src_py/main.py
```

### UI 自测

```bash
python src_py/ui/test_ui.py     # 离线渲染，150 项：设计令牌 / 对比度 / 光影分层 / 圆角裁切 / 交互
```

（Windows 控制台若报编码错，先 `set PYTHONIOENCODING=utf-8`。）

### 打包 exe

推荐走脚本（它会先把 PATH 里「自带 icuuc.dll」的目录剔掉 —— 那些目录会让 PyInstaller 打包
进与 PySide6 符号对不上的 ICU，exe 一启动就报 `DLL load failed while importing QtWidgets`）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
# 打包 + 直接部署到桌面目录：
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1 -DeployTo "C:\Users\<你>\Desktop\AirFloat程序"
```

手动打包的等价命令：

```bash
pyinstaller --clean --noconfirm --windowed --onedir --name AirFloat \
  --collect-all pillow_heif --collect-all PIL --paths src_py src_py/main.py
```

打包产物在 `dist/AirFloat/AirFloat.exe`。

---

## 说明

- 系统：**Windows 11**（用 DWM 的圆角偏好）；Windows 10 需要 **2004 及以上**（毛玻璃抓屏用到的
  `WDA_EXCLUDEFROMCAPTURE` 是那版才有的）。
- 本应用不自研 iOS 端，手机端使用官方免费 App **LocalSend**。
- 数据（收到的图片）保存在程序目录下的 `AirFloat数据/cache` 文件夹。
- 首次使用若手机搜不到电脑，请确认电脑防火墙已放行 `53317` 端口（UDP/TCP）。
- 毛玻璃背后那层是**实时抓屏再模糊**：抓的那一瞬间把自己从画面里摘掉（这个开关只影响截屏
  API，屏幕上看不见、不闪），抓屏与模糊都在工作线程里跑 —— 空闲约占单核 11~19%，最小化后 0%。
  抓不到桌面时（受保护内容 / 独占全屏）自动退回系统那层模糊：那条路四角会是方的，但总比一块黑的好。
