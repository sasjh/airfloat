"""AirFloat 设计令牌（材质 / 颜色 / 字体 / 间距 / 圆角）+ QSS 样式表。

设计依据：Apple 设计原则（技能 `apple-design`，WWDC 设计演讲）。

毛玻璃版的四条主线：
- **低透毛玻璃**：材质面要「实」到压得住背后的杂色 —— 内容（照片 / 文件名 / 正文）
  坐在低透的浅色面上，绝不让桌面颜色从字底下透上来。通透感交给光影去换，不靠更透明。
- **玻璃只做点缀**：只有「能摸的东西」套液态玻璃光影（按钮 / 菜单 / 窗口外壳 / 浮层）；
  内容是内容 —— 照片瓦片、设备行一律安静（低透面 + 发丝线），不跟主操作抢戏。
- **渐变光影出声，分割线闭嘴**：顶栏受光 → 内容居中 → 状态栏下沉，一档亮一档中一档深，
  层次由光来讲；区域之间不画硬线。整窗那一层「铺满上半屏的光泽带」已撤掉（那是奶膜 = 糊）。
- **对比按最差底校准**：文字不按白底校准，而按「材质最暗处」逐层压出来 —— 亚克力着色
  `BG #EAF4FF` @68% 压纯黑桌面 = `#9FA6AD`，再叠最重的结构洗（侧栏）+ 窗口底部内阴影
  = `#92999F`。所有文字按它达标（≥ 4.5:1），每项注真实测对比度。
- **用光表现厚度**：顶边受光（rim highlight）+ 底部内阴影交代材质厚度。
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont

# ---------- 材质（毛玻璃）----------
# 亚克力着色：Windows 的 ACCENT_ENABLE_ACRYLICBLURBEHIND 取 ABGR 整数。
# 0xAD = 173 = 68%。实测（深色壁纸）：68% 时内容区 = #AAADB1，100% 才 #D8DDE3 ——
# 68% 已经「低透」到文字随便读，再往下压才是糊。着色越实越不干扰文字，也越像磨砂膏。
GLASS_TINT_ABGR = 0xADFFF4EA
GLASS_SURFACE = 0.72           # 浅材质面（内容 / 控件）白色不透明度（低透：压得住背后杂色）
GLASS_SURFACE_HOVER = 0.88     # 悬停：面更实 = 更靠近手指（不是更透明）
GLASS_SURFACE_PRESSED = 0.52   # 按下：反馈发生在按下瞬间
RAIL_ALPHA = 0.06              # 侧栏：更重的材质，用来分隔结构分区（越重，栏内文字对比度越低）
WELL_ALPHA = 0.05              # 图片口：极轻的凹陷托盘，只做「这里是容器」的暗示
CHIP_ALPHA = 0.06              # 一次性轻底：列表行悬停 / 缩略图占位
HAIRLINE_ALPHA = 0.16          # 发丝线（缩略图轮廓等）
RECESS_WASH = "#0C0E12"        # 结构分区 / 托盘的基色（深色洗）
BOTTOM_SHADE = 8               # 窗口底部内阴影不透明度 /255（越重，状态栏文字越暗）
TOPBAR_SHEEN = 0.10            # 顶栏受光带（渐变光影：顶栏亮 → 内容中 → 状态栏深）
MENU_BG = "#1C1D22"            # 弹出菜单：深色材质
MENU_ALPHA = 0.94
MENU_ROW_HOVER = 26 / 255      # 菜单行悬停底（白色）
MENU_ROW_PRESSED = 46 / 255    # 菜单行按下底（更实 = 反馈发生在按下瞬间）

# ---------- 液态玻璃（Liquid Glass）光影 ----------
# 参考 rdev/liquid-glass-react。折射（对背后像素做位移）在 Qt 桌面端拿不到
# （背后的桌面由 DWM 在窗口之外合成），这里移植的是光影结构：边缘光 / 光泽 /
# 镜面热点 / 边缘色差 / 内阴影 / 落影。绘制入口在 liquid.paint_glass()。
GLASS_RIM_TOP = 0.86           # 受光边（左上）镜面强度
GLASS_RIM_BOTTOM = 0.20        # 背光边（右下）
GLASS_GLOSS = 0.30             # 顶部光泽带
GLASS_SPECULAR = 0.42          # 左上角镜面热点
GLASS_ABERRATION = 0.18        # 边缘色差（冷 / 暖各偏 1px）
GLASS_INNER_SHADOW = 0.10      # 按下：玻璃压进去的内阴影

# 高光强度：**只有这一张表**，各处不再写 lit= 字面量（见 docs/03 §2.2）。
# 面积越大，高光越要克制（拉满就发灰发糊）；越小的控件越敢亮。
GLASS_LIT_REST = 1.00          # 静息
GLASS_LIT_HOVER = 1.12         # 悬停：光更足 = 更靠近手指
GLASS_LIT_PRESSED = 0.90       # 按下：光收回去（配合内阴影）
GLASS_LIT_WINDOW = 0.55        # 整窗：面积大，高光拉满会发灰发糊
GLASS_LIT_LENS = 0.55          # 小透镜（隔空投送圆钮）：只压一层，别像贴纸
GLASS_LIT_MENU = 0.80          # 深色菜单面：高光太亮会把白字对比度拉下来
GLASS_LIT_MENU_ROW = 0.70      # 菜单行悬停片


def wash(alpha: float, base: str = RECESS_WASH) -> QColor:
    """深色洗：结构分区 / 托盘 / 发丝线统一走这里，避免各处随手写 alpha。"""
    color = QColor(base)
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


def wash_css(alpha: float, base: str = RECESS_WASH) -> str:
    """同 wash()，但给 QSS 用（QSS 只认 rgba(r, g, b, a)）。"""
    color = QColor(base)
    return "rgba(%d, %d, %d, %d)" % (color.red(), color.green(), color.blue(), round(alpha * 255))


def white_css(alpha: float) -> str:
    """浅材质面叠层（QSS 用）。"""
    color = QColor(CARD)
    return "rgba(%d, %d, %d, %d)" % (
        color.red(),
        color.green(),
        color.blue(),
        round(max(0.0, min(1.0, alpha)) * 255),
    )


# ---------- 颜色 ----------
BG = "#EAF4FF"                # 材质基色（亚克力 68% 压纯黑 = #9FA6AD，叠结构与底影 = #92999F）
CARD = "#FFFFFF"              # 浅材质面基色
TEXT = "#1B222C"              # 主文字（最差底 5.55:1）
TEXT_SECONDARY = "#28303A"    # 次要文字（最差底 4.62:1，≥ AA 4.5:1）
ACCENT = "#2E6CB0"            # 强调色：其上白字 5.40:1
ACCENT_HOVER = "#2A61A0"
ACCENT_PRESSED = "#24568F"
# 「发送」按钮的强调色玻璃：不透明度阶梯，每档都按最差底验过其上白字
ACCENT_GLASS_REST = 0.94       # 常态白字 5.20:1
ACCENT_GLASS_HOVER = 0.96      # 悬停白字 6.16:1
ACCENT_GLASS_PRESSED = 0.98    # 按下白字 7.39:1
ACCENT_ICON = "#1568C8"       # 图标底（隔空投送圆钮）：其上白色字形 5.46:1
OFFLINE = "#6B7280"           # 关闭态圆钮：其上白色字形 4.82:1
SUCCESS = "#08331F"           # 成功（文字用，最差底 4.84:1）
SUCCESS_FILL = "#1E7D5C"      # 成功填充（Toast 底，白字 5.07:1）
DANGER = "#B3403C"            # 错误填充（其上的白字 5.62:1）
DANGER_HOVER = "#9C3532"

# 玻璃片：tone 名 -> (底色, 不透明度)。图标按钮的底色表（静息 / 悬停各取一档）。
# 「dark」是压在**任意照片**上的遮罩片：取 0.58 才能让白字形在纯白照片上仍有
# 4.74:1（≥3:1 是图标底线）；0.30 那种轻玻璃会把白色字形洗掉。
TONE_MATERIALS: dict[str, tuple[str, float]] = {
    "light": ("#FFFFFF", GLASS_SURFACE),
    "bright": ("#FFFFFF", GLASS_SURFACE_HOVER),
    "dark": ("#0C0E12", 0.58),
    "danger": (DANGER, 0.92),
    "danger_deep": (DANGER_HOVER, 0.96),
}


def tone_material(name: str) -> tuple[QColor, float] | None:
    """把 tone 名解析成 paint_glass 的 (底色, 不透明度)；未知 / "none" = 不画底色。"""
    spec = TONE_MATERIALS.get(name)
    return None if spec is None else (QColor(spec[0]), spec[1])

# ---------- 圆角阶梯 ----------
RADIUS_WINDOW = 8             # 整窗：须与 DWM 系统圆角一致（见 glass._apply_rounding）
RADIUS_CARD = 14              # 模块卡片 / 缩略图
RADIUS_CONTROL = 10           # 图标按钮 / 菜单行
RADIUS_MENU = 18              # 弹出菜单

# ---------- 间距（4pt 网格）----------
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 24

# ---------- 字体 ----------
FONT_FAMILIES = [
    "Segoe UI Variable Text",
    "Segoe UI",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
]

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
    "cardTitle": (14, 600, -0.1),  # 模块卡片标题（隔空投送）
    "cardValue": (12, 400, 0.2),   # 模块卡片取值行（所有人 ⌄）
    "menuRow": (14, 400, -0.1),    # 弹出菜单行（大字号收紧字距）
    "emptyTitle": (14, 600, 0.0),
    "emptyBody": (12, 400, 0.2),
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


# ---- 设备类型图标 ----
# 用矢量而不是 emoji：彩色 emoji 在毛玻璃上显脏，且不同系统渲染不一致。
DEVICE_GLYPHS = {
    "mobile": "phone",
    "desktop": "laptop",
    "web": "globe",
    "headless": "chip",
    "server": "server",
}
DEFAULT_DEVICE_GLYPH = "antenna"


def device_glyph(device_type: str | None) -> str:
    """设备类型 -> 矢量图标名，未知类型回退为天线。"""
    return DEVICE_GLYPHS.get((device_type or "").lower(), DEFAULT_DEVICE_GLYPH)


_FAMILY_QSS = ", ".join('"%s"' % name for name in FONT_FAMILIES) + ", sans-serif"

# 注意：字号 / 字重不在 QSS 里写死，统一由 type_font()/apply_type() 下发，
# 避免「QSS 一套字号、代码另一套」的层级错乱。
QSS = f"""
* {{ font-family: {_FAMILY_QSS}; }}
QWidget {{ color: {TEXT}; }}

/* ---------- 窗口外壳 ----------
   玻璃与圆角由 AirFloatWindow.paintEvent 画（真模糊 + 窗口区域裁剪），
   这里所有容器一律透明：任何不透明底色都会挡住背后的模糊。 */
QWidget#airfloatWindow, QFrame#windowBody {{ background: transparent; }}

/* ---------- 顶栏 ---------- */
QFrame#topbar {{ background: transparent; }}
QLabel#brandName {{ background: transparent; }}
QLabel#selfAlias {{ color: {TEXT_SECONDARY}; background: transparent; }}
QToolButton#folderBtn, QToolButton#closeBtn {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_CONTROL}px;
}}
/* 图标按钮的玻璃面由 _GlyphButton.paintEvent 画（悬停 / 按下要有材质与回弹），
   这里保持透明，任何底色都会挡住玻璃。 */

/* ---------- 侧栏（更重的材质 = 结构分区）----------
   玻璃面同样由 paintEvent 画（liquid.paint_glass）。 */
QFrame#sidebar {{ background: transparent; }}
QLabel#groupTitle {{ color: {TEXT_SECONDARY}; background: transparent; }}
QListWidget#deviceList {{ background: transparent; border: none; outline: none; }}
QListWidget#deviceList::item {{ background: transparent; }}
QLabel#deviceEmpty {{ color: {TEXT_SECONDARY}; background: transparent; }}

/* ---------- 图片口（极轻的凹陷托盘）---------- */
QFrame#imagePort {{ background: transparent; }}
QLabel#emptyMain {{ color: {TEXT}; background: transparent; }}
QLabel#emptySub {{ color: {TEXT_SECONDARY}; background: transparent; }}
QLabel#dropOverlay {{
    border: 2px dashed {ACCENT};
    border-radius: {RADIUS_CARD}px;
    background: {white_css(0.92)};
    color: {ACCENT};
}}

/* ---------- 状态栏 ---------- */
QFrame#statusbar {{ background: transparent; }}
QLabel#statusHint {{ color: {TEXT_SECONDARY}; background: transparent; }}
QLabel#receivedCount {{ color: {SUCCESS}; background: transparent; }}
QLabel#progressLabel {{ color: {TEXT_SECONDARY}; background: transparent; }}
QPushButton#sendBtn {{
    background: transparent;
    color: #FFFFFF;
    border: none;
}}
/* 「发送」按钮是强调色液态玻璃，面由 _SendButton.paintEvent 画（含悬停 / 按下 / 回弹）。 */
QProgressBar#sendProgress {{ background: {white_css(0.55)}; border: none; border-radius: 3px; }}
QProgressBar#sendProgress::chunk {{ background: {ACCENT}; border-radius: 3px; }}

/* ---------- 缩略图上的删除键 ---------- */
QToolButton#thumbDelete {{
    background: transparent;
    border: none;
    color: #FFFFFF;
}}
/* 深色玻璃片 + 悬停变错误色，面由 _GlyphButton.paintEvent 画。 */

/* ---------- Toast ---------- */
QLabel#toast {{
    background: rgba(27, 34, 44, 235);
    color: #FFFFFF;
    border-radius: 16px;
}}
QLabel#toast[kind="error"] {{ background: rgba(179, 64, 60, 245); }}
QLabel#toast[kind="success"] {{ background: rgba(30, 125, 92, 245); }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {wash_css(0.28)}; border-radius: 3px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""
