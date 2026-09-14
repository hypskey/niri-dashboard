"""A mouse-operated graph of monitor branches, workspace rows and app nodes."""
import math
from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QCursor, QLinearGradient
from PySide6.QtWidgets import QApplication, QGraphicsLineItem, QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView
from .niri import ordered, position

BG = "#f5f2ed"
TEXT = "#434853"
MUTED = "#737681"
COLORS = ["#a9cdbf", "#b9b6dd", "#dfbca7", "#d7b4c9"]
NODE_W, NODE_H, STEP, ROW = 108, 100, 136, 144


def font(size, bold=False):
    return QFont("Sans Serif", size, QFont.Weight.DemiBold if bold else QFont.Weight.Normal)


class AppNode(QGraphicsObject):
    def __init__(self, window, icons, color):
        super().__init__()
        self.window = window
        self.label, self.icon = icons.resolve(window.get("app_id"))
        self.color = color
        self.hovered = False
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(5)
        pos = position(window)
        detail = "Floating · dropping inserts into tiling" if window.get("is_floating") else f"Column {pos[0]}, row {pos[1]}" if pos else "Position unavailable"
        self.setToolTip(f"{self.label}\n{window.get('title') or 'Untitled window'}\n{detail}\nDrag to a workspace or between apps")

    def boundingRect(self):
        return QRectF(-3, -3, NODE_W + 6, NODE_H + 6)

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        focused = self.window.get("is_focused")
        # A softly shaded circular badge; the labels sit directly on the canvas.
        p.setPen(Qt.PenStyle.NoPen)
        for spread, alpha in [(3, 6), (1.5, 10)]:
            p.setBrush(QColor(72, 64, 58, alpha))
            p.drawEllipse(QRectF(27 - spread, 3 - spread, 54 + spread * 2, 54 + spread * 2))
        gradient = QLinearGradient(34, 0, 72, 54)
        gradient.setColorAt(0, QColor("#fffcf8"))
        gradient.setColorAt(1, QColor(self.color).lighter(116))
        p.setBrush(gradient)
        p.setPen(QPen(QColor(self.color).darker(115) if focused or self.hovered else QColor("#ffffff"), 2 if focused else 1))
        p.drawEllipse(QRectF(27, 0, 54, 54))
        self.icon.paint(p, 35, 8, 38, 38)
        p.setFont(font(9, True))
        p.setPen(QColor(TEXT))
        label = p.fontMetrics().elidedText(self.label, Qt.TextElideMode.ElideRight, NODE_W - 12)
        p.drawText(QRectF(6, 56, NODE_W - 12, 18), Qt.AlignmentFlag.AlignCenter, label)
        p.setFont(font(8))
        p.setPen(QColor(MUTED))
        title = p.fontMetrics().elidedText(self.window.get("title") or "Untitled", Qt.TextElideMode.ElideRight, NODE_W - 12)
        p.drawText(QRectF(6, 77, NODE_W - 12, 16), Qt.AlignmentFlag.AlignCenter, title)
        if self.window.get("is_floating"):
            p.setPen(QColor(self.color))
            p.drawText(QRectF(84, 4, 18, 16), Qt.AlignmentFlag.AlignCenter, "~")
        if self.window.get("is_urgent"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#bd8053"))
            p.drawEllipse(QPointF(96, 12), 4, 4)

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()


class GraphView(QGraphicsView):
    move_requested = Signal(int, int, object)
    focus_requested = Signal(int)
    close_requested = Signal(int)
    escape_pressed = Signal()
    interaction_finished = Signal()
    hint = Signal(str)
    zoom_changed = Signal(int)

    def __init__(self, icons, translucent=False):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.icons = icons
        self.translucent = translucent
        self.nodes = {}
        self.rows = []
        self.data = None
        self.pressed = None
        self.dragging = False
        self.panning = False
        self.busy = False
        self.connected = False
        self.drop = None
        self.marker = None
        self.auto_fit = True
        self.space = False
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(Qt.BrushStyle.NoBrush if translucent else QColor(BG))
        if translucent:
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
            self.setStyleSheet("background: transparent; border: none;")
            self.setAutoFillBackground(False)
            self.viewport().setAutoFillBackground(False)
            self.viewport().setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
            self.viewport().setStyleSheet("background: transparent; border: none;")
            palette = self.viewport().palette()
            palette.setColor(palette.ColorRole.Window, QColor(0, 0, 0, 0))
            self.viewport().setPalette(palette)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.edge_timer = QTimer(self)
        self.edge_timer.setInterval(16)
        self.edge_timer.timeout.connect(self.edge_pan)

    @property
    def interacting(self):
        return self.pressed is not None or self.panning

    def text(self, text, x, y, size=10, color=TEXT, bold=False):
        item = self.scene().addSimpleText(text, font(size, bold))
        item.setBrush(QColor(color).darker(155) if color in COLORS else QColor(color))
        item.setPos(x, y)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        return item

    def line(self, x1, y1, x2, y2, color, width=2):
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        item = self.scene().addLine(x1, y1, x2, y2, pen)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        # Child strokes follow insertion markers and are removed with their parent.
        shadow = QGraphicsLineItem(x1, y1 + 1, x2, y2 + 1, item)
        shadow.setPen(QPen(QColor(88, 76, 68, 20), width + 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        shadow.setZValue(-1)
        shadow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        return item

    def render(self, data):
        self.data = data
        self.scene().clear()
        self.nodes = {}
        self.rows = []
        self.marker = None
        outputs = data["outputs"]
        names = sorted([name for name, out in outputs.items() if out.get("logical")],
                       key=lambda name: (outputs[name]["logical"].get("x", 0), outputs[name]["logical"].get("y", 0)))
        # Preserve workspaces during output disconnects / compositor transitions.
        for ws in data["workspaces"]:
            if ws.get("output") not in names:
                names.append(ws.get("output"))
        if not names:
            self.text("Your desktop will appear here", 20, 20, 20, bold=True)
            self.text("Waiting for an active monitor and its workspaces.", 20, 60, 11, MUTED)
        x = 32
        for branch, name in enumerate(names):
            color = COLORS[branch % len(COLORS)]
            workspaces = sorted([w for w in data["workspaces"] if w.get("output") == name], key=lambda w: w["idx"])
            groups = [ordered([w for w in data["windows"] if w.get("workspace_id") == ws["id"]]) for ws in workspaces]
            width = max(370, 152 + max((len(w) for w in groups), default=0) * STEP)
            self.line(x + 20, 67, x + 20, 114 + max(0, len(workspaces) - 1) * ROW + 27, color, 3)
            self.text(f"{branch + 1:02d}  /  {name or 'Unassigned'}", x, 8, 15, color, True)
            model = outputs.get(name, {}).get("model") or "Workspace branch"
            self.text(f"{model}  ·  {len(workspaces)} workspaces", x, 38, 9, MUTED)
            for row, (ws, windows) in enumerate(zip(workspaces, groups)):
                y = 114 + row * ROW
                self.line(x + 20, y + 27, x + 137, y + 27, color)
                dot = self.scene().addEllipse(x + 14, y + 21, 12, 12, QPen(QColor(color), 2), QColor(color if ws.get("is_active") else BG))
                dot.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self.text(f"{ws['idx']:02d}", x - 4, y + 4, 11, color, True)
                label = ws.get("name") or f"Workspace {ws['idx']}"
                self.text(label[:27] + ("…" if len(label) > 27 else ""), x + 52, y - 25, 10, TEXT, True)
                start = x + 110
                rect = QRectF(x + 45, y - 5, width - 45, 115)
                self.rows.append({"workspace": ws, "rect": rect, "start": start, "y": y, "windows": windows, "color": color})
                if not windows:
                    placeholder = self.scene().addEllipse(QRectF(start + 27, y, 54, 54), QPen(QColor(color), 1, Qt.PenStyle.DashLine))
                    placeholder.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    plus = self.text("+", start, y, 22, MUTED)
                    plus.setPos(start + 54 - plus.boundingRect().width() / 2, y + 27 - plus.boundingRect().height() / 2)
                for index, window in enumerate(windows):
                    nx = start + index * STEP
                    if index:
                        self.line(nx - STEP + 81, y + 27, nx + 27, y + 27, color)
                    node = AppNode(window, self.icons, color)
                    node.setPos(nx, y)
                    self.scene().addItem(node)
                    self.nodes[window["id"]] = node
                    pos = position(window)
                    if pos and sum(bool(position(w)) and position(w)[0] == pos[0] for w in windows) > 1:
                        self.text(f"STACK {pos[0]} · {pos[1]}", nx + 15, y + 104, 7, MUTED)
            x += width + 60
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-45, -45, 75, 65))
        if self.auto_fit:
            self.fit_graph()

    def fit_graph(self):
        self.auto_fit = True
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        if self.transform().m11() > 1.3:
            self.resetTransform()
            self.scale(1.3, 1.3)
        self.zoom_changed.emit(round(self.transform().m11() * 100))

    def zoom(self, factor):
        value = self.transform().m11() * factor
        if 0.12 <= value <= 2.5:
            self.auto_fit = False
            self.scale(factor, factor)
            self.zoom_changed.emit(round(value * 100))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit:
            self.fit_graph()

    def wheelEvent(self, event):
        self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        event.accept()

    def node_at(self, pos):
        return next((item for item in self.items(pos) if isinstance(item, AppNode)), None)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            node = self.node_at(event.position().toPoint())
            if node and self.connected and not self.busy and not self.interacting:
                self.close_requested.emit(node.window["id"])
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and self.space):
            self.panning = True
            self.pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            node = self.node_at(event.position().toPoint())
            if node and self.connected and not self.busy:
                self.pressed = node
                self.press_point = event.position().toPoint()
                self.origin = QPointF(node.pos())
                self.offset = self.mapToScene(self.press_point) - node.pos()
                event.accept()
                return
            if not node:
                self.panning = True
                self.pan_start = event.position().toPoint()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        if self.panning:
            delta = point - self.pan_start
            self.pan_start = point
            self.auto_fit = False
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        if self.pressed:
            if not self.dragging and (point - self.press_point).manhattanLength() >= QApplication.startDragDistance():
                self.dragging = True
                self.pressed.setZValue(50)
                self.pressed.setOpacity(0.85)
                self.edge_timer.start()
            if self.dragging:
                self.update_drag(point)
            return
        super().mouseMoveEvent(event)

    def update_drag(self, point):
        scene_pos = self.mapToScene(point)
        self.pressed.setPos(scene_pos - self.offset)
        self.drop = None
        if self.marker:
            self.scene().removeItem(self.marker)
            self.marker = None
        for row in self.rows:
            if not row["rect"].contains(scene_pos):
                continue
            # Anchors use original node coordinates, even while the dragged node moves.
            candidates = [(i, w) for i, w in enumerate(row["windows"]) if w["id"] != self.pressed.window["id"]]
            before = next(((i, w) for i, w in candidates if scene_pos.x() < row["start"] + i * STEP + NODE_W / 2), None)
            if before and position(before[1]):
                # A tiled insertion is between columns, never inside an existing stack.
                column = position(before[1])[0]
                before = next((pair for pair in candidates if position(pair[1]) and position(pair[1])[0] == column), before)
            elif before:
                # Floating windows have no column position; insert at the tiled end.
                before = None
            anchor = before[1]["id"] if before else None
            self.drop = row["workspace"]["id"], anchor
            mx = row["start"] + (before[0] * STEP if before else len(row["windows"]) * STEP) - 14
            self.marker = self.line(mx, row["y"] - 5, mx, row["y"] + NODE_H + 5, row["color"], 4)
            self.marker.setZValue(40)
            destination = row["workspace"].get("name") or f"Workspace {row['workspace']['idx']}"
            where = f"before {self.icons.resolve(before[1].get('app_id'))[0]}" if before else "at the end"
            self.hint.emit(f"Move to {row['workspace'].get('output') or 'unassigned'} / {destination} · {where}")
            break
        if self.drop is None:
            self.hint.emit("Drop on a workspace row · Esc cancels")

    def edge_pan(self):
        if not self.dragging:
            return
        point = self.viewport().mapFromGlobal(QCursor.pos())
        for value, limit, bar in [(point.x(), self.viewport().width(), self.horizontalScrollBar()), (point.y(), self.viewport().height(), self.verticalScrollBar())]:
            delta = -12 if value < 40 else 12 if value > limit - 40 else 0
            if delta:
                self.auto_fit = False
                bar.setValue(bar.value() + delta)
        self.update_drag(point)

    def cancel_drag(self):
        self.edge_timer.stop()
        if self.pressed:
            self.pressed.setPos(self.origin)
            self.pressed.setOpacity(1)
            self.pressed.setZValue(5)
        if self.marker:
            self.scene().removeItem(self.marker)
            self.marker = None
        self.pressed = None
        self.dragging = False
        self.drop = None
        self.hint.emit("")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return
        if self.panning:
            self.panning = False
            self.unsetCursor()
            self.interaction_finished.emit()
            return
        if self.pressed:
            wid = self.pressed.window["id"]
            dragging, drop = self.dragging, self.drop
            self.cancel_drag()
            if self.connected and not self.busy:
                if dragging and drop:
                    self.move_requested.emit(wid, *drop)
                elif not dragging:
                    self.focus_requested.emit(wid)
            self.interaction_finished.emit()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_drag()
            self.interaction_finished.emit()
            self.escape_pressed.emit()
        elif event.key() == Qt.Key.Key_Space:
            self.space = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif event.key() == Qt.Key.Key_F:
            self.fit_graph()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.space = False
            self.unsetCursor()
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.space = False
        self.panning = False
        if self.pressed:
            self.cancel_drag()
            self.interaction_finished.emit()
        super().focusOutEvent(event)

    def drawBackground(self, p, rect):
        if self.translucent:
            # Leave untouched pixels at alpha 0 so Niri's desktop shows through.
            return
        p.fillRect(rect, QColor(BG))
        p.setPen(QPen(QColor("#e3dfd8"), 1))
        step = 28 if self.transform().m11() > 0.4 else 56
        for x in range(math.floor(rect.left() / step) * step, math.ceil(rect.right()), step):
            for y in range(math.floor(rect.top() / step) * step, math.ceil(rect.bottom()), step):
                p.drawPoint(QPointF(x, y))
