"""Static glow and accent layers for the single focused route."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsObject


class FocusPath(QGraphicsObject):
    def __init__(self, root, junctions, endpoint, accent, background, settings):
        super().__init__()
        self.root = QPointF(root)
        self.junctions = tuple(QPointF(point) for point in junctions)
        self.endpoint = QPointF(endpoint)
        self.settings = settings
        self.path = QPainterPath(self.root)
        self.path.lineTo(self.junctions[-1])
        self.path.lineTo(self.endpoint)
        self.accent = QColor(accent)
        self.background = QColor(background)
        self.bright = QColor.fromRgbF(*[
            channel + (1.0 - channel) * .55
            for channel in (self.accent.redF(), self.accent.greenF(), self.accent.blueF())])
        self.bloom = self.pen(self.accent, settings.scaled_f(14), 24)
        self.inner = self.pen(self.accent, settings.scaled_f(8), 55)
        self.core = self.pen(self.accent, settings.scaled_f(4))
        self.ring = self.pen(self.accent, settings.scaled_f(3))
        self.junction_radius = settings.scaled_f(6)
        margin = settings.scaled_f(11)
        self._bounds = self.path.boundingRect().adjusted(
            -margin, -margin, margin, margin)
        self.setZValue(1)  # above structure, below the existing app cards (z=5)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCacheMode(QGraphicsObject.CacheMode.DeviceCoordinateCache)

    @staticmethod
    def pen(color, width, alpha=255):
        color = QColor(color)
        color.setAlpha(alpha)
        return QPen(color, width, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

    def boundingRect(self):
        return self._bounds

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
            painter.drawEllipse(point, self.junction_radius, self.junction_radius)
        if self.settings.focus_path_glow:
            painter.setPen(Qt.PenStyle.NoPen)
            halo = QColor(self.accent)
            halo.setAlpha(45)
            painter.setBrush(halo)
            painter.drawEllipse(self.endpoint, self.settings.scaled_f(7),
                                self.settings.scaled_f(7))
            painter.setBrush(self.bright)
            painter.drawEllipse(self.endpoint, self.settings.scaled_f(2.5),
                                self.settings.scaled_f(2.5))
