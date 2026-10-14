"""AirFloat 设计令牌（材质 / 颜色 / 字体 / 间距 / 圆角）+ QSS 样式表。

设计依据：Apple 设计原则（技能 `apple-design`，WWDC 设计演讲）。

毛玻璃版的五条主线：
- **低透 + 局部加厚**：整窗只着色 13%，桌面真的从玻璃底下上得来；有字的区域各自垫一层
  薄面，把该区的亮度下限抬回 AA；图片口这种大块内容保持**真透**。通透感来自「大面积
  真透 + 小面积厚度」的对比，不是把整窗调实 —— 整窗调实就是把桌面挡回去（那才是「糊」）。
- **玻璃只做点缀**：只有「能摸的东西」套液态玻璃光影（按钮 / 菜单 / 窗口外壳 / 浮层）；
  内容是内容 —— 照片瓦片、设备行一律安静（低透面 + 发丝线），不跟主操作抢戏。
- **渐变光影出声，分割线闭嘴**：顶栏受光 → 内容居中 → 状态栏下沉，一档亮一档中一档深，
  层次由光来讲；区域之间不画硬线（薄面一律带渐隐，不留硬边）。
- **对比按最差底校准**：文字不按白底校准，而按「材质最暗处」逐层压出来 —— 着色
  `BG #EAF4FF` @13% 压纯黑桌面 = `#1E2021`，再叠文字区薄面 = `#939494`，再叠窗口
  底部内阴影 = `#8F9090`。所有文字按它达标（≥ 4.5:1），每项注真实测对比度。
- **用光表现厚度**：顶边受光（rim highlight）+ 底部内阴影交代材质厚度。
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont

# ---------- 材质（毛玻璃）----------
# 玻璃着色：Windows 的 SetWindowCompositionAttribute 取 ABGR 整数。
# 0x21 = 33 = 13%：**几乎全透** —— 壁纸的色与影整片上得来，窗口像一片立在桌面上的玻璃。
# 代价是字形底下的亮度下限跟着掉，所以「读得清」不再由整窗一个人扛：有字的区域各自
# 垫一层薄面（见下面的 FACE 一组），图片口这种大块内容保持真透。
# 着色每往下压一档，薄面就得往上补一档 —— 这是一对，动一个必须动另一个（见 test_ui §13）。
GLASS_TINT_ABGR = 0x21FFF4EA
GLASS_SURFACE = 0.72           # 浅材质面（内容 / 控件）白色不透明度（低透：压得住背后杂色）
# 控件玻璃（按钮 / 卡片这类「能摸的东西」）：比内容面**透**得多 —— 半透才有呼吸感。
# 内容面负责「看得清」，控件面负责「像玻璃」，两套材质各司其职，别互相将就。
CONTROL_GLASS = 0.42           # 控件玻璃：静息
CONTROL_GLASS_HOVER = 0.54     # 悬停：更实一档 = 更靠近手指
CONTROL_GLASS_PRESSED = 0.30   # 按下：更透 = 反馈发生在按下瞬间
# ---------- 文字区薄面（低透 + 局部加厚）----------
# **整窗就这一档**：0.30。它薄到「能让桌面原样上得来」，又厚到「字还站得住」—— 用户一路
# 把侧栏 / 上栏 / 下栏都推到了这一档（「上下框要透很多」「左边的框也要很透」）。同一套材质
# 只有一个价，所以三处共用，不做位置差价。
# 代价是明摆着的：薄面越薄，深色字压深色桌面就越吃力 —— 这一档在最暗的底上只有 ~2.5-2.9:1
# （0.52 那档是 4.5-5.0:1 的 AA）。既然厚薄选了这一档，字就跟着收深（见下面的 TEXT / 
# TEXT_SECONDARY / SUCCESS），能抢多少抢多少；再想反悔就只改这一个数（test_ui §13 会把
# 「0.52 时回到 AA」这条对照也算给你看）。
SIDEBAR_FACE = 0.30            # 侧栏 / 顶栏 / 状态栏：整窗唯一的一档薄面
TOPBAR_FACE = 0.30             # 顶栏（再往上叠 TOPBAR_SHEEN，所以最上沿仍略亮）
STATUSBAR_FACE = 0.30          # 状态栏（底影会再压一档，所以它仍比顶栏沉）
FACE_FALLOFF = 1.8             # 薄面高度 = 该栏高度 × 它，向内容区渐隐到 0
# 图片口的空态提示：图片口是整窗最透的地方，深色文字在这儿根本站不住（1.02:1）。参考图
# （iOS「Clear」）给的答案很干脆 —— **亮字，周围什么都不加**：垫浅底就是一块发灰的板，
# 垫深底就是一块发黑的板，加描边就是字周围多出一圈不透明（用户说的「两种透明度」）。
# 所以空态只有**一档不透明度**：亮字（HINT_TEXT），大标题 + 副行同一档（差的是字号，
# 不是透明度），周围不铺任何东西 —— 图片口因此一直是一片全透的玻璃（见 test_ui §13）。
HINT_TEXT = "#F2F7FF"          # 空态提示的字色：亮字（参考图里 Clear 面板就是白字）
CHIP_ALPHA = 0.06              # 一次性深色轻底：缩略图占位（压在浅色瓦片上）
ROW_HOVER_FACE = 0.12          # 设备行悬停：**亮**一档（悬停 = 更靠近手指 = 光更足）
HAIRLINE_ALPHA = 0.16          # 发丝线（缩略图轮廓等）
RECESS_WASH = "#0C0E12"        # 托盘 / 凹槽 / 深色片的基色（深色洗）
BOTTOM_SHADE = 8               # 窗口底部内阴影不透明度 /255（越重，状态栏文字越暗）
# 顶栏最上沿再亮一档（光从上面来：顶栏亮 → 内容中 → 状态栏深）。薄面只剩 0.30 之后，
# 这层「受光带」是顶栏还看得出是顶栏的唯一凭据；但也不能重 —— 它是**光**，不是第二层底。
TOPBAR_SHEEN = 0.08
MENU_BG = "#1C1D22"            # 弹出菜单：深色材质
MENU_ALPHA = 0.94
MENU_ROW_HOVER = 26 / 255      # 菜单行悬停底（白色）
MENU_ROW_PRESSED = 46 / 255    # 菜单行按下底（更实 = 反馈发生在按下瞬间）

# ---------- 液态玻璃（Liquid Glass）光影 ----------
# 参考 rdev/liquid-glass-react。折射（对背后像素做位移）在 Qt 桌面端拿不到
# （背后的桌面由 DWM 在窗口之外合成），这里移植的是光影结构：边缘光 / 光泽 /
# 镜面热点 / 边缘色差 / 内阴影 / 落影。绘制入口在 liquid.paint_glass()。
GLASS_RIM_TOP = 0.80           # 受光边（左上）镜面强度
GLASS_RIM_BOTTOM = 0.42        # 背光边（右下）：不能太暗 —— 一整圈亮边才是玻璃的签名
# 那圈细亮边到底有多细：参考图（iOS「Clear」）里它是一根**发丝**，不是一条乳白带。
# 0.75px + 抗锯齿 = 视觉上 1px 左右、边缘干净；再粗就从「玻璃的边」变成「塑料的框」。
GLASS_RIM_WIDTH = 0.75
# 不随光位变的一圈底子：参考实现是 `0 0 0 0.5px rgba(255,255,255,.5) inset`。
# 光位只管「哪一段更亮」，这圈底子保证任何光位下窗口轮廓都立得住。
GLASS_RING = 0.30
GLASS_GLOSS = 0.30             # 顶部光泽带
GLASS_SPECULAR = 0.42          # 左上角镜面热点
GLASS_ABERRATION = 0.18        # 边缘色差（冷 / 暖各偏 1px）
GLASS_INNER_SHADOW = 0.10      # 按下：玻璃压进去的内阴影

# ---------- 指针光（让玻璃「活着」）----------
# 一整块界面共用**一个光源**：指针在哪，光就从哪来 —— 所有玻璃的高光方向因此一致。
# 指针每动一下只跟一小步，所以高光是「跟过来」的，不是瞬移；这一点点延迟就是
# 「有生命的液体」和「一张贴纸」的区别。
GLASS_LIGHT_REST = (-0.72, -0.72)  # 静息光位（左上）：没有指针时的设计约定
GLASS_LIGHT_EASE = 0.16            # 每个心跳跟进的比例（越小越「懒」）：按 16ms 归一
GLASS_LIGHT_SETTLE = 0.0015        # 跟到这个差距就落定：再小只是肉眼看不见的抖，白重绘
LIGHT_TICK_MS = 16                 # 光场心跳：60fps —— 光要走得**顺**，步子就必须密
GLASS_LIGHT_SHIFT = 0.35           # 镜面热点：从光源侧边缘朝玻璃中心挪这个比例（0 = 贴边）
GLASS_CAUSTIC = 0.13               # 背光侧的焦散细弧：光穿过玻璃，在另一侧聚成一道亮边
GLASS_CAUSTIC_INSET = 2.0          # 焦散弧离边缘多远（px）
GLASS_EDGE_GLOW = 0.10             # 受光边那圈内圈薄光：大面板只给「边」给光，不给面
GLASS_EDGE_GLOW_WIDTH = 20.0       # 内圈薄光的宽度（px）：**像素**不是比例，放大不会糊成一片
GLASS_EDGE_HOTSPOT = 0.06          # 受光边正中那朵**沿边**的柔光（跟着指针绕窗口）
# 那朵光的半径 / 所在边的长度。**别贪大**：它是个有限半径的径向渐变，铺得越大，渐变的
# 外沿就越容易在玻璃中间显出一条弧（看着像贴了张圆形的膜）。0.35 × 边长 ≈ 只在边中附近
# 亮一小段，配合下面那串密一点的过渡点，落点才「软」。
GLASS_EDGE_HOTSPOT_R = 0.35
GLASS_SQUASH = 0.55                # 按下的各向异性：纵向压多少，横向就鼓多少（0 = 各向同性）

# ---------- 内容的环境光（玻璃被内容染色）----------
# 收到的照片把自己的颜色借给玻璃一点：新图进来，整片玻璃慢慢染过去。
# 只借一点点 —— 玻璃不能变成彩色塑料。
AMBIENT_MIX = 0.55                 # 内容色保留多少饱和度（其余归中性）
AMBIENT_ALPHA = 0.13               # 环境光那层光的强度
AMBIENT_SETTLE_MS = 850            # 染色渐变的时间
AMBIENT_DIP = 0.45                 # 再来一张图时先退到当前强度的这个比例，再重新染上去（呼吸）
AMBIENT_SPREAD = 0.90              # 染光半径 / 窗口长边
AMBIENT_VALUE_FLOOR = 0.45         # 染光明度下限：太暗的照片不能把底压到吃掉 AA
AMBIENT_VALUE_CEIL = 0.85          # 染光明度上限：太亮的照片不许把玻璃洗白

# 高光强度：**只有这一张表**，各处不再写 lit= 字面量（见 docs/03 §2.2）。
# 面积越大，高光越要克制（拉满就发灰发糊）；越小的控件越敢亮。
GLASS_LIT_REST = 1.00          # 静息
GLASS_LIT_HOVER = 1.12         # 悬停：光更足 = 更靠近手指
GLASS_LIT_PRESSED = 0.90       # 按下：光收回去（配合内阴影）
GLASS_LIT_WINDOW = 0.72        # 整窗：面积大，高光要克制；但太弱那圈细亮边就立不住
GLASS_LIT_LENS = 0.55          # 小透镜（隔空投送圆钮）：只压一层，别像贴纸
GLASS_LIT_MENU = 0.80          # 深色菜单面：高光太亮会把白字对比度拉下来
GLASS_LIT_MENU_ROW = 0.70      # 菜单行悬停片

# ---------- 凹槽环玻璃（参考图那枚圆钮 / 胶囊：细描边 + 弱阴影 + 半透）----------
# 和上面的液态玻璃分工不同：它**不铺浅色面** —— 槽底只是一层半透的底座色
# （背后的亚克力模糊能透上来，玻璃才像在呼吸）；立体感全靠一圈发丝环 + 顶内阴影
# + 底内受光。槽底的实与不实，取决于它压着什么颜色的字形 ——
# 所以槽底的不透明度不在这一组里，跟着它的底色走（见下面的 SEND_WELL）。
RING_EDGE_TOP = 0.70           # 发丝环上缘
RING_EDGE_BOTTOM = 0.95        # 发丝环下缘（参考图里下缘最亮 —— 那是反光）
RING_FILL_TOP = 1.22           # 槽底渐变：顶部（凹进去那侧）最实
RING_FILL_FLOOR = 0.82         # 槽底渐变：底部最浅 —— 也是字形脚下最亮的一档，对比度按它算
RING_TOP_SHADE = 0.26          # 顶内阴影（凹）
RING_BOTTOM_LIGHT = 0.34       # 底内受光（反光）：只贴边那一条，不铺到字形下面
RING_LIGHT_TOP = 0.80          # 底内受光带的起点：0.80 正好落在字形盒之下（见 test_ui）
RING_SHADOW = 0.22             # 环外那条弱落影
RING_INSET = 1.0               # 凹槽内缩 1px：把外缘那 1px 留给环外的弱落影

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
# 字色跟薄面是一对：薄面降到 0.30 之后，墨色跟着收深一档，把在近透玻璃上还能守住的那点
# 对比度全抢回来（#1B222C → #10151C、#232A34 → #141A24 等，实测见 test_ui §13）。
BG = "#EAF4FF"                # 材质基色（着色 13% 压纯黑 = #1E2021，叠薄面 0.30 = #626364）
CARD = "#FFFFFF"              # 浅材质面基色
TEXT = "#10151C"              # 主文字（近透档最暗底 2.91:1；薄面回到 0.52 时 5.7:1）
TEXT_SECONDARY = "#141A24"    # 次要文字（近透档最暗底 2.77:1；薄面回到 0.52 时 5.4:1）
ACCENT = "#2E6CB0"            # 强调色：其上白字 5.40:1
ACCENT_HOVER = "#2A61A0"
ACCENT_PRESSED = "#24568F"
# 「发送」键的凹槽底（强调色）：主操作要立得住，所以比控件玻璃实得多 ——
# 白箭头压在它上面必须 ≥3:1（图标底线），三档都按最亮底（纯白壁纸）验过。
SEND_WELL = 0.90               # 常态
SEND_WELL_HOVER = 0.94         # 悬停：更实一档 = 更靠近手指
SEND_WELL_PRESSED = 0.96       # 按下：槽更深（回弹交给 PressSpring）
ACCENT_ICON = "#1568C8"       # 图标底（隔空投送圆钮）：其上白色字形 5.46:1
OFFLINE = "#6B7280"           # 关闭态圆钮：其上白色字形 4.82:1
SUCCESS = "#07211A"           # 成功（文字用：近透档最暗底 2.68:1；薄面回到 0.52 时 5.0:1）
SUCCESS_FILL = "#1E7D5C"      # 成功填充（Toast 底，白字 5.07:1）
DANGER = "#B3403C"            # 错误填充（其上的白字 5.62:1）
DANGER_HOVER = "#9C3532"

# 玻璃片：tone 名 -> (底色, 不透明度)。图标按钮的底色表（静息 / 悬停各取一档）。
# 「light」是悬停片：走控件玻璃那一档（半透），玻璃才有呼吸感；字形是深色的，
# 面越浅对比越高，所以控件面透一点不影响可读性。
# 「dark」是压在**任意照片**上的遮罩片：取 0.58 才能让白字形在纯白照片上仍有
# 4.74:1（≥3:1 是图标底线）；0.30 那种轻玻璃会把白色字形洗掉。
TONE_MATERIALS: dict[str, tuple[str, float]] = {
    "light": ("#FFFFFF", CONTROL_GLASS_HOVER),
    "dark": ("#0C0E12", 0.58),
    "danger": (DANGER, 0.92),
    "danger_deep": (DANGER_HOVER, 0.96),
}


def tone_material(name: str) -> tuple[QColor, float] | None:
    """把 tone 名解析成 paint_glass 的 (底色, 不透明度)；未知 / "none" = 不画底色。"""
    spec = TONE_MATERIALS.get(name)
    return None if spec is None else (QColor(spec[0]), spec[1])

# ---------- 圆角阶梯 ----------
# 整窗圆角有两套值，用哪套取决于**谁在裁那层模糊**（见 glass.GlassMaterial.set_rounded）：
# 纯模糊时模糊跟着窗口区域走，圆角就归我们管 —— 想多圆有多圆；亚克力兜底时模糊由 DWM
# 画、不认区域，圆角只能交给 DWM，而它的半径是**系统固定**的（100% DPI 下 8px），这时
# 我们画的弧必须跟它同半径，否则四角会出现两条不同心的弧。
RADIUS_WINDOW = 16            # 整窗（区域裁得住模糊时）：比系统那档圆得多，像一块真的玻璃片
RADIUS_WINDOW_SYSTEM = 8      # 整窗（DWM 裁模糊时）：系统固定值，只能跟
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
    "emptyTitle": (24, 700, -0.2), # 空态大标题：大、粗、亮（参考图 Clear 那一行）
    "emptySub": (13, 500, 0.1),    # 空态副行：**同一个不透明度**，差的只是字号
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

/* ---------- 图片口（极轻的凹陷托盘）---------- */
QFrame#imagePort {{ background: transparent; }}
/* 空态提示走参考图那条路：亮字，周围什么都不加（不垫底、不描边），只有一档不透明度；
   大标题与副行差的是字号，不是透明度。 */
QLabel#emptyMain, QLabel#emptySub {{ color: {HINT_TEXT}; background: transparent; }}
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
/* 「发送」是强调色凹槽环玻璃圆钮：面与那圈发丝环都由 _SendButton.paintEvent 画
   （含悬停 / 按下 / 回弹）。这里只留一个透明底，任何底色都会挡住玻璃。 */
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
