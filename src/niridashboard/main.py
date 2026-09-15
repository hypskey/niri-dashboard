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

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget
from niridashboard.controller import DashboardController
from niridashboard.graph import GraphView

def dashboard_style(palette, settings):
    return f"""
QMainWindow, QWidget {{ background: {palette.dashboard_background}; color: {palette.primary_text}; font-family: '{settings.font_family}'; }}
QLabel#muted {{ color: {palette.secondary_text}; }}
QLabel#error {{ color: {palette.error_text}; background: {palette.error_background}; padding: 10px; border-radius: 6px; }}
QScrollBar:horizontal {{ height: 9px; background: {palette.dashboard_background}; }}
QScrollBar:vertical {{ width: 9px; background: {palette.dashboard_background}; }}
QScrollBar::handle {{ background: {palette.node_border}; border-radius: 4px; min-width: 24px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
"""


class GraphWindow(QMainWindow):
    """Common graph/controller wiring; each window keeps its own scene and framing."""
    def __init__(self, controller, translucent=False):
        super().__init__()
        self.controller = controller
        self.backend = controller.backend  # Compatibility for callers inspecting the worker.
        self.view = GraphView(controller.icons, translucent=translucent, appearance=controller.appearance)
        self.pending = None
        self.last_state = None
        self.error_kind = None
        self.view.move_requested.connect(lambda wid, ws, before: self.command("move", wid, ws, before))
        self.view.focus_requested.connect(lambda wid: self.command("focus", wid))
        self.view.close_requested.connect(lambda wid: self.command("close", wid))
        self.view.interaction_finished.connect(self.apply_pending)
        controller.appearance_changed.connect(self.receive_appearance)

    def receive_appearance(self):
        self.view.set_appearance()

    def command(self, kind, *args):
        self.controller.action(self, kind, *args)

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
        super().__init__(controller)
        self.setWindowTitle("Niri Dashboard")
        self.resize(1440, 900)
        self.setMinimumSize(760, 480)
        palette = controller.appearance.palette
        settings = controller.appearance.settings
        self.setStyleSheet(dashboard_style(palette, settings))
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("NIRI  /  DASHBOARD")
        title.setStyleSheet(f"font-size: {settings.normal_text_size * 2}px; font-weight: 700; letter-spacing: 2px;")
        header.addWidget(title)
        self.badge = QLabel("ALPHA" + (" · DEMO" if demo else ""))
        self.badge.setStyleSheet(f"color: {palette.focused_text}; padding: 5px 9px; background: {palette.focused_background}; border-radius: 5px;")
        header.addWidget(self.badge)
        header.addStretch()
        layout.addLayout(header)
        self.summary = QLabel("Connecting to your desktop…")
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        layout.addWidget(self.view, 1)
        footer = QHBoxLayout()
        self.status = QLabel("Starting…")
        self.status.setStyleSheet(f"color: {palette.output_label};")
        footer.addWidget(self.status)
        footer.addStretch()
        self.help = QLabel("Drag to move · Click to focus · Wheel to zoom · Drag background to pan")
        self.help.setObjectName("muted")
        footer.addWidget(self.help)
        self.zoom_label = QLabel("100%")
        footer.addWidget(self.zoom_label)
        layout.addLayout(footer)
        self.setCentralWidget(root)
        self.view.hint.connect(self.set_hint)
        self.view.zoom_changed.connect(lambda percent: self.zoom_label.setText(f"{percent}%"))
        self.shortcuts = []
        for key, callback in [("F11", self.toggle_fullscreen), ("Ctrl+0", self.view.fit_graph)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        controller.attach(self)

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def set_hint(self, message):
        self.help.setText(message or "Drag to move · Click to focus · Wheel to zoom · Drag background to pan")

    def action_started(self, kind):
        super().action_started(kind)
        self.status.setText({"move": "Moving window…", "focus": "Focusing window…", "close": "Closing window…"}[kind])

    def action_finished(self, success, message):
        super().action_finished(success, message)
        self.status.setText(message if success else "Action failed")

    def receive_health(self, connected, message):
        super().receive_health(connected, message)
        if not self.view.busy:
            self.status.setText(message if connected else "Disconnected · retrying…")

    def apply_pending(self):
        super().apply_pending()
        if self.last_state is not None:
            data = self.last_state
            count = sum(bool(o.get("logical")) for o in data["outputs"].values())
            self.summary.setText(f"{count} monitors   /   {len(data['workspaces'])} workspaces   /   {len(data['windows'])} windows     ·     Your entire desktop, connected")

    def receive_appearance(self):
        super().receive_appearance()
        palette = self.controller.appearance.palette
        settings = self.controller.appearance.settings
        self.setStyleSheet(dashboard_style(palette, settings))
        self.badge.setStyleSheet(f"color: {palette.focused_text}; padding: 5px 9px; background: {palette.focused_background}; border-radius: 5px;")
        self.status.setStyleSheet(f"color: {palette.output_label};")

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
