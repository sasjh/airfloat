"""Apple 液态玻璃（Liquid Glass）的 Qt 落地。

参考实现：``rdev/liquid-glass-react``（MIT）——它用 SVG 位移图 + 色差，对**窗口背后**
的内容做折射。浏览器有 backdrop-filter / SVG filter，能直接采样背后的像素；Qt 桌面端
拿不到：窗口背后的桌面由 DWM 在**窗口之外**合成（亚克力模糊就是 DWM 画的），Qt 读不到
那层像素。所以像素级位移折射无法保真移植。

能保真移植的是**光影结构**——液态玻璃之所以「像玻璃」，靠的正是这几样：
- 镜面边缘光（rim light）：受光边（左上）亮、背光边（右下）暗 = 玻璃的厚度；
- 顶部光泽（gloss）：低透明度、自上而下渐隐 = 表面反光；
- 镜面热点（specular）：左上角一撮更亮的椭圆 = 光源在左上；
- 边缘色差（chromatic aberration）：冷 / 暖描边各偏 1px（对应 aberrationIntensity）；
- 内阴影（inner shadow）：按下时压进去，玻璃凹下去。

落影这里不画：控件布局都是紧贴的（卡片、缩略图没有留白），画了会被自己的矩形裁掉；
弹出菜单本来就带 Qt 的 ``QGraphicsDropShadowEffect``，够用。

折射用「边缘亮度梯度」近似：边缘越亮，越像被掰弯的高光。
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QVariantAnimation, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QWidget

from .styles import (
    GLASS_ABERRATION,
    GLASS_GLOSS,
    GLASS_INNER_SHADOW,
    GLASS_RIM_BOTTOM,
    GLASS_RIM_TOP,
    GLASS_SPECULAR,
    animations_enabled,
)

# 落影 / 色差的冷暖，一条定死，避免各处随手写 rgb
SHADOW_INK = (12, 14, 18)
ABERRATION_COOL = (150, 195, 255)
ABERRATION_WARM = (255, 190, 150)


def glass_path(rect: QRectF, radius: float) -> QPainterPath:
    """圆角玻璃轮廓。"""
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def scaled_rect(rect: QRectF, scale: float) -> QRectF:
    """以中心为原点缩放矩形（按下回弹用）。"""
    if scale == 1.0:
        return rect
    dx = rect.width() * (1.0 - scale) / 2.0
    dy = rect.height() * (1.0 - scale) / 2.0
    return rect.adjusted(dx, dy, -dx, -dy)


def paint_glass(
    painter: QPainter,
    rect: QRectF,
    radius: float,
    *,
    tint: QColor | None = None,
    alpha: float = 0.0,
    lit: float = 1.0,
    pressed: bool = False,
    gloss: bool = True,
    specular: bool = True,
    aberration: bool = True,
    rim: bool = True,
) -> None:
    """把一块液态玻璃画进 ``rect``。

    ``tint`` / ``alpha`` 是玻璃的底色（``None`` = 全透明，只留光影）；``lit`` 缩放所有
    高光强度（悬停调高、按下调低）；``pressed`` 追加内阴影，玻璃看上去被压进去。
    图层顺序：底色 → 光泽 → 镜面热点 → 内阴影 → 边缘色差 → 镜面边缘光。
    """
    lit = max(0.0, lit)
    path = glass_path(rect, radius)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 1) 底色：上亮下暗，材质本身也有受光
    if tint is not None and alpha > 0:
        top = QColor(tint)
        top.setAlphaF(min(1.0, alpha * 1.12))
        bottom = QColor(tint)
        bottom.setAlphaF(max(0.0, alpha * 0.84))
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0.0, top)
        fill.setColorAt(1.0, bottom)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPath(path)

    painter.setClipPath(path)

    # 2) 顶部光泽
    if gloss and GLASS_GLOSS > 0:
        band = QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.55)
        sheen = QLinearGradient(band.topLeft(), band.bottomLeft())
        sheen.setColorAt(0.0, QColor(255, 255, 255, round(255 * GLASS_GLOSS * lit)))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sheen)
        painter.drawRect(band)

    # 3) 镜面热点：光源在左上
    if specular and GLASS_SPECULAR > 0:
        center = QPointF(
            rect.left() + rect.width() * 0.24, rect.top() + rect.height() * 0.06
        )
        spread = max(rect.width(), rect.height()) * 0.55
        hot = QRadialGradient(center, spread)
        hot.setColorAt(0.0, QColor(255, 255, 255, round(255 * GLASS_SPECULAR * lit)))
        hot.setColorAt(0.55, QColor(255, 255, 255, round(255 * GLASS_SPECULAR * 0.28 * lit)))
        hot.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(hot)
        painter.drawRect(rect)

    # 4) 内阴影：按下时玻璃压进去（受光面的顶边先暗）
    if pressed and GLASS_INNER_SHADOW > 0:
        band = QRectF(rect.left(), rect.top(), rect.width(), rect.height() * 0.5)
        dent = QLinearGradient(band.topLeft(), band.bottomLeft())
        dent.setColorAt(0.0, QColor(*SHADOW_INK, round(255 * GLASS_INNER_SHADOW)))
        dent.setColorAt(1.0, QColor(*SHADOW_INK, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dent)
        painter.drawRect(band)

    painter.setClipping(False)

    # 5) 边缘色差：冷上暖下各偏一点，玻璃边缘才有「厚度」的彩边
    if aberration and GLASS_ABERRATION > 0:
        for dy, rgb in ((-0.6, ABERRATION_COOL), (0.6, ABERRATION_WARM)):
            color = QColor(*rgb)
            color.setAlpha(round(255 * GLASS_ABERRATION * lit))
            pen = QPen(color)
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(
                glass_path(rect.adjusted(1.0, 1.0 + dy, -1.0, -1.0 + dy), radius - 1.0)
            )

    # 6) 镜面边缘光：对角渐变 —— 左上受光、右下背光
    if rim:
        edge = QLinearGradient(rect.topLeft(), rect.bottomRight())
        edge.setColorAt(0.0, QColor(255, 255, 255, round(255 * GLASS_RIM_TOP * lit)))
        edge.setColorAt(0.45, QColor(255, 255, 255, round(255 * GLASS_RIM_TOP * 0.35 * lit)))
        edge.setColorAt(1.0, QColor(255, 255, 255, round(255 * GLASS_RIM_BOTTOM * lit)))
        pen = QPen()
        pen.setBrush(edge)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    painter.restore()


class GlassSurface(QFrame):
    """一块液态玻璃底板（侧栏 / 图片口这类结构分区）。

    结构分区是**铺满**的：不套边缘光、也不套色差（全出血的矩形上画描边会变成硬分割线，
    而设计约定「区域之间不画硬线」），只保留底色与顶部光泽 —— 材质本身有厚度就够了。
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        tint: QColor | None = None,
        alpha: float = 0.0,
        radius: float = 0.0,
        lit: float = 1.0,
        gloss: bool = True,
    ) -> None:
        super().__init__(parent)
        self._tint = tint
        self._alpha = alpha
        self._radius = radius
        self._lit = lit
        self._gloss = gloss

    def paintEvent(self, _e) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_glass(
            painter,
            QRectF(0.0, 0.0, float(self.width()), float(self.height())),
            self._radius,
            tint=self._tint,
            alpha=self._alpha,
            lit=self._lit,
            gloss=self._gloss,
            specular=False,
            aberration=False,
            rim=False,
        )
        painter.end()


class PressSpring:
    """按下回弹：按下缩一点，松手用 OutBack 弹回（对应参考实现的 elasticity）。

    尊重系统「减少动态效果」：动画关闭时直接落终态。
    """

    def __init__(self, widget: QWidget, depth: float = 0.035) -> None:
        self._widget = widget
        self._depth = depth
        self._scale = 1.0
        self._animation = QVariantAnimation(widget)
        self._animation.setDuration(200 if animations_enabled() else 0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutBack)
        self._animation.valueChanged.connect(self._on_value)

    @property
    def scale(self) -> float:
        return self._scale

    def press(self) -> None:
        self._run(1.0 - self._depth)

    def release(self) -> None:
        self._run(1.0)

    def _run(self, target: float) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._scale)
        self._animation.setEndValue(target)
        self._animation.start()
        if self._animation.duration() == 0:
            self._on_value(target)

    def _on_value(self, value) -> None:
        self._scale = float(value)
        self._widget.update()
