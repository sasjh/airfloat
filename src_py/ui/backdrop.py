"""窗口背后那块真实桌面：自己抓、自己糊、自己裁。

**为什么不让 DWM 糊（实测结论）**：``SetWindowCompositionAttribute`` 的模糊是 DWM 铺在
窗口**矩形**上的 —— 它 **不理会窗口区域**（把区域设成 60px 圆角，模糊依旧是个方角，四角
露出方块），而 DWM 自己的圆角（``DWMWA_WINDOW_CORNER_PREFERENCE``）半径是系统固定的，
在这扇无边框窗上实测只有 ~4px。要「任意半径的圆弧 + 真模糊 + 不留方角」，那层模糊只能
自己抓、自己糊、自己裁进圆角路径。

**怎么抓到「没有我们这扇窗」的桌面**：抓之前用
``SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`` 把自己从画面里摘出去，BitBlt 拿到的
就是干净的桌面；抓完立刻恢复。这个开关只影响**截屏 API**，不影响屏幕上的显示 —— 看不见、
不闪、不抢焦点。

**糊多狠是有讲究的**（``BACKDROP_BLUR_PX``）：这只旋钮看着像性能参数，其实是**观感参数** ——
糊太弱（缩 6 倍糊 2 遍量出来只有 σ≈4px ≈2.6 逻辑像素）时壁纸的线条、桌面图标照样看得清，
那不是玻璃而是一层薄纱；糊太狠又会糊成一片马赛克（结构全没了，看着假）。调之前先量。
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPixmap

from .styles import (
    BACKDROP_BLUR_HALF,
    BACKDROP_BLUR_PASSES,
    BACKDROP_BLUR_PX,
    BACKDROP_BLUR_SCALE,
    BACKDROP_MOVE_MS,
    BACKDROP_TICK_MS,
)

try:  # Pillow 是可选依赖（HEIC 解码用的），少了就退回纯 Qt 的糊法
    from PIL import Image, ImageFilter

    _HAS_PIL = True
except Exception:  # pragma: no cover - 只在本机没装 Pillow 时走到
    _HAS_PIL = False

WDA_NONE = 0
WDA_EXCLUDEFROMCAPTURE = 0x11
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BLACK_RUN_LIMIT = 64  # 连续这么多个采样点全是纯黑，就当作「抓不到」（受保护内容 / 集成显卡怪癖）


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


def _load():
    if not sys.platform.startswith("win"):
        return None, None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    except OSError:
        return None, None
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_void_p, ctypes.POINTER(_BitmapInfoHeader), ctypes.c_uint]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    return user32, gdi32


def _shrink(image: QImage, factor: int) -> QImage:
    if factor <= 1:
        return image
    return image.scaled(
        max(1, image.width() // factor),
        max(1, image.height() // factor),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _box_blur(image: QImage) -> QImage:
    """没有 Pillow 时的兜底：缩小再放大（缩出来的就是一次盒式滤波）。"""
    if BACKDROP_BLUR_SCALE <= 1 or BACKDROP_BLUR_PASSES <= 0:
        return image
    out = image
    for _ in range(BACKDROP_BLUR_PASSES):
        out = _shrink(out, BACKDROP_BLUR_SCALE)
        out = out.scaled(
            image.width(),
            image.height(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return out


def _blur(image: QImage) -> QImage:
    """把抓到的那层桌面糊掉。

    用**真高斯**（Pillow）。早先那版是纯 Qt 的「缩小到 1/N 再放大」—— 便宜，但放大只有
    双线性插值：缩到 1/20 再拉回来 20 倍，画面就成了**一片片斜坡**，看着像盖了层马赛克，
    用户一眼就说「不自然」。真高斯的核是圆的，过渡连续，这才是磨砂玻璃该有的样子。

    先缩一半再糊（半径同减半）纯粹为了省 CPU（实测 24ms → 6.4ms），最后放大回来只是 2×
    双线性，对一张已经糊过的图肉眼看不出差别。没有 Pillow 的机器退回 ``_box_blur``。
    """
    if BACKDROP_BLUR_PX <= 0:
        return image
    full_w, full_h = image.width(), image.height()
    factor = max(1, int(BACKDROP_BLUR_HALF))
    work = _shrink(image, factor)
    if _HAS_PIL:
        pil = Image.frombuffer(
            "RGBA",
            (work.width(), work.height()),
            work.constBits(),
            "raw",
            "BGRA",
            work.bytesPerLine(),
            1,
        )
        pil = pil.filter(ImageFilter.GaussianBlur(BACKDROP_BLUR_PX / factor))
        blurred = QImage(
            pil.tobytes("raw", "BGRA"), pil.width, pil.height, QImage.Format.Format_RGB32
        )
    else:
        blurred = _box_blur(work)
    if (full_w, full_h) == (blurred.width(), blurred.height()):
        return blurred.copy()  # 同一尺寸时 scaled 可能直接还你同一块缓冲，拷一份保险
    return blurred.scaled(
        full_w, full_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


class Backdrop(QObject):
    """窗口背后那块桌面：抓一次、糊一次，交给窗口当玻璃的底。

    抓不到的机器（受保护内容、抓屏被策略挡掉）会一直返回 False，窗口据此退回 DWM
    那层系统模糊 —— 那条路四角会露出方角，但总比一块黑的好。
    """

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._user32, self._gdi32 = _load()
        self._widget = None
        self._hwnd: int | None = None
        self._pixmap: QPixmap | None = None
        self._active = False
        self._suspended = False
        self._last = 0.0  # 上一次抓成功的时间戳，给拖动时的限速跟随用
        self._timer = QTimer(self)
        self._timer.setInterval(BACKDROP_TICK_MS)
        self._timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------------ 状态

    @property
    def active(self) -> bool:
        """底是不是由我们自己画（抓屏成功）。"""
        return self._active

    def pixmap(self) -> QPixmap | None:
        return self._pixmap

    # ------------------------------------------------------------------ 开关

    def attach(self, widget) -> None:
        self._widget = widget
        self._hwnd = int(widget.winId())

    def start(self) -> bool:
        """挂上并抓第一张。抓得到才算「活了」。"""
        if self._user32 is None or self._hwnd is None:
            return False
        if not self.refresh():
            return False
        self._active = True
        self._timer.start()
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._active = False
        self._pixmap = None

    def suspend(self) -> None:
        """拖动 / 缩放期间别抓：窗口在动，抓来也是废的，还白花 CPU。"""
        self._suspended = True

    def resume(self) -> None:
        self._suspended = False
        self.refresh()

    # ------------------------------------------------------------------ 干活

    def refresh(self) -> bool:
        widget = self._widget
        if self._user32 is None or widget is None:
            return False
        if self._suspended or not widget.isVisible() or widget.isMinimized():
            return False
        rect = self._window_rect()
        if rect is None:
            return False
        image = self._grab(rect)
        if image is None:
            return False
        pixmap = QPixmap.fromImage(_blur(image))
        pixmap.setDevicePixelRatio(widget.devicePixelRatioF())
        self._pixmap = pixmap
        self._last = time.monotonic()
        self.changed.emit()
        return True

    def refresh_throttled(self) -> bool:
        """拖动 / 缩放时用：距上次抓成功还不到 BACKDROP_MOVE_MS 就跳过。

        窗口在动的时候要在每一帧抓一次桌面，抓一次 ~7ms，贴着每帧抓会把拖动拖卡 ——
        限到 ~14 次/秒既跟得上眼睛，又不掉帧。停手后 ``resume()`` 会补一张最新的。
        """
        if time.monotonic() - self._last < BACKDROP_MOVE_MS / 1000.0:
            return False
        return self.refresh()

    def _window_rect(self):
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(wintypes.HWND(self._hwnd), ctypes.byref(rect)):
            return None
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        return rect.left, rect.top, w, h

    def _grab(self, rect) -> QImage | None:
        x, y, w, h = rect
        screen = self._user32.GetDC(None)
        if not screen:
            return None
        mem = self._gdi32.CreateCompatibleDC(screen)
        bitmap = self._gdi32.CreateCompatibleBitmap(screen, w, h)
        if not mem or not bitmap:
            return None
        old = self._gdi32.SelectObject(mem, bitmap)
        head = _BitmapInfoHeader()
        head.biSize = ctypes.sizeof(_BitmapInfoHeader)
        head.biWidth = w
        head.biHeight = -h  # 负数 = 自上而下，省一次翻转
        head.biPlanes = 1
        head.biBitCount = 32
        head.biCompression = 0
        buf = ctypes.create_string_buffer(w * h * 4)
        ok = False
        try:
            # 抓的这一瞬间把自己摘出画面，拿到的就是**没有我们这扇窗**的真实桌面
            self._user32.SetWindowDisplayAffinity(wintypes.HWND(self._hwnd), WDA_EXCLUDEFROMCAPTURE)
            try:
                drew = self._gdi32.BitBlt(mem, 0, 0, w, h, screen, x, y, SRCCOPY)
                got = self._gdi32.GetDIBits(mem, bitmap, 0, h, buf, ctypes.byref(head), DIB_RGB_COLORS)
                ok = bool(drew) and got == h
            finally:
                self._user32.SetWindowDisplayAffinity(wintypes.HWND(self._hwnd), WDA_NONE)
        finally:
            self._gdi32.SelectObject(mem, old)
            self._gdi32.DeleteObject(bitmap)
            self._gdi32.DeleteDC(mem)
            self._user32.ReleaseDC(None, screen)
        if not ok:
            return None
        raw = buf.raw
        if _looks_blocked(raw):
            return None
        # RGB32：小端下字节序是 B,G,R,A，正好对上 Format_RGB32
        return QImage(raw, w, h, w * 4, QImage.Format.Format_RGB32).copy()


def _looks_blocked(raw: bytes) -> bool:
    """整块纯黑 = 抓不到（受保护内容 / 全屏独占），认输。"""
    step = max(4, (len(raw) // 4096) & ~3)
    run = 0
    for i in range(0, len(raw) - 4, step):
        if raw[i] == 0 and raw[i + 1] == 0 and raw[i + 2] == 0:
            run += 1
            if run >= BLACK_RUN_LIMIT:
                return True
        else:
            run = 0
    return False
