"""A mouse-operated graph of monitor branches, workspace rows and app nodes."""
import math
from PySide6.QtCore import (QEasingCurve, QElapsedTimer, QPoint, QPointF,
                            QPropertyAnimation, QRectF, Qt, Signal, QTimer)
from PySide6.QtGui import (QColor, QFont, QInputDevice,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QTransform)
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsLineItem, QGraphicsObject, QGraphicsRectItem, QGraphicsScene, QGraphicsView
from .appearance import DEFAULT_PALETTE, DashboardSettings
from .dashboard_nodes import dashboard_nodes
from .hints import HintAssignments
from .focus_path import FocusPath
from .niri import ordered, position
from .pet import PET_HEIGHT, PetGraphicsItem

BG = DEFAULT_PALETTE.dashboard_background
TEXT = DEFAULT_PALETTE.primary_text
MUTED = DEFAULT_PALETTE.secondary_text
COLORS = list(DEFAULT_PALETTE.pipe_colors)
NODE_W, NODE_H, STEP, ROW = 108, 100, 136, 144
MAX_MANUAL_ZOOM = 1.5
MOUSE_DRAG_THRESHOLD = 12
TOUCH_DRAG_THRESHOLD = 22
FORCE_CLOSE_DOUBLE_TAP_MS = 600
# The dedicated dashboard display is intentionally absent from the desktop
# topology. This becomes a user-configurable output list in a later iteration.
HIDDEN_DASHBOARD_OUTPUTS = frozenset({"HDMI-A-5"})


def font(size, bold=False, settings=None):
    settings = settings or DashboardSettings()
    return QFont(settings.font_family, settings.scaled(size),
                 QFont.Weight.DemiBold if bold else QFont.Weight.Normal)


class AppNode(QGraphicsObject):
    @staticmethod
    def icon_circle_rect(settings):
        icon_size = settings.scaled(settings.icon_size)
        padding = settings.scaled_f(8)
        left = (settings.scaled(settings.node_width) - icon_size) / 2 - padding
        return QRectF(left, 0, icon_size + padding * 2,
                      icon_size + padding * 2)

    def __init__(self, dashboard_node, icons, color, hints=None, palette=None, settings=None):
        super().__init__()
        self.dashboard_node = dashboard_node
        self.window = dashboard_node.window
        self.icons = icons
        self.label, self.icon = icons.resolve_for_window(
            self.window.get("app_id"), self.window.get("title"),
            self.window.get("browser_hostname"), self.window.get("icon_override"))
        self.color = color
        self.hints = {member["id"]: str(hints[member["id"]])
                      for member in dashboard_node.members
                      if hints and member["id"] in hints}
        self.hint = self.hints.get(self.window["id"], "")
        self.palette = palette or DEFAULT_PALETTE
        self.settings = settings or DashboardSettings()
        self.width = self.settings.scaled(self.settings.node_width)
        self.height = self.settings.scaled(self.settings.node_height)
        self.hovered = False
        self.pressed_feedback = False
        self.feedback_animation = None
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(5)
        self.setTransformOriginPoint(self.width / 2, self.height / 2)
        pos = position(self.window)
        detail = "Floating · dropping inserts into tiling" if self.window.get("is_floating") else f"Column {pos[0]}, row {pos[1]}" if pos else "Position unavailable"
        if dashboard_node.is_stack:
            names = [icons.resolve_for_window(member.get("app_id"), member.get("title"),
                     member.get("browser_hostname"), member.get("icon_override"))[0]
                     for member in dashboard_node.members]
            self.setToolTip(f"Stack: {names[0]} / {names[1]}\n{detail}\nDrag the whole stack")
        else:
            self.setToolTip(f"{self.label}\n{self.window.get('title') or 'Untitled window'}\n{detail}\nDrag to a workspace or between apps")

    def member_at(self, scene_point):
        """Choose a stack member by icon half; the label area uses the active one."""
        if not self.dashboard_node.is_stack:
            return self.window
        circle = self.icon_circle_rect(self.settings)
        point = self.mapFromScene(scene_point)
        if circle.top() <= point.y() <= circle.bottom():
            # The two icon halves remain targetable across the full width of
            # the icon band, including the transparent corners of the circle.
            return self.dashboard_node.members[0 if point.y() < circle.center().y() else 1]
        return self.dashboard_node.focused_member

    def boundingRect(self):
        edge = self.settings.scaled_f(3)
        return QRectF(-edge, -edge, self.width + edge * 2,
                      self.height + edge * 2)

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        focused = self.dashboard_node.focused
        s = self.settings.scaled
        sf = self.settings.scaled_f
        icon_size = s(self.settings.icon_size)
        circle = self.icon_circle_rect(self.settings)
        icon_x = circle.left() + sf(8)
        p.setFont(font(self.settings.hint_badge_font_size, True, self.settings))
        badge_height = s(20)
        badge_width = max(s(20), p.fontMetrics().horizontalAdvance(self.hint) + s(10))
        badge_rect = QRectF(self.width - badge_width, 0, badge_width, badge_height)
        base = QColor(self.palette.focused_background
                      if focused or self.pressed_feedback
                      else self.palette.node_background)
        gradient = QLinearGradient(icon_x, 0, icon_x + icon_size, icon_size)
        gradient.setColorAt(0, base.lighter(108))
        gradient.setColorAt(1, base.darker(108))
        p.setBrush(gradient)
        border = self.palette.focused_border if focused or self.hovered else self.palette.node_border
        p.setPen(QPen(QColor(border),
                      sf(2 if focused or self.pressed_feedback else 1)))
        p.drawEllipse(circle)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.dashboard_node.is_stack:
            self._paint_stack_icons(p, circle)
            for index, member in enumerate(self.dashboard_node.members):
                member_focused = member is self.dashboard_node.focused_member and focused
                label_font = font(self.settings.application_title_size, True, self.settings)
                if member_focused:
                    label_font.setWeight(QFont.Weight.Bold)
                p.setFont(label_font)
                p.setPen(QColor(self.palette.primary_text if member_focused
                                else self.palette.application_title))
                name = self.icons.resolve_for_window(
                    member.get("app_id"), member.get("title"),
                    member.get("browser_hostname"), member.get("icon_override"))[0]
                name = p.fontMetrics().elidedText(
                    name, Qt.TextElideMode.ElideRight, self.width - s(24))
                label_rect = QRectF(s(6), circle.bottom() + s(4 + 18 * index),
                                    self.width - s(12), s(18))
                p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, name)
                if member_focused:
                    dot_x = max(sf(7), (self.width - p.fontMetrics().horizontalAdvance(name)) / 2 - sf(7))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(self.palette.focused_route))
                    p.drawEllipse(QPointF(dot_x, label_rect.center().y()), sf(2.5), sf(2.5))
            badge_font = font(self.settings.hint_badge_font_size, True, self.settings)
            p.setFont(badge_font)
            badge_height = s(20)
            for index, member in enumerate(self.dashboard_node.members):
                hint = self.hints.get(member["id"])
                if hint:
                    width = max(s(20), p.fontMetrics().horizontalAdvance(hint) + s(10))
                    gap = sf(4)
                    x = (circle.left() - gap - width if index == 0
                         else circle.right() + gap)
                    y = circle.top() if index == 0 else circle.bottom() - badge_height
                    badge = QRectF(x, y, width, badge_height)
                    self._paint_hint_badge(p, badge, hint, badge_font)
            return
        pixmap = self.icons.rendered(
            self.window.get("app_id"), icon_size, self.window.get("title"),
            self.window.get("browser_hostname"), self.window.get("icon_override"))
        if not pixmap.isNull():
            pixmap_size = pixmap.deviceIndependentSize()
            px = icon_x + (icon_size - pixmap_size.width()) / 2
            py = sf(8) + (icon_size - pixmap_size.height()) / 2
            p.drawPixmap(QPointF(px, py), pixmap)
        label_font = font(self.settings.application_title_size, True, self.settings)
        if focused:
            label_font.setWeight(QFont.Weight.Bold)
        p.setFont(label_font)
        p.setPen(QColor(self.palette.primary_text if focused else self.palette.application_title))
        label_width = self.width - s(20 if focused else 12)
        label = p.fontMetrics().elidedText(
            self.label, Qt.TextElideMode.ElideRight, label_width)
        label_rect = QRectF(s(6), icon_size + s(18), self.width - s(12), s(18))
        p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)
        if focused:
            # The Noctalia accent foreground is designed for an accent fill and
            # can be almost invisible on this dark card. Keep the words legible;
            # let a small accent marker carry the focus color instead.
            text_width = p.fontMetrics().horizontalAdvance(label)
            dot_x = max(sf(7), (self.width - text_width) / 2 - sf(7))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.palette.focused_route))
            p.drawEllipse(QPointF(dot_x, label_rect.center().y()), sf(2.5), sf(2.5))
        title_font = font(self.settings.window_title_size, settings=self.settings)
        if focused:
            title_font.setWeight(QFont.Weight.Medium)
        p.setFont(title_font)
        p.setPen(QColor(self.palette.primary_text if focused else self.palette.window_title))
        title = p.fontMetrics().elidedText(
            self.window.get("title") or "Untitled", Qt.TextElideMode.ElideRight,
            self.width - s(12))
        p.drawText(QRectF(s(6), icon_size + s(38), self.width - s(12), s(16)),
                   Qt.AlignmentFlag.AlignCenter, title)
        if self.window.get("is_floating"):
            p.setPen(QColor(self.palette.secondary_text))
            p.drawText(QRectF(s(2), s(2), s(18), s(16)),
                       Qt.AlignmentFlag.AlignCenter, "~")
        if self.window.get("is_urgent"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.palette.pipe_colors[2]))
            p.drawEllipse(QPointF(self.width - sf(5), self.height - sf(5)),
                          sf(4), sf(4))
        if self.hint:
            self._paint_hint_badge(p, badge_rect, self.hint)

    def _paint_hint_badge(self, painter, rect, hint, badge_font=None):
        painter.setFont(badge_font or font(self.settings.hint_badge_font_size, True, self.settings))
        painter.setPen(QPen(QColor(self.palette.hint_border), self.settings.scaled_f(1)))
        painter.setBrush(QColor(self.palette.hint_background))
        radius = self.settings.scaled_f(5)
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(QColor(self.palette.hint_text))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, hint)

    def _paint_stack_icons(self, painter, circle):
        ellipse = QPainterPath()
        ellipse.addEllipse(circle)
        icon_size = self.settings.scaled(self.settings.icon_size)
        for index, member in enumerate(self.dashboard_node.members):
            half = QPainterPath()
            half.addRect(QRectF(circle.left(), circle.top() + index * circle.height() / 2,
                                circle.width(), circle.height() / 2))
            painter.save()
            painter.setClipPath(ellipse.intersected(half))
            pixmap = self.icons.rendered(
                member.get("app_id"), icon_size, member.get("title"),
                member.get("browser_hostname"), member.get("icon_override"))
            if not pixmap.isNull():
                center = circle.center()
                size = pixmap.deviceIndependentSize()
                painter.drawPixmap(QPointF(center.x() - size.width() / 2,
                                           center.y() - size.height() / 2), pixmap)
            painter.restore()
        separator = QColor(self.palette.focused_border if self.dashboard_node.focused
                           else self.palette.node_border)
        separator.setAlpha(190)
        painter.save()
        painter.setClipPath(ellipse)
        painter.setPen(QPen(separator, self.settings.scaled_f(1)))
        painter.drawLine(QPointF(circle.left(), circle.center().y()),
                         QPointF(circle.right(), circle.center().y()))
        painter.restore()

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()

    def set_pressed_feedback(self, pressed):
        self.pressed_feedback = pressed
        if pressed:
            if self.feedback_animation is not None:
                self.feedback_animation.stop()
            self.setScale(1.035)
        else:
            self.setScale(1.0)
        self.update()

    def animate_click(self):
        self.pressed_feedback = True
        animation = QPropertyAnimation(self, b"scale", self)
        animation.setDuration(170)
        animation.setStartValue(1.035)
        animation.setKeyValueAt(.55, .985)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(self._finish_click_feedback)
        self.feedback_animation = animation
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self.update()

    def _finish_click_feedback(self):
        self.pressed_feedback = False
        self.feedback_animation = None
        self.setScale(1.0)
        self.update()


class GraphView(QGraphicsView):
    move_requested = Signal(int, int, object)
    focus_requested = Signal(int)
    close_requested = Signal(int)
    force_close_requested = Signal(int)
    icon_picker_requested = Signal(int, object)
    escape_pressed = Signal()
    interaction_finished = Signal()
    hint = Signal(str)
    zoom_changed = Signal(int)
    numeric_pressed = Signal(str)
    attention_dismiss_requested = Signal()

    def __init__(self, icons, translucent=False, appearance=None, hint_assignments=None,
                 background_opacity=1.0, show_pet=False):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.icons = icons
        self.translucent = translucent
        self.background_opacity = background_opacity
        self.numeric_selection_enabled = False
        self.appearance = appearance
        self.colors = appearance.palette if appearance else DEFAULT_PALETTE
        self.settings = appearance.settings if appearance else DashboardSettings()
        self.hint_assignments = hint_assignments or HintAssignments()
        self.shared_hint_assignments = hint_assignments is not None
        self.show_pet = show_pet
        self.pet_item = None
        self.pet_world_anchors = {}
        self.pet_screen_anchors = {}
        self.pet_focused_output = None
        self.attention = None
        self.nodes = {}
        self.rows = []
        self.trailing_targets = []
        self.data = None
        self.pressed = None
        self.close_candidate = None
        self.close_target_id = None
        self.close_press_point = None
        self.close_is_touch = False
        self.close_cancelled = False
        self.close_force_candidate = False
        self.close_sequence_window_id = None
        self.close_sequence_timer = QElapsedTimer()
        self.dragging = False
        self.drag_scene_rect = None
        self.drag_transform = None
        self.drag_center = None
        self.drag_point = None
        self.drag_auto_fit = None
        self.drag_scene_expanded = False
        self.press_is_touch = False
        self.panning = False
        self.busy = False
        self.connected = False
        self.drop = None
        self.marker = None
        self.auto_fit = True
        self.default_transform = QTransform()
        self.default_scale = None
        self.background_grid = True
        self.appearance_pending = False
        self.space = False
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(Qt.BrushStyle.NoBrush if translucent else QColor(self.colors.dashboard_background))
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
        # Panning and edge scrolling still use the scrollbar values internally;
        # hiding the chrome prevents temporary drag bounds from flashing bars.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.edge_timer = QTimer(self)
        self.edge_timer.setInterval(33)
        self.edge_timer.timeout.connect(self.edge_pan)
        self.focus_path = None
        self.graph_bounds = QRectF()
        self.interaction_finished.connect(self._finish_appearance_update)
        self.horizontalScrollBar().valueChanged.connect(self._sync_pet_overlay)
        self.verticalScrollBar().valueChanged.connect(self._sync_pet_overlay)

    def set_attention(self, cue):
        self.attention = cue
        if self.pet_item is not None:
            self.pet_item.set_attention(cue)

    @property
    def interacting(self):
        return (self.pressed is not None or self.panning or
                self.close_candidate is not None)

    def set_appearance(self):
        if self.appearance:
            self.colors = self.appearance.palette
            self.settings = self.appearance.settings
        if not self.translucent:
            self.setBackgroundBrush(QColor(self.colors.dashboard_background))
            widget_palette = QGraphicsView.palette(self)
            widget_palette.setColor(widget_palette.ColorRole.Window, QColor(self.colors.dashboard_background))
            self.setPalette(widget_palette)
        if self.data is not None:
            if self.interacting:
                self.appearance_pending = True
            else:
                self.render(self.data)

    def _finish_appearance_update(self):
        if self.appearance_pending and not self.interacting and self.data is not None:
            self.appearance_pending = False
            self.render(self.data)

    def text(self, text, x, y, size=None, color=None, bold=False):
        size = size if size is not None else self.settings.normal_text_size
        color = color or self.colors.primary_text
        item = self.scene().addSimpleText(text, font(size, bold, self.settings))
        item.setBrush(QColor(color))
        item.setPos(x, y)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        return item

    def line(self, x1, y1, x2, y2, color, width=2):
        width = self.settings.scaled_f(width)
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        item = self.scene().addLine(x1, y1, x2, y2, pen)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        # Child strokes follow insertion markers and are removed with their parent.
        shadow = QGraphicsLineItem(x1, y1 + 1, x2, y2 + 1, item)
        shadow_color = QColor(self.colors.secondary_text)
        shadow_color.setAlpha(28)
        shadow.setPen(QPen(shadow_color, width + 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        shadow.setZValue(-1)
        shadow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        return item

    def render(self, data):
        self.data = data
        s = self.settings.scaled
        sf = self.settings.scaled_f
        ls = self.settings.layout_scaled
        view_transform = QTransform(self.transform())
        horizontal_scroll = self.horizontalScrollBar().value()
        vertical_scroll = self.verticalScrollBar().value()
        pet_item = self.pet_item if self.show_pet else None
        if pet_item is not None and pet_item.scene() is self.scene():
            self.scene().removeItem(pet_item)
        self.focus_path = None
        self.pet_item = pet_item
        self.scene().clear()
        self.nodes = {}
        self.rows = []
        self.trailing_targets = []
        self.marker = None
        outputs = data["outputs"]
        names = sorted([name for name, out in outputs.items()
                        if out.get("logical") and
                        name not in HIDDEN_DASHBOARD_OUTPUTS],
                       key=lambda name: (outputs[name]["logical"].get("x", 0), outputs[name]["logical"].get("y", 0)))
        # Preserve workspaces during output disconnects / compositor transitions.
        for ws in data["workspaces"]:
            if (ws.get("output") not in names and
                    ws.get("output") not in HIDDEN_DASHBOARD_OUTPUTS):
                names.append(ws.get("output"))
        if not names:
            self.text("Your desktop will appear here", ls(20), ls(20),
                      self.settings.output_label_size, self.colors.primary_text, True)
            self.text("Waiting for an active monitor and its workspaces.",
                      ls(20), ls(60), self.settings.normal_text_size,
                      self.colors.secondary_text)
        branches = []
        ordered_window_ids = []
        for name in names:
            all_workspaces = sorted([w for w in data["workspaces"] if w.get("output") == name], key=lambda w: w["idx"])
            all_groups = [dashboard_nodes(w for w in data["windows"]
                                          if w.get("workspace_id") == ws["id"])
                          for ws in all_workspaces]
            last_occupied = max((index for index, windows in enumerate(all_groups) if windows), default=None)
            trailing_workspace = None
            if last_occupied is None:
                workspaces, groups = all_workspaces[:1], all_groups[:1]
            else:
                workspaces, groups = all_workspaces[:last_occupied + 1], all_groups[:last_occupied + 1]
                if last_occupied + 1 < len(all_workspaces):
                    trailing_workspace = all_workspaces[last_occupied + 1]
            ordered_window_ids.extend(member["id"] for group in groups
                                      for node in group for member in node.members)
            branches.append((name, workspaces, groups, trailing_workspace))
        hint_by_id = (dict(self.hint_assignments.by_window) if self.shared_hint_assignments
                      else self.hint_assignments.update(ordered_window_ids))
        x = 0
        focused_window = next((window for window in data["windows"] if window.get("is_focused")), None)
        focused_workspace_id = focused_window.get("workspace_id") if focused_window else None
        focused_workspace = next(
            (workspace for workspace in data["workspaces"]
             if workspace.get("id") == focused_workspace_id), None)
        focused_output = focused_workspace.get("output") if focused_workspace else None
        pet_anchors = {}
        for branch, (name, workspaces, groups, trailing_workspace) in enumerate(branches):
            color = self.colors.neutral_pipe
            node_width = s(self.settings.node_width)
            node_height = s(self.settings.node_height)
            circle = AppNode.icon_circle_rect(self.settings)
            circle_y = circle.center().y()
            step = max(ls(self.settings.workspace_step), node_width + ls(28))
            row_height = max(ls(self.settings.workspace_row), node_height + ls(44))
            width = max(node_width + ls(262),
                        ls(152) + max((len(w) for w in groups), default=0) * step)
            trunk_x = x + ls(20)
            if self.show_pet:
                pet_anchors[name] = QPointF(
                    x + ls(4), ls(4) - sf(PET_HEIGHT))
            self.line(trunk_x, ls(67), trunk_x,
                      ls(114) + max(0, len(workspaces) - 1) * row_height + circle_y,
                      color, 3)
            self.text(f"{branch + 1:02d}  /  {name or 'Unassigned'}",
                      x, ls(8), self.settings.output_label_size,
                      self.colors.output_label, True)
            model = outputs.get(name, {}).get("model") or "Workspace branch"
            self.text(f"{model}  ·  {len(workspaces)} workspaces", x, ls(38),
                      self.settings.normal_text_size, self.colors.secondary_text)
            for row, (ws, nodes) in enumerate(zip(workspaces, groups)):
                y = ls(114) + row * row_height
                branch_y = y + circle_y
                start = x + ls(110)
                self.line(trunk_x, branch_y, start + circle.left(), branch_y, color)
                dot_fill = (color if ws.get("is_active")
                            else self.colors.dashboard_background)
                dot_size = s(12)
                dot = self.scene().addEllipse(
                    trunk_x - dot_size / 2, branch_y - dot_size / 2,
                    dot_size, dot_size,
                    QPen(QColor(color), sf(2)), QColor(dot_fill))
                dot.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                number = self.text(f"{ws['idx']:02d}", 0, y + ls(4),
                                   self.settings.workspace_number_size,
                                   self.colors.workspace_number, True)
                number.setX(trunk_x - dot_size / 2 - ls(8) -
                            number.boundingRect().width())
                rect = QRectF(x + ls(45), y - ls(5), width - ls(45),
                              node_height + s(15))
                self.rows.append({"workspace": ws, "rect": rect,
                                  "hit_rect": rect.adjusted(
                                      0, -s(8), 0, s(8)),
                                  "start": start, "y": y, "windows": nodes,
                                  "color": color, "step": step,
                                  "node_width": node_width,
                                  "node_height": node_height})
                if not nodes:
                    placeholder_size = min(s(54), s(self.settings.icon_size) + s(16))
                    placeholder_rect = QRectF(
                        start + circle.left(), branch_y - placeholder_size / 2,
                        placeholder_size, placeholder_size)
                    placeholder = self.scene().addEllipse(
                        placeholder_rect,
                        QPen(QColor(color), sf(1), Qt.PenStyle.DashLine))
                    placeholder.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    plus = self.text("+", start, y, 22, self.colors.secondary_text)
                    plus_bounds = plus.boundingRect()
                    plus.setPos(
                        placeholder_rect.center().x() - plus_bounds.width() / 2,
                        placeholder_rect.center().y() - plus_bounds.height() / 2 -
                        sf(1.5))
                for index, dashboard_node in enumerate(nodes):
                    nx = start + index * step
                    if index:
                        self.line(nx - step + circle.right(), branch_y,
                                  nx + circle.left(), branch_y, color)
                    node = AppNode(dashboard_node, self.icons, color,
                                   hint_by_id, self.colors, self.settings)
                    node.setPos(nx, y)
                    self.scene().addItem(node)
                    for member in dashboard_node.members:
                        self.nodes[member["id"]] = node
                    pos = position(dashboard_node.window)
                    if (pos and sum(bool(position(other.window)) and
                                    position(other.window)[0] == pos[0]
                                    for other in nodes) > 2):
                        self.text(f"STACK {pos[0]} · {pos[1]}", nx + ls(15),
                                  y + node_height + ls(4),
                                  max(6, self.settings.normal_text_size - 2),
                                  self.colors.secondary_text)
            focus_row = next((index for index, ws in enumerate(workspaces)
                              if ws["id"] == focused_workspace_id), None)
            if focus_row is not None:
                focus_nodes = groups[focus_row]
                focus_index = next((index for index, node in enumerate(focus_nodes)
                                    if node.contains(focused_window["id"])), None)
                if focus_index is not None:
                    accent = self.colors.focused_route
                    focus_y = ls(114) + focus_row * row_height + circle_y
                    # Keep the same root, junctions and destination. Intermediate
                    # cards mask the continuous path at their existing z-order.
                    self.focus_path = FocusPath(
                        QPointF(trunk_x, ls(67)),
                        [QPointF(trunk_x, ls(114) + row * row_height + circle_y)
                         for row in range(focus_row + 1)],
                        QPointF(start + circle.left() + focus_index * step, focus_y),
                        accent, self.colors.dashboard_background, self.settings)
                    self.scene().addItem(self.focus_path)
            if trailing_workspace and workspaces:
                target_y = ls(114) + len(workspaces) * row_height - ls(20)
                target_rect = QRectF(
                    x + ls(45), target_y, width - ls(45),
                    max(s(72), node_height))
                self.trailing_targets.append({
                    "workspace": trailing_workspace,
                    "rect": target_rect,
                    "hit_rect": target_rect.adjusted(
                        -s(8), -s(10), s(8), s(12)),
                    "output": name,
                })
            x += width + ls(self.settings.branch_gap)
        if self.show_pet and names:
            if self.pet_item is None:
                self.pet_item = PetGraphicsItem(
                    self.colors.focused_route,
                    self.colors.dashboard_background)
                self.pet_item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            self.pet_item.set_ui_scale(self.settings.global_scale)
            self.scene().addItem(self.pet_item)
            self.pet_item.set_hud_colors(
                self.colors.focused_route,
                self.colors.dashboard_background,
                self.colors.primary_text)
            self.pet_item.set_attention(self.attention)
        self.pet_world_anchors = pet_anchors
        self.pet_focused_output = focused_output
        padding = ls(self.settings.graph_padding)
        pet_in_scene = (self.pet_item is not None and
                        self.pet_item.scene() is self.scene())
        if pet_in_scene:
            self.scene().removeItem(self.pet_item)
        focus_in_scene = self.focus_path is not None and self.focus_path.scene() is self.scene()
        if focus_in_scene:
            self.scene().removeItem(self.focus_path)
        self.graph_bounds = self.scene().itemsBoundingRect()
        if focus_in_scene:
            self.scene().addItem(self.focus_path)
        if pet_in_scene:
            self.scene().addItem(self.pet_item)
        next_rect = self.graph_bounds.adjusted(-padding, -padding, padding, padding)
        layout_changed = next_rect != self.sceneRect()
        self.scene().setSceneRect(next_rect)
        if self.dragging:
            self.setTransform(view_transform)
            self.horizontalScrollBar().setValue(horizontal_scroll)
            self.verticalScrollBar().setValue(vertical_scroll)
        elif layout_changed and self.auto_fit:
            self.fit_graph()
        else:
            self.setTransform(view_transform)
            self.horizontalScrollBar().setValue(horizontal_scroll)
            self.verticalScrollBar().setValue(vertical_scroll)
        if layout_changed or self.pet_screen_anchors.keys() != pet_anchors.keys():
            self._place_pet_over_outputs()
        else:
            self._sync_pet_overlay()
        self.update_pet_dock_anchor()

    @property
    def hint_targets(self):
        return {str(hint): window_id for window_id, hint in self.hint_assignments.by_window.items()}

    def fit_graph(self):
        if self.dragging:
            return
        self.auto_fit = True
        # Always derive the default from an identity transform.  This makes
        # fitting idempotent after wheel zoom and prevents refreshes/actions
        # from accumulating scale around the mouse cursor.
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.resetTransform()
        bounds = self.sceneRect()
        if not bounds.isEmpty():
            # Scene bounds contain only graph geometry and symmetric padding.
            scale = min(1.0,
                        max(1, self.viewport().width() - 2) / bounds.width(),
                        max(1, self.viewport().height() - 2) / bounds.height())
            self.scale(scale, scale)
        self.centerOn(self.sceneRect().center())
        self.setTransformationAnchor(anchor)
        self.default_transform = QTransform(self.transform())
        self.default_scale = self.transform().m11()
        self.zoom_changed.emit(100)
        self._place_pet_over_outputs()
        self.update_pet_dock_anchor()

    def _place_pet_over_outputs(self):
        """Project graph-relative monitor positions into the screen overlay layer."""
        if self.pet_item is None:
            return
        width = self.pet_item.scaled_motion_rect().width()
        margin = self.settings.scaled(8)
        self.pet_screen_anchors = {}
        for name, world in self.pet_world_anchors.items():
            point = self.mapFromScene(world)
            self.pet_screen_anchors[name] = QPoint(
                max(margin, min(point.x(), self.viewport().width() - width - margin)),
                max(margin, point.y()))
        self._sync_pet_overlay()

    def _sync_pet_overlay(self):
        if self.pet_item is None or self.pet_item.scene() is not self.scene():
            return
        anchors = {name: self.mapToScene(point)
                   for name, point in self.pet_screen_anchors.items()}
        self.pet_item.set_output_anchors(anchors, self.pet_focused_output)
        self.update_pet_dock_anchor()

    def update_pet_dock_anchor(self):
        if getattr(self, "pet_item", None) is None or self.viewport().width() <= 0:
            return
        # Pet artwork ignores the graph transform; its dimensions here are
        # device pixels. The speech bubble does not affect its dock position.
        pet_corner = self.pet_item.scaled_motion_rect().bottomRight()
        point = QPoint(
            round(self.viewport().width() - self.settings.scaled(14) - pet_corner.x()),
            round(self.viewport().height() - self.settings.scaled(10) - pet_corner.y()))
        self.pet_item.set_dock_anchor(self.mapToScene(point))

    def zoom(self, factor):
        if self.dragging:
            return
        if self.default_scale is None:
            self.fit_graph()
        current = self.transform().m11()
        minimum = self.default_scale or current
        maximum = minimum * MAX_MANUAL_ZOOM
        target = max(minimum, min(maximum, current * factor))
        if math.isclose(target, current, rel_tol=1e-9, abs_tol=1e-9):
            return
        if math.isclose(target, minimum, rel_tol=1e-9, abs_tol=1e-9):
            self.fit_graph()
            return
        self.auto_fit = False
        self.scale(target / current, target / current)
        self.zoom_changed.emit(round(target / minimum * 100))
        self._sync_pet_overlay()
        self.update_pet_dock_anchor()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit and not self.dragging:
            self.fit_graph()
        else:
            self._sync_pet_overlay()
            self.update_pet_dock_anchor()

    def wheelEvent(self, event):
        self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        point = event.position().toPoint()
        if (event.button() == Qt.MouseButton.LeftButton and
                (event.modifiers() | QApplication.keyboardModifiers()) &
                Qt.KeyboardModifier.ControlModifier):
            if self.node_at(point) is not None:
                self.mousePressEvent(event)
            else:
                event.accept()
            return
        pet_hit = (self.pet_item is not None and
                   self.pet_item in self.items(point))
        if (event.button() == Qt.MouseButton.LeftButton and
                self.node_at(point) is None and not pet_hit):
            self.fit_graph()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def node_at(self, pos):
        return next((item for item in self.items(pos) if isinstance(item, AppNode)), None)

    def member_id_at(self, node, point):
        return node.member_at(self.mapToScene(point))["id"]

    @staticmethod
    def _is_touch_event(event):
        device = event.pointingDevice()
        return (event.source() != Qt.MouseEventSource.MouseEventNotSynthesized or
                (device is not None and
                 device.type() == QInputDevice.DeviceType.TouchScreen))

    def drag_threshold(self):
        threshold = (TOUCH_DRAG_THRESHOLD if self.press_is_touch
                     else MOUSE_DRAG_THRESHOLD)
        return max(QApplication.startDragDistance(), threshold)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            node = self.node_at(event.position().toPoint())
            if node and self.connected and not self.busy and not self.interacting:
                self.close_requested.emit(self.member_id_at(node, event.position().toPoint()))
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            node = self.node_at(event.position().toPoint())
            if node and not self.interacting:
                self.icon_picker_requested.emit(
                    self.member_id_at(node, event.position().toPoint()),
                    self.viewport().mapToGlobal(event.position().toPoint()))
                event.accept()
                return
            self.panning = True
            self.pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if (event.button() == Qt.MouseButton.LeftButton and
                (event.modifiers() | QApplication.keyboardModifiers()) &
                Qt.KeyboardModifier.AltModifier):
            node = self.node_at(event.position().toPoint())
            if node and not self.interacting:
                self.icon_picker_requested.emit(
                    self.member_id_at(node, event.position().toPoint()),
                    self.viewport().mapToGlobal(event.position().toPoint()))
                event.accept()
                return
        if (event.button() == Qt.MouseButton.LeftButton and not self.space and
                self.pet_item is not None and
                self.pet_item in self.items(event.position().toPoint())):
            if self.pet_item.attention_active:
                self.attention_dismiss_requested.emit()
                event.accept()
                return
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.pet_item.toggle_focus_session()
            else:
                self.update_pet_dock_anchor()
                self.pet_item.toggle_dock()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.space:
            self.panning = True
            self.pan_start = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if (event.button() == Qt.MouseButton.LeftButton and
                (event.modifiers() | QApplication.keyboardModifiers()) &
                Qt.KeyboardModifier.ControlModifier):
            node = self.node_at(event.position().toPoint())
            if node and not self.interacting:
                target_id = self.member_id_at(node, event.position().toPoint())
                repeated = (self.close_sequence_window_id == target_id and
                            self.close_sequence_timer.isValid() and
                            self.close_sequence_timer.elapsed() <= FORCE_CLOSE_DOUBLE_TAP_MS)
                if self.connected and (not self.busy or repeated):
                    self.close_candidate = node
                    self.close_target_id = target_id
                    self.close_press_point = event.position().toPoint()
                    self.close_is_touch = self._is_touch_event(event)
                    self.close_cancelled = False
                    self.close_force_candidate = repeated
                    node.set_pressed_feedback(True)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            node = self.node_at(event.position().toPoint())
            if node and self.connected and not self.busy:
                self.pressed = node
                self.press_is_touch = self._is_touch_event(event)
                self.press_point = event.position().toPoint()
                self.origin = QPointF(node.pos())
                self.offset = self.mapToScene(self.press_point) - node.pos()
                node.set_pressed_feedback(True)
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
        if self.close_candidate is not None:
            threshold = (TOUCH_DRAG_THRESHOLD if self.close_is_touch
                         else MOUSE_DRAG_THRESHOLD)
            if ((point - self.close_press_point).manhattanLength() >=
                    max(QApplication.startDragDistance(), threshold)):
                self.close_cancelled = True
                self.close_candidate.set_pressed_feedback(False)
            event.accept()
            return
        if self.panning:
            delta = point - self.pan_start
            self.pan_start = point
            self.auto_fit = False
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self.update_pet_dock_anchor()
            return
        if self.pressed:
            if (not self.dragging and
                    (point - self.press_point).manhattanLength() >=
                    self.drag_threshold()):
                self.dragging = True
                self.drag_scene_rect = QRectF(self.sceneRect())
                self.drag_transform = QTransform(self.transform())
                self.drag_center = self.mapToScene(
                    self.viewport().rect().center())
                self.drag_auto_fit = self.auto_fit
                self.drag_scene_expanded = False
                self.pressed.set_pressed_feedback(False)
                self.pressed.setZValue(50)
                self.pressed.setOpacity(0.85)
                self.edge_timer.start()
            if self.dragging:
                self.update_drag(point)
            return
        super().mouseMoveEvent(event)

    def update_drag(self, point):
        self.drag_point = QPoint(point)
        scene_pos = self.mapToScene(point)
        self.pressed.setPos(scene_pos - self.offset)
        base_scene_rect = (QRectF(self.drag_scene_rect)
                           if self.drag_scene_rect is not None
                           else QRectF(self.sceneRect()))
        desired_scene_rect = base_scene_rect
        self.drop = None
        if self.marker:
            self.scene().removeItem(self.marker)
            self.marker = None
        for row in self.rows:
            if not row["hit_rect"].contains(scene_pos):
                continue
            # Anchors use original node coordinates, even while the dragged node moves.
            # Re-index the remaining cards after removing the dragged one.  Using
            # their old positions leaves a phantom gap on same-row reorders.
            candidates = list(enumerate(
                node for node in row["windows"]
                if not node.contains(self.pressed.window["id"])))
            before = next(((i, node) for i, node in candidates
                           if scene_pos.x() < row["start"] + i * row["step"] +
                           row["node_width"] / 2), None)
            if before and position(before[1].window):
                # A tiled insertion is between columns, never inside an existing stack.
                column = position(before[1].window)[0]
                before = next((pair for pair in candidates if position(pair[1].window)
                               and position(pair[1].window)[0] == column), before)
            elif before:
                # Floating windows have no column position; insert at the tiled end.
                before = None
            anchor = before[1].window["id"] if before else None
            self.drop = row["workspace"]["id"], anchor
            mx = (row["start"] +
                  (before[0] * row["step"] if before
                   else len(candidates) * row["step"]) -
                  self.settings.scaled(14))
            circle = AppNode.icon_circle_rect(self.settings)
            marker_radius = self.settings.scaled_f(2)
            self.marker = self.line(
                mx, row["y"] + circle.top() + marker_radius, mx,
                row["y"] + circle.bottom() - marker_radius,
                row["color"], 4)
            self.marker.setZValue(40)
            destination = f"{row['workspace']['idx']:02d}"
            where = f"before {self.icons.resolve(before[1].window.get('app_id'))[0]}" if before else "at the end"
            self.hint.emit(f"Move to {row['workspace'].get('output') or 'unassigned'} / {destination} · {where}")
            break
        if self.drop is None:
            for target in self.trailing_targets:
                if not target["hit_rect"].contains(scene_pos):
                    continue
                self.drop = target["workspace"]["id"], None
                rect = target["rect"]
                self.marker = QGraphicsRectItem(
                    QRectF(0, 0, rect.width(), rect.height()))
                self.marker.setPos(rect.topLeft())
                self.marker.setPen(QPen(
                    QColor(self.colors.focused_route),
                    self.settings.scaled_f(2), Qt.PenStyle.DashLine))
                fill = QColor(self.colors.node_background)
                fill.setAlpha(225)
                self.marker.setBrush(fill)
                self.marker.setZValue(40)
                self.marker.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self.scene().addItem(self.marker)
                label = self.text("+ Create workspace", 0, 0, self.settings.normal_text_size,
                                  self.colors.focused_route, True)
                label.setParentItem(self.marker)
                label.setPos((rect.width() - label.boundingRect().width()) / 2,
                             (rect.height() - label.boundingRect().height()) / 2)
                margin = self.settings.scaled(8)
                desired_scene_rect = base_scene_rect.united(
                    rect.adjusted(-margin, -margin, margin, margin))
                self.hint.emit(f"Move to {target['output'] or 'unassigned'} / create workspace")
                break
        if self.dragging and self.sceneRect() != desired_scene_rect:
            # Extending the scene for the temporary target must not move the
            # camera.  Always derive it from the pre-drag bounds, then preserve
            # the current center (including any deliberate edge pan).
            center = self.mapToScene(self.viewport().rect().center())
            transform = QTransform(self.transform())
            self.scene().setSceneRect(desired_scene_rect)
            self.setTransform(transform)
            self.centerOn(center)
        self.drag_scene_expanded = desired_scene_rect != base_scene_rect
        if self.drop is None:
            self.hint.emit("Drop on a workspace row · Esc cancels")

    def edge_pan(self):
        if not self.dragging or self.drag_point is None:
            return
        point = self.drag_point
        moved = False
        for value, limit, bar in [(point.x(), self.viewport().width(), self.horizontalScrollBar()), (point.y(), self.viewport().height(), self.verticalScrollBar())]:
            edge = self.settings.scaled(40)
            speed = self.settings.scaled(8)
            delta = -speed if value < edge else speed if value > limit - edge else 0
            if delta:
                before = bar.value()
                bar.setValue(bar.value() + delta)
                moved = moved or bar.value() != before
        if not moved:
            return
        self.auto_fit = False
        self.update_pet_dock_anchor()
        self.update_drag(point)

    def cancel_drag(self):
        self.edge_timer.stop()
        if self.close_candidate is not None:
            self.close_candidate.set_pressed_feedback(False)
            if self.close_force_candidate:
                self.close_sequence_window_id = None
                self.close_sequence_timer.invalidate()
            self.close_candidate = None
            self.close_target_id = None
            self.close_press_point = None
            self.close_is_touch = False
            self.close_cancelled = False
            self.close_force_candidate = False
        was_dragging = self.dragging
        if self.pressed:
            self.pressed.setPos(self.origin)
            self.pressed.setOpacity(1)
            self.pressed.setZValue(5)
            self.pressed.set_pressed_feedback(False)
        if self.marker:
            self.scene().removeItem(self.marker)
            self.marker = None
        if was_dragging and self.drag_scene_rect is not None:
            self.scene().setSceneRect(self.drag_scene_rect)
            if self.drag_transform is not None:
                self.setTransform(self.drag_transform)
            if self.drag_center is not None:
                self.centerOn(self.drag_center)
            if self.drag_auto_fit is not None:
                self.auto_fit = self.drag_auto_fit
        self.drag_scene_rect = None
        self.drag_transform = None
        self.drag_center = None
        self.drag_point = None
        self.drag_auto_fit = None
        self.drag_scene_expanded = False
        self.press_is_touch = False
        self.pressed = None
        self.dragging = False
        self.drop = None
        self.hint.emit("")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.close_candidate is not None:
            candidate = self.close_candidate
            target_id = self.close_target_id
            force = self.close_force_candidate
            threshold = (TOUCH_DRAG_THRESHOLD if self.close_is_touch
                         else MOUSE_DRAG_THRESHOLD)
            should_close = (not self.close_cancelled and
                            (event.position().toPoint() - self.close_press_point).manhattanLength() <
                            max(QApplication.startDragDistance(), threshold) and
                            self.node_at(event.position().toPoint()) is candidate and
                            self.connected and (not self.busy or force))
            self.cancel_drag()
            if should_close:
                candidate.animate_click()
                if force:
                    self.close_sequence_window_id = None
                    self.close_sequence_timer.invalidate()
                    self.force_close_requested.emit(target_id)
                else:
                    self.close_sequence_window_id = target_id
                    self.close_sequence_timer.start()
                    self.close_requested.emit(target_id)
            elif force:
                self.close_sequence_window_id = None
                self.close_sequence_timer.invalidate()
            self.interaction_finished.emit()
            event.accept()
            return
        if self.panning:
            self.panning = False
            self.unsetCursor()
            self.interaction_finished.emit()
            return
        if self.pressed:
            clicked_node = self.pressed
            wid = self.pressed.window["id"]
            clicked_id = self.member_id_at(clicked_node, event.position().toPoint())
            dragging, drop = self.dragging, self.drop
            self.cancel_drag()
            if self.connected and not self.busy:
                if dragging and drop:
                    self.move_requested.emit(wid, *drop)
                elif not dragging:
                    clicked_node.animate_click()
                    self.focus_requested.emit(clicked_id)
            self.interaction_finished.emit()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_drag()
            self.interaction_finished.emit()
            self.escape_pressed.emit()
        elif self.numeric_selection_enabled and event.text() in "0123456789" and len(event.text()) == 1:
            self.numeric_pressed.emit(event.text())
            event.accept()
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
        if self.pressed or self.close_candidate is not None:
            self.cancel_drag()
            self.interaction_finished.emit()
        super().focusOutEvent(event)

    def drawBackground(self, p, rect):
        if not self.translucent:
            p.fillRect(rect, QColor(self.colors.dashboard_background))
        if not self.background_grid:
            return
        grid_color = QColor(self.colors.secondary_text)
        grid_color.setAlpha(round(22 * self.background_opacity))
        p.setPen(QPen(grid_color, 1))
        step = (self.settings.scaled(28) if self.transform().m11() > 0.4
                else self.settings.scaled(56))
        for x in range(math.floor(rect.left() / step) * step, math.ceil(rect.right()), step):
            for y in range(math.floor(rect.top() / step) * step, math.ceil(rect.bottom()), step):
                p.drawPoint(QPointF(x, y))
