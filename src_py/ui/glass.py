"""窗口材质：真实的桌面模糊（毛玻璃）。

实测结论（Windows 11 25H2 / Qt 6.12）：
  - DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE) 在 Qt 的分层窗口上会退化成
    一块不透明的浅色填充，看不到背后的桌面；
  - SetWindowCompositionAttribute(ACCENT_ENABLE_ACRYLICBLURBEHIND) 才是真正把窗口
    背后的内容做高斯模糊的方案。
亚克力模糊作用于整块窗口矩形，所以圆角必须靠窗口区域裁剪（SetWindowRgn），否则
四角会露出方形的模糊块。拖动 / 缩放期间亚克力跟随会有拖影，交互期间临时降级成
纯色，停手后再切回来。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19

MODE_ACRYLIC = "acrylic"
MODE_BLUR = "blur"
MODE_SOLID = "solid"


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("accent_state", ctypes.c_uint),
        ("accent_flags", ctypes.c_uint),
        ("gradient_color", ctypes.c_uint),   # ABGR
        ("animation_id", ctypes.c_uint),
    ]


class _CompositionAttribData(ctypes.Structure):
    _fields_ = [
        ("attribute", ctypes.c_int),
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
    ]


def _load_libraries():
    if not sys.platform.startswith("win"):
        return None, None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    except OSError:
        return None, None
    user32.SetWindowCompositionAttribute.argtypes = [wintypes.HWND, ctypes.POINTER(_CompositionAttribData)]
    user32.SetWindowCompositionAttribute.restype = wintypes.BOOL
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
    gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    return user32, gdi32


class GlassMaterial:
    """把窗口变成毛玻璃，并对窗口做圆角裁剪。"""

    def __init__(self) -> None:
        self._user32, self._gdi32 = _load_libraries()
        self._hwnd: int | None = None
        self._mode = MODE_SOLID
        self._tint = 0xB8FFFFFF
        self._region_key: tuple | None = None
        self._suspended = False

    # ------------------------------------------------------------------ 状态

    @property
    def mode(self) -> str:
        """实际生效的材质：acrylic / blur / solid（降级）。"""
        return self._mode

    # ------------------------------------------------------------------ 应用

    def attach(self, hwnd: int, tint_abgr: int) -> str:
        self._hwnd = int(hwnd)
        self._tint = tint_abgr
        if self._apply_accent(ACCENT_ENABLE_ACRYLICBLURBEHIND, tint_abgr):
            self._mode = MODE_ACRYLIC
        elif self._apply_accent(ACCENT_ENABLE_BLURBEHIND, tint_abgr):
            self._mode = MODE_BLUR
        else:
            self._mode = MODE_SOLID
        return self._mode

    def set_tint(self, tint_abgr: int) -> None:
        self._tint = tint_abgr
        self._reapply()

    def suspend(self) -> None:
        """拖动 / 缩放期间降级为纯色，避免亚克力跟随延迟造成的拖影。"""
        if self._suspended or self._mode == MODE_SOLID:
            return
        self._suspended = True
        self._apply_accent(ACCENT_DISABLED, self._tint)

    def resume(self) -> None:
        if not self._suspended:
            return
        self._suspended = False
        self._reapply()

    def _reapply(self) -> None:
        state = ACCENT_ENABLE_BLURBEHIND if self._mode == MODE_BLUR else ACCENT_ENABLE_ACRYLICBLURBEHIND
        self._apply_accent(state, self._tint)

    def _apply_accent(self, state: int, tint_abgr: int) -> bool:
        if not self._user32 or self._hwnd is None:
            return False
        policy = _AccentPolicy(state, 0, tint_abgr, 0)
        data = _CompositionAttribData(
            WCA_ACCENT_POLICY,
            ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p),
            ctypes.sizeof(policy),
        )
        try:
            return bool(self._user32.SetWindowCompositionAttribute(wintypes.HWND(self._hwnd), ctypes.byref(data)))
        except Exception:
            return False

    # ------------------------------------------------------------------ 圆角

    def set_rounded(self, width: int, height: int, radius: int, dpr: float = 1.0, enabled: bool = True) -> None:
        if not self._gdi32 or self._hwnd is None:
            return
        key = (width, height, radius, round(dpr, 2), enabled)
        if key == self._region_key:
            return
        self._region_key = key
        if not enabled:
            self.clear_region()
            return
        scaled_w = max(1, int(round(width * dpr)))
        scaled_h = max(1, int(round(height * dpr)))
        scaled_r = max(0, int(round(radius * dpr)))
        region = self._gdi32.CreateRoundRectRgn(0, 0, scaled_w + 1, scaled_h + 1, scaled_r * 2, scaled_r * 2)
        if not region:
            return
        if not self._user32.SetWindowRgn(wintypes.HWND(self._hwnd), region, True):
            self._gdi32.DeleteObject(region)

    def clear_region(self) -> None:
        if not self._user32 or self._hwnd is None:
            return
        self._region_key = None
        try:
            self._user32.SetWindowRgn(wintypes.HWND(self._hwnd), None, True)
        except Exception:
            pass