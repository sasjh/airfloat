#!/usr/bin/env python3
"""AirFloat 浮窗 UI 自测（离屏运行：``python src_py/ui/test_ui.py``）。

守住的是「看得见的承诺」：
- 材质：窗口是真实的桌面模糊（纯模糊，不掺系统乳白）+ 圆角裁剪，拿不到时降级为纯色薄膜；
- 几何：无边框窗口可八向缩放，守住最小尺寸，列数随宽度变化；
- 模块卡片：圆钮开关 / 点卡片出菜单，状态与 _state 永远一致；
- 弹出菜单：三项、勾选行跟随当前取值、选中即回传 receive_mode_changed；
- 图片口：每张缩略图都有删除键，删除只影响列表与待发送队列；
- 移动：拖窗口期间不降级材质（亚克力一路都在，桌面在玻璃底下跟着走）；
- 对比度：文字按「最暗底」逐层压出来校；白色字形按「最亮底」校。
  近透档（整窗薄面 0.30）≥ 2.6:1，厚面档（薄面 0.52）≥ 4.5:1 —— 两档的数都摆在 §13 里。
- 空态：图片口裸透（自己不画任何东西），亮字只有一档不透明度、周围不垫任何东西。
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import (  # noqa: E402
    QByteArray,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402
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


def _glow_probe(light: QPointF | None = None) -> QImage:
    """只画「受光边那圈薄光」的离屏小图（80x40 的玻璃片）。"""
    image = QImage(80, 40, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    ui_liquid.paint_edge_glow(painter, QRectF(0.5, 0.5, 79.0, 39.0), 10.0, light=light)
    painter.end()
    return image


def _well_probe(**kwargs) -> QImage:
    """把一枚凹槽环玻璃画进离屏小图：验证槽底 / 发丝环 / 顶影 / 底光的分布。"""
    image = QImage(60, 60, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    fill = kwargs.pop("fill", styles.SEND_WELL)
    ui_liquid.paint_well_glass(painter, QRectF(0.5, 0.5, 59.0, 59.0), 29.5, fill=fill, **kwargs)
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
    # 圆角有**两套**半径，用哪套取决于「谁在裁那层模糊」（见 glass.region_clips_backdrop）：
    # 纯模糊时模糊跟着窗口区域走（实测 16px 的区域把模糊也裁圆了），圆角归我们管 —— 想多
    # 圆有多圆，同时必须让 DWM 别插手；亚克力兜底时模糊由 DWM 画、不认区域，圆角只能交给
    # DWM，半径是系统固定的那档，我们画的弧得跟它同半径，否则四角出现两条不同心的弧。
    check("glass 接的是 DWM 圆角偏好",
          ui_glass.DWMWA_WINDOW_CORNER_PREFERENCE == 33 and ui_glass.DWMWCP_ROUND == 2
          and ui_glass.DWMWCP_DONOTROUND == 1)
    check("窗口裁剪半径 = 当前生效的那套圆角令牌（绘制与裁剪同一个值）",
          window._material._region_key is not None
          and window._material._region_key[2] == window._window_radius(),
          str(window._material._region_key))
    check("整套半径与文档一致：自己裁 16 / 系统裁 8",
          (mw.RADIUS_WINDOW, mw.RADIUS_WINDOW_SYSTEM) == (16, 8),
          f"{mw.RADIUS_WINDOW} / {mw.RADIUS_WINDOW_SYSTEM}")
    check("两条圆角规则互斥：DWM 在裁圆角时，区域就不再负责裁模糊（不会各裁一刀）",
          not (window._material.rounded_by_dwm and window._material.region_clips_backdrop))

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
    # 最差底是「逐层压出来」的，不是写死的：玻璃着色 → 文字区薄面 → 底部内阴影。
    # 三层全部取自令牌，所以动了其中任何一个都会在这里被重新校验，不会悄悄漂移。
    tint_alpha = ((styles.GLASS_TINT_ABGR >> 24) & 0xFF) / 255.0
    floor_bg = _flatten(styles.BG, tint_alpha, "#000000")      # 玻璃压纯黑桌面（图片口 = 最透处）
    page_bg = _flatten(styles.CARD, styles.SIDEBAR_FACE, floor_bg)   # 侧栏 = 顶栏 = 状态栏（同一档）
    worst = _flatten(styles.RECESS_WASH, styles.BOTTOM_SHADE / 255.0, page_bg)  # + 底部内阴影
    check(f"最差底 = 玻璃@{tint_alpha:.0%} + 薄面@{styles.SIDEBAR_FACE:.0%} + 底影 = #5F6061",
          worst == "#5F6061", worst)
    check("整窗薄面只有一档（三处同价，不做位置差价）",
          styles.SIDEBAR_FACE == styles.TOPBAR_FACE == styles.STATUSBAR_FACE,
          f"{styles.SIDEBAR_FACE} / {styles.TOPBAR_FACE} / {styles.STATUSBAR_FACE}")
    # 顶栏亮 → 内容中 → 状态栏沉：底影得看得见，但不能把字吃掉（上面那条就是它）。
    check("底影把最差底又压下去一档（状态栏仍比顶栏沉）",
          _contrast(styles.TEXT, worst) < _contrast(styles.TEXT, page_bg))
    # 深色文字按 worst（最暗底）校；白色字形反过来按 lightest（最亮底 = 纯白壁纸）校。
    lightest = _flatten(styles.BG, tint_alpha, "#FFFFFF")
    # 整窗现在走的是**近透档**（薄面 0.30）：桌面几乎原样上得来，代价就是深色字压在深色桌面上
    # 只剩 2.6~2.9:1 —— 这是**刻意的取舍**（用户一路把侧栏 / 上栏 / 下栏都推到这一档），
    # 所以口径是「比裸玻璃（1.02:1）好得多、且三支墨都还拿得出手」，不再套 AA。
    # 想换回 AA 只需要把薄面调回 0.52 —— 下面那条对照就是给这件事留的凭据：同一套字色，
    # 薄面回到 0.52 时三支墨都 ≥ 4.5:1。透明度和对比度在这个材质里就是一根跷跷板。
    for name, color, floor in (
        ("主文字 TEXT", styles.TEXT, 2.8),
        ("次要文字 TEXT_SECONDARY", styles.TEXT_SECONDARY, 2.7),
        ("成功文字 SUCCESS", styles.SUCCESS, 2.6),
    ):
        ratio = _contrast(color, worst)
        check(f"{name} {ratio:.2f}:1 ≥ {floor}（近透档）", ratio >= floor)
    check("但三支墨都比裸玻璃上强太多（薄面不是白加的）",
          min(_contrast(c, worst) for c in (styles.TEXT, styles.TEXT_SECONDARY, styles.SUCCESS))
          > 2.0 * _contrast(styles.TEXT, floor_bg))
    aa_worst = _flatten(styles.RECESS_WASH, styles.BOTTOM_SHADE / 255.0,
                       _flatten(styles.CARD, 0.52, floor_bg))
    aa_ratios = [_contrast(c, aa_worst) for c in
                 (styles.TEXT, styles.TEXT_SECONDARY, styles.SUCCESS)]
    check(f"薄面调回 0.52 时同一套字色 ≥ 4.5:1（AA）：{aa_ratios[1]:.2f} —— "
          f"透明是**换**来的，不是白得的",
          all(r >= 4.5 for r in aa_ratios), str([round(r, 2) for r in aa_ratios]))
    # 图片口是整窗最透的一处：深色文字在这儿根本压不住（上面那条就是它），所以空态提示走
    # 参考图（iOS「Clear」面板）那条路 —— **亮字、只有一档不透明度**，周围不垫任何东西。
    # 参考图里那行白字就是直接压在墙上，靠字号 / 字重立层级，不是靠加底。加底反而会在
    # 这块玻璃上浮出一片灰（深色桌面上尤其显眼），正是本轮要拿掉的东西。所以这里不再校
    # 比值 —— 亮字压在亮壁纸上天然低对比，那是刻意的 —— 只守两条：一档不透明度、不带底。
    bare_dark = _contrast(styles.TEXT, floor_bg)
    check(f"最透处裸玻璃上深色文字 {bare_dark:.2f}:1 站不住 ⇒ 空态提示走亮字", bare_dark < 4.5,
          f"{bare_dark:.2f}")
    check("空态只有一档不透明度：大标题 / 副行同取 HINT_TEXT（差的只是字号）",
          re.search(r"QLabel#emptyMain, QLabel#emptySub \{ color: %s; background: transparent; \}"
                    % re.escape(styles.HINT_TEXT), styles.QSS) is not None,
          styles.HINT_TEXT)
    check("空态周围不垫任何东西：衬底 / 光晕 / 内衬距令牌都已删",
          not any(hasattr(styles, name) for name in
                  ("HINT_SCRIM", "HINT_HALO", "HINT_FEATHER", "HINT_PAD_X", "HINT_PAD_Y")))
    # 设备行悬停是**亮**一档（悬停 = 更靠近手指 = 光更足），不是压暗 —— 行内是次要文字，
    # 压暗会把它先推到读不清；亮一档反而把底抬起来，近透档下悬停那行的字比常态更好读。
    hover_bg = _flatten(styles.CARD, styles.ROW_HOVER_FACE, page_bg)
    hover_ratio = _contrast(styles.TEXT_SECONDARY, hover_bg)
    rest_ratio = _contrast(styles.TEXT_SECONDARY, page_bg)
    check(f"设备行悬停底更亮，行内次要文字从 {rest_ratio:.2f} 升到 {hover_ratio:.2f}:1（≥ 常态 × 1.25）",
          styles.ROW_HOVER_FACE > 0 and hover_ratio >= rest_ratio * 1.25, hover_bg)
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
    # 前面几节用手动鼠标事件做过交互，那会把**指针光**带到别处；量光影之前先回到静息光位
    # （真实运行时，那正是「指针不在窗口上」时的样子）。
    light_field = ui_liquid.pointer_light()
    light_field._current = light_field._target = QPointF(*styles.GLASS_LIGHT_REST)
    # 一层一层验：高光强度可关（lit=0 必须全透明，绝不挡住背后的真实模糊）
    check("lit=0 ⇒ 整块透明（高光强度可控）", _peak_alpha(_glass_probe(lit=0.0), QRect(0, 0, 79, 39)) == 0)
    # 默认只画光影：内部透明、边缘发光 —— 玻璃是「边缘在反光」，不是一块实心贴纸。
    # 「远离高光处」得取**对角**的那个角：光轴锚点现在落在**边上**（见 liquid._edge_hit），
    # 静息光位下镜面热点就贴着上边中段，离它最远的是右下角。
    rim = _glass_probe()
    check("内部保持透明（对角那一侧不实心挡底）", rim.pixelColor(77, 37).alpha() == 0,
          str(rim.pixelColor(77, 37).alpha()))
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
    flat = {"tint": QColor("#FFFFFF"), "alpha": styles.GLASS_SURFACE,
            "gloss": False, "specular": False,
            "aberration": False, "rim": False}
    plain, dent = _glass_probe(**flat), _glass_probe(**flat, pressed=True)
    check("按下压出内阴影（顶边变暗）",
          dent.pixelColor(40, 3).lightness() < plain.pixelColor(40, 3).lightness(),
          f"{dent.pixelColor(40, 3).lightness()} vs {plain.pixelColor(40, 3).lightness()}")
    # 浅材质面是「低透」：不是实底（背后模糊会被挡死），也不能让背后脏色透上来。
    # 上下界直接由令牌推出，改 GLASS_SURFACE 就必须重算，不会和注释漂移。
    surface = styles.GLASS_SURFACE
    face = _glass_probe(
        tint=QColor("#FFFFFF"), alpha=surface, gloss=False, specular=False,
        aberration=False, rim=False
    ).pixelColor(40, 20).alpha()
    low, high = round(255 * surface * 0.84), round(255 * surface * 1.12)
    check(f"浅材质面低透（{low} ≤ alpha ≤ {high}）", low <= face <= high, str(face))
    # 回弹：按下缩一点、松手弹回
    spring = mw.PressSpring(window)
    spring.press()
    QTest.qWait(260)
    check("按下回弹：按下时缩一点", spring.scale < 1.0, f"{spring.scale:.3f}")
    spring.release()
    QTest.qWait(260)
    check("松手弹回原尺寸", abs(spring.scale - 1.0) < 1e-6, f"{spring.scale:.3f}")
    # 发送键不再是文字按钮：白箭头压在强调色槽底上，最亮底（纯白壁纸）也要 ≥ 3:1
    for label, color, fill in (
        ("常态", styles.ACCENT, styles.SEND_WELL),
        ("悬停", styles.ACCENT_HOVER, styles.SEND_WELL_HOVER),
        ("按下", styles.ACCENT_PRESSED, styles.SEND_WELL_PRESSED),
    ):
        # 槽底是上深下浅的渐变：字形脚下最亮的一档是 fill * RING_FILL_FLOOR
        ratio = _contrast("#FFFFFF", _flatten(color, fill * styles.RING_FILL_FLOOR, lightest))
        check(f"发送键白箭头（{label}）{ratio:.2f}:1 ≥ 3.0", ratio >= 3.0)
    check("底内受光只贴边（不爬到箭头下面）",
          styles.RING_LIGHT_TOP > 0.5 + mw.SEND_GLYPH / 2.0,
          f"{styles.RING_LIGHT_TOP} vs {0.5 + mw.SEND_GLYPH / 2.0}")
    # 接线：画的确实是「圆形凹槽环玻璃 + 白色向上箭头」，槽底走 SEND_WELL 令牌
    drawn: dict = {}
    real_glyph, real_well = mw.paint_glyph, mw.paint_well_glass
    mw.paint_glyph = lambda p, name, rect, color: drawn.setdefault(
        "glyph", (name, QColor(color).name()))
    mw.paint_well_glass = lambda p, rect, radius, **kw: drawn.setdefault(
        "well", (rect, radius, kw))
    window._send_btn.paintEvent(None)
    mw.paint_glyph, mw.paint_well_glass = real_glyph, real_well
    well = drawn.get("well")
    check("发送键是圆形凹槽环玻璃", bool(well) and abs(well[1] - mw.SEND_BTN / 2.0) < 0.01,
          str(well[1] if well else None))
    check("发送键的槽底走 SEND_WELL 令牌",
          bool(well) and well[2].get("fill") == styles.SEND_WELL,
          str(well[2].get("fill") if well else None))
    check("发送键画的是白色向上箭头（不再是文字）",
          drawn.get("glyph") == ("arrow_up", "#ffffff"), str(drawn.get("glyph")))
    # 接线：该用玻璃的地方都用上了；容器不再自己铺底色（否则会挡住玻璃）
    check("侧栏是玻璃底板", isinstance(window.findChild(mw.GlassSurface), mw.GlassSurface))
    check("发送键是自绘圆钮（_SendButton）", isinstance(window._send_btn, mw._SendButton))
    check("图标按钮悬挂停玻璃（文件夹 / 关闭）",
          (window._folder_btn._hover_tone, window._close_btn._hover_tone) == ("light", "danger"))
    probe_thumb = mw.ThumbWidget(paths[0], "probe.png")
    check("删除键：常显深色玻璃 + 悬停错误色",
          (probe_thumb._delete_btn._rest_tone, probe_thumb._delete_btn._hover_tone) == ("dark", "danger"))
    probe_thumb.deleteLater()
    check("tone 表认得 light，未知回退 None",
          styles.tone_material("light") is not None
          and styles.tone_material("none") is None
          and styles.tone_material("nope") is None)
    # 删除键压在**任意照片**上：最差是纯白照片，白字形也得 ≥ 3:1
    scrim = _flatten("#0C0E12", 0.58, "#FFFFFF")
    ratio = _contrast("#FFFFFF", scrim)
    check(f"删除键白字形（压纯白照片）{ratio:.2f}:1 ≥ 3.0", ratio >= 3.0, scrim)
    check("页面容器不再自己铺底色（玻璃由 paintEvent 画）",
          "QFrame#sidebar { background: transparent; }" in styles.QSS
          and "QFrame#imagePort { background: transparent; }" in styles.QSS
          and "QPushButton#sendBtn:hover" not in styles.QSS)

    print("\n[16] 层级与克制：低透面 / 渐变光影 / 玻璃只做点缀")
    # ① 两套材质分工：内容面负责「看得清」（实），控件面负责「像玻璃」（透）；
    #    控件悬停更「实」（不是更透明），按下退回去。
    check("控件玻璃比内容玻璃透（半透才有呼吸感）",
          styles.CONTROL_GLASS < styles.GLASS_SURFACE,
          f"{styles.CONTROL_GLASS} vs {styles.GLASS_SURFACE}")
    check("材质阶梯：内容面 > 控件悬停 > 控件 > 控件按下",
          styles.GLASS_SURFACE > styles.CONTROL_GLASS_HOVER > styles.CONTROL_GLASS
          > styles.CONTROL_GLASS_PRESSED,
          f"{styles.GLASS_SURFACE} / {styles.CONTROL_GLASS_HOVER} / "
          f"{styles.CONTROL_GLASS} / {styles.CONTROL_GLASS_PRESSED}")
    # ② 玻璃只做点缀：内容（照片瓦片）不再套玻璃光影，只留低透的面 + 发丝线
    seen: dict = {}
    real_paint = mw.paint_glass
    mw.paint_glass = lambda p, r, rad, **kw: seen.update(kw)
    tile = mw.ThumbWidget(paths[0], "tile.png")
    tile.resize(mw.THUMB_W, mw.THUMB_CELL_H)
    tile.paintEvent(None)
    mw.paint_glass = real_paint
    check("内容瓦片不套玻璃光影（玻璃只做点缀）",
          not any(seen.get(key) for key in ("gloss", "specular", "aberration", "rim")), str(seen))
    check("内容瓦片的面取自 GLASS_SURFACE 令牌",
          seen.get("alpha") == styles.GLASS_SURFACE, str(seen.get("alpha")))
    tile.deleteLater()
    # ③ 整窗不再铺满光泽带（那层铺满上半屏的白就是「奶膜」= 糊）
    shell: list = []
    mw.paint_glass = lambda p, r, rad, **kw: shell.append(kw)
    window.paintEvent(None)
    mw.paint_glass = real_paint
    check("整窗不铺光泽带（gloss=False）", bool(shell) and shell[0].get("gloss") is False, str(shell))
    check("整窗高光走令牌且比控件克制",
          shell[0].get("lit") == styles.GLASS_LIT_WINDOW < styles.GLASS_LIT_REST,
          str(shell[0].get("lit")))
    # ④ 规范统一：高光强度只有一张表，组件里不准再出现 lit= 字面量
    source = open(mw.__file__, encoding="utf-8").read()
    check("光影强度全部走令牌（组件里没有 lit= 字面量）", re.search(r"lit=\d", source) is None)
    check("tone 材质表已搬到 styles（唯一令牌来源）", not hasattr(mw, "_TONES"))
    # ⑤ 渐变光影：顶栏受光带要压得住正下方；整窗一档亮在顶、一档深在底。
    # 离屏环境会按降级路径铺一层纯色薄膜（那是给人看的兜底），会盖住光本身 ——
    # 这里临时把薄膜关掉，才量得到「光」的分布。
    saved_mode = window._material._mode
    window._material._mode = ui_glass.MODE_ACRYLIC
    window.show()
    app.processEvents()
    QTest.qWait(120)
    shot = window.grab().toImage()
    window._material._mode = saved_mode
    canvas = QImage(shot.size(), QImage.Format.Format_RGB32)
    canvas.fill(QColor("#808080"))          # 窗口是半透明的：先压到固定中灰再比亮度
    cp = QPainter(canvas)
    cp.drawImage(0, 0, shot)
    cp.end()

    def band_lum(y: int) -> float:
        # 只量顶栏右半段：既躲开左上角镜面热点（它在侧栏上方），也躲开右上角的图标按钮
        left, right = max(mw.SIDEBAR_W + 8, canvas.width() // 2), canvas.width() - 60
        row = [canvas.pixelColor(x, y).lightness() for x in range(left, right, 6)]
        return sum(row) / max(1, len(row))

    top = band_lum(6)                       # 受光带顶部
    below = band_lum(mw.TOPBAR_H - 6)       # 受光带底部（仍在顶栏内，只差渐变）
    foot = band_lum(canvas.height() - 6)
    check("顶栏受光带：上亮下暗（渐变光影）", top > below, f"{top:.1f} vs {below:.1f}")
    check("渐变光影：顶亮底深（一档亮、一档深）", top > foot, f"{top:.1f} vs {foot:.1f}")

    # ⑥ 凹槽环玻璃：环亮、顶暗底亮 —— 「凹」是光说出来的，不是描边描出来的
    well = _well_probe()
    top_edge, bottom_edge = _peak_alpha(well, QRect(24, 0, 12, 2)), _peak_alpha(well, QRect(24, 58, 12, 2))
    check("凹槽环：下缘比上缘亮（参考图里下缘是反光）", bottom_edge > top_edge,
          f"{bottom_edge} vs {top_edge}")
    check("凹槽底：上深下浅（凹进去）",
          well.pixelColor(30, 8).lightness() < well.pixelColor(30, 52).lightness(),
          f"{well.pixelColor(30, 8).lightness()} vs {well.pixelColor(30, 52).lightness()}")
    blue_tinted = _well_probe(tint=QColor(styles.ACCENT)).pixelColor(30, 30).blue()
    blue_plain = _well_probe(tint=None).pixelColor(30, 30).blue()
    check("凹槽底可着色（发送键的强调色从这里上）", blue_tinted > blue_plain + 60,
          f"{blue_tinted} vs {blue_plain}")
    check("槽底档位可调（fill 越大越实）",
          _well_probe(fill=styles.CONTROL_GLASS_PRESSED).pixelColor(30, 30).alpha()
          < _well_probe(fill=styles.SEND_WELL).pixelColor(30, 30).alpha())
    # ⑦ 移动：拖动期间不降级材质 —— 亚克力一路都在，桌面才会在玻璃底下跟着走。
    #    原来一拖就切成不透明薄膜，「背景跟着动」这件事在属性上直接就没了。
    saved_mode = window._material._mode
    window._material._mode = ui_glass.MODE_ACRYLIC
    origin = window.pos()
    window._begin_move(QPoint(300, 200))
    check("拖动期间不降级材质（亚克力一路都在）",
          window._material._suspended is False, str(window._material._suspended))
    window._apply_move(QPoint(430, 200))
    check("拖动跟手（位移 = 鼠标位移）", window.pos() == origin + QPoint(130, 0),
          f"{origin} -> {window.pos()}")
    window._end_move()
    check("松手结束拖动会话", window._move_session is None)
    window._material._mode = saved_mode
    window._material._suspended = False

    print("\n[17] 让玻璃「活着」：指针光 / 焦散 / 环境光 / 各向异性")
    # ① 指针光：一块玻璃的光影由**光位**决定，光一挪整套光影都得跟着挪。
    #    只开镜面热点（关掉光泽 / 边缘光 / 色差 / 焦散），才量得到热点本身。
    only_spec = {"gloss": False, "rim": False, "aberration": False, "caustic": False}
    corner_tl, corner_br = QRect(0, 0, 28, 14), QRect(44, 22, 36, 18)
    # 光位全部显式给：这几条量的是**光位 → 光影**的对应关系，不该受全局指针光影响。
    rest_spec = _glass_probe(light=QPointF(*styles.GLASS_LIGHT_REST), **only_spec)
    far_spec = _glass_probe(light=QPointF(0.9, 0.9), **only_spec)
    check("光位可跟（同一块玻璃，光源换了位置就是另一套光）",
          _pixel_diff(rest_spec, far_spec) > 0)
    check("镜面热点朝着光源（静息在左上，指针到右下就跟过去）",
          _peak_alpha(rest_spec, corner_tl) > _peak_alpha(rest_spec, corner_br)
          and _peak_alpha(far_spec, corner_br) > _peak_alpha(far_spec, corner_tl),
          f"{_peak_alpha(rest_spec, corner_tl)}/{_peak_alpha(rest_spec, corner_br)} -> "
          f"{_peak_alpha(far_spec, corner_tl)}/{_peak_alpha(far_spec, corner_br)}")
    #    受光边跟着转：光从下面来，下缘就该比上缘亮（整圈亮边的方向是活的）
    only_rim = {"gloss": False, "specular": False, "aberration": False, "caustic": False}
    top_band, bottom_band = QRect(30, 0, 20, 2), QRect(30, 38, 20, 2)
    rest_rim = _glass_probe(light=QPointF(*styles.GLASS_LIGHT_REST), **only_rim)
    down_rim = _glass_probe(light=QPointF(0.0, 1.0), **only_rim)
    check("受光边跟着光源转（光从下面来 ⇒ 下缘反而更亮）",
          _peak_alpha(rest_rim, top_band) > _peak_alpha(rest_rim, bottom_band)
          and _peak_alpha(down_rim, bottom_band) > _peak_alpha(down_rim, top_band),
          f"{_peak_alpha(down_rim, top_band)} vs {_peak_alpha(down_rim, bottom_band)}")
    # ② 边缘焦散：光穿过玻璃，在**背光侧**聚成一道亮弧（关掉就没有）
    only_caustic = {"gloss": False, "specular": False, "aberration": False, "rim": False}
    arc = _glass_probe(light=QPointF(0.0, -1.0), caustic=True, **only_caustic)
    check("焦散确实画了（这是「光穿过玻璃」的那道弧）",
          _pixel_diff(arc, _glass_probe(light=QPointF(0.0, -1.0), caustic=False, **only_caustic)) > 0)
    check("焦散聚在背光侧（光从上面来 ⇒ 亮弧在下缘）",
          _peak_alpha(arc, QRect(30, 35, 20, 5)) > _peak_alpha(arc, QRect(30, 0, 20, 5)),
          f"{_peak_alpha(arc, QRect(30, 0, 20, 5))} vs {_peak_alpha(arc, QRect(30, 35, 20, 5))}")
    # ③ 指针光不是瞬移：刚挪过去还留在原处，随后一档一档追上（那点延迟就是黏度）
    field = ui_liquid.pointer_light()
    field._current = QPointF(*styles.GLASS_LIGHT_REST)
    field._target = QPointF(*styles.GLASS_LIGHT_REST)
    field.aim_at(window, QPointF(window.mapToGlobal(QPoint(window.width() - 2, window.height() - 2))))
    check("指针光不瞬移（刚挪过去还留在静息光位）",
          abs(field.direction.x() - styles.GLASS_LIGHT_REST[0]) < 0.05,
          f"{field.direction.x():.3f}")
    QTest.qWait(700)
    check("指针光最终跟上（热点落到指针那一侧）",
          field.direction.x() > 0.5 and field.direction.y() > 0.5, str(field.direction))
    # ④ 内容环境光：只借色调（保色相 / 降饱和 / 夹明度），不能变成彩色塑料
    def borrow(fill: str) -> QColor:
        pixmap = QPixmap(8, 8)
        pixmap.fill(QColor(fill))
        return mw._average_color(pixmap)

    source = QColor("#2E86AB")
    got = borrow("#2E86AB")
    check("借色：保色相、降饱和（降不下去玻璃就成了彩色塑料）",
          abs(got.getHsvF()[0] - source.getHsvF()[0]) < 0.02
          and got.getHsvF()[1] <= source.getHsvF()[1] * styles.AMBIENT_MIX + 0.02,
          f"{got.getHsvF()}")
    check("借色：明度夹在 FLOOR..CEIL（雪景洗不白、夜景压不暗）",
          borrow("#FFFFFF").valueF() <= styles.AMBIENT_VALUE_CEIL + 1e-3
          and borrow("#000000").valueF() >= styles.AMBIENT_VALUE_FLOOR - 1e-3,
          f"{borrow('#FFFFFF').valueF():.2f} / {borrow('#000000').valueF():.2f}")
    # 环境光压在薄面**之下**，所以最坏情况也只是把底色轻微挪一点（染色不许拿可读性去换）：
    # 按最暗的那种借色重算，对比度掉幅必须很小（近透档已经只有 2.7:1，再掉就真读不清了）。
    darkest_borrow = QColor.fromHsvF(0.0, styles.AMBIENT_MIX, styles.AMBIENT_VALUE_FLOOR)
    with_ambient = _flatten(
        "#%02X%02X%02X" % (darkest_borrow.red(), darkest_borrow.green(), darkest_borrow.blue()),
        styles.AMBIENT_ALPHA,
        floor_bg,
    )
    ambient_worst = _flatten(
        styles.RECESS_WASH,
        styles.BOTTOM_SHADE / 255.0,
        _flatten(styles.CARD, styles.SIDEBAR_FACE, with_ambient),
    )
    ratio = _contrast(styles.TEXT_SECONDARY, ambient_worst)
    plain = _contrast(styles.TEXT_SECONDARY,
                      _flatten(styles.RECESS_WASH, styles.BOTTOM_SHADE / 255.0,
                               _flatten(styles.CARD, styles.SIDEBAR_FACE, floor_bg)))
    check(f"叠上最暗的借色后对比度几乎不掉（{ratio:.2f} vs 不染色 {plain:.2f}，掉幅 < 5%）",
          ratio >= plain * 0.95, ambient_worst)
    item = {"file_path": paths[0], "file_name": "borrow.png"}
    window._settle_ambient(item)
    QTest.qWait(styles.AMBIENT_SETTLE_MS + 200)
    check("新图进来 ⇒ 玻璃真的被染上（环境光淡入到满）",
          window._ambient_color is not None and window._ambient_level > 0.99,
          f"{window._ambient_level:.2f}")
    window._received_items.clear()   # 内容清空（不是只剩一份列表，是真的没有了）
    window._render_thumbs()
    QTest.qWait(styles.AMBIENT_SETTLE_MS + 200)
    check("内容清空 ⇒ 染色退干净（不留一块没来由的色）",
          window._ambient_color is None and window._ambient_level < 0.01,
          f"{window._ambient_level:.2f}")
    # ⑤ 按下：纵向压、横向鼓 —— 各向异性才是「一滴液体」，等比缩放只是图标在缩
    squash = mw.PressSpring(window)
    squash.press()
    QTest.qWait(260)
    check("按下：纵向压 + 横向鼓（各向异性）",
          styles.GLASS_SQUASH > 0 and squash.sy < 1.0 and squash.sx > 1.0,
          f"{squash.sx:.4f} x {squash.sy:.4f}")
    squash.release()
    QTest.qWait(260)
    check("松手回到各向同性（1 : 1）",
          abs(squash.sx - 1.0) < 1e-6 and abs(squash.sy - 1.0) < 1e-6,
          f"{squash.sx:.4f} x {squash.sy:.4f}")
    # ⑥ 材质：首选**纯模糊**。亚克力（ACCENT_ENABLE_ACRYLICBLURBEHIND）在 Windows 11 上
    #    会额外叠一层系统乳白，不跟着我们的令牌走 —— 桌面再透也上不来，就是「廉价」的来源。
    material = ui_glass.GlassMaterial()
    wanted: list = []
    material._apply_accent = lambda state, tint: (wanted.append(state), True)[1]
    material._dwmapi = None
    material.attach(1, styles.GLASS_TINT_ABGR)
    check("材质首选纯模糊（系统不掺色，着色 / 加厚 / 高光全由我们自己画）",
          wanted == [ui_glass.ACCENT_ENABLE_BLURBEHIND], str(wanted))
    # ⑦ 大面板不铺面：整窗任何一层都不许有光泽带 / 镜面热点 —— 一块几万像素的板，
    #    柔光铺开就是一片奶白，那正是「糊」。**指针光只归窗口外壳**：图片口里一层玻璃
    #    也不画（既没有光泽 / 镜面热点，也没有跟着光位转的那圈受光薄光）。
    faces: list = []
    glows: list = []
    real_paint, real_glow = mw.paint_glass, mw.paint_edge_glow
    mw.paint_glass = lambda p, r, rad, **kw: faces.append(kw)
    mw.paint_edge_glow = lambda p, r, rad, **kw: glows.append(kw)
    window.paintEvent(None)
    shell_faces, shell_glows = len(faces), len(glows)
    window._image_port._empty_state.setVisible(True)
    window._image_port.paintEvent(None)
    port_faces, port_glows = len(faces) - shell_faces, len(glows) - shell_glows
    mw.paint_glass, mw.paint_edge_glow = real_paint, real_glow
    check("整窗不铺光泽 / 镜面热点（大面板只沿边给光）",
          shell_faces > 0
          and all(kw.get("gloss") is False and kw.get("specular") is False for kw in faces[:shell_faces]),
          str(faces[:shell_faces]))
    check("指针光只在窗口外壳上：图片口里一层玻璃也不画", port_faces == 0 and port_glows == 0,
          f"{port_faces} / {port_glows}")
    check("受光边那圈薄光真的画在窗口上（跟着全局光位）",
          shell_glows == 1 and glows[0].get("light") is None, str(glows))
    # 薄光的**锚点必须在边上**。斜光位下把锚点取在窗口里面（旧写法 center + (dx·w/2,
    # dy·h/2) 恰恰就是里面那个点）会让 QLinearGradient 的 PadSpread 把「锚点以外」整片补成
    # 第一档颜色：玻璃上凭空出现一大片**平铺的光**，还带着一条笔直的边 —— 这就是用户说的
    # 「光好廉价」。实测旧写法在对角（背光侧）也有 26/255 的光，新写法是 0。
    # 所以守两条：亮只压在光源那侧（对角必须是 0）+ 往里很快淡。
    glow_rest = _glow_probe(QPointF(*styles.GLASS_LIGHT_REST))
    edge_peak = _peak_alpha(glow_rest, QRect(3, 1, 20, 3))
    inner_peak = _peak_alpha(glow_rest, QRect(28, 14, 24, 8))
    far_peak = _peak_alpha(glow_rest, QRect(58, 30, 18, 8))
    check("受光薄光只压在光源那侧：背光的对角一个像素都不亮（锚点在边上，不在窗口里面）",
          far_peak == 0, str(far_peak))
    check("薄光贴着光源那条边、往里很快淡（内部 ≤ 边上的 1/3）",
          edge_peak > 0 and inner_peak * 3 <= edge_peak, f"{edge_peak} vs {inner_peak}")
    jumps = []
    for row in (8, 20, 32):
        line = [glow_rest.pixelColor(x, row).alpha() for x in range(3, 77)]
        jumps.extend(abs(b - a) for a, b in zip(line, line[1:]))
    check(f"薄光过渡是连续的（扫描线上相邻落差最大 {max(jumps)}/255 ≤ 12）", max(jumps) <= 12,
          str(max(jumps)))
    # 图片口现在是**裸透**：它自己不画任何东西 —— 没有托盘洗、没有光池、没有描边。空态那
    # 两行亮字是**子控件**画的，且不带底 / 框 / 滤镜。于是「该有的像素」只剩中间一小块，
    # 四角 / 四边必须是 0：铺满整块的洗、或一大片光池（在 13% 的玻璃上就是中间一团发灰的
    # 光晕，上一轮用户点名的那个），都会在这两条上露馅。
    port_shot = QImage(window._image_port.size(), QImage.Format.Format_ARGB32_Premultiplied)
    port_shot.fill(QColor(0, 0, 0, 0))
    window._image_port.render(port_shot)
    port_w, port_h = port_shot.width(), port_shot.height()
    lit_box: list | None = None
    lit_px = 0
    for py in range(0, port_h, 2):
        for px in range(0, port_w, 2):
            if port_shot.pixelColor(px, py).alpha() > 6:
                lit_px += 1
                if lit_box is None:
                    lit_box = [px, py, px, py]
                else:
                    lit_box = [min(lit_box[0], px), min(lit_box[1], py),
                               max(lit_box[2], px), max(lit_box[3], py)]
    rim_alpha = max(
        port_shot.pixelColor(5, 5).alpha(),
        port_shot.pixelColor(port_w - 6, port_h - 6).alpha(),
        port_shot.pixelColor(port_w // 2, 4).alpha(),
        port_shot.pixelColor(4, port_h // 2).alpha(),
    )
    check("图片口裸透：四角 / 四边一个像素都不画（没有托盘洗 / 光池 / 描边）",
          rim_alpha == 0, str(rim_alpha))
    check("图片口里只有中间那一小块有像素（空态图标 + 两行字）",
          lit_box is not None and lit_px * 4 <= port_w * port_h * 0.30
          and lit_box[0] > port_w * 0.12 and lit_box[2] < port_w * 0.88,
          f"{lit_box} / {lit_px * 4}px")
    check("空态两行字不带任何底 / 框 / 滤镜（没有 QGraphicsEffect 托底）",
          window._image_port._empty_state.graphicsEffect() is None,
          str(window._image_port._empty_state.graphicsEffect()))
    check("弹层里的移动也算本窗口的（Qt.Popup 是顶层窗口，isAncestorOf 认不出来）",
          window._owns(window._menu) and window._owns(window._send_btn) and not window._owns(app))

    check("自测没有写用户真实配置", _snapshot(QSettings(*real_scope)) == real_before)
    QSettings(mw.SETTINGS_ORG, mw.SETTINGS_APP).clear()

    print(f"\n{'=' * 60}\n共 {CHECKS} 项，失败 {len(FAILURES)} 项")
    for failure in FAILURES:
        print("  FAIL  " + failure)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
