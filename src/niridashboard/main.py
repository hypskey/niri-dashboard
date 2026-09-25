"""Niri Dashboard alpha entry point."""
import sys
from pathlib import Path

# Keep the original direct-script invocation working alongside python -m.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Dispatch direct-script commands before importing Qt, including the toggle client.
if __name__ == "__main__":
    from niridashboard.cli import main
    sys.exit(main())

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget
from niridashboard.controller import DashboardController
from niridashboard.graph import GraphView
from niridashboard.icon_catalog import DEFAULT_CATALOG
from niridashboard.icon_picker import IconPicker
from niridashboard.system_status import SystemStatusWidget

def dashboard_style(palette, settings, transparent=False):
    background = "transparent" if transparent else palette.dashboard_background
    s = settings.scaled
    return f"""
QMainWindow, QWidget {{ background: {background}; color: {palette.primary_text}; font-family: '{settings.font_family}'; font-size: {s(settings.normal_text_size)}px; }}
QLabel#muted {{ color: {palette.secondary_text}; }}
QLabel#error {{ color: {palette.error_text}; background: {palette.error_background}; padding: {s(10)}px; border-radius: {s(6)}px; }}
QScrollBar:horizontal {{ height: {s(9)}px; background: {background}; }}
QScrollBar:vertical {{ width: {s(9)}px; background: {background}; }}
QScrollBar::handle {{ background: {palette.node_border}; border-radius: {s(4)}px; min-width: {s(24)}px; min-height: {s(24)}px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
"""


class GraphWindow(QMainWindow):
    """Common graph/controller wiring; each window keeps its own scene and framing."""
    def __init__(self, controller, translucent=False, background_opacity=1.0, show_pet=False):
        super().__init__()
        self.controller = controller
        self.backend = controller.backend  # Compatibility for callers inspecting the worker.
        self.view = GraphView(controller.icons, translucent=translucent, appearance=controller.appearance,
                              hint_assignments=controller.hint_assignments,
                              background_opacity=background_opacity, show_pet=show_pet)
        self.pending = None
        self.last_state = None
        self.error_kind = None
        self.icon_picker = None
        self.view.move_requested.connect(lambda wid, ws, before: self.command("move", wid, ws, before))
        self.view.focus_requested.connect(lambda wid: self.command("focus", wid))
        self.view.close_requested.connect(lambda wid: self.command("close", wid))
        self.view.force_close_requested.connect(lambda wid: self.command("force_close", wid))
        self.view.icon_picker_requested.connect(self.open_icon_picker)
        self.view.interaction_finished.connect(self.apply_pending)
        controller.appearance_changed.connect(self.receive_appearance)

    def receive_appearance(self):
        self.view.set_appearance()

    def command(self, kind, *args):
        self.controller.action(self, kind, *args)

    def open_icon_picker(self, window_id, position):
        if self.icon_picker is not None:
            self.icon_picker.close()
        picker = IconPicker(DEFAULT_CATALOG, self.controller.icons,
                            self.controller.appearance.palette, self.controller.appearance.settings,
                            self, usage=self.controller.icon_usage)
        self.icon_picker = picker
        picker.selected.connect(self.controller.icon_usage.record)
        picker.selected.connect(lambda icon_id: self.controller.icon_overrides.set(window_id, icon_id))
        picker.reset_requested.connect(lambda: self.controller.icon_overrides.reset(window_id))
        picker.finished.connect(lambda: self._picker_finished(picker))
        picker.finished.connect(picker.deleteLater)
        picker.open_at(position)

    def _picker_finished(self, picker):
        if self.icon_picker is picker:
            self.icon_picker = None

    def action_started(self, kind):
        self.error.hide()
        self.error_kind = None

    def action_finished(self, success, message):
        if not success:
            self.error_kind = "action"
            self.error.setText(f"Action could not finish: {message}")
            self.error.show()
        self.apply_pending()

    def receive_busy(self, busy):
        self.view.busy = busy
        self.apply_pending()

    def receive_health(self, connected, message):
        self.view.connected = connected
        if not connected:
            self.error_kind = "connection"
            self.error.setText(message)
            self.error.show()
            if self.view.pressed:
                self.view.cancel_drag()
                self.apply_pending()
        elif self.error_kind == "connection":
            self.error.hide()
            self.error_kind = None

    def receive_state(self, data):
        self.pending = data
        self.apply_pending()

    def apply_pending(self):
        if self.pending is None or self.view.interacting or self.view.busy:
            return
        state, self.pending = self.pending, None
        if state == self.last_state:
            return
        self.last_state = state
        self.view.render(state)


class Dashboard(GraphWindow):
    def __init__(self, demo=False, start_backend=True, controller=None):
        self.owns_controller = controller is None
        controller = controller or DashboardController(demo, start_backend)
        self.background_opacity = controller.appearance.settings.background_opacity
        super().__init__(controller, translucent=self.background_opacity < 1,
                         background_opacity=self.background_opacity,
                         show_pet=controller.appearance.settings.show_pet)
        self.setWindowTitle("Niri Dashboard")
        self.resize(1440, 900)
        palette = controller.appearance.palette
        settings = controller.appearance.settings
        self.setMinimumSize(760, 480)
        if self.background_opacity < 1:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(dashboard_style(palette, settings, self.background_opacity < 1))
        root = QWidget()
        root.setObjectName("niridashboard-main-root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view)
        self.error = QLabel(self.view.viewport())
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.setMaximumWidth(500)
        self.error.move(12, 12)
        self.error.hide()
        self.setCentralWidget(root)
        # Viewport children are screen overlays: neither the HUD nor the pet
        # can add scene bounds or consume graph layout space.
        self.system_status = (SystemStatusWidget(
            palette, settings, parent=self.view.viewport())
            if settings.show_hud else None)
        controller.attention.changed.connect(self.view.set_attention)
        self.view.attention_dismiss_requested.connect(controller.attention.clear)
        self.view.set_attention(controller.attention.current)
        self.shortcuts = []
        for key, callback in [("F11", self.toggle_fullscreen), ("Ctrl+0", self.view.fit_graph)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        controller.attach(self)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.background_opacity < 1:
            color = QColor(self.controller.appearance.palette.dashboard_background)
            color.setAlphaF(self.background_opacity)
            painter = QPainter(self)
            painter.fillRect(event.rect(), color)
            painter.end()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def receive_appearance(self):
        super().receive_appearance()
        palette = self.controller.appearance.palette
        settings = self.controller.appearance.settings
        self.setStyleSheet(dashboard_style(palette, settings, self.background_opacity < 1))
        if self.system_status is not None:
            self.system_status.set_appearance(palette, settings)

    def closeEvent(self, event):
        self.view.cancel_drag()
        if self.owns_controller:
            self.controller.stop()
            if self.backend.isRunning():
                event.ignore()
                self.hide()
                QTimer.singleShot(100, self.close)
                return
        event.accept()


def main():
    from .cli import main as run
    return run()
