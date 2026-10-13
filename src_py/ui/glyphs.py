"""自绘单色矢量图标。

毛玻璃上不用 emoji：彩色 emoji 在高亮材质上会显脏，且各系统渲染不一致、
基线也对不齐。这里统一用 QPainter 画，颜色与线宽由调用方给定。
所有图形都在传入的 rect 内按比例绘制，因此同一套图标可用于 14px 与 44px。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen


def _width(rect: QRectF, ratio: float) -> float:
    return max(1.2, rect.height() * ratio)


def _stroke_pen(rect: QRectF, color, ratio: float) -> QPen:
    pen = QPen(color, _width(rect, ratio))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def airdrop(painter: QPainter, rect: QRectF, color) -> None:
    """隔空投送：中心点 + 一圈环 + 两道向上张开的弧（雷达状）。"""
    cx = rect.center().x()
    cy = rect.center().y() + rect.height() * 0.06
    unit = rect.height() * 0.082

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QPointF(cx, cy), unit * 0.92, unit * 0.92)

    painter.setPen(_stroke_pen(rect, color, 0.072))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for factor, span in ((2.05, None), (3.5, 104.0), (4.85, 104.0)):
        radius = unit * factor
        box = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        if span is None:
            painter.drawEllipse(box)
        else:
            painter.drawArc(box, int((90.0 - span / 2.0) * 16), int(span * 16))


def chevron_updown(painter: QPainter, rect: QRectF, color) -> None:
    """chevron.up.chevron.down：暗示「可展开选择」。"""
    painter.setPen(_stroke_pen(rect, color, 0.155))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx = rect.center().x()
    span = rect.width() * 0.34
    gap = rect.height() * 0.10
    top = rect.top() + rect.height() * 0.28
    bottom = rect.bottom() - rect.height() * 0.28

    up = QPainterPath()
    up.moveTo(cx - span, top + gap)
    up.lineTo(cx, top)
    up.lineTo(cx + span, top + gap)
    painter.drawPath(up)

    down = QPainterPath()
    down.moveTo(cx - span, bottom - gap)
    down.lineTo(cx, bottom)
    down.lineTo(cx + span, bottom - gap)
    painter.drawPath(down)


def folder(painter: QPainter, rect: QRectF, color) -> None:
    """接收目录：文件夹轮廓（左侧标签页 + 主体），描边而不是实心块。"""
    painter.setPen(_stroke_pen(rect, color, 0.068))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    left = rect.left() + rect.width() * 0.12
    right = rect.right() - rect.width() * 0.12
    top = rect.top() + rect.height() * 0.28
    bottom = rect.bottom() - rect.height() * 0.22
    step = (bottom - top) * 0.22
    tab = left + (right - left) * 0.40
    path = QPainterPath()
    path.moveTo(left, bottom)
    path.lineTo(left, top)
    path.lineTo(tab, top)
    path.lineTo(tab, top + step)
    path.lineTo(right, top + step)
    path.lineTo(right, bottom)
    path.closeSubpath()
    painter.drawPath(path)


def close(painter: QPainter, rect: QRectF, color) -> None:
    """关闭：两条斜线。"""
    painter.setPen(_stroke_pen(rect, color, 0.092))
    inset = rect.width() * 0.30
    inner = rect.adjusted(inset, inset, -inset, -inset)
    painter.drawLine(inner.topLeft(), inner.bottomRight())
    painter.drawLine(inner.topRight(), inner.bottomLeft())


def phone(painter: QPainter, rect: QRectF, color) -> None:
    """手机：竖屏机身 + Home 指示条。"""
    body = QRectF(
        rect.left() + rect.width() * 0.31,
        rect.top() + rect.height() * 0.08,
        rect.width() * 0.38,
        rect.height() * 0.84,
    )
    painter.setPen(_stroke_pen(rect, color, 0.098))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(body, body.width() * 0.30, body.width() * 0.30)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    bar = body.width() * 0.36
    painter.drawRoundedRect(
        QRectF(body.center().x() - bar / 2, body.bottom() - body.height() * 0.16, bar, max(1.2, rect.height() * 0.05)),
        1.0,
        1.0,
    )


def laptop(painter: QPainter, rect: QRectF, color) -> None:
    """电脑：屏幕 + 底座。"""
    screen = QRectF(
        rect.left() + rect.width() * 0.21,
        rect.top() + rect.height() * 0.17,
        rect.width() * 0.58,
        rect.height() * 0.44,
    )
    painter.setPen(_stroke_pen(rect, color, 0.098))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(screen, screen.height() * 0.16, screen.height() * 0.16)
    base = QRectF(
        rect.left() + rect.width() * 0.11,
        screen.bottom() + rect.height() * 0.11,
        rect.width() * 0.78,
        rect.height() * 0.11,
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(base, base.height() * 0.45, base.height() * 0.45)


def globe(painter: QPainter, rect: QRectF, color) -> None:
    """浏览器：球体 + 经线 + 赤道。"""
    radius = min(rect.width(), rect.height()) * 0.39
    center = rect.center()
    painter.setPen(_stroke_pen(rect, color, 0.098))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(center, radius, radius)
    painter.drawEllipse(center, radius * 0.45, radius)
    painter.drawLine(QPointF(center.x() - radius, center.y()), QPointF(center.x() + radius, center.y()))


def chip(painter: QPainter, rect: QRectF, color) -> None:
    """无屏设备 / 机器人：芯片轮廓（外壳 + 内核）。"""
    side = min(rect.width(), rect.height()) * 0.62
    outer = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
    painter.setPen(_stroke_pen(rect, color, 0.098))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(outer, side * 0.24, side * 0.24)
    inner = side * 0.34
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(
        QRectF(rect.center().x() - inner / 2, rect.center().y() - inner / 2, inner, inner), inner * 0.24, inner * 0.24
    )


def server(painter: QPainter, rect: QRectF, color) -> None:
    """服务器：两层机架 + 指示灯。"""
    width = rect.width() * 0.66
    height = rect.height() * 0.26
    left = rect.center().x() - width / 2
    painter.setPen(_stroke_pen(rect, color, 0.098))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for index in range(2):
        top = rect.top() + rect.height() * 0.18 + index * rect.height() * 0.38
        painter.drawRoundedRect(QRectF(left, top, width, height), height * 0.34, height * 0.34)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        dot = height * 0.26
        painter.drawEllipse(QPointF(left + height * 0.5, top + height / 2), dot, dot)
        painter.setPen(_stroke_pen(rect, color, 0.098))
        painter.setBrush(Qt.BrushStyle.NoBrush)


def antenna(painter: QPainter, rect: QRectF, color) -> None:
    """未知设备：天线（信号塔）。"""
    center = rect.center()
    painter.setPen(_stroke_pen(rect, color, 0.098))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(center.x(), rect.top() + rect.height() * 0.52), QPointF(center.x(), rect.bottom() - rect.height() * 0.20))
    painter.drawLine(
        QPointF(center.x() - rect.width() * 0.18, rect.bottom() - rect.height() * 0.20),
        QPointF(center.x() + rect.width() * 0.18, rect.bottom() - rect.height() * 0.20),
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QPointF(center.x(), rect.top() + rect.height() * 0.44), rect.height() * 0.075, rect.height() * 0.075)
    painter.setPen(_stroke_pen(rect, color, 0.098))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for factor, span in ((1.0, 96.0), (1.7, 96.0)):
        radius = rect.height() * 0.18 * factor
        box = QRectF(center.x() - radius, center.y() - rect.height() * 0.06 - radius, radius * 2, radius * 2)
        painter.drawArc(box, int((90.0 - span / 2.0) * 16), int(span * 16))


def check(painter: QPainter, rect: QRectF, color) -> None:
    """勾选：菜单里标出当前生效的项。"""
    painter.setPen(_stroke_pen(rect, color, 0.16))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(rect.left() + rect.width() * 0.08, rect.top() + rect.height() * 0.55)
    path.lineTo(rect.left() + rect.width() * 0.36, rect.top() + rect.height() * 0.82)
    path.lineTo(rect.left() + rect.width() * 0.92, rect.top() + rect.height() * 0.18)
    painter.drawPath(path)


def image(painter: QPainter, rect: QRectF, color) -> None:
    """空态：图片轮廓（相框 + 太阳 + 远山）。"""
    frame = QRectF(
        rect.left() + rect.width() * 0.10,
        rect.top() + rect.height() * 0.14,
        rect.width() * 0.80,
        rect.height() * 0.72,
    )
    painter.setPen(_stroke_pen(rect, color, 0.055))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(frame, frame.height() * 0.14, frame.height() * 0.14)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    sun_r = frame.height() * 0.085
    painter.drawEllipse(
        QPointF(frame.left() + frame.width() * 0.29, frame.top() + frame.height() * 0.30), sun_r, sun_r
    )

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(_stroke_pen(rect, color, 0.055))
    hills = QPainterPath()
    hills.moveTo(frame.left() + frame.width() * 0.08, frame.bottom() - frame.height() * 0.10)
    hills.lineTo(frame.left() + frame.width() * 0.38, frame.top() + frame.height() * 0.52)
    hills.lineTo(frame.left() + frame.width() * 0.60, frame.bottom() - frame.height() * 0.10)
    hills.lineTo(frame.left() + frame.width() * 0.72, frame.top() + frame.height() * 0.70)
    hills.lineTo(frame.right() - frame.width() * 0.06, frame.bottom() - frame.height() * 0.10)
    painter.drawPath(hills)


_GLYPHS = {
    "airdrop": airdrop,
    "phone": phone,
    "laptop": laptop,
    "globe": globe,
    "chip": chip,
    "server": server,
    "antenna": antenna,
    "chevron": chevron_updown,
    "folder": folder,
    "close": close,
    "image": image,
    "check": check,
}


def paint_glyph(painter: QPainter, name: str, rect, color) -> bool:
    """在 rect 内画 name 对应的单色图形；未知名字返回 False（调用方可回退文字）。"""
    fn = _GLYPHS.get(name)
    if fn is None:
        return False
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    fn(painter, QRectF(rect), color)
    painter.restore()
    return True