"""AirFloat 设计令牌（颜色 / 字体 / 间距 / 圆角）+ QSS 样式表。

设计依据：Apple 设计原则（技能 `apple-design`）。
- 字体：字号越大字距越紧、越小越松；层级由「字号 + 字重」共同建立，不靠字号单打。
- 对比：正文 / 次要文字 / 白字填充均按 WCAG AA 4.5:1 校准（每项注释为实测对比度）。
- 间距：4pt 网格；同组紧凑、异组拉开，用邻近性表达从属关系。
- 圆角：统一阶梯（窗口 12 / 卡片 10 / 控件 8），不再各处随手 7/8/12/16。
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont

# ---------- 颜色 ----------
BG = "#EAF3FB"                # 淡蓝背景
CARD = "#FFFFFF"              # 白色卡片
TEXT = "#1F2D3D"              # 主文字（白底 13.99:1）
TEXT_SECONDARY = "#5A6B7E"    # 次要文字（白底 5.47:1 / 蓝底 4.87:1）
DIVIDER = "#D3E2F0"           # 分隔线 / 发丝边
PRIMARY = "#4A90D9"           # 浅蓝：仅作装饰填充（开关滑块过渡），不作文字/白字底
ACCENT = "#2E6CB0"            # 强调色：文字 4.81:1（蓝底）；其上的白字 5.40:1
ACCENT_HOVER = "#2A61A0"
ACCENT_PRESSED = "#24568F"
ACCENT_TINT = "#E4EFFB"       # 选中行浅底（其上的强调色文字 4.64:1）
ACCENT_TINT_BORDER = "#BBD3EE"
HOVER_BG = "#EEF4FB"          # 悬停底（中性，不与选中的强调底色混淆）
OFFLINE = "#9AA7B4"           # 关闭 / 离线
SUCCESS = "#1E7D5C"           # 成功（白底 5.07:1）
DANGER = "#B3403C"            # 错误（其上的白字 5.65:1）
WARN_BG = "#FFF6E5"
WARN_TEXT = "#8A5A12"         # 5.51:1 on WARN_BG

# ---------- 圆角阶梯 ----------
RADIUS_WINDOW = 12            # 窗口 / 顶栏 / 状态栏
RADIUS_CARD = 10              # 卡片 / 按钮 / 缩略图 / 拖放提示
RADIUS_CONTROL = 8            # 列表项 / 图标按钮 / 选项行

# ---------- 间距（4pt 网格）----------
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16

# ---------- 字体 ----------
FONT_FAMILIES = ["Segoe UI", "Microsoft YaHei", "PingFang SC"]

# 角色 -> (像素字号, 字重, 字距 px)。字距：大字号收紧、小字号略放开。
TYPE: dict[str, tuple[int, int, float]] = {
    "brand": (15, 700, -0.3),      # 品牌名
    "alias": (11, 400, 0.3),       # 本机别名
    "rowLabel": (13, 600, 0.0),    # 侧栏行标题
    "groupTitle": (11, 600, 0.4),  # 分组小标题
    "control": (13, 400, 0.0),     # 选项 / 按钮
    "itemTitle": (13, 600, 0.0),   # 列表项主行
    "itemSub": (11, 400, 0.3),     # 列表项副行
    "caption": (11, 400, 0.2),     # 缩略图文件名等说明文字
    "emptyTitle": (14, 600, 0.0),
    "emptyBody": (12, 400, 0.2),
    "emptyIcon": (40, 400, 0.0),
    "status": (11, 400, 0.3),      # 状态栏
    "button": (13, 600, 0.0),
    "toast": (12, 500, 0.2),
    "drop": (14, 600, 0.0),
}


def type_font(role: str, weight: int | None = None) -> QFont:
    """按角色返回 QFont；weight 可覆盖（例如选中态加粗）。"""
    px, wt, tracking = TYPE[role]
    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPixelSize(px)
    font.setWeight(QFont.Weight(weight if weight is not None else wt))
    if tracking:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, tracking)
    return font


def apply_type(widget, role: str):
    """给控件套用某排版角色。"""
    widget.setFont(type_font(role))
    return widget


def animations_enabled() -> bool:
    """是否播放动效。

    尊重系统级「减少动态效果」：Windows 下读取 SPI_GETCLIENTAREAANIMATION
    （设置 → 辅助功能 → 视觉效果 → 动画效果）。关闭时动效降级为直接切换。
    """
    if sys.platform == "win32":
        try:
            import ctypes

            SPI_GETCLIENTAREAANIMATION = 0x1042
            enabled = ctypes.c_int(1)
            ok = ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
            )
            if ok:
                return bool(enabled.value)
        except Exception:
            pass
    return True


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


_FAMILY_QSS = ", ".join('"%s"' % name for name in FONT_FAMILIES) + ", sans-serif"

# 注意：字号 / 字重不在 QSS 里写死，统一由 type_font()/apply_type() 下发，
# 避免「QSS 一套字号、代码另一套」的层级错乱。
QSS = f"""
* {{ font-family: {_FAMILY_QSS}; }}
QWidget {{ color: {TEXT}; }}

/* ---------- 窗口主体（承载投影，定义浮窗轮廓与深度）---------- */
QFrame#windowBody {{
    background: {CARD};
    border-radius: {RADIUS_WINDOW}px;
}}

/* ---------- 顶栏 ---------- */
QFrame#topbar {{
    background: {CARD};
    border-top-left-radius: {RADIUS_WINDOW}px;
    border-top-right-radius: {RADIUS_WINDOW}px;
}}
QLabel#brandName {{ background: transparent; }}
QLabel#selfAlias {{ color: {TEXT_SECONDARY}; background: transparent; }}
QToolButton#folderBtn, QToolButton#closeBtn {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_CONTROL}px;
}}
QToolButton#folderBtn:hover {{
    background: {HOVER_BG};
    border-color: {DIVIDER};
    color: {TEXT};
}}
QToolButton#closeBtn:hover {{
    background: #FAEBEA;
    border-color: #EBC9C6;
    color: {DANGER};
}}
QToolButton#folderBtn:focus, QToolButton#closeBtn:focus {{ border-color: {ACCENT}; }}

/* ---------- 侧栏 ---------- */
QFrame#sidebar {{ background: {CARD}; border-right: 1px solid {DIVIDER}; }}
QLabel#rowLabel {{ background: transparent; }}
QLabel#groupTitle {{ color: {TEXT_SECONDARY}; background: transparent; }}
QPushButton#modeOption {{
    text-align: left;
    padding: 7px 10px;
    border: 1px solid transparent;
    border-radius: {RADIUS_CONTROL}px;
    background: transparent;
    color: {TEXT};
}}
QPushButton#modeOption:hover {{ background: {HOVER_BG}; }}
QPushButton#modeOption:focus {{ border-color: {ACCENT}; }}
QPushButton#modeOption:checked {{
    background: {ACCENT_TINT};
    border-color: {ACCENT_TINT_BORDER};
    color: {ACCENT};
}}
QListWidget#deviceList {{ background: transparent; border: none; outline: none; }}
QListWidget#deviceList::item {{ background: transparent; }}
QLabel#deviceEmpty {{ color: {TEXT_SECONDARY}; background: transparent; }}

/* ---------- 图片口 ---------- */
QFrame#imagePort {{ background: {BG}; }}
QLabel#emptyIcon {{ color: {TEXT_SECONDARY}; background: transparent; }}
QLabel#emptyMain {{ color: {TEXT}; background: transparent; }}
QLabel#emptySub {{ color: {TEXT_SECONDARY}; background: transparent; }}
QLabel#dropOverlay {{
    border: 2px dashed {ACCENT};
    border-radius: {RADIUS_CARD}px;
    background: rgba(234, 243, 251, 235);
    color: {ACCENT};
}}

/* ---------- 状态栏 ---------- */
QFrame#statusbar {{
    background: {CARD};
    border-bottom-left-radius: {RADIUS_WINDOW}px;
    border-bottom-right-radius: {RADIUS_WINDOW}px;
}}
QLabel#statusHint {{ color: {TEXT_SECONDARY}; background: transparent; }}
QLabel#receivedCount {{ color: {SUCCESS}; background: transparent; }}
QLabel#progressLabel {{ color: {TEXT_SECONDARY}; background: transparent; }}
QPushButton#sendBtn {{
    background: {ACCENT};
    color: #FFFFFF;
    border: 1px solid transparent;
    border-radius: {RADIUS_CARD}px;
}}
QPushButton#sendBtn:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#sendBtn:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#sendBtn:focus {{ border-color: #FFFFFF; }}
QProgressBar#sendProgress {{ background: {BG}; border: none; border-radius: 3px; }}
QProgressBar#sendProgress::chunk {{ background: {ACCENT}; border-radius: 3px; }}

/* ---------- Toast ---------- */
QLabel#toast {{
    background: rgba(31, 45, 61, 235);
    color: #FFFFFF;
    border-radius: 16px;
}}
QLabel#toast[kind="error"] {{ background: rgba(179, 64, 60, 245); }}
QLabel#toast[kind="success"] {{ background: rgba(30, 125, 92, 245); }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {DIVIDER}; border-radius: 3px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""
