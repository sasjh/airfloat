#!/usr/bin/env python3
"""AirFloat 浮窗 UI 自测（离屏运行：``python src_py/ui/test_ui.py``）。

守住的是「看得见的承诺」：
- 材质：窗口是真实的桌面模糊（亚克力）+ 圆角裁剪，拿不到时降级为纯色薄膜；
- 几何：无边框窗口可八向缩放，守住最小尺寸，列数随宽度变化；
- 模块卡片：圆钮开关 / 点卡片出菜单，状态与 _state 永远一致；
- 弹出菜单：三项、勾选行跟随当前取值、选中即回传 receive_mode_changed；
- 图片口：每张缩略图都有删除键，删除只影响列表与待发送队列；
- 对比度：文字按「材质最差底」校准，达 WCAG AA。
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QByteArray, QPoint, QRect, QRectF, QSettings, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import ui.main_window as mw  # noqa: E402
from ui import glass as ui_glass  # noqa: E402
from ui import liquid as ui_liquid  # noqa: E402
from ui import styles  # noqa: E402

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILURES.append(f"{label} {detail}".strip())
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"  [{detail}]" if detail and not ok else ""))


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    raw = color.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    lo, hi = min(a, b), max(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _flatten(fg_hex: str, alpha: float, under_hex: str) -> str:
    """把半透明前景压在底色上，得到等效实色 —— 对比度必须按这个实色算。"""
    f, u = fg_hex.lstrip("#"), under_hex.lstrip("#")
    out = []
    for i in (0, 2, 4):
        fv, uv = int(f[i : i + 2], 16), int(u[i : i + 2], 16)
        out.append(round(fv * alpha + uv * (1 - alpha)))
    return "#%02X%02X%02X" % tuple(out)


def _glass_probe(**kwargs) -> QImage:
    """把一块液态玻璃画进离屏小图：验证光影分层用，不依赖真实桌面。"""
    image = QImage(80, 40, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    ui_liquid.paint_glass(painter, QRectF(0.5, 0.5, 79.0, 39.0), 10.0, **kwargs)
    painter.end()
    return image


def _peak_alpha(image: QImage, area: QRect) -> int:
    """区域内最大的 alpha：边缘描边被抗锯齿摊开，取峰值最稳。"""
    return max(
        image.pixelColor(x, y).alpha()
        for y in range(area.top(), area.bottom() + 1)
        for x in range(area.left(), area.right() + 1)
    )


def _pixel_diff(first: QImage, second: QImage) -> int:
    """两张同尺寸图有多少像素不同。"""
    return sum(
        1
        for y in range(first.height())
        for x in range(first.width())
        if first.pixel(x, y) != second.pixel(x, y)
    )


def _sample_images(count: int) -> list[str]:
    folder = tempfile.mkdtemp(prefix="airfloat_ui_")
    paths = []
    for index in range(count):
        image = QImage(240, 180, QImage.Format.Format_RGB32)
        image.fill(QColor(["#E4572E", "#17BEBB", "#2E86AB", "#A23B72", "#F3A712"][index % 5]))
        painter = QPainter(image)
        painter.end()
        path = os.path.join(folder, f"sample_{index}.png")
        image.save(path)
        paths.append(path)
    return paths


def _snapshot(settings: QSettings) -> dict:
    """把一份配置拍平成可比对的字典（QByteArray 转 bytes）。"""
    snap = {}
    for key in settings.allKeys():
        value = settings.value(key)
        snap[key] = bytes(value) if isinstance(value, QByteArray) else value
    return snap


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    paths = _sample_images(5)

    # 自测绝不能读写用户的真实配置：换独立 scope 并清空，保证可重复运行；
    # 收尾再断言真实 scope 一字未改（窗口几何会随 closeEvent 落盘，必须隔离）。
    real_scope = ("AirFloat", "AirFloatWindow")
    real_before = _snapshot(QSettings(*real_scope))
    mw.SETTINGS_ORG, mw.SETTINGS_APP = "AirFloatUITest", "AirFloatUITest"
    QSettings(mw.SETTINGS_ORG, mw.SETTINGS_APP).clear()

    window = mw.AirFloatWindow()
    window.show()
    app.processEvents()

    print("\n[1] 几何：可缩放 + 最小尺寸")
    check("最小尺寸 = MIN_WINDOW", window.minimumSize() == QSize(*mw.MIN_WINDOW), str(window.minimumSize()))
    check("默认尺寸 = DEFAULT_WINDOW", window.size() == QSize(*mw.DEFAULT_WINDOW), str(window.size()))
    check("不再是固定尺寸", window.minimumSize() != window.maximumSize())
    window.resize(700, 600)
    app.processEvents()
    check("放大后窗口尺寸跟随", window.width() == 700, str(window.width()))
    window.resize(100, 100)
    app.processEvents()
    check("缩小被最小尺寸挡住", (window.width(), window.height()) == mw.MIN_WINDOW, str(window.size()))
    window.resize(*mw.DEFAULT_WINDOW)
    app.processEvents()

    print("\n[2] 缩放热区 / 光标")
    left_edge = window._edges_at(QPoint(1, 100))
    check("左边缘命中 LeftEdge", bool(left_edge & Qt.Edge.LeftEdge))
    corner = window._edges_at(QPoint(2, 2))
    check("左上角命中双对角", window._cursor_for(corner) == Qt.CursorShape.SizeFDiagCursor)
    check("中部不命中热区", window._edges_at(QPoint(200, 200)) is None)

    print("\n[3] 材质")
    check("材质对象存在", window._material is not None)
    check("材质模式可读", window._material.mode in ("acrylic", "blur", "solid"), window._material.mode)
    # 圆角：模糊是 DWM 画的、不认窗口区域，所以必须让 DWM 自己圆角（常量接线要对），
    # 而窗口自己的裁剪半径要与 DWM 的系统半径一致，避免出现两条不同心的弧。
    check("glass 接的是 DWM 圆角偏好",
          ui_glass.DWMWA_WINDOW_CORNER_PREFERENCE == 33 and ui_glass.DWMWCP_ROUND == 2)
    check("窗口裁剪半径 = RADIUS_WINDOW 令牌",
          window._material._region_key is not None and window._material._region_key[2] == mw.RADIUS_WINDOW,
          str(window._material._region_key))
    check("RADIUS_WINDOW 与文档一致（8）", mw.RADIUS_WINDOW == 8, str(mw.RADIUS_WINDOW))

    print("\n[4] 模块卡片：状态显示")
    window.on_state({"enabled": True, "receiveMode": "everyone", "alias": "我的电脑"})
    app.processEvents()
    check("开启 + 所有人", window._card._value_label.text() == mw.MODE_LABELS["everyone"], window._card._value_label.text())
    window.on_state({"enabled": False, "receiveMode": "everyone"})
    app.processEvents()
    check("关闭时显示接收关闭", window._card._value_label.text() == mw.MODE_LABELS["off"], window._card._value_label.text())

    print("\n[5] 模块卡片：点圆钮 = 开关（圆钮外的区域不触发开关）")
    emitted: list[bool] = []
    window.enabled_changed.connect(emitted.append)
    window.on_state({"enabled": False})
    app.processEvents()
    QTest.mouseClick(window._card, Qt.MouseButton.LeftButton, pos=QPoint(80, 120))
    app.processEvents()
    check("点卡片主体不触发开关", emitted == [], str(emitted))
    icon_center = window._card._icon_rect().center().toPoint()
    QTest.mouseClick(window._card, Qt.MouseButton.LeftButton, pos=icon_center)
    app.processEvents()
    check("点圆钮触发 enabled_changed(True)", emitted[-1:] == [True], str(emitted))
    check("开关后卡片取值跟着走", window._card._value_label.text() == mw.MODE_LABELS["everyone"], window._card._value_label.text())

    print("\n[6] 弹出菜单：三项 / 勾选 / 回传")
    window.on_state({"enabled": True, "receiveMode": "contacts"})
    app.processEvents()
    QTest.mouseClick(window._card, Qt.MouseButton.LeftButton, pos=QPoint(80, 120))
    app.processEvents()
    check("点卡片主体弹出菜单", window._menu.isVisible())
    check("菜单三项", list(window._menu.rows.keys()) == list(mw.MODE_ORDER), str(list(window._menu.rows.keys())))
    check("勾选跟随当前取值", window._menu.rows["contacts"]._selected and not window._menu.rows["off"]._selected)
    check("菜单宽 = MENU_W", window._menu._panel.width() == mw.MENU_W, str(window._menu._panel.width()))
    chosen: list[str] = []
    window.receive_mode_changed.connect(chosen.append)
    QTest.mouseClick(window._menu.rows["everyone"], Qt.MouseButton.LeftButton, pos=window._menu.rows["everyone"].rect().center())
    app.processEvents()
    check("选「所有人」回传 mode", chosen == ["everyone"], str(chosen))
    check("选完菜单关闭", not window._menu.isVisible())
    check("卡片取值更新", window._card._value_label.text() == mw.MODE_LABELS["everyone"])

    print("\n[7] 选「接收关闭」= 关掉接收（不动上一次的 receiveMode）")
    window.on_state({"enabled": True, "receiveMode": "everyone"})
    app.processEvents()
    window._on_mode_chosen("off")
    app.processEvents()
    check("enabled 变 False", window._state["enabled"] is False)
    check("receiveMode 保持不变", window._state["receiveMode"] == "everyone", window._state["receiveMode"])
    check("卡片显示接收关闭", window._card._value_label.text() == mw.MODE_LABELS["off"])
    window._toggle_enabled()
    app.processEvents()
    check("再开回到上次的「所有人」", window._state["enabled"] and window._card._value_label.text() == mw.MODE_LABELS["everyone"])

    print("\n[8] 图片口：缩略图 + 删除键")
    for index, path in enumerate(paths[:4]):
        window.on_received_item({"file_path": path, "file_name": f"照片_{index + 1}.png"})
    app.processEvents()
    thumbs = [window._image_port._grid.itemAt(i).widget() for i in range(window._image_port._grid.count())]
    check("收了 4 张就有 4 个缩略图", len(thumbs) == 4, str(len(thumbs)))
    check("每张都有删除键", all(isinstance(t, mw.ThumbWidget) and t._delete_btn is not None for t in thumbs))
    check("删除键在卡片右上角", thumbs[0]._delete_btn.x() == mw.THUMB_W - mw.DELETE_BTN - mw.DELETE_INSET)

    before = len(window._received_items)
    target = window._received_items[1]
    QTest.mouseClick(thumbs[1]._delete_btn, Qt.MouseButton.LeftButton, pos=QPoint(mw.DELETE_BTN // 2, mw.DELETE_BTN // 2))
    app.processEvents()
    check("删除键只删掉这一张", len(window._received_items) == before - 1, str(len(window._received_items)))
    check("删掉的正是被点的那张", all(item is not target for item in window._received_items))
    check("剩下的顺序不变", [item["file_name"] for item in window._received_items] == ["照片_1.png", "照片_3.png", "照片_4.png"],
          str([item["file_name"] for item in window._received_items]))
    check("计数跟着更新", window._received_count.text() == "已接收 3 张", window._received_count.text())

    print("\n[9] 拖入的图被删掉时，待发送队列也要清掉")
    window._pending_send.clear()
    window.on_received_item({"file_path": paths[4], "file_name": "照片_5.png"})
    window._pending_send.append(paths[4])
    app.processEvents()
    removed = window._received_items[-1]
    window._remove_item(removed)
    app.processEvents()
    check("待发送队列里不再有它", paths[4] not in window._pending_send, str(window._pending_send))

    print("\n[10] 列数随宽度变化")
    window.resize(mw.MIN_WINDOW[0], 520)
    app.processEvents()
    narrow = window._image_port._columns
    window.resize(820, 520)
    app.processEvents()
    wide = window._image_port._columns
    check("变宽后列数变多", wide > narrow, f"{narrow} -> {wide}")
    rows_used = {window._image_port._grid.getItemPosition(i)[0] for i in range(window._image_port._grid.count())}
    check("重排后没有溢出网格", max(rows_used) < len(window._received_items))

    print("\n[11] Toast 定位在窗口内")
    window.show_toast("已接收：照片_1.png", "success")
    app.processEvents()
    QTest.qWait(400)
    geo = window._toast_label.geometry()
    check("Toast 可见", window._toast_label.isVisible())
    check("Toast 水平居中", abs((geo.x() + geo.width() // 2) - window.width() // 2) <= 1, str(geo))
    check("Toast 在窗口内", geo.right() <= window.width() and geo.bottom() <= window.height(), str(geo))

    print("\n[12] 关闭出口")
    window.keyPressEvent(type("E", (), {"key": lambda self: Qt.Key.Key_Escape, "accept": lambda self: None,
                                        "ignore": lambda self: None})())
    app.processEvents()
    check("Esc 关闭窗口", not window.isVisible())

    print("\n[13] 对比度：按材质最差底（玻璃最暗处）校准")
    # 最差底是「逐层压出来」的，不是写死的：玻璃着色 → 最重的结构洗（侧栏）→ 底部内阴影。
    # 三层全部取自令牌，所以动了其中任何一个都会在这里被重新校验，不会悄悄漂移。
    tint_alpha = ((styles.GLASS_TINT_ABGR >> 24) & 0xFF) / 255.0
    worst = _flatten(styles.BG, tint_alpha, "#000000")          # 玻璃压纯黑桌面
    worst = _flatten(styles.RECESS_WASH, styles.RAIL_ALPHA, worst)   # 再加侧栏的深色洗
    worst = _flatten(styles.RECESS_WASH, styles.BOTTOM_SHADE / 255.0, worst)  # 再加底部内阴影
    check(f"最差底 = 玻璃@{tint_alpha:.0%} + 侧栏洗 + 底影 = #92999F", worst == "#92999F", worst)
    for name, color, floor in (
        ("主文字 TEXT", styles.TEXT, 4.5),
        ("次要文字 TEXT_SECONDARY", styles.TEXT_SECONDARY, 4.5),
        ("成功文字 SUCCESS", styles.SUCCESS, 4.5),
    ):
        ratio = _contrast(color, worst)
        check(f"{name} {ratio:.2f}:1 ≥ {floor}", ratio >= floor)
    for name, fg, bg, floor in (
        ("强调色上的白字", "#FFFFFF", styles.ACCENT, 4.5),
        ("圆钮白字形", "#FFFFFF", styles.ACCENT_ICON, 3.0),
        ("关闭态白字形", "#FFFFFF", styles.OFFLINE, 3.0),
        ("删除键悬停白字形", "#FFFFFF", styles.DANGER, 4.5),
    ):
        ratio = _contrast(fg, bg)
        check(f"{name} {ratio:.2f}:1 ≥ {floor}", ratio >= floor)
    menu_bg = _flatten(styles.MENU_BG, styles.MENU_ALPHA, worst)
    check(f"菜单文字白字 {_contrast('#FFFFFF', menu_bg):.2f}:1 ≥ 4.5", _contrast("#FFFFFF", menu_bg) >= 4.5)

    print("\n[14] 拖动窗口：顶栏按下即跟手移动（不依赖 startSystemMove）")
    window.show()
    window.resize(*mw.DEFAULT_WINDOW)
    window.move(200, 160)
    app.processEvents()
    topbar = window.findChild(mw.TopBar)
    check("找到顶栏", topbar is not None)
    QTest.mousePress(topbar, Qt.MouseButton.LeftButton, pos=QPoint(200, 22))
    app.processEvents()
    check("按下顶栏即进入拖动会话", window._move_session is not None)
    QTest.mouseMove(topbar, QPoint(240, 47))
    app.processEvents()
    check("窗口跟手位移 (+40,+25)", (window.x(), window.y()) == (240, 185), f"{window.x()},{window.y()}")
    QTest.mouseRelease(topbar, Qt.MouseButton.LeftButton, pos=QPoint(240, 47))
    app.processEvents()
    check("松手结束拖动会话", window._move_session is None)
    check("松手后窗口停在新位置", (window.x(), window.y()) == (240, 185), f"{window.x()},{window.y()}")

    print("\n[15] 液态玻璃：光影结构 + 玻璃面接线")
    # 一层一层验：高光强度可关（lit=0 必须全透明，绝不挡住背后的真实模糊）
    check("lit=0 ⇒ 整块透明（高光强度可控）", _peak_alpha(_glass_probe(lit=0.0), QRect(0, 0, 79, 39)) == 0)
    # 默认只画光影：内部透明、边缘发光 —— 玻璃是「边缘在反光」，不是一块实心贴纸
    rim = _glass_probe()
    check("内部保持透明（远离高光处不实心挡底）", rim.pixelColor(60, 33).alpha() == 0,
          str(rim.pixelColor(60, 33).alpha()))
    top_edge, bottom_edge = QRect(30, 0, 20, 2), QRect(30, 38, 20, 2)
    check("受光边（上）有镜面高光", _peak_alpha(rim, top_edge) > 0)
    check("背光边（下）比受光边淡", _peak_alpha(rim, top_edge) > _peak_alpha(rim, bottom_edge),
          f"{_peak_alpha(rim, top_edge)} vs {_peak_alpha(rim, bottom_edge)}")
    # 四层光影各自独立接线：关掉任何一层，画面都必须变
    for label, kwargs in (
        ("顶部光泽", {"gloss": False}),
        ("镜面热点", {"specular": False}),
        ("边缘色差", {"aberration": False}),
        ("镜面边缘光", {"rim": False}),
    ):
        check(f"{label}确实画了", _pixel_diff(rim, _glass_probe(**kwargs)) > 0)
    # 按下：内阴影把顶边压暗（同一块玻璃，按下后更暗）
    flat = {"tint": QColor("#FFFFFF"), "alpha": 0.55, "gloss": False, "specular": False,
            "aberration": False, "rim": False}
    plain, dent = _glass_probe(**flat), _glass_probe(**flat, pressed=True)
    check("按下压出内阴影（顶边变暗）",
          dent.pixelColor(40, 3).lightness() < plain.pixelColor(40, 3).lightness(),
          f"{dent.pixelColor(40, 3).lightness()} vs {plain.pixelColor(40, 3).lightness()}")
    # 浅材质面是半透明的（实底会把背后的模糊挡死）
    face = _glass_probe(
        tint=QColor("#FFFFFF"), alpha=0.55, gloss=False, specular=False, aberration=False, rim=False
    ).pixelColor(40, 20).alpha()
    check("浅材质面半透明（落在 0.55 的上下渐变里，不是实底）", 115 <= face <= 160, str(face))
    # 回弹：按下缩一点、松手弹回
    spring = mw.PressSpring(window)
    spring.press()
    QTest.qWait(260)
    check("按下回弹：按下时缩一点", spring.scale < 1.0, f"{spring.scale:.3f}")
    spring.release()
    QTest.qWait(260)
    check("松手弹回原尺寸", abs(spring.scale - 1.0) < 1e-6, f"{spring.scale:.3f}")
    # 玻璃是半透明的：白字压在强调色玻璃上（最差底）也得 ≥ 4.5:1
    for label, color, alpha in (
        ("常态", styles.ACCENT, 0.94),
        ("悬停", styles.ACCENT_HOVER, 0.96),
        ("按下", styles.ACCENT_PRESSED, 0.98),
    ):
        ratio = _contrast("#FFFFFF", _flatten(color, alpha, worst))
        check(f"发送键白字（{label}）{ratio:.2f}:1 ≥ 4.5", ratio >= 4.5)
    # 接线：该用玻璃的地方都用上了；容器不再自己铺底色（否则会挡住玻璃）
    check("侧栏是玻璃底板", isinstance(window.findChild(mw.GlassSurface), mw.GlassSurface))
    check("发送键是强调色玻璃按钮", isinstance(window._send_btn, mw._SendButton))
    check("图标按钮悬挂停玻璃（文件夹 / 关闭）",
          (window._folder_btn._hover_tone, window._close_btn._hover_tone) == ("light", "danger"))
    probe_thumb = mw.ThumbWidget(paths[0], "probe.png")
    check("删除键：常显深色玻璃 + 悬停错误色",
          (probe_thumb._delete_btn._rest_tone, probe_thumb._delete_btn._hover_tone) == ("dark", "danger"))
    probe_thumb.deleteLater()
    check("tone 表认得 light，未知回退 None",
          mw._tone("light") is not None and mw._tone("none") is None and mw._tone("nope") is None)
    # 删除键压在**任意照片**上：最差是纯白照片，白字形也得 ≥ 3:1
    scrim = _flatten("#0C0E12", 0.58, "#FFFFFF")
    ratio = _contrast("#FFFFFF", scrim)
    check(f"删除键白字形（压纯白照片）{ratio:.2f}:1 ≥ 3.0", ratio >= 3.0, scrim)
    check("页面容器不再自己铺底色（玻璃由 paintEvent 画）",
          "QFrame#sidebar { background: transparent; }" in styles.QSS
          and "QFrame#imagePort { background: transparent; }" in styles.QSS
          and "QPushButton#sendBtn:hover" not in styles.QSS)

    check("自测没有写用户真实配置", _snapshot(QSettings(*real_scope)) == real_before)
    QSettings(mw.SETTINGS_ORG, mw.SETTINGS_APP).clear()

    print(f"\n{'=' * 60}\n共 {CHECKS} 项，失败 {len(FAILURES)} 项")
    for failure in FAILURES:
        print("  FAIL  " + failure)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
