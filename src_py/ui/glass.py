"""窗口材质：真实的桌面模糊（毛玻璃）。

实测结论（Windows 11 25H2 / Qt 6.12）：
  - DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE) 在 Qt 的分层窗口上会退化成
    一块不透明的浅色填充，看不到背后的桌面；
  - SetWindowCompositionAttribute 才能真把窗口背后的内容做高斯模糊。但**两种**都要挑：
    ACCENT_ENABLE_ACRYLICBLURBEHIND（亚克力）在 Windows 11 上会额外叠一层**系统乳白**，
    它不跟着我们的令牌走 —— 整窗压上一片奶白，桌面再透也上不来，看起来就是「廉价的
    塑料板」。ACCENT_ENABLE_BLURBEHIND（纯模糊）只做高斯模糊、不掺颜色，着色 / 加厚 /
    高光全由我们自己画（styles.GLASS_TINT_ABGR + paint_glass），所以**首选纯模糊**。
圆角的坑（实测，2026-10-14 复测）：**DWM 这层模糊根本不理会窗口区域** —— 把区域设成
60px 圆角，模糊依旧是个方角（四角露出方形模糊块）；而 DWM 自己的圆角
（DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND）在这扇无边框窗上只有 ~4px。所以
「任意半径的圆弧」这条路由 ui/backdrop.py 接管：模糊自己抓、自己糊、自己裁，DWM 那层
模糊整个关掉（见 MODE_BACKDROP）。抓不到桌面的机器才退回下面这条 DWM 模糊的老路。

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
MODE_BACKDROP = "backdrop"   # 底是我们自己抓来的模糊（主路径）


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
        self._suspended = False

    # ------------------------------------------------------------------ 状态

    @property
    def mode(self) -> str:
        """实际生效的材质：backdrop / acrylic / blur / solid（逐级降级）。"""
        return self._mode

    @property
    def rounded_by_dwm(self) -> bool:
        """DWM 是否接管了圆角裁剪（模糊才会跟着圆）。"""
        return self._rounded_by_dwm

    @property
    def backdrop_is_ours(self) -> bool:
        """底（那层桌面模糊）是不是由我们自己画的 —— 圆角半径该取哪一档就看它。"""
        return self._mode == MODE_BACKDROP

    # ------------------------------------------------------------------ 应用

    def attach(self, hwnd: int, tint_abgr: int, backdrop: bool = False) -> str:
        """挂材质。``backdrop=True`` = 桌面模糊由 ui/backdrop.py 自己抓自己画。

        自己画的时候，DWM 那层模糊要**整个关掉**：留着的话，它会在窗口矩形上再铺一层
        不理会圆角的方模糊（就是「四角有直角」的根源），而且两层模糊叠在一起更糊。
        """
        self._hwnd = int(hwnd)
        self._tint = tint_abgr
        if backdrop:
            self._apply_accent(ACCENT_DISABLED, 0)
            self._mode = MODE_BACKDROP
            # 圆角我们自己画（AA）、自己裁 —— 别让 DWM 那把小半径的刀再切一刀
            self._apply_rounding(rounded=False)
            return self._mode
        # 首选纯模糊（系统不掺色），亚克力只作兜底：乳白那一层会把我们自己的光影糊掉。
        if self._apply_accent(ACCENT_ENABLE_BLURBEHIND, tint_abgr):
            self._mode = MODE_BLUR
        elif self._apply_accent(ACCENT_ENABLE_ACRYLICBLURBEHIND, tint_abgr):
            self._mode = MODE_ACRYLIC
        else:
            self._mode = MODE_SOLID
        self._apply_rounding(rounded=True)
        return self._mode

    def set_tint(self, tint_abgr: int) -> None:
        self._tint = tint_abgr
        self._reapply()

    def suspend(self) -> None:
        """拖动 / 缩放期间降级为纯色，避免亚克力跟随延迟造成的拖影。"""
        if self._suspended or self._mode == MODE_SOLID:
            return
        if self._mode == MODE_BACKDROP:
            # 底是我们自己画的：拖影靠 ui/backdrop 那边暂停抓屏来避免，DWM 这儿没事可做
            self._suspended = True
            return
        self._suspended = True
        self._apply_accent(ACCENT_DISABLED, self._tint)

    def resume(self) -> None:
        if not self._suspended:
            return
        self._suspended = False
        self._reapply()

    def _reapply(self) -> None:
        if self._mode == MODE_BACKDROP:
            self._apply_rounding(rounded=False)
            return
        state = ACCENT_ENABLE_BLURBEHIND if self._mode == MODE_BLUR else ACCENT_ENABLE_ACRYLICBLURBEHIND
        self._apply_accent(state, self._tint)
        self._apply_rounding(rounded=True)

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

        ``rounded=False`` 不是「不圆角」，而是「**别插手**」：底由我们自己画时，圆角也是
        我们自己画的（QPainterPath + 抗锯齿），半径才不受系统那个固定值约束。
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

