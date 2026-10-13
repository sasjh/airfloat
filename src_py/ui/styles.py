"""AirFloat 淡蓝主题：颜色常量 + QSS 样式表。

颜色对齐 `docs/03-UI设计规范.md` 与 `src/renderer/styles.css`。
"""

from __future__ import annotations

# ---- 配色 ----
BG = "#EAF3FB"              # 淡蓝背景
PRIMARY = "#4A90D9"         # 主蓝（强调/按钮/开关）
PRIMARY_DARK = "#3B7CC0"    # 主蓝深色
CARD = "#FFFFFF"            # 白卡片
TEXT = "#1F2D3D"            # 主文字（深灰蓝）
TEXT_SECONDARY = "#7A8B9E"  # 次要文字
DIVIDER = "#DCE8F3"         # 分隔线
SUCCESS = "#3EB489"         # 成功/在线
OFFLINE = "#9AA7B4"         # 关闭/离线
WARN_BG = "#FFF6E5"
WARN_TEXT = "#B07A1C"
DANGER = "#E45B5B"

RADIUS = 12                 # 窗口外圆角
FONT_FAMILY = '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'

# ---- 设备类型图标（与 Node renderer 对齐）----
DEVICE_ICONS = {
    "mobile": "📱",
    "desktop": "🖥️",
    "web": "🌐",
    "headless": "🤖",
    "server": "🗄️",
}
DEFAULT_DEVICE_ICON = "📡"


def device_icon(device_type: str | None) -> str:
    """设备类型 -> emoji 图标，未知类型回退为天线。"""
    return DEVICE_ICONS.get((device_type or "").lower(), DEFAULT_DEVICE_ICON)


QSS = f"""
* {{ font-family: {FONT_FAMILY}; }}
QWidget {{ font-size: 12px; color: {TEXT}; }}

/* ---------- 顶栏 ---------- */
QFrame#topbar {{
    background: {CARD};
    border-top-left-radius: {RADIUS}px;
    border-top-right-radius: {RADIUS}px;
}}
QLabel#brandName {{ font-size: 15px; font-weight: 700; color: {TEXT}; background: transparent; }}
QLabel#selfAlias {{ font-size: 11px; color: {TEXT_SECONDARY}; background: transparent; }}
QToolButton#folderBtn {{ background: transparent; border: none; border-radius: 7px; font-size: 15px; color: {TEXT_SECONDARY}; }}
QToolButton#folderBtn:hover {{ background: {BG}; color: {PRIMARY}; }}

/* ---------- 侧栏 ---------- */
QFrame#sidebar {{ background: {CARD}; border-right: 1px solid {DIVIDER}; }}
QLabel#rowLabel {{ font-weight: 600; font-size: 13px; background: transparent; }}
QLabel#groupTitle {{ font-size: 11px; color: {TEXT_SECONDARY}; font-weight: 600; background: transparent; }}

/* 可接收对象选项 */
QPushButton#modeOption {{
    text-align: left;
    padding: 6px 10px;
    border: none;
    border-radius: 7px;
    background: transparent;
    color: {TEXT};
    font-size: 12px;
}}
QPushButton#modeOption:hover {{ background: {BG}; }}
QPushButton#modeOption:checked {{ background: {BG}; color: {PRIMARY}; font-weight: 600; }}

/* 附近设备列表 */
QListWidget#deviceList {{ background: transparent; border: none; outline: none; }}
QListWidget#deviceList::item {{ background: transparent; }}
QLabel#deviceEmpty {{ font-size: 11px; color: {TEXT_SECONDARY}; background: transparent; }}

/* ---------- 图片口 ---------- */
QFrame#imagePort {{ background: {BG}; }}
QLabel#emptyIcon {{ font-size: 40px; color: {TEXT_SECONDARY}; background: transparent; }}
QLabel#emptyMain {{ font-size: 13px; color: {TEXT}; font-weight: 600; background: transparent; }}
QLabel#emptySub {{ font-size: 12px; color: {TEXT_SECONDARY}; background: transparent; }}
QLabel#dropOverlay {{
    border: 2px dashed {PRIMARY};
    border-radius: 10px;
    background: rgba(234, 243, 251, 235);
    color: {PRIMARY};
    font-weight: 600;
    font-size: 14px;
}}

/* ---------- 状态栏 ---------- */
QFrame#statusbar {{
    background: {CARD};
    border-bottom-left-radius: {RADIUS}px;
    border-bottom-right-radius: {RADIUS}px;
}}
QLabel#statusHint {{ font-size: 11px; color: {TEXT_SECONDARY}; background: transparent; }}
QLabel#receivedCount {{ font-size: 11px; color: {SUCCESS}; font-weight: 600; background: transparent; }}
QLabel#progressLabel {{ font-size: 11px; color: {TEXT_SECONDARY}; background: transparent; }}

QProgressBar#sendProgress {{ background: {BG}; border: none; border-radius: 3px; height: 6px; }}
QProgressBar#sendProgress::chunk {{ background: {PRIMARY}; border-radius: 3px; }}

/* ---------- Toast ---------- */
QLabel#toast {{
    background: rgba(31, 45, 61, 235);
    color: #FFFFFF;
    border-radius: 16px;
    font-size: 12px;
}}
QLabel#toast[kind="error"] {{ background: rgba(228, 91, 91, 242); }}
QLabel#toast[kind="success"] {{ background: rgba(62, 180, 137, 242); }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {DIVIDER}; border-radius: 3px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {PRIMARY}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""
