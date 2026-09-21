"""Lightweight, directional paint layers for the single focused route."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsObject


class FocusPath(QGraphicsObject):
    TRACER_WIDTH = 2.0
    DASH_PATTERN = (7.0, 29.0)
    PERIOD = sum(DASH_PATTERN) * TRACER_WIDTH
    SPEED = 36.0  # scene pixels / second at flow_speed = 1

    def __init__(self, root, junctions, endpoint, accent, background, settings, distance=0.0):
        super().__init__()
        self.root = QPointF(root)
        self.junctions = tuple(QPointF(point) for point in junctions)
        self.endpoint = QPointF(endpoint)
        self.settings = settings
        self.distance = distance
        self.path = QPainterPath(self.root)
        self.path.lineTo(self.junctions[-1])
        self.path.lineTo(self.endpoint)
        self.accent = QColor(accent)
        self.background = QColor(background)
        self.bright = QColor.fromRgbF(*[
            channel + (1.0 - channel) * .55
            for channel in (self.accent.redF(), self.accent.greenF(), self.accent.blueF())])
        self.bloom = self.pen(self.accent, 14, 24)
        self.inner = self.pen(self.accent, 8, 55)
        self.core = self.pen(self.accent, 4)
        self.tracer = self.pen(self.bright, self.TRACER_WIDTH, 215)
        self.tracer.setDashPattern(list(self.DASH_PATTERN))
        self.ring = self.pen(self.accent, 3)
        self._bounds = self.path.boundingRect().adjusted(-11, -11, 11, 11)
        # Only the 2px tracer changes; the wider glow and endpoint stay static.
        corner = self.junctions[-1]
        self.dirty_rects = (
            QRectF(self.root, corner).normalized().adjusted(-3, -3, 3, 3),
            QRectF(corner, self.endpoint).normalized().adjusted(-3, -3, 3, 3),
        )
        self.setZValue(1)  # above structure, below the existing app cards (z=5)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCacheMode(QGraphicsObject.CacheMode.DeviceCoordinateCache)
        self.tracer_item = _FlowTracer(self) if settings.focus_path_flow else None

    @staticmethod
    def pen(color, width, alpha=255):
        color = QColor(color)
        color.setAlpha(alpha)
        return QPen(color, width, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    def boundingRect(self):
        return self._bounds

    def set_distance(self, distance):
        self.distance = distance % self.PERIOD

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.settings.focus_path_glow:
            for pen in (self.bloom, self.inner):
                painter.setPen(pen)
                painter.drawPath(self.path)
        painter.setPen(self.core)
        painter.drawPath(self.path)
        painter.setPen(self.ring)
        for index, point in enumerate(self.junctions):
            painter.setBrush(self.accent if index == len(self.junctions) - 1 else self.background)
            painter.drawEllipse(point, 6, 6)
        if self.settings.focus_path_glow:
            painter.setPen(Qt.PenStyle.NoPen)
            halo = QColor(self.accent)
            halo.setAlpha(45)
            painter.setBrush(halo)
            painter.drawEllipse(self.endpoint, 7, 7)
            painter.setBrush(self.bright)
            painter.drawEllipse(self.endpoint, 2.5, 2.5)


class _FlowTracer(QGraphicsObject):
    """Only this small paint pass changes; Qt caches the static parent layers."""
    def __init__(self, route):
        super().__init__(route)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return self.parentItem().boundingRect()

    def paint(self, painter, option, widget=None):
        route = self.parentItem()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Qt dash offsets are in pen-width units. Decreasing the offset moves
        # each dash forward along the root -> down -> right path.
        route.tracer.setDashOffset(-route.distance / route.TRACER_WIDTH)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(route.tracer)
        painter.drawPath(route.path)
