"""AirFloat 主窗口（PySide6 / Qt6 原生 GUI，替代 Electron）。

布局（对齐 docs/03）：
- 顶栏：品牌 + 本机别名 + 打开接收目录按钮（无边框窗口拖拽区）。
- 左窄栏：隔空投送开关 / 可接收对象三选 / 附近设备列表。
- 右宽栏「图片口」：缩略图网格 + 空态提示；支持拖入图片发送、拖出缩略图。
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
    Property,
    QEasingCurve,
    QEvent,
    QMimeData,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDrag,
    QFont,
    QFontMetrics,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFrame,
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

from .styles import (
    BG,
    CARD,
    DEFAULT_DEVICE_ICON,
    DIVIDER,
    OFFLINE,
    PRIMARY,
    QSS,
    TEXT,
    TEXT_SECONDARY,
    device_icon,
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
MODE_LABELS = {"everyone": "所有人", "contacts": "仅联系人", "off": "接收关闭"}
MODE_ORDER = ("everyone", "contacts", "off")

WINDOW_W, WINDOW_H = 360, 500
SIDEBAR_W = 158
TOPBAR_H = 40
STATUSBAR_H = 30

# 缩略图网格
THUMB_W = 84
THUMB_IMG_H = 62
THUMB_NAME_H = 18
THUMB_CELL_H = THUMB_IMG_H + THUMB_NAME_H
GRID_COLUMNS = 2
GRID_GAP = 8


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _blend(c1: QColor, c2: QColor, t: float) -> QColor:
    """线性混合两个颜色，t∈[0,1]。"""
    t = max(0.0, min(1.0, t))
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * t),
        round(c1.green() + (c2.green() - c1.green()) * t),
        round(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


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


# --------------------------------------------------------------------------- #
# 开关（iOS 风格，开=蓝 / 关=灰）
# --------------------------------------------------------------------------- #
class ToggleSwitch(QAbstractButton):
    """无边框圆角开关，带拇指滑动动画。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 26)
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._on_toggled)

    # -- 动画属性 --
    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, v: float) -> None:
        self._offset = v
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _on_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def sizeHint(self) -> QSize:  # noqa: D102
        return QSize(44, 26)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        track = _blend(QColor(OFFLINE), QColor(PRIMARY), self._offset)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(track))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)

        margin = 2.0
        travel = float(w - h)
        x = margin + self._offset * travel
        d = h - 2 * margin
        p.setBrush(QBrush(QColor("#FFFFFF")))
        p.drawEllipse(QRectF(x, margin, d, d))
        p.end()


# --------------------------------------------------------------------------- #
# 附近设备列表委托（emoji 图标 + 别名 + 类型，两行）
# --------------------------------------------------------------------------- #
class DeviceItemDelegate(QStyledItemDelegate):
    """绘制设备条目：选中态高亮主蓝。"""

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
            painter.setBrush(QColor(PRIMARY))
            painter.drawRoundedRect(rect, 8, 8)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BG))
            painter.drawRoundedRect(rect, 8, 8)

        alias = index.data(Qt.ItemDataRole.UserRole) or index.text() or "未知设备"
        dtype = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        emoji = index.data(Qt.ItemDataRole.UserRole + 2) or DEFAULT_DEVICE_ICON

        x = rect.left() + 8
        icon_rect = QRectF(x, rect.top() + rect.height() / 2 - 11, 22, 22)
        painter.setFont(QFont("Segoe UI Emoji", 12))
        painter.setPen(QColor("#FFFFFF" if selected else TEXT))
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, emoji)

        text_x = icon_rect.right() + 7
        right = rect.right() - 6

        f_alias = QFont(option.font)
        f_alias.setPixelSize(13)
        f_alias.setBold(True)
        painter.setFont(f_alias)
        painter.setPen(QColor("#FFFFFF" if selected else TEXT))
        alias_elided = QFontMetrics(f_alias).elidedText(str(alias), Qt.TextElideMode.ElideRight, right - int(text_x))
        painter.drawText(QPoint(int(text_x), rect.top() + 17), alias_elided)

        f_type = QFont(option.font)
        f_type.setPixelSize(11)
        painter.setFont(f_type)
        painter.setPen(QColor("rgba(255,255,255,0.85)" if selected else TEXT_SECONDARY))
        dtype_elided = QFontMetrics(f_type).elidedText(str(dtype), Qt.TextElideMode.ElideRight, right - int(text_x))
        painter.drawText(QPoint(int(text_x), rect.top() + 31), dtype_elided)

        painter.restore()


# --------------------------------------------------------------------------- #
# 缩略图（可拖出）
# --------------------------------------------------------------------------- #
class ThumbWidget(QWidget):
    """接收到的单张图片缩略图；按住拖出浮窗触发系统级文件拖拽。"""

    def __init__(self, file_path: str, file_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file_path = file_path or ""
        self._file_name = file_name or ""
        self.setFixedSize(THUMB_W, THUMB_CELL_H)
        self.setToolTip(self._file_name or self._file_path)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._pixmap = _load_thumb(self._file_path, THUMB_W, THUMB_IMG_H)
        self._press_pos: QPoint | None = None

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        card = QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(card, 8, 8)
        p.setClipPath(path)

        p.setPen(QPen(QColor(DIVIDER), 1))
        p.setBrush(QColor(CARD))
        p.drawRoundedRect(card, 8, 8)

        img_rect = QRectF(1, 1, w - 2, THUMB_IMG_H - 2)
        if self._pixmap is not None:
            p.drawPixmap(img_rect.toRect(), self._pixmap)
        else:
            p.fillRect(img_rect, QColor(BG))
            p.setPen(QColor(TEXT_SECONDARY))
            p.setFont(QFont("Segoe UI Emoji", 16))
            p.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, "🖼️")

        p.setPen(QColor(TEXT_SECONDARY))
        f = QFont(self.font())
        f.setPixelSize(10)
        p.setFont(f)
        name_rect = QRectF(5, THUMB_IMG_H + 1, w - 10, THUMB_NAME_H - 2)
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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._columns = GRID_COLUMNS
        self._drag_depth = 0

        # 空态
        self._empty_state = QWidget(self)
        ev = QVBoxLayout(self._empty_state)
        ev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.setSpacing(6)
        icon = QLabel("🖼️", self._empty_state)
        icon.setObjectName("emptyIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main = QLabel("手机发来的图会出现在这里", self._empty_state)
        main.setObjectName("emptyMain")
        main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("拖图片进来可发给手机", self._empty_state)
        sub.setObjectName("emptySub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(icon)
        ev.addWidget(main)
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
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setHorizontalSpacing(GRID_GAP)
        self._grid.setVerticalSpacing(GRID_GAP)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self._grid_host)

        # 拖入提示浮层（透明于鼠标）
        self._drop_overlay = QLabel("松开以发送到所选设备", self)
        self._drop_overlay.setObjectName("dropOverlay")
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
# 顶栏（无边框窗口拖拽区 + 打开接收目录）
# --------------------------------------------------------------------------- #
class TopBar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(TOPBAR_H)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                e.accept()
                return
        super().mousePressEvent(e)


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
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(QSS)

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
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏
        topbar = TopBar(self)
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(12, 0, 8, 0)
        tb.setSpacing(8)
        brand = QLabel("AirFloat", topbar)
        brand.setObjectName("brandName")
        self._self_alias_label = QLabel("", topbar)
        self._self_alias_label.setObjectName("selfAlias")
        self._self_alias_label.setVisible(False)
        self._folder_btn = QToolButton(topbar)
        self._folder_btn.setObjectName("folderBtn")
        self._folder_btn.setText("📁")
        self._folder_btn.setToolTip("打开接收目录")
        self._folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tb.addWidget(brand)
        tb.addWidget(self._self_alias_label)
        tb.addStretch(1)
        tb.addWidget(self._folder_btn)
        root.addWidget(topbar)

        # 主体（两栏）
        main = QHBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # 左窄栏
        sidebar = QFrame(self)
        sidebar.setObjectName("sidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setFixedWidth(SIDEBAR_W)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(10, 12, 10, 10)
        sb.setSpacing(8)

        # ① 隔空投送开关
        switch_row = QHBoxLayout()
        switch_row.setSpacing(6)
        switch_label = QLabel("隔空投送", sidebar)
        switch_label.setObjectName("rowLabel")
        self._switch = ToggleSwitch(sidebar)
        switch_row.addWidget(switch_label)
        switch_row.addStretch(1)
        switch_row.addWidget(self._switch)
        sb.addLayout(switch_row)

        # ② 可接收对象
        group_title = QLabel("可接收对象", sidebar)
        group_title.setObjectName("groupTitle")
        sb.addWidget(group_title)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_buttons: list[QPushButton] = []
        for mode in MODE_ORDER:
            btn = QPushButton(MODE_LABELS[mode], sidebar)
            btn.setObjectName("modeOption")
            btn.setCheckable(True)
            btn.setProperty("mode", mode)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.toggled.connect(lambda checked, m=mode: self._on_mode_toggled(m, checked))
            self._mode_group.addButton(btn)
            self._mode_buttons.append(btn)
            sb.addWidget(btn)

        # ③ 附近设备
        dev_title = QLabel("附近设备", sidebar)
        dev_title.setObjectName("groupTitle")
        sb.addWidget(dev_title)

        self._device_list = QListWidget(sidebar)
        self._device_list.setObjectName("deviceList")
        self._device_list.setItemDelegate(DeviceItemDelegate(self._device_list))
        self._device_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._device_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._device_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._device_list.setSpacing(2)
        sb.addWidget(self._device_list, 1)

        self._device_empty = QLabel("未发现手机，请确认同一 WiFi", sidebar)
        self._device_empty.setObjectName("deviceEmpty")
        self._device_empty.setWordWrap(True)
        self._device_empty.setVisible(False)
        sb.addWidget(self._device_empty)

        main.addWidget(sidebar)

        # 右宽栏「图片口」
        self._image_port = ImagePort(self)
        main.addWidget(self._image_port, 1)

        root.addLayout(main, 1)

        # 底部状态栏
        statusbar = QFrame(self)
        statusbar.setObjectName("statusbar")
        statusbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        statusbar.setFixedHeight(STATUSBAR_H)
        st = QHBoxLayout(statusbar)
        st.setContentsMargins(12, 0, 12, 0)
        st.setSpacing(10)

        self._progress_container = QWidget(statusbar)
        pc = QHBoxLayout(self._progress_container)
        pc.setContentsMargins(0, 0, 0, 0)
        pc.setSpacing(8)
        self._progress = QProgressBar(self._progress_container)
        self._progress.setObjectName("sendProgress")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedSize(110, 6)
        self._progress_label = QLabel("", self._progress_container)
        self._progress_label.setObjectName("progressLabel")
        pc.addWidget(self._progress)
        pc.addWidget(self._progress_label)
        self._progress_container.setVisible(False)
        st.addWidget(self._progress_container)

        self._status_hint = QLabel("", statusbar)
        self._status_hint.setObjectName("statusHint")
        st.addWidget(self._status_hint, 1)

        self._received_count = QLabel("", statusbar)
        self._received_count.setObjectName("receivedCount")
        self._received_count.setVisible(False)
        st.addWidget(self._received_count)

        self._send_btn = QPushButton("发送", statusbar)
        self._send_btn.setObjectName("sendBtn")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setFixedSize(72, 28)
        self._send_btn.setStyleSheet(
            "QPushButton#sendBtn { background: %s; color: white; border: none; border-radius: 12px; font-size: 12px; }"
            "QPushButton#sendBtn:hover { background: #3a80c9; }"
            "QPushButton#sendBtn:pressed { background: #2f6fb0; }" % PRIMARY
        )
        self._send_btn.clicked.connect(self._on_send_clicked)
        st.addWidget(self._send_btn)

        root.addWidget(statusbar)

        # Toast（浮层）
        self._toast_label = QLabel("", self)
        self._toast_label.setObjectName("toast")
        self._toast_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast_label.setVisible(False)
        self._toast_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: self._toast_label.setVisible(False))

        # 进度隐藏定时器
        self._progress_timer = QTimer(self)
        self._progress_timer.setSingleShot(True)
        self._progress_timer.timeout.connect(lambda: self._progress_container.setVisible(False))

    def _wire_signals(self) -> None:
        self._switch.toggled.connect(self._on_switch_toggled)
        self._device_list.currentItemChanged.connect(self._on_device_current)
        self._folder_btn.clicked.connect(lambda: self.reveal_cache_requested.emit())
        self._image_port.drop_requested.connect(self._on_drop_paths)
        self._image_port.reveal_requested.connect(lambda: self.reveal_cache_requested.emit())

    # ------------------------------------------------------------------ #
    # 内部事件
    # ------------------------------------------------------------------ #
    def _on_switch_toggled(self, checked: bool) -> None:
        self._state["enabled"] = bool(checked)
        self.enabled_changed.emit(bool(checked))
        self._update_status()

    def _on_mode_toggled(self, mode: str, checked: bool) -> None:
        if not checked or mode not in MODE_LABELS:
            return
        if self._state.get("receiveMode") == mode:
            return
        self._state["receiveMode"] = mode
        self.receive_mode_changed.emit(mode)
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
                it.setData(Qt.ItemDataRole.UserRole + 2, device_icon(dtype))
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

            empty = not self._devices
            self._device_list.setVisible(not empty)
            self._device_empty.setVisible(empty)
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
        self._update_received_count()
        self.show_toast(f"已接收：{item.get('file_name') or item.get('fileName') or '图片'}", "success")

    def _apply_state(self, state) -> None:
        if not isinstance(state, dict):
            return
        if "enabled" in state:
            self._set_enabled_ui(bool(state["enabled"]))
        if "receiveMode" in state:
            self._set_mode_ui(str(state["receiveMode"]))
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
        self._progress_label.setText(f"正在传输 {name} {pct}%")
        self._progress_container.setVisible(True)
        self._progress_timer.stop()
        if pct >= 100:
            self._progress_timer.start(1200)

    def _apply_toast(self, payload) -> None:
        if not isinstance(payload, dict):
            return
        msg = str(payload.get("msg") or "")
        kind = str(payload.get("kind") or "")
        self._toast_label.setProperty("kind", kind)
        self._toast_label.style().unpolish(self._toast_label)
        self._toast_label.style().polish(self._toast_label)
        self._toast_label.setText(msg)
        self._toast_label.adjustSize()
        self._toast_label.setVisible(True)
        self._toast_label.raise_()
        self._position_toast()
        self._toast_timer.start(3200)

    def _render_thumbs(self) -> None:
        while self._image_port._grid.count():
            it = self._image_port._grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        has = bool(self._received_items)
        self._image_port._empty_state.setVisible(not has)
        if not has:
            return
        for idx, item in enumerate(self._received_items):
            path = item.get("file_path") or item.get("filePath") or ""
            name = item.get("file_name") or item.get("fileName") or ""
            tw = ThumbWidget(path, name)
            r, c = divmod(idx, self._image_port._columns)
            self._image_port._grid.addWidget(tw, r, c)

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
            hint = "点击左侧设备以选择发送目标"
        else:
            hint = "未发现手机，请确认同一 WiFi"
        self._status_hint.setText(hint)

    def _set_enabled_ui(self, enabled: bool) -> None:
        self._state["enabled"] = bool(enabled)
        self._switch.blockSignals(True)
        self._switch.setChecked(bool(enabled))
        self._switch.blockSignals(False)
        self._switch.update()

    def _set_mode_ui(self, mode: str) -> None:
        if mode not in MODE_LABELS:
            return
        self._state["receiveMode"] = mode
        for btn in self._mode_buttons:
            btn.blockSignals(True)
            btn.setChecked(btn.property("mode") == mode)
            btn.blockSignals(False)

    def _position_toast(self) -> None:
        lw = self._toast_label.width()
        lh = self._toast_label.height()
        x = (self.width() - lw) // 2
        y = self.height() - lh - 46
        self._toast_label.move(max(8, x), max(8, y))

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._position_toast()

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
