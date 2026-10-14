"""窗口材质：真实的桌面模糊（毛玻璃）。

实测结论（Windows 11 25H2 / Qt 6.12）：
  - DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE) 在 Qt 的分层窗口上会退化成
    一块不透明的浅色填充，看不到背后的桌面；
  - SetWindowCompositionAttribute 才能真把窗口背后的内容做高斯模糊。但**两种**都要挑：
    ACCENT_ENABLE_ACRYLICBLURBEHIND（亚克力）在 Windows 11 上会额外叠一层**系统乳白**，
    它不跟着我们的令牌走 —— 整窗压上一片奶白，桌面再透也上不来，看起来就是「廉价的
    塑料板」。ACCENT_ENABLE_BLURBEHIND（纯模糊）只做高斯模糊、不掺颜色，着色 / 加厚 /
    高光全由我们自己画（styles.GLASS_TINT_ABGR + paint_glass），所以**首选纯模糊**。
圆角的坑（实测）：亚克力模糊是 DWM 画的，**它不理会 SetWindowRgn**——只做区域裁剪的话
四角照样会露出方形的模糊块。正解是让 DWM 自己按圆角裁剪
（DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND，Windows 11 22H2+）；DWM 的圆角半径
是系统固定的（100% DPI 下 8px，随 DPI 缩放），应用无法指定更大值，所以窗口自己绘制的
半径要与它对齐（见 styles.RADIUS_WINDOW），否则圆角处会出现两条不同心的弧。

拖动 / 缩放期间亚克力跟随会有拖影，交互期间临时降级成纯色，停手后再切回来。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19

# 让 DWM 自己把窗口切成圆角（模糊才会跟着圆）。半径由系统决定，
# 100% DPI 下约 8px 并随 DPI 缩放，应用不能指定更大的值。
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2
DWMWCP_DONOTROUND = 1
DWMWA_COLOR_NONE = 0xFFFFFFFE

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
        return None, None, None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    except OSError:
        return None, None, None
    user32.SetWindowCompositionAttribute.argtypes = [wintypes.HWND, ctypes.POINTER(_CompositionAttribData)]
    user32.SetWindowCompositionAttribute.restype = wintypes.BOOL
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
    gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    return user32, gdi32, dwmapi


class GlassMaterial:
    """把窗口变成毛玻璃，并对窗口做圆角裁剪。"""

    def __init__(self) -> None:
        self._user32, self._gdi32, self._dwmapi = _load_libraries()
        self._hwnd: int | None = None
        self._mode = MODE_SOLID
        self._rounded_by_dwm = False
        self._tint = 0xB8FFFFFF
        self._region_key: tuple | None = None
        self._suspended = False

    # ------------------------------------------------------------------ 状态

    @property
    def mode(self) -> str:
        """实际生效的材质：acrylic / blur / solid（降级）。"""
        return self._mode

    @property
    def rounded_by_dwm(self) -> bool:
        """DWM 是否接管了圆角裁剪（模糊才会跟着圆）。"""
        return self._rounded_by_dwm

    @property
    def region_clips_backdrop(self) -> bool:
        """窗口区域能不能裁住那层模糊 —— 判断「圆角该归谁管」的唯一依据。

        纯模糊（``ACCENT_ENABLE_BLURBEHIND``）时，那层模糊是 DWM **按窗口区域**画的：
        实测把区域设成 16px 圆角，四角连模糊一起被裁得干干净净（见开发日志）。这时圆角
        归我们管，想多圆有多圆。亚克力兜底时模糊是系统 backdrop、不认窗口区域，圆角只能
        交给 DWM，而它的半径是系统固定的 —— 这就是两套半径的来由（styles.RADIUS_WINDOW
        / RADIUS_WINDOW_SYSTEM）。
        """
        return self._mode != MODE_ACRYLIC

    # ------------------------------------------------------------------ 应用

    def attach(self, hwnd: int, tint_abgr: int) -> str:
        self._hwnd = int(hwnd)
        self._tint = tint_abgr
        # 首选纯模糊（系统不掺色），亚克力只作兜底：乳白那一层会把我们自己的光影糊掉。
        if self._apply_accent(ACCENT_ENABLE_BLURBEHIND, tint_abgr):
            self._mode = MODE_BLUR
        elif self._apply_accent(ACCENT_ENABLE_ACRYLICBLURBEHIND, tint_abgr):
            self._mode = MODE_ACRYLIC
        else:
            self._mode = MODE_SOLID
        self._apply_rounding(rounded=not self.region_clips_backdrop)
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
        self._apply_rounding(rounded=not self.region_clips_backdrop)

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

    def _apply_rounding(self, *, rounded: bool = True) -> bool:
        """圆角交给 DWM（``rounded=True``）还是让开（``rounded=False``），并去掉默认边框线。

        ``rounded=False`` 不是「不圆角」，而是「**别插手**」：我们自己用窗口区域裁，半径
        才不受系统那个固定值约束。两者必须二选一 —— 同时开着的话，DWM 会按它的小半径
        再裁一刀，四角就出现两条不同心的弧。
        """
        if not self._dwmapi or self._hwnd is None:
            return False
        try:
            pref = ctypes.c_int(DWMWCP_ROUND if rounded else DWMWCP_DONOTROUND)
            ok = self._dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(self._hwnd),
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(pref),
                ctypes.sizeof(pref),
            )
            border = ctypes.c_uint(DWMWA_COLOR_NONE)
            self._dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(self._hwnd),
                DWMWA_BORDER_COLOR,
                ctypes.byref(border),
                ctypes.sizeof(border),
            )
            self._rounded_by_dwm = rounded and ok == 0
        except Exception:
            self._rounded_by_dwm = False
        return self._rounded_by_dwm

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
