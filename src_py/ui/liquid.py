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

在这套光影结构之上，还有四件让玻璃「活着」的事（都收在 styles 令牌里）：
- **指针光**：整块界面只有**一个光源**（``LightField``）。指针在哪，光就从哪来 ——
  镜面热点朝光源偏移、受光边跟着转。指针每动一下光只跟一小步，所以是「跟过来」的，
  不是瞬移。这一点延迟正是「有生命的液体」和「一张贴纸」的区别。
- **边缘焦散**：光穿过玻璃，在**背光侧**聚成一道细亮弧（真正的玻璃边缘就有这圈）。
  它跟着指针光转，光一挪，亮弧就绕到另一边去。
- **内容环境光**：收到的照片把自己的颜色借给整窗玻璃一点（见 main_window 的 AMBIENT_*）。
- **各向异性压扁**：按下时纵向压、横向鼓 —— 像一滴液体被指尖按下去（``PressSpring``）。
"""

from __future__ import annotations

import math

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QObject,
    QPointF,
    QRectF,
    QTimer,
    QVariantAnimation,
    Qt,
    Signal,
)
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
    GLASS_CAUSTIC,
    GLASS_CAUSTIC_INSET,
    GLASS_EDGE_GLOW,
    GLASS_EDGE_HOTSPOT,
    GLASS_EDGE_HOTSPOT_R,
    GLASS_EDGE_GLOW_WIDTH,
    GLASS_GLOSS,
    GLASS_INNER_SHADOW,
    GLASS_LIGHT_OMEGA,
    GLASS_LIGHT_REST,
    GLASS_LIGHT_SETTLE,
    GLASS_LIGHT_SHIFT,
    GLASS_RIM_BOTTOM,
    GLASS_RIM_TOP,
    GLASS_RIM_WIDTH,
    GLASS_RING,
    GLASS_SQUASH,
    GLASS_SPECULAR,
    GLASS_SPECULAR_R,
    LIGHT_TICK_MS,
    RECESS_WASH,
    RING_BOTTOM_LIGHT,
    RING_EDGE_BOTTOM,
    RING_EDGE_TOP,
    RING_FILL_FLOOR,
    RING_FILL_TOP,
    RING_INSET,
    RING_LIGHT_TOP,
    RING_SHADOW,
    RING_TOP_SHADE,
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


def squashed_rect(rect: QRectF, sx: float, sy: float) -> QRectF:
    """以中心为原点**分轴**缩放矩形（按下时纵向压、横向鼓）。"""
    if sx == 1.0 and sy == 1.0:
        return rect
    dx = rect.width() * (1.0 - sx) / 2.0
    dy = rect.height() * (1.0 - sy) / 2.0
    return rect.adjusted(dx, dy, -dx, -dy)


def _clamp_unit(value: float) -> float:
    return max(-1.0, min(1.0, value))


class LightField(QObject):
    """全局指针光：**一整个界面只有一个光源**。

    光位是归一化方向（-1..1，相对所在窗口的中心）：指针在哪，光就从哪来。
    跟随是一条**临界阻尼弹簧**（位置 + 速度，`GLASS_LIGHT_OMEGA`），不是「每心跳挪固定
    比例」：比例跟随在指针拐弯时**速度会突变**（看到的就是一道折角），而弹簧的速度连续 ——
    起步从 0 加速、末段自然收住，那点延迟就是玻璃里液体的黏度。
    """

    moved = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._current = QPointF(*GLASS_LIGHT_REST)
        self._target = QPointF(*GLASS_LIGHT_REST)
        self._velocity = QPointF(0.0, 0.0)
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.setInterval(LIGHT_TICK_MS)
        self._timer.timeout.connect(self._step)

    @property
    def direction(self) -> QPointF:
        return QPointF(self._current)

    def aim_at(self, host: QWidget, global_pos: QPointF) -> None:
        """把光源挪到指针处（相对 host 窗口中心归一化）。"""
        rect = host.rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        local = host.mapFromGlobal(global_pos.toPoint())
        self._target = QPointF(
            _clamp_unit((local.x() - rect.width() / 2.0) / (rect.width() / 2.0)),
            _clamp_unit((local.y() - rect.height() / 2.0) / (rect.height() / 2.0)),
        )
        if not self._timer.isActive():
            self._clock.restart()
            self._timer.start()

    def _step(self) -> None:
        # 按**真实间隔**推进：掉帧那一步就多走一点，光不会因为卡了一下而走成一段一段
        # （8ms 心跳只是采样密度，不是「必须等 8ms」）。上限 100ms：真卡了宁可多花几帧
        # 追上，也不要一步跳到指针那儿 —— 那一下就是「瞬移」，黏度就没了。
        dt = max(1.0, min(float(self._clock.restart()), 100.0)) / 1000.0
        self._advance(dt)
        delta = self._target - self._current
        if abs(delta.x()) < GLASS_LIGHT_SETTLE and abs(delta.y()) < GLASS_LIGHT_SETTLE:
            self._current = QPointF(self._target)
            self._velocity = QPointF(0.0, 0.0)
            self._timer.stop()
        self.moved.emit()

    def _advance(self, dt: float) -> None:
        """临界阻尼弹簧走一步（**解析解**，不是逐步欧拉）。

        误差 e = 目标 - 当前，速度记在位置这一侧：临界阻尼下
        ``e(t) = (e0 + (ė0 + ω·e0)·t) · e^(-ω·t)``。
        用解析解而不是欧拉：欧拉在 dt 大一点（掉一帧、或系统休眠刚回来）时会**发散**，
        玻璃上的光会突然抖一下甚至飞出去；解析解对任意 dt 都稳。
        """
        omega = GLASS_LIGHT_OMEGA
        error = self._target - self._current          # 位置误差
        rate = -self._velocity                        # 误差的导数
        slope = rate + error * omega
        decay = math.exp(-omega * dt)
        error_new = (error + slope * dt) * decay
        rate_new = (slope - (error + slope * dt) * omega) * decay
        self._current = self._target - error_new
        self._velocity = -rate_new


_LIGHT_FIELD: LightField | None = None


def pointer_light() -> LightField:
    """取全局光场（首次调用时创建）。"""
    global _LIGHT_FIELD
    if _LIGHT_FIELD is None:
        _LIGHT_FIELD = LightField()
    return _LIGHT_FIELD


def follow_light(widget: QWidget) -> None:
    """让一块玻璃跟着全局指针光重绘：光挪一步，它就亮一次。

    PySide6 在接收者（QObject）销毁时会自动断掉连接，所以缩略图上那个删了又建的
    删除键不会攒下连接，也不会被信号吊住不释放（实测见开发日志）。
    """
    pointer_light().moved.connect(widget.update)


def light_direction() -> QPointF:
    """当前光位；光场还没建起来就是静息光位（左上）。"""
    return QPointF(*GLASS_LIGHT_REST) if _LIGHT_FIELD is None else _LIGHT_FIELD.direction


def _light_unit(light: QPointF | None) -> tuple[float, float]:
    """光源方向的单位向量；零向量回退到静息光位。"""
    direction = light_direction() if light is None else light
    dx, dy = float(direction.x()), float(direction.y())
    length = math.hypot(dx, dy)
    if length < 1e-6:
        dx, dy = GLASS_LIGHT_REST
        length = math.hypot(dx, dy)
    return dx / length, dy / length


def _edge_hit(rect: QRectF, dx: float, dy: float) -> tuple[QPointF, QPointF]:
    """光轴打到窗口**边**上的那个点，以及那条边的**向内法线**。

    这里是「光脏」的根源，值得写清楚：以前锚点取的是 ``center + (dx*w/2, dy*h/2)``，
    斜光位下那是窗口**里面**的一个点（比如 (0.72,0.72) 落在右下角内侧 80px 处）。而
    ``QLinearGradient`` 在起点以外是 **PadSpread** —— 整片补成第一档颜色。于是那圈受光
    薄光在玻璃中间切出一条笔直的分界，看着像贴了一张膜（用户说的「光好廉价」）。
    锚点必须真的落在边上，渐变才只往窗口**里**走。
    """
    center = rect.center()
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return center, QPointF(0.0, 0.0)
    sx = (rect.width() / 2.0) / abs(dx) if abs(dx) > 1e-9 else math.inf
    sy = (rect.height() / 2.0) / abs(dy) if abs(dy) > 1e-9 else math.inf
    if sx <= sy:
        return (QPointF(rect.left() if dx < 0 else rect.right(), center.y()),
                QPointF(-1.0 if dx > 0 else 1.0, 0.0))
    return (QPointF(center.x(), rect.top() if dy < 0 else rect.bottom()),
            QPointF(0.0, -1.0 if dy > 0 else 1.0))


def _light_axis(rect: QRectF, light: QPointF | None) -> tuple[QPointF, QPointF]:
    """沿光轴取两个端点：光源侧（亮，**正好在边上**）与背光侧（暗，对称落在里面）。"""
    dx, dy = _light_unit(light)
    light_side, _ = _edge_hit(rect, dx, dy)
    return light_side, rect.center() * 2.0 - light_side


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
    light: QPointF | None = None,
    caustic: bool | None = None,
) -> None:
    """把一块液态玻璃画进 ``rect``。

    ``tint`` / ``alpha`` 是玻璃的底色（``None`` = 全透明，只留光影）；``lit`` 缩放所有
    高光强度（悬停调高、按下调低）；``pressed`` 追加内阴影，玻璃看上去被压进去。
    ``light`` 是光源方向（``None`` = 用全局指针光）：光泽、镜面热点、边缘光与焦散
    全部朝它对齐 —— 所有玻璃因此共用同一个光源。``caustic`` 缺省跟随 ``rim``。
    图层顺序：底色 → 光泽 → 镜面热点 → 内阴影 → 边缘色差 → 焦散 → 镜面边缘光。
    """
    lit = max(0.0, lit)
    if caustic is None:
        caustic = rim
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

    # 2) 表面光泽：顺着光轴，从光源那侧铺开、到中线前就淡没
    if gloss and GLASS_GLOSS > 0:
        light_side, shade_side = _light_axis(rect, light)
        sheen = QLinearGradient(light_side, shade_side)
        sheen.setColorAt(0.0, QColor(255, 255, 255, round(255 * GLASS_GLOSS * lit)))
        sheen.setColorAt(0.55, QColor(255, 255, 255, 0))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sheen)
        painter.drawRect(rect)

    # 3) 镜面热点：跟着光源走（指针在哪，亮点就在哪一侧）
    if specular and GLASS_SPECULAR > 0:
        light_side, _ = _light_axis(rect, light)
        center = light_side + (rect.center() - light_side) * GLASS_LIGHT_SHIFT
        # 半径是**像素**、不跟边长走：小卡片上只有一颗小光点（跟着指针走的那粒「光针」），
        # 按边长铺开的话，一张 176px 的卡片会被这朵光糊掉半个面。
        spread = GLASS_SPECULAR_R
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

    # 6) 边缘焦散：光穿过玻璃，在**背光侧**聚成一道细亮弧
    if caustic and GLASS_CAUSTIC > 0:
        light_side, shade_side = _light_axis(rect, light)
        arc = QLinearGradient(light_side, shade_side)
        arc.setColorAt(0.0, QColor(255, 255, 255, 0))
        arc.setColorAt(0.45, QColor(255, 255, 255, 0))
        arc.setColorAt(1.0, QColor(255, 255, 255, round(255 * GLASS_CAUSTIC * lit)))
        pen = QPen()
        pen.setBrush(arc)
        pen.setWidthF(1.4)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = GLASS_CAUSTIC_INSET
        painter.drawPath(
            glass_path(rect.adjusted(inset, inset, -inset, -inset), max(0.0, radius - inset))
        )

    # 7) 镜面边缘光：沿光轴渐变 —— 光源那侧受光、另一侧背光
    if rim:
        # 7a) 不随光位变的底子：参考实现那圈 `0 0 0 0.5px rgba(255,255,255,.5) inset`。
        #     它保证窗口轮廓在任何光位下都立得住 —— 光位只管「哪一段更亮」。
        if GLASS_RING > 0:
            pen = QPen(QColor(255, 255, 255, round(255 * GLASS_RING * lit)))
            pen.setWidthF(GLASS_RIM_WIDTH)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        # 7b) 受光的那一段：细发丝（0.75px + 抗锯齿 ≈ 眼里的一根亮线）
        light_side, shade_side = _light_axis(rect, light)
        edge = QLinearGradient(light_side, shade_side)
        edge.setColorAt(0.0, QColor(255, 255, 255, round(255 * GLASS_RIM_TOP * lit)))
        edge.setColorAt(0.5, QColor(255, 255, 255, round(255 * GLASS_RIM_TOP * 0.35 * lit)))
        edge.setColorAt(1.0, QColor(255, 255, 255, round(255 * GLASS_RIM_BOTTOM * lit)))
        pen = QPen()
        pen.setBrush(edge)
        pen.setWidthF(GLASS_RIM_WIDTH)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    painter.restore()


def paint_edge_glow(
    painter: QPainter,
    rect: QRectF,
    radius: float,
    *,
    light: QPointF | None = None,
) -> None:
    """受光边那圈内圈薄光：沿光源那侧的一条亮带 + 边正中一小朵沿边的柔光。

    大面板上的取舍：铺**面**就是奶白（一块几万像素的板，任何一层柔光都会糊成一片），
    完全不给光又变成一块死玻璃。所以只给**边** —— 而且宽度是**像素**（不是比例），
    窗口放大时它不会跟着摊开。光跟着指针走，这条亮带就绕着窗口转。

    细节（用户：光别太明显、但要更细）：亮带本身分**三段**淡出（贴边一线最亮 → 快速跌
    下去 → 拖一条长尾），再叠一小朵**沿边**的柔光。后者是关键 —— 只有一条均匀亮带时，
    灯一挪整条边一起变亮，看着像贴纸；有了这朵沿边的光，亮的地方在边上**走**，才是光。
    """
    if GLASS_EDGE_GLOW <= 0 and GLASS_EDGE_HOTSPOT <= 0:
        return
    dx, dy = _light_unit(light)
    light_side, normal = _edge_hit(rect, dx, dy)
    inner = light_side + normal * GLASS_EDGE_GLOW_WIDTH
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setClipPath(glass_path(rect, radius))
    painter.setPen(Qt.PenStyle.NoPen)
    if GLASS_EDGE_GLOW > 0:
        band = QLinearGradient(light_side, inner)
        for stop, level in ((0.0, 1.0), (0.18, 0.42), (0.52, 0.11), (1.0, 0.0)):
            band.setColorAt(stop, QColor(255, 255, 255, round(255 * GLASS_EDGE_GLOW * level)))
        painter.setBrush(band)
        painter.drawRect(rect)
    if GLASS_EDGE_HOTSPOT > 0:
        # 光沿**最近的那条边**走：横向光就落在左 / 右边中，纵向光就落在上 / 下边中 ——
        # 这朵光就压在 `light_side` 上（它已经在边上了），沿边走、往里淡。
        edge_len = rect.height() if normal.x() != 0.0 else rect.width()
        spot = QRadialGradient(light_side, max(edge_len * GLASS_EDGE_HOTSPOT_R, 1.0))
        # 过渡点给密一点（近似指数衰减）：三点式的径向渐变在玻璃上会显出一圈「外沿」，
        # 那不是光，那是渐变的边。
        for stop, level in ((0.0, 1.0), (0.16, 0.70), (0.34, 0.42), (0.54, 0.21),
                            (0.74, 0.08), (0.88, 0.02), (1.0, 0.0)):
            spot.setColorAt(stop, QColor(255, 255, 255, round(255 * GLASS_EDGE_HOTSPOT * level)))
        painter.setBrush(spot)
        painter.drawRect(rect)
    painter.restore()


def paint_well_glass(
    painter: QPainter,
    rect: QRectF,
    radius: float,
    *,
    fill: float,
    lit: float = 1.0,
    tint: QColor | None = None,
) -> None:
    """凹槽环玻璃（参考图里那枚圆钮 / 胶囊）：半透 + 细描边 + 弱阴影。

    和 ``paint_glass`` 的分工很明确：这里**不铺浅色面**，只画「一个凹槽」——
    半透的槽底（上深下浅 = 凹）+ 顶内阴影 + 底内受光 + 一圈发丝亮环 + 环外一条弱落影。
    因为不铺面，背后的亚克力模糊能整片透上来，玻璃才像在呼吸；立体感全靠光。

    ``tint`` 是槽底座色（缺省 = 深色洗）：发送键传强调色，槽就是「强调色凹槽」；
    底色越实、其上字形对比越低，所以 ``fill`` 与 ``tint`` 要跟对比度一起调。
    图层顺序：槽底 → 顶内阴影 → 底内受光 → 弱落影 → 发丝环（最后画，环才完整）。
    """
    lit = max(0.0, lit)
    well_rect = rect.adjusted(RING_INSET, RING_INSET, -RING_INSET, -RING_INSET)
    path = glass_path(well_rect, max(0.0, radius - RING_INSET))
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 1) 槽底：半透的底座色，上深下浅 —— 上深下浅才像「凹进去」
    base = QColor(RECESS_WASH) if tint is None else QColor(tint)
    top = QColor(base)
    top.setAlphaF(min(1.0, fill * RING_FILL_TOP))
    bottom = QColor(base)
    bottom.setAlphaF(max(0.0, fill * RING_FILL_FLOOR))
    well = QLinearGradient(well_rect.topLeft(), well_rect.bottomLeft())
    well.setColorAt(0.0, top)
    well.setColorAt(1.0, bottom)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(well)
    painter.drawPath(path)

    painter.setClipPath(path)

    # 2) 顶内阴影：短带渐隐，把「凹」再压一层
    if RING_TOP_SHADE > 0:
        band = QRectF(well_rect.left(), well_rect.top(), well_rect.width(), well_rect.height() * 0.55)
        shade = QLinearGradient(band.topLeft(), band.bottomLeft())
        shade.setColorAt(0.0, QColor(*SHADOW_INK, round(255 * RING_TOP_SHADE * lit)))
        shade.setColorAt(1.0, QColor(*SHADOW_INK, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        painter.drawRect(band)

    # 3) 底内受光：贴底那圈收到的反光（凹面才不是一块平贴纸）
    if RING_BOTTOM_LIGHT > 0:
        band = QRectF(
            well_rect.left(),
            well_rect.top() + well_rect.height() * RING_LIGHT_TOP,
            well_rect.width(),
            well_rect.height() * (1.0 - RING_LIGHT_TOP),
        )
        glow = QLinearGradient(band.topLeft(), band.bottomLeft())
        glow.setColorAt(0.0, QColor(255, 255, 255, 0))
        glow.setColorAt(1.0, QColor(255, 255, 255, round(255 * RING_BOTTOM_LIGHT * lit)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawRect(band)

    painter.setClipping(False)

    # 4) 弱落影：环外偏下一条极轻的深色 —— 细描边在外，弱阴影在更外面
    if RING_SHADOW > 0:
        pen = QPen(QColor(*SHADOW_INK, round(255 * RING_SHADOW * lit)))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(glass_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius))

    # 5) 发丝环：1px，上缘暗一档、下缘最亮（参考图的下缘就是亮的 —— 那是反光）
    edge = QLinearGradient(well_rect.topLeft(), well_rect.bottomLeft())
    edge.setColorAt(0.0, QColor(255, 255, 255, round(255 * RING_EDGE_TOP * lit)))
    edge.setColorAt(1.0, QColor(255, 255, 255, round(255 * RING_EDGE_BOTTOM * lit)))
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
    """按下回弹：按下纵向压、横向鼓，松手用 OutBack 弹回（参考实现的 elasticity）。

    **各向异性**是「液体」的关键：一按就等比缩小只是个图标在缩放，纵向压扁 + 横向
    鼓起才像一滴液体被指尖按下去（``GLASS_SQUASH`` 控制横鼓有多少）。
    尊重系统「减少动态效果」：动画关闭时直接落终态。
    """

    def __init__(self, widget: QWidget, depth: float = 0.035) -> None:
        self._widget = widget
        self._depth = depth
        self._progress = 0.0        # 0 = 静息，1 = 按到底
        self._animation = QVariantAnimation(widget)
        self._animation.setDuration(200 if animations_enabled() else 0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutBack)
        self._animation.valueChanged.connect(self._on_value)

    @property
    def scale(self) -> float:
        """纵向缩放（沿用旧名：按下「缩一点」的那一档）。"""
        return self.sy

    @property
    def sx(self) -> float:
        """横向缩放：按下时反而**鼓**出来一点。"""
        return 1.0 + self._depth * GLASS_SQUASH * self._progress

    @property
    def sy(self) -> float:
        """纵向缩放：按下时压扁。"""
        return 1.0 - self._depth * self._progress

    def press(self) -> None:
        self._run(1.0)

    def release(self) -> None:
        self._run(0.0)

    def _run(self, target: float) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(target)
        self._animation.start()
        if self._animation.duration() == 0:
            self._on_value(target)

    def _on_value(self, value) -> None:
        self._progress = float(value)
        self._widget.update()
