"""AirFloat 主窗口（PySide6 / Qt6 原生 GUI，替代 Electron）。

布局（对齐 docs/03）：
- 顶栏：品牌 + 本机别名 + 打开接收目录按钮（无边框窗口拖拽区）。
- 外壳：无边框毛玻璃窗口（真实桌面模糊 + 圆角裁剪），八向可缩放，尺寸/位置持久化。
- 左窄栏（功能键）：隔空投送模块卡片（点圆钮开关 / 点卡片选可接收对象）+ 附近设备列表。
- 右宽栏「图片口」：缩略图网格（每张带删除键）+ 空态提示；支持拖入图片发送、拖出缩略图。
- 底部状态栏：进度条 + 状态提示 + 已接收数量。

线程模型：
- 协议回调（on_received / on_peer / on_progress）在后台线程触发，由 main.py 调
  用本窗口的 ``on_received_item / on_devices / on_state / on_progress``；这些方法
  内部通过 Qt 信号（AutoConnection，跨线程自动转为队列）marshal 到主线程渲染。
- 用户操作通过公开信号回传 main.py：
  ``send_files_requested(list)`` / ``receive_mode_changed(str)`` / ``enabled_changed(bool)``。
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QMimeData,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QFontMetrics,
    QGuiApplication,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyledItemDelegate,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .glass import MODE_SOLID, GlassMaterial
from .glyphs import paint_glyph
from .liquid import (
    GlassSurface,
    PressSpring,
    follow_light,
    glass_path,
    paint_edge_glow,
    paint_glass,
    paint_well_glass,
    pointer_light,
    squashed_rect,
)
from .styles import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_ICON,
    ACCENT_PRESSED,
    AMBIENT_ALPHA,
    AMBIENT_DIP,
    AMBIENT_MIX,
    AMBIENT_SETTLE_MS,
    AMBIENT_SPREAD,
    AMBIENT_VALUE_CEIL,
    AMBIENT_VALUE_FLOOR,
    BG,
    BOTTOM_SHADE,
    CARD,
    CHIP_ALPHA,
    CONTROL_GLASS,
    CONTROL_GLASS_HOVER,
    CONTROL_GLASS_PRESSED,
    DEFAULT_DEVICE_GLYPH,
    FACE_FALLOFF,
    GLASS_LIT_HOVER,
    GLASS_LIT_LENS,
    GLASS_LIT_MENU,
    GLASS_LIT_MENU_ROW,
    GLASS_LIT_PRESSED,
    GLASS_LIT_REST,
    GLASS_LIT_WINDOW,
    GLASS_SURFACE,
    GLASS_TINT_ABGR,
    HAIRLINE_ALPHA,
    HINT_TEXT,
    MENU_ALPHA,
    MENU_BG,
    MENU_ROW_HOVER,
    MENU_ROW_PRESSED,
    OFFLINE,
    QSS,
    RADIUS_CARD,
    RADIUS_CONTROL,
    RADIUS_MENU,
    RADIUS_WINDOW,
    RADIUS_WINDOW_SYSTEM,
    RECESS_WASH,
    ROW_HOVER_FACE,
    SEND_WELL,
    SEND_WELL_HOVER,
    SEND_WELL_PRESSED,
    SIDEBAR_FACE,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    SPACE_5,
    STATUSBAR_FACE,
    TEXT,
    TEXT_SECONDARY,
    TOPBAR_FACE,
    TOPBAR_SHEEN,
    animations_enabled,
    apply_type,
    device_glyph,
    tone_material,
    type_font,
    wash,
)

# HEIC 解码（pillow-heif 注册到 Pillow，兜底 Qt 不支持的格式）
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    from PIL import Image as _PILImage
    _HAS_PILLOW = True
except Exception:
    _HAS_PILLOW = False

# ---- 常量 ----
# 可接收对象：菜单顺序对齐 Apple 隔空投送（关闭 → 仅限联系人 → 所有人）
MODE_LABELS = {"off": "接收关闭", "contacts": "仅限联系人", "everyone": "所有人"}
MODE_ORDER = ("off", "contacts", "everyone")
DEFAULT_MODE = "everyone"

# 窗口：玻璃就是窗口本身（不再为投影留白），所以没有 GUTTER；
# 无边框窗口的尺寸完全交给用户，只守住一个下限。
DEFAULT_WINDOW = (400, 560)
MIN_WINDOW = (340, 440)
RESIZE_MARGIN = 6              # 八向缩放热区：无边框窗口的手感全在这几像素上
SETTINGS_ORG, SETTINGS_APP = "AirFloat", "AirFloatWindow"
RESIZE_SETTLE_MS = 180         # 停手多久后把亚克力切回来

SIDEBAR_W = 158
TOPBAR_H = 44
STATUSBAR_H = 36
ICON_BTN = 26
SEND_BTN = 34                  # 发送：圆钮直径（只有箭头图标，不再有文字标签）
SEND_GLYPH = 0.56              # 发送：箭头图形占圆钮的比例（照参考图量）
AMBIENT_PROBE = 24             # 取内容环境光时缩到多大再平均（够稳，也不解码一张大图）

# 隔空投送模块卡片（左侧功能键）
CARD_W = SIDEBAR_W - 2 * SPACE_3
CARD_H = 132
CARD_ICON = 44                 # 圆钮直径

# 缩略图网格
THUMB_W = 84
THUMB_IMG_H = 62
THUMB_NAME_H = 18
THUMB_CELL_H = THUMB_IMG_H + THUMB_NAME_H
GRID_COLUMNS = 2               # 初始列数；实际列数随窗口宽度算（见 _sync_columns）
GRID_GAP = 8
DELETE_BTN = 20                # 缩略图右上角的删除键
DELETE_INSET = 4

# 可接收对象弹出菜单
MENU_W = 196
MENU_ROW_H = 44
MENU_PAD = 6
MENU_SHADOW = 14               # 菜单四周留给投影的透明边


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _center_crop(pm: QPixmap, w: int, h: int) -> QPixmap | None:
    if pm is None or pm.isNull():
        return None
    if pm.width() == w and pm.height() == h:
        return pm
    x = (pm.width() - w) // 2
    y = (pm.height() - h) // 2
    x = max(0, x)
    y = max(0, y)
    return pm.copy(x, y, min(w, pm.width()), min(h, pm.height()))


def _pillow_to_qimage(pil_img):
    """Pillow Image -> QImage。"""
    from PySide6.QtGui import QImage
    img = pil_img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return qimg.copy()


def _load_thumb_via_pillow(path: str, w: int, h: int) -> QPixmap | None:
    """HEIC 等 Qt 不支持的格式：用 Pillow(pillow-heif) 解码。"""
    if not _HAS_PILLOW:
        return None
    try:
        with _PILImage.open(path) as im:
            im.thumbnail((w * 4, h * 4))
            qimg = _pillow_to_qimage(im)
        if qimg.isNull():
            return None
        return _center_crop(QPixmap.fromImage(qimg), w, h)
    except Exception:
        return None


def _load_thumb(path: str, w: int, h: int) -> QPixmap | None:
    """读取图片并生成 w×h 的封面缩略图（保持比例裁剪）。HEIC 走 Pillow 兜底。"""
    if not path:
        return None
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            scale = max(w / size.width(), h / size.height())
            reader.setScaledSize(QSize(round(size.width() * scale), round(size.height() * scale)))
            img = reader.read()
            if not img.isNull():
                return _center_crop(QPixmap.fromImage(img), w, h)
    except Exception:
        pass
    return _load_thumb_via_pillow(path, w, h)


def _average_color(pixmap: QPixmap | None) -> QColor | None:
    """一张图借给玻璃的那点颜色：**保色相、降饱和、夹明度**（见 AMBIENT_* 令牌）。

    直接拿平均色去染玻璃是错的：一张雪景会把整窗洗白，一张夜景会把字压到 AA 以下。
    所以只借色调（饱和度乘 AMBIENT_MIX），明度夹在 FLOOR..CEIL 之间 —— 玻璃能看出
    「刚收到的那张图是暖的还是冷的」，但读起来还是玻璃，不是彩色塑料。
    """
    if pixmap is None or pixmap.isNull():
        return None
    small = pixmap.toImage().scaled(
        8, 8, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    red = green = blue = count = 0
    for y in range(small.height()):
        for x in range(small.width()):
            pixel = small.pixelColor(x, y)
            if pixel.alpha() == 0:
                continue
            red += pixel.red()
            green += pixel.green()
            blue += pixel.blue()
            count += 1
    if not count:
        return None
    hue, saturation, value, _ = QColor(red // count, green // count, blue // count).getHsvF()
    return QColor.fromHsvF(
        hue if hue >= 0.0 else 0.0,
        saturation * AMBIENT_MIX,
        min(max(value, AMBIENT_VALUE_FLOOR), AMBIENT_VALUE_CEIL),
    )


# --------------------------------------------------------------------------- #
# 小控件：矢量图标（毛玻璃上不用 emoji —— 彩色 emoji 会显脏、基线也对不齐）
# --------------------------------------------------------------------------- #
class _GlyphButton(QToolButton):
    """矢量图标按钮：图标由 QPainter 画，底色是液态玻璃片（悬停 / 按下带材质与回弹）。"""

    def __init__(
        self,
        glyph: str,
        tip: str,
        size: int = ICON_BTN,
        color: str = "",
        hover_color: str = "",
        parent: QWidget | None = None,
        *,
        tone: str = "none",
        hover_tone: str = "light",
    ) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._color = QColor(color or TEXT)
        self._hover_color = QColor(hover_color) if hover_color else None
        self._rest_tone = tone
        self._hover_tone = hover_tone
        self._hover = False
        self._pressed = False
        self._spring = PressSpring(self)
        self.setToolTip(tip)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        follow_light(self)      # 光一挪，这枚玻璃就跟着重新受光

    def _glass_tone(self) -> str:
        """当前该画哪一片玻璃：按下比悬停更「实」（错误色按下再深一档）。"""
        if self._pressed:
            tone = self._hover_tone
            return "danger_deep" if tone == "danger" else tone
        return self._hover_tone if self._hover else self._rest_tone

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._spring.press()
            self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._pressed:
            self._pressed = False
            self._spring.release()
            self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = squashed_rect(
            QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0),
            self._spring.sx,
            self._spring.sy,
        )
        fill = tone_material(self._glass_tone())
        if fill is not None:
            tint, alpha = fill
            if self._pressed:
                lit = GLASS_LIT_PRESSED
            elif self._hover:
                lit = GLASS_LIT_HOVER
            else:
                lit = GLASS_LIT_REST
            paint_glass(
                p,
                rect,
                RADIUS_CONTROL,
                tint=tint,
                alpha=alpha,
                lit=lit,
                pressed=self._pressed,
                specular=False,
            )
        color = self._hover_color if (self._hover and self._hover_color is not None) else self._color
        paint_glyph(p, self._glyph, rect, color)
        if self.hasFocus():
            p.setPen(QPen(QColor(ACCENT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), RADIUS_CONTROL - 2, RADIUS_CONTROL - 2)
        p.end()


class _SendButton(QPushButton):
    """「发送」按钮：强调色的凹槽环玻璃圆钮 + 细描边的白色向上箭头。

    照着参考图（129ca2…）那枚圆钮的做法：槽底比板面深一档 + 一圈发丝亮环 +
    顶内阴影 + 底内受光。不留文字标签 —— 箭头是通用语义，画面上少一个元素，
    主操作反而更立得住；可读性交给 tooltip 与无障碍名，不拿无障碍换干净。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setToolTip("发送到所选设备")
        self.setAccessibleName("发送")
        self._hover = False
        self._pressed = False
        self._spring = PressSpring(self)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        follow_light(self)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._spring.press()
            self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._pressed:
            self._pressed = False
            self._spring.release()
            self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = squashed_rect(
            QRectF(0.0, 0.0, float(self.width()), float(self.height())),
            self._spring.sx,
            self._spring.sy,
        )
        if self._pressed:
            tint, fill, lit = ACCENT_PRESSED, SEND_WELL_PRESSED, GLASS_LIT_PRESSED
        elif self._hover:
            tint, fill, lit = ACCENT_HOVER, SEND_WELL_HOVER, GLASS_LIT_HOVER
        else:
            tint, fill, lit = ACCENT, SEND_WELL, GLASS_LIT_REST
        paint_well_glass(
            p,
            rect,
            rect.width() / 2.0,
            fill=fill,
            lit=lit,
            tint=QColor(tint),
        )
        # 箭头：比例照参考图 —— 图形约占圆钮的 56%，细描边、圆头。
        side = rect.width() * SEND_GLYPH
        glyph = QRectF(0.0, 0.0, side, side)
        glyph.moveCenter(rect.center())
        paint_glyph(p, "arrow_up", glyph, QColor("#FFFFFF"))
        if self.hasFocus():
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(rect.adjusted(2, 2, -2, -2))
        p.end()


class _GlyphLabel(QWidget):
    """空态里的大图标：矢量绘制，任意尺寸都不糊。"""

    def __init__(self, glyph: str, size: int, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        paint_glyph(p, self._glyph, self.rect(), self._color)
        p.end()


# --------------------------------------------------------------------------- #
# 附近设备列表委托（emoji 图标 + 别名 + 类型，两行）
# --------------------------------------------------------------------------- #
class DeviceItemDelegate(QStyledItemDelegate):
    """绘制设备条目：emoji + 别名 + 类型两行；选中态用强调色实底。"""

    def sizeHint(self, _option, _index) -> QSize:  # noqa: D102
        return QSize(120, 46)

    def paint(self, painter, option, index) -> None:  # noqa: D102
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(0, 1, 0, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(rect, RADIUS_CONTROL, RADIUS_CONTROL)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(wash(ROW_HOVER_FACE, CARD))
            painter.drawRoundedRect(rect, RADIUS_CONTROL, RADIUS_CONTROL)

        alias = index.data(Qt.ItemDataRole.UserRole) or index.text() or "未知设备"
        dtype = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        glyph = index.data(Qt.ItemDataRole.UserRole + 2) or DEFAULT_DEVICE_GLYPH

        x = rect.left() + 7
        icon_rect = QRectF(x, rect.top() + rect.height() / 2 - 10, 20, 20)
        paint_glyph(painter, glyph, icon_rect, QColor("#FFFFFF" if selected else TEXT))

        text_x = icon_rect.right() + 7
        right = rect.right() - 6

        f_alias = type_font("itemTitle")
        painter.setFont(f_alias)
        painter.setPen(QColor("#FFFFFF" if selected else TEXT))
        alias_elided = QFontMetrics(f_alias).elidedText(
            str(alias), Qt.TextElideMode.ElideRight, right - int(text_x)
        )
        painter.drawText(QPoint(int(text_x), rect.top() + 18), alias_elided)

        f_type = type_font("itemSub")
        painter.setFont(f_type)
        # 注意：QColor 不认 CSS 的 "rgba(r,g,b,a)" 字符串（会得到无效色 -> 画成黑色），
        # 半透明白要用整数构造函数。
        painter.setPen(QColor(255, 255, 255, 230) if selected else QColor(TEXT_SECONDARY))
        dtype_elided = QFontMetrics(f_type).elidedText(
            str(dtype), Qt.TextElideMode.ElideRight, right - int(text_x)
        )
        painter.drawText(QPoint(int(text_x), rect.top() + 32), dtype_elided)

        painter.restore()


# --------------------------------------------------------------------------- #
# 缩略图（可拖出）
# --------------------------------------------------------------------------- #
class ThumbWidget(QWidget):
    """接收到的单张图片缩略图：右上角有删除键；按住拖出浮窗触发系统级文件拖拽。"""

    delete_requested = Signal()

    def __init__(self, file_path: str, file_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file_path = file_path or ""
        self._file_name = file_name or ""
        self.setFixedSize(THUMB_W, THUMB_CELL_H)
        self.setToolTip(self._file_name or self._file_path)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFont(type_font("caption"))
        self._pixmap = _load_thumb(self._file_path, THUMB_W, THUMB_IMG_H)
        self._press_pos: QPoint | None = None

        # 删除键：常显（照片上的删除键要一眼看见），悬停变错误色
        self._delete_btn = _GlyphButton(
            "close",
            "移除这张图",
            size=DELETE_BTN,
            color="#FFFFFF",
            hover_color="#FFFFFF",
            parent=self,
            tone="dark",
            hover_tone="danger",
        )
        self._delete_btn.setObjectName("thumbDelete")
        self._delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._delete_btn.clicked.connect(self.delete_requested.emit)
        self._delete_btn.move(THUMB_W - DELETE_BTN - DELETE_INSET, DELETE_INSET)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        card = QRectF(0, 0, w, h)
        path = glass_path(card, RADIUS_CARD)

        # 内容是内容：照片瓦片只留「低透的面 + 发丝线」，不套玻璃光影 —— 玻璃只做点缀。
        # 图片压在上面，露出来的只有文件名条；面要实到压得住背后杂色，文件名才不糊。
        paint_glass(
            p,
            card,
            RADIUS_CARD,
            tint=QColor(255, 255, 255),
            alpha=GLASS_SURFACE,
            gloss=False,
            specular=False,
            aberration=False,
            rim=False,
        )
        p.setPen(QPen(wash(HAIRLINE_ALPHA), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card, RADIUS_CARD, RADIUS_CARD)
        p.setClipPath(path)

        img_rect = QRectF(1, 1, w - 2, THUMB_IMG_H - 2)
        if self._pixmap is not None:
            p.drawPixmap(img_rect.toRect(), self._pixmap)
        else:
            p.fillRect(img_rect, wash(CHIP_ALPHA))
            side = 24.0
            paint_glyph(
                p,
                "image",
                QRectF(img_rect.center().x() - side / 2, img_rect.center().y() - side / 2, side, side),
                QColor(TEXT_SECONDARY),
            )

        p.setPen(QColor(TEXT_SECONDARY))
        f = type_font("caption")
        p.setFont(f)
        name_rect = QRectF(6, THUMB_IMG_H + 1, w - 12, THUMB_NAME_H - 2)
        elided = QFontMetrics(f).elidedText(self._file_name, Qt.TextElideMode.ElideRight, int(name_rect.width()))
        p.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        p.end()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if not (e.buttons() & Qt.MouseButton.LeftButton) or self._press_pos is None:
            return
        if (e.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._start_drag()
        self._press_pos = None

    def _start_drag(self) -> None:
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self._file_path)])
        mime.setText(self._file_name or self._file_path)
        drag.setMimeData(mime)
        pm = self.grab()
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(pm.width() // 2, pm.height() // 2))
        drag.exec(Qt.DropAction.CopyAction)


# --------------------------------------------------------------------------- #
# 图片口（右宽栏）：拖入发送 / 拖出缩略图 / 空态
# --------------------------------------------------------------------------- #
class ImagePort(QFrame):
    """图片口：缩略图网格 + 空态；支持拖入图片文件发送。"""

    drop_requested = Signal(list)   # [path, ...]
    reveal_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("imagePort")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setToolTip("把图片拖进来可发给手机")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._columns = GRID_COLUMNS
        self._drag_depth = 0

        # 空态
        self._empty_state = QWidget(self)
        ev = QVBoxLayout(self._empty_state)
        ev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.setSpacing(SPACE_2)
        # 空态提示照参考图（iOS「Clear」）那套排：一个符号 + 一行大标题 + 一行副行，
        # **只有一档不透明度**（都是亮字，差的只是字号），周围不垫底也不描边 ——
        # 图片口是整窗最透的地方，垫什么都是一块看得见的板，加描边就是字周围多出一圈。
        icon = _GlyphLabel("image", 40, HINT_TEXT, self._empty_state)
        title = apply_type(QLabel("手机发来的图", self._empty_state), "emptyTitle")
        title.setObjectName("emptyMain")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = apply_type(QLabel("会出现在这里", self._empty_state), "emptySub")
        sub.setObjectName("emptySub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(icon)
        ev.addWidget(title)
        ev.addWidget(sub)

        # 缩略图网格（滚动）
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll.viewport().setAutoFillBackground(False)
        # QScrollArea 会拦截拖放事件，导致拖入图片无法到达 ImagePort；
        # 用事件过滤器把 viewport 的拖放事件转发给 ImagePort。
        self._scroll.setAcceptDrops(False)
        self._scroll.viewport().setAcceptDrops(False)
        self._scroll.installEventFilter(self)
        self._scroll.viewport().installEventFilter(self)

        self._grid_host = QWidget()
        self._grid_host.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        self._grid.setHorizontalSpacing(GRID_GAP)
        self._grid.setVerticalSpacing(GRID_GAP)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self._grid_host)

        # 拖入提示浮层（透明于鼠标）
        self._drop_overlay = QLabel("松开以发送到所选设备", self)
        self._drop_overlay.setObjectName("dropOverlay")
        self._drop_overlay.setFont(type_font("drop"))
        self._drop_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._drop_overlay.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._scroll)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._empty_state.setGeometry(self.rect())
        self._drop_overlay.setGeometry(self.rect().adjusted(6, 6, -6, -6))

    # -- 拖入文件 -> 发送 --
    def eventFilter(self, obj, ev):  # noqa: N802
        t = ev.type()
        if t == QEvent.Type.DragEnter:
            self.dragEnterEvent(ev)
            return True
        if t == QEvent.Type.DragMove:
            self.dragMoveEvent(ev)
            return True
        if t == QEvent.Type.Drop:
            self.dropEvent(ev)
            return True
        if t == QEvent.Type.DragLeave:
            self.dragLeaveEvent(ev)
            return True
        return super().eventFilter(obj, ev)

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            self._drag_depth += 1
            e.acceptProposedAction()
            self._drop_overlay.show()
            self._drop_overlay.raise_()

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._drag_depth = max(0, self._drag_depth - 1)
        if self._drag_depth == 0:
            self._drop_overlay.hide()
        e.accept()

    def dropEvent(self, e) -> None:  # noqa: N802
        self._drag_depth = 0
        self._drop_overlay.hide()
        paths = []
        for url in e.mimeData().urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())
        if paths:
            self.drop_requested.emit(paths)
        e.acceptProposedAction()

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        self.reveal_requested.emit()
        e.accept()


# --------------------------------------------------------------------------- #
# 隔空投送模块卡片（左侧功能键）：点圆钮开关，点卡片选可接收对象
# --------------------------------------------------------------------------- #
class AirdropCard(QWidget):
    """对齐 Apple 隔空投送模块：圆钮 + 标题 + 取值行（所有人 ⌄），整卡可点。

    两个热区各司其职（与系统隔空投送一致）：左上圆钮 = 开 / 关，
    其余区域 = 展开「可接收对象」菜单；两者都有 tooltip 交代，不必猜。
    """

    toggle_requested = Signal()
    menu_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("点圆钮开 / 关隔空投送；点卡片选择可接收对象")
        follow_light(self)

        self._enabled = False
        self._hover = False
        self._pressed = False
        self._icon_hover = False
        self._icon_pressed = False

        self._title = apply_type(QLabel("隔空投送", self), "cardTitle")
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._value_label = apply_type(QLabel(MODE_LABELS["off"], self), "cardValue")
        self._value_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._place_text()

    # -- 状态（真相永远在 AirFloatWindow._state，本控件只负责显示）--

    def set_state(self, enabled: bool, value: str) -> None:
        self._enabled = bool(enabled)
        if self._value_label.text() != value:
            self._value_label.setText(value)
            self._value_label.adjustSize()
        self._place_text()
        self.update()

    # -- 几何 --

    def _icon_rect(self) -> QRectF:
        return QRectF(SPACE_3 + 2, SPACE_3 + 2, CARD_ICON, CARD_ICON)

    def _place_text(self) -> None:
        left = SPACE_3 + 2
        self._title.adjustSize()
        self._value_label.adjustSize()
        self._value_label.move(left, CARD_H - SPACE_3 - self._value_label.height())
        self._title.move(left, self._value_label.y() - self._title.height() - 1)

    # -- 绘制 --

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)

        # 控件玻璃：卡片是「能摸的东西」，走半透那一档（比内容面透），玻璃才有呼吸感；
        # 悬停更实、按下更透 —— 反馈由面与光一起交代。
        # 液态玻璃：镜面边缘光 + 顶部光泽 + 左上镜面热点。
        # 不套边缘色差：色差是「玻璃压在桌面上」才成立的折射彩边；压在**浅色卡片**上就成了
        # 白边旁的一道粉 / 蓝重影（实测 R/B 差 14/255，肉眼可见的脏）。卡片是浅色实体面，
        # 立体感交给边缘光与光泽就够了。
        card_pressed = self._pressed and not self._icon_pressed
        if card_pressed:
            alpha, lit = CONTROL_GLASS_PRESSED, GLASS_LIT_PRESSED   # 按下就变，不等抬起
        elif self._hover:
            alpha, lit = CONTROL_GLASS_HOVER, GLASS_LIT_HOVER
        else:
            alpha, lit = CONTROL_GLASS, GLASS_LIT_REST
        paint_glass(
            p,
            rect,
            RADIUS_CARD,
            tint=QColor(255, 255, 255),
            alpha=alpha,
            lit=lit,
            pressed=card_pressed,
            aberration=False,
        )

        # 圆钮：开 = 强调蓝（其上白色字形 5.46:1），关 = 中性灰（4.82:1）
        icon = self._icon_rect()
        fill = QColor(ACCENT_ICON if self._enabled else OFFLINE)
        if self._icon_pressed:
            fill = fill.darker(112)
        elif self._icon_hover:
            fill = fill.lighter(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawEllipse(icon)
        # 圆钮也是一枚小透镜：压一层高光，否则像贴纸
        paint_glass(p, icon, icon.width() / 2.0, lit=GLASS_LIT_LENS, aberration=False)
        paint_glyph(p, "airdrop", icon.adjusted(SPACE_3, SPACE_3, -SPACE_3, -SPACE_3), QColor("#FFFFFF"))

        # 取值行尾的展开提示
        geo = self._value_label.geometry()
        paint_glyph(
            p,
            "chevron",
            QRectF(geo.right() + SPACE_1, geo.top(), 12, max(12, geo.height())),
            QColor(TEXT_SECONDARY),
        )

        # 自绘控件默认没有焦点环，键盘焦点必须可见
        if self.hasFocus():
            p.setPen(QPen(QColor(ACCENT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), RADIUS_CARD - 1, RADIUS_CARD - 1)
        p.end()

    # -- 交互 --

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._icon_pressed = self._icon_rect().contains(e.position())
        self._pressed = True
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        on_icon = self._icon_pressed
        self._pressed = False
        self._icon_pressed = False
        self.update()
        if e.button() != Qt.MouseButton.LeftButton or not self.rect().contains(e.position().toPoint()):
            return
        if not on_icon:
            self.menu_requested.emit()
        elif self._icon_rect().contains(e.position()):
            self.toggle_requested.emit()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        inside = self._icon_rect().contains(e.position())
        if inside != self._icon_hover:
            self._icon_hover = inside
            self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self._pressed = False
        self._icon_pressed = False
        self._icon_hover = False
        self.update()
        super().leaveEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.menu_requested.emit()
            return
        super().keyPressEvent(e)


# --------------------------------------------------------------------------- #
# 可接收对象弹出菜单（深色材质 + 勾选行）
# --------------------------------------------------------------------------- #
class _MenuPanel(QFrame):
    """菜单底板：深色材质 + 顶边受光。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        follow_light(self)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        # 深色液态玻璃：底色 + 顶部光泽 + 镜面边缘光。
        # lit 压到 0.8：深色面上高光太亮会发灰，白字对比度反而掉。
        paint_glass(
            p, rect, RADIUS_MENU, tint=QColor(MENU_BG), alpha=MENU_ALPHA, lit=GLASS_LIT_MENU
        )
        p.end()


class _ModeRow(QWidget):
    """菜单行：勾选列 + 文字；悬停 / 按下 / 选中三态各自可见。"""

    chosen = Signal(str)

    def __init__(self, mode: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._selected = False
        self._hover = False
        self._pressed = False
        self.setFixedHeight(MENU_ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)
        follow_light(self)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(SPACE_3, 0, SPACE_3, 0)
        lay.setSpacing(SPACE_3)
        self._label = apply_type(QLabel(label, self), "menuRow")
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addSpacing(16)            # 勾选列：选中行才画勾，文字位置不动
        lay.addWidget(self._label)
        lay.addStretch(1)
        self._apply_text_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self._apply_text_style()
        self.update()

    def _apply_text_style(self) -> None:
        color = "rgba(255, 255, 255, 255)" if self._selected else "rgba(255, 255, 255, 226)"
        self._label.setStyleSheet(f"color: {color}; background: transparent;")

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        if self._hover or self._pressed:
            paint_glass(
                p,
                rect,
                RADIUS_CONTROL,
                tint=QColor(255, 255, 255),
                alpha=MENU_ROW_PRESSED if self._pressed else MENU_ROW_HOVER,
                lit=GLASS_LIT_MENU_ROW,
                pressed=self._pressed,
                specular=False,
                aberration=False,
            )
        if self._selected:
            paint_glyph(
                p, "check", QRectF(SPACE_3 - 1, (self.height() - 13) / 2.0, 13, 13), QColor("#FFFFFF")
            )
        if self.hasFocus():
            p.setPen(QPen(QColor(255, 255, 255, 150), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, RADIUS_CONTROL, RADIUS_CONTROL)
        p.end()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        pressed = self._pressed
        self._pressed = False
        self.update()
        if pressed and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.chosen.emit(self._mode)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        inside = self.rect().contains(e.position().toPoint())
        if inside != self._hover:
            self._hover = inside
            self.update()

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.chosen.emit(self._mode)
            return
        super().keyPressEvent(e)


class _ModePopup(QWidget):
    """可接收对象菜单：锚在触发它的卡片下方（菜单从来源处「长出来」）。"""

    mode_chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._current = MODE_ORDER[0]
        self._panel = _MenuPanel(self)
        shadow = QGraphicsDropShadowEffect(self._panel)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 7)
        shadow.setColor(QColor(12, 14, 18, 85))
        self._panel.setGraphicsEffect(shadow)

        inner = QVBoxLayout(self._panel)
        inner.setContentsMargins(MENU_PAD, MENU_PAD, MENU_PAD, MENU_PAD)
        inner.setSpacing(0)
        self._rows: dict[str, _ModeRow] = {}
        for mode in MODE_ORDER:
            row = _ModeRow(mode, MODE_LABELS[mode], self._panel)
            row.chosen.connect(self._on_chosen)
            self._rows[mode] = row
            inner.addWidget(row)
        self._panel.setFixedWidth(MENU_W)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MENU_SHADOW, MENU_SHADOW, MENU_SHADOW, MENU_SHADOW)
        outer.setSpacing(0)
        outer.addWidget(self._panel)

        # 出现时「材质化」而不是硬切：淡入 + 自上而下 6px 长出
        duration = 150 if animations_enabled() else 0
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(duration)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._rise = QPropertyAnimation(self, b"pos", self)
        self._rise.setDuration(duration)
        self._rise.setEasingCurve(QEasingCurve.Type.OutCubic)

    @property
    def rows(self) -> dict:
        return self._rows

    def _on_chosen(self, mode: str) -> None:
        self.mode_chosen.emit(mode)
        self.close()

    def popup_at(self, anchor: QPoint, current: str) -> None:
        """anchor = 卡片左下角的全局坐标。放不下就翻到卡片上方，并让出屏幕边。"""
        self._current = current
        for mode, row in self._rows.items():
            row.set_selected(mode == current)
        self.adjustSize()
        target = QPoint(anchor.x() - MENU_SHADOW - SPACE_1, anchor.y() - MENU_SHADOW)
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            if target.x() + self.width() > area.right() + 1:
                target.setX(area.right() + 1 - self.width())
            if target.y() + self.height() > area.bottom() + 1:
                target.setY(anchor.y() - self.height() + MENU_SHADOW + SPACE_1)
            target.setX(max(area.left(), target.x()))
            target.setY(max(area.top(), target.y()))
        self.move(target)
        self.show()
        self.raise_()
        if animations_enabled():
            self.setWindowOpacity(0.0)
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
            self._rise.stop()
            self._rise.setStartValue(QPoint(target.x(), target.y() - 6))
            self._rise.setEndValue(target)
            self._rise.start()
        else:
            self.setWindowOpacity(1.0)
        # 焦点交给菜单本身：打开时不高亮任何一行（否则选中行会多一圈焦点环）。
        # 用方向键浏览时才逐行给焦点，键盘可见性照旧。
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        # 投影留白是透明的：点在留白上应当关掉菜单，而不是被吞掉
        if not self._panel.geometry().contains(e.position().toPoint()):
            self.close()
            return
        super().mousePressEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            focused = next((row for row in self._rows.values() if row.hasFocus()), None)
            if focused is not None:
                focused.chosen.emit(focused._mode)
            else:
                self._on_chosen(self._current)
            return
        if e.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            order = list(self._rows.values())
            if order:
                focused = next((i for i, row in enumerate(order) if row.hasFocus()), None)
                step = -1 if e.key() == Qt.Key.Key_Up else 1
                index = 0 if focused is None else (focused + step) % len(order)
                order[index].setFocus(Qt.FocusReason.TabFocusReason)
            return
        super().keyPressEvent(e)


# --------------------------------------------------------------------------- #
# 顶栏（无边框窗口拖拽区 + 打开接收目录 + 关闭）
# --------------------------------------------------------------------------- #
class TopBar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TOPBAR_H)
        self.setMouseTracking(True)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            if isinstance(window, AirFloatWindow):
                # 上边缘也要能缩放：先给缩放热区一次机会，再退回「拖动窗口」
                local = self.mapTo(window, e.position().toPoint())
                if window._try_resize_at(local, e.globalPosition().toPoint()):
                    e.accept()
                    return
                window._begin_move(e.globalPosition().toPoint())
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        window = self.window()
        if isinstance(window, AirFloatWindow):
            if window._move_session is not None:
                window._apply_move(e.globalPosition().toPoint())
                e.accept()
                return
            window._update_resize_cursor(self.mapTo(window, e.position().toPoint()))
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        window = self.window()
        if isinstance(window, AirFloatWindow) and window._move_session is not None:
            window._end_move()
            e.accept()
            return
        super().mouseReleaseEvent(e)


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #
class AirFloatWindow(QWidget):
    """AirFloat 主窗口。"""

    # -- 公开信号（供 main.py 连接）--
    send_files_requested = Signal(list)   # 拖入图片后：文件路径列表
    receive_mode_changed = Signal(str)    # everyone / contacts / off
    enabled_changed = Signal(bool)        # 隔空投送开关
    reveal_cache_requested = Signal()     # 打开接收目录
    device_selected = Signal(str)         # 选中设备的 fingerprint
    send_pending_requested = Signal(list) # 点击「发送」按钮：待发送图片路径列表

    # -- 内部信号：把协议回调 marshal 到主线程（AutoConnection 跨线程自动排队）--
    _sig_received = Signal(object)
    _sig_devices = Signal(object)
    _sig_state = Signal(object)
    _sig_progress = Signal(object)
    _sig_toast = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("airfloatWindow")
        self.setWindowTitle("AirFloat")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(*MIN_WINDOW))
        self.resize(QSize(*DEFAULT_WINDOW))
        self.setStyleSheet(QSS)
        # 让窗口自身可持有焦点：启动时焦点环不落在某个次要按钮上（键盘 Tab 时仍可见）
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # -- 材质 / 几何 --
        self._material = GlassMaterial()
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._glass_ready = False
        self._resize_session: dict | None = None
        self._move_session: dict | None = None
        self._resize_settle = QTimer(self)
        self._resize_settle.setSingleShot(True)
        self._resize_settle.timeout.connect(self._material.resume)

        # -- 指针光 / 内容环境光（让玻璃「活着」）--
        # 整块界面只有**一个光源**：指针在哪，光就从哪来。装应用级过滤器而不是靠事件
        # 冒泡 —— 按下的控件会把鼠标移动吃掉（按钮要处理「拖出去就取消」），光会卡住。
        self._light = pointer_light()
        follow_light(self)
        QApplication.instance().installEventFilter(self)
        # 内容环境光：收到的照片把颜色借给玻璃一点，整片慢慢染过去（见 _settle_ambient）
        self._ambient_color: QColor | None = None
        self._ambient_level = 0.0
        self._ambient = QVariantAnimation(self)
        self._ambient.setDuration(AMBIENT_SETTLE_MS if animations_enabled() else 0)
        self._ambient.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._ambient.valueChanged.connect(self._on_ambient_value)

        # -- 状态 --
        self._protocol = None
        self._state = {"enabled": False, "receiveMode": "everyone", "alias": ""}
        self._devices: list[dict] = []
        self._selected_fingerprint: str | None = None
        self._received_items: list[dict] = []
        self._pending_send: list[str] = []
        self._updating_devices = False
        self._airfloat_send_handler = None  # main.py 注入：点「发送」时直接调用

        self._build_ui()
        self._wire_signals()

        # -- 内部 marshal 连接 --
        self._sig_received.connect(self._apply_received)
        self._sig_devices.connect(self._apply_devices)
        self._sig_state.connect(self._apply_state)
        self._sig_progress.connect(self._apply_progress)
        self._sig_toast.connect(self._apply_toast)

        self._update_status()

    # ------------------------------------------------------------------ #
    # 构建 UI
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        # 玻璃铺满整窗：不再留 GUTTER 画投影（投影留白会挡住背后的模糊）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._body = QFrame(self)
        self._body.setObjectName("windowBody")
        self._body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self._body)

        root = QVBoxLayout(self._body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏：品牌 + 本机别名 + 打开接收目录 + 关闭（无边框窗口的拖拽区）
        topbar = TopBar(self._body)
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(SPACE_3, 0, SPACE_2, 0)
        tb.setSpacing(SPACE_2)
        brand = apply_type(QLabel("AirFloat", topbar), "brand")
        brand.setObjectName("brandName")
        self._self_alias_label = apply_type(QLabel("", topbar), "alias")
        self._self_alias_label.setObjectName("selfAlias")
        self._self_alias_label.setVisible(False)
        self._folder_btn = _GlyphButton("folder", "打开接收目录", parent=topbar)
        self._folder_btn.setObjectName("folderBtn")
        self._close_btn = _GlyphButton(
            "close",
            "关闭窗口",
            color=TEXT,
            hover_color="#FFFFFF",
            parent=topbar,
            hover_tone="danger",
        )
        self._close_btn.setObjectName("closeBtn")
        tb.addWidget(brand)
        tb.addWidget(self._self_alias_label)
        tb.addStretch(1)
        tb.addWidget(self._folder_btn)
        tb.addWidget(self._close_btn)
        root.addWidget(topbar)

        # 主体（两栏）
        main = QHBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # 左窄栏
        # 侧栏是结构分区：整窗是透的，栏内的字靠这层浅面托住 —— 比内容区亮一档
        # 就是「更厚」，分区靠材质立，不靠描边。
        sidebar = GlassSurface(self._body, tint=QColor(CARD), alpha=SIDEBAR_FACE, gloss=False)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(SIDEBAR_W)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
        sb.setSpacing(0)

        # ① 隔空投送模块卡片：开关与「可接收对象」合到一处（对齐 Apple 隔空投送模块）
        self._card = AirdropCard(sidebar)
        sb.addWidget(self._card, 0, Qt.AlignmentFlag.AlignLeft)
        sb.addSpacing(SPACE_5)

        # ② 附近设备
        dev_title = apply_type(QLabel("附近设备", sidebar), "groupTitle")
        dev_title.setObjectName("groupTitle")
        sb.addWidget(dev_title)
        sb.addSpacing(SPACE_1)

        self._device_list = QListWidget(sidebar)
        self._device_list.setObjectName("deviceList")
        self._device_list.setItemDelegate(DeviceItemDelegate(self._device_list))
        self._device_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._device_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._device_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._device_list.setSpacing(2)
        self._device_list.setCursor(Qt.CursorShape.PointingHandCursor)

        # 列表空着就空着：原因由状态栏那一条唯一的口径交代，侧栏不再重复同样一句话。
        sb.addWidget(self._device_list, 1)

        main.addWidget(sidebar)

        # 右宽栏「图片口」
        self._image_port = ImagePort(self._body)
        main.addWidget(self._image_port, 1)

        root.addLayout(main, 1)

        # 底部状态栏
        statusbar = QFrame(self._body)
        statusbar.setObjectName("statusbar")
        statusbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        statusbar.setFixedHeight(STATUSBAR_H)
        st = QHBoxLayout(statusbar)
        st.setContentsMargins(SPACE_3, 0, SPACE_3, 0)
        st.setSpacing(SPACE_2)

        self._progress_container = QWidget(statusbar)
        pc = QHBoxLayout(self._progress_container)
        pc.setContentsMargins(0, 0, 0, 0)
        pc.setSpacing(SPACE_2)
        self._progress = QProgressBar(self._progress_container)
        self._progress.setObjectName("sendProgress")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedSize(100, 6)
        self._progress_label = apply_type(QLabel("", self._progress_container), "status")
        self._progress_label.setObjectName("progressLabel")
        pc.addWidget(self._progress)
        pc.addWidget(self._progress_label)
        self._progress_container.setVisible(False)
        st.addWidget(self._progress_container)

        self._status_hint = apply_type(QLabel("", statusbar), "status")
        self._status_hint.setObjectName("statusHint")
        st.addWidget(self._status_hint, 1)

        self._received_count = apply_type(QLabel("", statusbar), "status")
        self._received_count.setObjectName("receivedCount")
        self._received_count.setVisible(False)
        st.addWidget(self._received_count)

        self._send_btn = _SendButton(statusbar)
        self._send_btn.setObjectName("sendBtn")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setFixedSize(SEND_BTN, SEND_BTN)
        apply_type(self._send_btn, "button")
        self._send_btn.clicked.connect(self._on_send_clicked)
        st.addWidget(self._send_btn)

        root.addWidget(statusbar)

        # Toast（浮层）
        self._toast_label = apply_type(QLabel("", self), "toast")
        self._toast_label.setObjectName("toast")
        self._toast_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast_label.setVisible(False)
        self._toast_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._toast_opacity = QGraphicsOpacityEffect(self._toast_label)
        self._toast_opacity.setOpacity(0.0)
        self._toast_label.setGraphicsEffect(self._toast_opacity)
        self._toast_fade = QPropertyAnimation(self._toast_opacity, b"opacity", self)
        self._toast_fade.setDuration(160 if animations_enabled() else 0)
        self._toast_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._toast_fade.finished.connect(self._on_toast_faded)
        self._toast_rise = QPropertyAnimation(self._toast_label, b"pos", self)
        self._toast_rise.setDuration(200 if animations_enabled() else 0)
        self._toast_rise.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_toast)

        # 可接收对象菜单：Qt.Popup 自己处理「点外面 / Esc 关闭」，不必额外转发事件
        self._menu = _ModePopup(self)

        # 进度隐藏定时器
        self._progress_timer = QTimer(self)
        self._progress_timer.setSingleShot(True)
        self._progress_timer.timeout.connect(self._on_progress_hidden)

    def _wire_signals(self) -> None:
        self._card.toggle_requested.connect(self._toggle_enabled)
        self._card.menu_requested.connect(self._open_mode_menu)
        self._menu.mode_chosen.connect(self._on_mode_chosen)
        self._device_list.currentItemChanged.connect(self._on_device_current)
        self._folder_btn.clicked.connect(lambda: self.reveal_cache_requested.emit())
        self._close_btn.clicked.connect(self.close)
        self._image_port.drop_requested.connect(self._on_drop_paths)
        self._image_port.reveal_requested.connect(lambda: self.reveal_cache_requested.emit())

    # ------------------------------------------------------------------ #
    # 内部事件
    # ------------------------------------------------------------------ #
    # -- 隔空投送模块：开关 / 可接收对象 --

    def _display_mode(self) -> str:
        """当前要展示的取值：关掉隔空投送就等于「接收关闭」。"""
        if not self._state.get("enabled"):
            return "off"
        mode = self._state.get("receiveMode") or DEFAULT_MODE
        return mode if mode in MODE_LABELS else DEFAULT_MODE

    def _sync_card(self) -> None:
        self._card.set_state(bool(self._state.get("enabled")), MODE_LABELS[self._display_mode()])

    def _toggle_enabled(self) -> None:
        """圆钮：开 / 关。关掉不改动 receiveMode，再打开就回到上次的选择（与系统一致）。"""
        enabled = not self._state.get("enabled")
        self._state["enabled"] = enabled
        self.enabled_changed.emit(enabled)
        self._sync_card()
        self._update_status()

    def _open_mode_menu(self) -> None:
        anchor = self._card.mapToGlobal(QPoint(0, self._card.height()))
        self._menu.popup_at(anchor, self._display_mode())

    def _on_mode_chosen(self, mode: str) -> None:
        if mode not in MODE_LABELS:
            return
        if mode == "off":
            if self._state.get("enabled"):
                self._state["enabled"] = False
                self.enabled_changed.emit(False)
        else:
            if not self._state.get("enabled"):
                self._state["enabled"] = True
                self.enabled_changed.emit(True)
            if self._state.get("receiveMode") != mode:
                self._state["receiveMode"] = mode
                self.receive_mode_changed.emit(mode)
        self._sync_card()
        self._update_status()

    def _on_device_current(self, current: QListWidgetItem | None, _previous) -> None:
        if self._updating_devices:
            return
        if current is not None:
            fp = current.data(Qt.ItemDataRole.UserRole + 3)
            self._selected_fingerprint = fp or None
            if fp:
                self.device_selected.emit(fp)
        else:
            self._selected_fingerprint = None
        self._update_status()

    def _on_drop_paths(self, paths: list) -> None:
        import os
        # 收集图片文件（支持拖入单个图片文件，或整个文件夹）
        img_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif"}
        files = []
        for p in paths:
            if not isinstance(p, str):
                continue
            if os.path.isfile(p):
                files.append(p)
            elif os.path.isdir(p):
                try:
                    for root, _dirs, fs in os.walk(p):
                        for f in fs:
                            fp = os.path.join(root, f)
                            if os.path.isfile(fp) and os.path.splitext(f)[1].lower() in img_exts:
                                files.append(fp)
                except Exception:
                    pass
        added = []
        for fp in files:
            self._received_items.append({"file_path": fp, "file_name": os.path.basename(fp)})
            self._pending_send.append(fp)
            added.append(fp)
        if self._received_items:
            self._render_thumbs()
            self._update_received_count()
        if added:
            self.show_toast(f"已加入 {len(added)} 张，选中设备后点「发送」", "success")
        else:
            self.show_toast("没有识别到图片，请拖图片文件（jpg/png 等）", "error")

    def _on_send_clicked(self) -> None:
        if not self._pending_send:
            self.show_toast("没有待发送的图片，先拖图进来", "error")
            return
        if not self.selected_device():
            self.show_toast("请先在左侧选择要发送的设备", "error")
            return
        paths = list(self._pending_send)
        self._pending_send.clear()
        if self._airfloat_send_handler is not None:
            self._airfloat_send_handler(paths)
        else:
            self.send_pending_requested.emit(paths)

    # ------------------------------------------------------------------ #
    # 渲染
    # ------------------------------------------------------------------ #
    def _apply_devices(self, devices) -> None:
        self._updating_devices = True
        try:
            self._devices = [d for d in (devices or []) if isinstance(d, dict)]
            lst = self._device_list
            lst.blockSignals(True)
            lst.clear()
            for d in self._devices:
                fp = d.get("fingerprint")
                alias = d.get("alias") or "未知设备"
                dtype = d.get("device_type") or ""
                it = QListWidgetItem()
                it.setText(alias)
                it.setData(Qt.ItemDataRole.UserRole, alias)
                it.setData(Qt.ItemDataRole.UserRole + 1, dtype)
                it.setData(Qt.ItemDataRole.UserRole + 2, device_glyph(dtype))
                it.setData(Qt.ItemDataRole.UserRole + 3, fp)
                it.setToolTip(f"{alias} · {dtype}")
                lst.addItem(it)
            lst.blockSignals(False)

            # 恢复选中
            if self._selected_fingerprint:
                found = False
                for i in range(lst.count()):
                    it = lst.item(i)
                    if it.data(Qt.ItemDataRole.UserRole + 3) == self._selected_fingerprint:
                        lst.setCurrentItem(it)
                        found = True
                        break
                if not found:
                    self._selected_fingerprint = None

            self._device_list.setVisible(True)
        finally:
            self._updating_devices = False
        self._update_status()

    def _apply_received(self, item) -> None:
        if not isinstance(item, dict):
            return
        self._received_items.append(item)
        if len(self._received_items) > 500:
            self._received_items = self._received_items[-500:]
        self._render_thumbs()
        self._settle_ambient(item)
        self._update_received_count()
        self.show_toast(f"已接收：{item.get('file_name') or item.get('fileName') or '图片'}", "success")

    def _apply_state(self, state) -> None:
        if not isinstance(state, dict):
            return
        if "enabled" in state:
            self._set_enabled_ui(bool(state["enabled"]))
        mode = state.get("receiveMode", state.get("receive_mode"))
        if mode:
            self._set_mode_ui(str(mode))
        if "alias" in state:
            alias = str(state.get("alias") or "")
            self._state["alias"] = alias
            self._self_alias_label.setText(f"· {alias}" if alias else "")
            self._self_alias_label.setVisible(bool(alias))
        self._update_status()

    def _apply_progress(self, ev) -> None:
        if not isinstance(ev, dict):
            return
        name = ev.get("file_name") or ev.get("fileName") or ""
        sent = ev.get("sent_bytes", ev.get("sentBytes", 0)) or 0
        total = ev.get("total_bytes", ev.get("totalBytes", 0)) or 0
        pct = round(sent * 100 / total) if total > 0 else 0
        pct = max(0, min(100, pct))
        self._progress.setValue(pct)
        # 收窄文案，避免与状态提示在同一行里挤成一团（Apple：标签要简洁）
        self._progress_label.setText(self._elide(f"{pct}%  {name}", 100, self._progress_label.font()))
        self._set_progress_visible(True)
        self._progress_timer.stop()
        if pct >= 100:
            self._progress_timer.start(1200)

    def _on_progress_hidden(self) -> None:
        self._set_progress_visible(False)

    def _set_progress_visible(self, visible: bool) -> None:
        """进度与状态提示/计数互斥。

        状态栏只有 336px；传输时只留当前最相关的一条信息，避免三样并排挤成一团。
        """
        self._progress_container.setVisible(visible)
        self._status_hint.setVisible(not visible)
        if visible:
            self._received_count.setVisible(False)
        else:
            self._update_received_count()

    def _apply_toast(self, payload) -> None:
        if not isinstance(payload, dict):
            return
        msg = str(payload.get("msg") or "")
        kind = str(payload.get("kind") or "")
        self._toast_fade.stop()
        self._toast_rise.stop()
        self._toast_label.setProperty("kind", kind)
        self._toast_label.style().unpolish(self._toast_label)
        self._toast_label.style().polish(self._toast_label)
        self._toast_label.setText(msg)
        self._toast_label.adjustSize()
        self._toast_label.setVisible(True)
        self._toast_label.raise_()
        self._position_toast()
        # 入场：淡入 + 轻微上浮（Apple：别只是「啪」地出现）
        end = self._toast_label.pos()
        self._toast_rise.setStartValue(QPoint(end.x(), end.y() + 8))
        self._toast_rise.setEndValue(end)
        self._toast_rise.start()
        self._toast_fade.setStartValue(self._toast_opacity.opacity())
        self._toast_fade.setEndValue(1.0)
        self._toast_fade.start()
        self._toast_timer.start(3200)

    def _hide_toast(self) -> None:
        """出场：先淡出再隐藏，避免生硬消失。"""
        self._toast_fade.stop()
        self._toast_fade.setStartValue(self._toast_opacity.opacity())
        self._toast_fade.setEndValue(0.0)
        self._toast_fade.start()

    def _on_toast_faded(self) -> None:
        if self._toast_opacity.opacity() <= 0.001:
            self._toast_label.setVisible(False)

    def _render_thumbs(self) -> None:
        while self._image_port._grid.count():
            it = self._image_port._grid.takeAt(0)
            w = it.widget()
            if w is not None:
                # deleteLater 要等事件循环空闲才真正销毁：先摘下来并隐藏，
                # 否则这一帧里旧缩略图仍挂在原位，会和重排后的新图叠在一起
                #（连收几张图、或缩放窗口触发重排时都能看到）。
                w.hide()
                w.setParent(None)
                w.deleteLater()
        has = bool(self._received_items)
        self._image_port._empty_state.setVisible(not has)
        if not has:
            self._clear_ambient()
            return
        for idx, item in enumerate(self._received_items):
            path = item.get("file_path") or item.get("filePath") or ""
            name = item.get("file_name") or item.get("fileName") or ""
            tw = ThumbWidget(path, name)
            tw.delete_requested.connect(lambda item=item: self._remove_item(item))
            r, c = divmod(idx, self._image_port._columns)
            self._image_port._grid.addWidget(tw, r, c)

    # -- 内容环境光：收到的照片把颜色借给玻璃一点（整片慢慢染过去）--
    def _settle_ambient(self, item: dict) -> None:
        """新图进来：先退一点再重新染上去（呼吸），而不是「啪」地换色。"""
        path = item.get("file_path") or item.get("filePath") or ""
        color = _average_color(_load_thumb(path, AMBIENT_PROBE, AMBIENT_PROBE))
        if color is None:
            return
        self._ambient_color = color
        self._ambient.stop()
        self._ambient.setStartValue(self._ambient_level * AMBIENT_DIP)
        self._ambient.setEndValue(1.0)
        self._ambient.start()
        if self._ambient.duration() == 0:
            self._on_ambient_value(1.0)

    def _clear_ambient(self) -> None:
        """内容清空了：玻璃上的染色慢慢退掉，不留一块没来由的色。"""
        if self._ambient_color is None:
            return
        self._ambient.stop()
        self._ambient.setStartValue(self._ambient_level)
        self._ambient.setEndValue(0.0)
        self._ambient.start()
        if self._ambient.duration() == 0:
            self._on_ambient_value(0.0)

    def _on_ambient_value(self, value) -> None:
        self._ambient_level = float(value)
        if self._ambient_level <= 0.001 and self._ambient.endValue() == 0.0:
            self._ambient_color = None       # 退干净了就把颜色扔掉，避免空转重绘
        self.update()

    def _remove_item(self, item: dict) -> None:
        """删除键：只把这张从列表里拿掉，不动磁盘上的文件（不替用户决定删文件）。"""
        for index, candidate in enumerate(self._received_items):
            if candidate is item:
                del self._received_items[index]
                break
        else:
            return
        path = item.get("file_path") or item.get("filePath") or ""
        if path in self._pending_send:
            self._pending_send.remove(path)
        name = item.get("file_name") or item.get("fileName") or "图片"
        self._render_thumbs()
        self._update_received_count()
        self.show_toast(f"已移除：{name}")

    def _sync_columns(self) -> None:
        """列数跟着窗口宽度走：放大就多排几张，缩回去也不会溢出。"""
        port_w = max(0, self.width() - SIDEBAR_W)
        columns = max(1, (port_w - 2 * SPACE_2 - 8 + GRID_GAP) // (THUMB_W + GRID_GAP))
        if columns != self._image_port._columns:
            self._image_port._columns = int(columns)
            self._render_thumbs()

    def _update_received_count(self) -> None:
        n = len(self._received_items)
        self._received_count.setText(f"已接收 {n} 张")
        self._received_count.setVisible(n > 0)

    def _update_status(self) -> None:
        if not self._state.get("enabled"):
            hint = "隔空投送已关闭"
        elif self.selected_device():
            hint = "将发送到：" + (self.selected_device().get("alias") or "设备")
        elif self._devices:
            hint = "选择左侧设备以发送"
        else:
            hint = "未发现手机，请确认同一 WiFi"
        self._status_hint.setText(hint)

    def _set_enabled_ui(self, enabled: bool) -> None:
        self._state["enabled"] = bool(enabled)
        self._sync_card()

    def _set_mode_ui(self, mode: str) -> None:
        if mode not in MODE_LABELS:
            return
        self._state["receiveMode"] = mode
        self._sync_card()

    def _position_toast(self) -> None:
        # 窗口可缩放：Toast 按当前尺寸居中，不再依赖固定常数
        lw = self._toast_label.width()
        lh = self._toast_label.height()
        x = (self.width() - lw) // 2
        y = self.height() - lh - STATUSBAR_H - SPACE_3
        self._toast_label.move(max(0, x), max(0, y))

    @staticmethod
    def _elide(text: str, width: int, font) -> str:
        return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, width)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._update_region()
        self._position_toast()
        self._sync_columns()
        if self._resize_session is not None:
            self._material.suspend()
            self._resize_settle.start(RESIZE_SETTLE_MS)

    def changeEvent(self, e) -> None:  # noqa: N802
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._update_region)

    def _owns(self, widget: QWidget) -> bool:
        """这个控件算不算本窗口的？

        不能只用 ``isAncestorOf``：弹出菜单是 ``Qt.Popup``（有父窗口，但自己是顶层窗口），
        ``isAncestorOf`` 对它返回 False —— 指针移到菜单上时光就会卡住。所以顺着
        ``parentWidget()`` 往上找。
        """
        node: QWidget | None = widget if isinstance(widget, QWidget) else None
        while node is not None:
            if node is self:
                return True
            node = node.parentWidget()
        return False

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """指针光：本窗口里任何一处（含子控件）的移动都点亮**同一个光源**。

        不用 mouseMoveEvent 冒泡：按下的按钮会把移动事件吃掉，光会卡在按钮上不动。
        应用级过滤器看到的每一处移动都算，光才是「整个界面共用一个光源」。
        """
        if (
            event.type() == QEvent.Type.MouseMove
            and isinstance(obj, QWidget)
            and self._owns(obj)
        ):
            self._light.aim_at(self, event.globalPosition())
        return super().eventFilter(obj, event)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        if not self._glass_ready:
            self._glass_ready = True
            # 窗口句柄要 show 之后才成立：材质与圆角裁剪都挂在这一刻
            self._material.attach(int(self.winId()), GLASS_TINT_ABGR)
            self._restore_geometry()
            self._update_region()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def closeEvent(self, e) -> None:  # noqa: N802
        try:
            self._settings.setValue("geometry", self.saveGeometry())
        except Exception:
            pass
        super().closeEvent(e)

    # ------------------------------------------------------------------ #
    # 材质 / 几何（毛玻璃 + 无边框缩放）
    # ------------------------------------------------------------------ #
    def _restore_geometry(self) -> None:
        stored = self._settings.value("geometry")
        if stored is not None:
            self.restoreGeometry(stored)
            return
        self.resize(QSize(*DEFAULT_WINDOW))
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center() - QPoint(self.width() // 2, area.height() // 3))

    def _update_region(self) -> None:
        """窗口内容裁进圆角区域。

        半径由 `_window_radius()` 给：谁在裁那层模糊，圆角就归谁 —— 纯模糊时区域裁得住
        模糊，圆角归我们（想多圆有多圆）；亚克力兜底时模糊由 DWM 画、圆角也归 DWM，
        半径只能跟系统那档。绘制与裁剪取同一个值，四角就不会出现两条不同心的弧。
        """
        if not self._glass_ready:
            return
        self._material.set_rounded(
            self.width(),
            self.height(),
            self._window_radius(),
            self.devicePixelRatioF(),
            enabled=not self.isMaximized(),
        )

    def _window_radius(self) -> int:
        """当前生效的整窗圆角半径（绘制与裁剪共用这一个值）。"""
        material = getattr(self, "_material", None)
        if material is not None and not material.region_clips_backdrop:
            return RADIUS_WINDOW_SYSTEM
        return RADIUS_WINDOW

    def _edges_at(self, pos: QPoint):
        margin = RESIZE_MARGIN
        edges = None
        if pos.x() <= margin:
            edges = Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - margin:
            edges = Qt.Edge.RightEdge
        if pos.y() <= margin:
            edges = Qt.Edge.TopEdge if edges is None else edges | Qt.Edge.TopEdge
        elif pos.y() >= self.height() - margin:
            edges = Qt.Edge.BottomEdge if edges is None else edges | Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for(edges):
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def _update_resize_cursor(self, pos: QPoint) -> None:
        edges = None if self.isMaximized() else self._edges_at(pos)
        if edges:
            self.setCursor(self._cursor_for(edges))
        else:
            self.unsetCursor()

    def _try_resize_at(self, pos: QPoint, global_pos: QPoint) -> bool:
        """命中缩放热区就走系统缩放（原生手感）；系统不支持时退回手动缩放。"""
        if self.isMaximized():
            return False
        edges = self._edges_at(pos)
        if not edges:
            return False
        handle = self.windowHandle()
        if handle is not None and handle.startSystemResize(edges):
            self._material.suspend()
            self._resize_settle.start(RESIZE_SETTLE_MS)
            return True
        self._resize_session = {"edges": edges, "origin": global_pos, "geometry": QRect(self.geometry())}
        self._material.suspend()
        self.setCursor(self._cursor_for(edges))
        return True

    def _begin_move(self, global_pos: QPoint) -> None:
        """开始拖动：记住按下点与当时的窗口位置。

        不用 QWindow.startSystemMove()：无边框 + 分层（透明）窗口在 Win11 上实测它返回
        True，窗口却纹丝不动（真机与自动化各测两次，位移全是 0）。自己跟手移动最稳，
        行为也和八向缩放保持一致。

        亚克力**不**在移动期间降级：窗口一路保留真实模糊，玻璃才「一路都在」；
        缩放仍然降级 —— 边长每帧都在变，模糊跟不上的错位比降级更显眼。
        """
        self._move_session = {"origin": global_pos, "geometry": QRect(self.geometry())}

    def _apply_move(self, global_pos: QPoint) -> None:
        """跟手移动窗口：位移量 = 当前鼠标 - 按下时鼠标。"""
        session = self._move_session
        if session is None:
            return
        self.move(session["geometry"].topLeft() + (global_pos - session["origin"]))

    def _end_move(self) -> None:
        self._move_session = None
        self._resize_settle.start(RESIZE_SETTLE_MS)

    def _apply_manual_resize(self, global_pos: QPoint) -> None:
        session = self._resize_session
        edges = session["edges"]
        delta = global_pos - session["origin"]
        rect = QRect(session["geometry"])
        min_w, min_h = MIN_WINDOW
        if edges & Qt.Edge.LeftEdge:
            rect.setLeft(min(rect.left() + delta.x(), rect.right() - min_w))
        elif edges & Qt.Edge.RightEdge:
            rect.setRight(max(rect.right() + delta.x(), rect.left() + min_w))
        if edges & Qt.Edge.TopEdge:
            rect.setTop(min(rect.top() + delta.y(), rect.bottom() - min_h))
        elif edges & Qt.Edge.BottomEdge:
            rect.setBottom(max(rect.bottom() + delta.y(), rect.top() + min_h))
        self.setGeometry(rect)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self._try_resize_at(
            e.position().toPoint(), e.globalPosition().toPoint()
        ):
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._resize_session is not None:
            self._apply_manual_resize(e.globalPosition().toPoint())
            return
        self._update_resize_cursor(e.position().toPoint())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._resize_session is not None:
            self._resize_session = None
            self.unsetCursor()
            QTimer.singleShot(120, self._material.resume)
            return
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        """窗口外壳：透玻璃 + 文字区薄面 —— 整窗真透，有字的地方局部加厚。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = 0 if self.isMaximized() else self._window_radius()
        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = glass_path(rect, radius)

        # 降级：拿不到真实模糊时，铺一层接近材质色的薄膜，别让窗口变成透明水印
        if self._material.mode == MODE_SOLID:
            base = QLinearGradient(0.0, 0.0, 0.0, self.height())
            bottom = QColor(BG)
            bottom.setAlpha(224)
            base.setColorAt(0.0, QColor(255, 255, 255, 230))
            base.setColorAt(1.0, bottom)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(base)
            p.drawPath(path)

        # ① 光影结构先垫底：只有那圈折射彩边（冷 / 暖各偏 1px），方向跟着**指针光**走。
        #    整窗**不铺光泽带、也不点镜面热点**：一块几万像素的面板上，一撮热点扩散开来
        #    就是一片铺满的奶白 —— 那正是「糊」和「廉价」的来源。大面板的玻璃签名是
        #    **边缘**（③ 的镜面边缘光 + 焦散），里面必须能让桌面原样上得来。
        paint_glass(p, rect, radius, lit=GLASS_LIT_WINDOW, gloss=False, specular=False, rim=False)

        # ①.5 内容环境光：收到的照片把颜色借给玻璃一点（图片口附近最浓，向外淡出）。
        #      它压在薄面**之下** —— 染色是玻璃的事，不能拿文字区的可读性去换。
        self._paint_ambient(p, path, rect)

        # ② 文字区薄面：整窗只有 44%（桌面真的上得来），所以有字的区域各自垫一层浅面，
        #    把该区的亮度下限抬回 AA。面只铺在「有字的那几条」，图片口这种大块内容保持
        #    真透 —— 大面积真透 + 小面积厚度，「高级」是这么来的。两层都向内容区渐隐，
        #    所以分区之间没有硬边。
        p.setPen(Qt.PenStyle.NoPen)
        p.save()
        p.setClipPath(path)
        self._paint_top_face(p)
        self._paint_foot_face(p)
        p.restore()

        # ③ 边缘收束：先铺受光边的内圈薄光（光源那侧的「被照亮的一条边」，跟着指针转），
        #    再压上焦散 + 镜面边缘光 —— 那圈细亮边是「玻璃」的签名，不能被薄面盖掉。
        paint_edge_glow(p, rect, radius)
        paint_glass(
            p, rect, radius, lit=GLASS_LIT_WINDOW, gloss=False, specular=False, aberration=False
        )
        p.end()

    def _ambient_center(self, rect: QRectF) -> QPointF:
        """染光中心 = 图片口中心（内容在那儿，颜色就从那儿漫出来）。"""
        port = getattr(self, "_image_port", None)
        if port is None:
            return rect.center()
        return QPointF(port.mapTo(self, port.rect().center()))

    def _paint_ambient(self, p: QPainter, path, rect: QRectF) -> None:
        """内容环境光：一片跟着内容走的柔光，到窗口边缘已经淡没（不会变成一块色斑）。"""
        if self._ambient_color is None or self._ambient_level <= 0.001:
            return
        level = AMBIENT_ALPHA * self._ambient_level
        core = QColor(self._ambient_color)
        core.setAlphaF(level)
        mid = QColor(self._ambient_color)
        mid.setAlphaF(level * 0.35)
        glow = QRadialGradient(
            self._ambient_center(rect), AMBIENT_SPREAD * max(self.width(), self.height())
        )
        glow.setColorAt(0.0, core)
        glow.setColorAt(0.55, mid)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.save()
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawRect(rect)
        p.restore()

    def _paint_top_face(self, p: QPainter) -> None:
        """顶栏浅面 + 最上沿再亮一档，往下渐隐进内容（顶栏亮 → 内容中）。

        渐隐的那一段只铺**内容列**：侧栏那一列有它自己的薄面（SIDEBAR_FACE），两套面
        叠在同一块地方，会把侧栏顶上一条抬成一块发白的斑 —— 材质只有一本账。
        """
        band_h = TOPBAR_H * FACE_FALLOFF
        sheen = QLinearGradient(QPointF(0.0, 0.0), QPointF(0.0, band_h))
        sheen.setColorAt(0.0, QColor(255, 255, 255, round(255 * (TOPBAR_FACE + TOPBAR_SHEEN))))
        sheen.setColorAt(TOPBAR_H / band_h, QColor(255, 255, 255, round(255 * TOPBAR_FACE)))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(sheen)
        # 同一支渐变分两块铺（顶栏本身整宽 + 往下的渐隐段只给内容列），两块严丝合缝
        p.drawRect(QRectF(0.0, 0.0, float(self.width()), float(TOPBAR_H)))
        p.drawRect(
            QRectF(float(SIDEBAR_W), float(TOPBAR_H), float(self.width() - SIDEBAR_W), band_h - TOPBAR_H)
        )

    def _paint_foot_face(self, p: QPainter) -> None:
        """状态栏浅面 + 底部内阴影：一档亮（面）一档深（影），沉下去而字仍清楚。

        与顶栏同一条规矩：渐隐段只铺内容列，不和侧栏的薄面叠在一起。
        """
        band_h = STATUSBAR_H * FACE_FALLOFF
        band_top = float(self.height()) - band_h
        face = QLinearGradient(QPointF(0.0, band_top), QPointF(0.0, float(self.height())))
        face.setColorAt(0.0, QColor(255, 255, 255, 0))
        floor = QColor(255, 255, 255, round(255 * STATUSBAR_FACE))
        face.setColorAt(1.0 - STATUSBAR_H / band_h, floor)
        face.setColorAt(1.0, floor)
        p.setBrush(face)
        p.drawRect(
            QRectF(
                float(SIDEBAR_W),
                band_top,
                float(self.width() - SIDEBAR_W),
                band_h - STATUSBAR_H,
            )
        )
        p.drawRect(
            QRectF(0.0, float(self.height() - STATUSBAR_H), float(self.width()), float(STATUSBAR_H))
        )
        # 底部内阴影：交代材质下沉，玻璃不是一块平板。
        # 它压着状态栏文字，所以不透明度是令牌（BOTTOM_SHADE），要跟对比度一起调。
        shade = QLinearGradient(0.0, self.height() * 0.72, 0.0, float(self.height()))
        shade.setColorAt(0.0, QColor(0, 0, 0, 0))
        shade.setColorAt(1.0, wash(BOTTOM_SHADE / 255.0))
        p.setBrush(shade)
        p.drawRect(QRectF(0.0, self.height() * 0.72, float(self.width()), self.height() * 0.28))

    def keyPressEvent(self, e) -> None:  # noqa: N802
        # 无边框窗口要给出可预期的「出口」（Esc = 关闭）
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    # ------------------------------------------------------------------ #
    # 公开 API（供 main.py 调用）
    # ------------------------------------------------------------------ #
    def set_protocol(self, protocol) -> None:
        """注入协议实例并读取自身信息/初始设备（尽力而为）。"""
        self._protocol = protocol
        if protocol is None:
            return
        try:
            info = protocol.get_self()
            if isinstance(info, dict):
                self.on_state(info)
        except Exception:
            pass
        try:
            peers = protocol.get_peers()
            if isinstance(peers, list):
                self.on_devices(peers)
        except Exception:
            pass

    @property
    def protocol(self):
        return self._protocol

    def selected_device(self) -> dict | None:
        """当前选中设备（dict），无则 None。"""
        for d in self._devices:
            if d.get("fingerprint") == self._selected_fingerprint:
                return d
        return None

    @property
    def selected_fingerprint(self) -> str | None:
        return self._selected_fingerprint

    # -- 协议回调入口（线程安全：跨线程经内部 Signal 排队到主线程）--
    def on_received_item(self, item: dict) -> None:
        self._sig_received.emit(item)

    def on_devices(self, devices: list) -> None:
        self._sig_devices.emit(devices)

    def on_state(self, state: dict) -> None:
        self._sig_state.emit(state)

    def on_progress(self, ev: dict) -> None:
        self._sig_progress.emit(ev)

    def show_toast(self, msg: str, kind: str = "") -> None:
        self._sig_toast.emit({"msg": msg, "kind": kind})
