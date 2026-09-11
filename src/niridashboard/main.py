"""Niri Dashboard alpha entry point."""
import argparse
import sys
from pathlib import Path

# Keep the original direct-script invocation working alongside python -m.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QVBoxLayout, QWidget
from niridashboard.backend import Backend
from niridashboard.graph import GraphView
from niridashboard.icons import Icons

STYLE = """
QMainWindow, QWidget { background: #0c111c; color: #e5edf9; font-family: 'Sans Serif'; }
QPushButton { background: #192437; border: 1px solid #30405a; border-radius: 7px; padding: 8px 13px; }
QPushButton:hover { background: #293b53; border-color: #69dfc5; }
QLineEdit { background: #141e2e; border: 1px solid #30405a; border-radius: 7px; padding: 9px; }
QLabel#muted { color: #8191a9; }
QLabel#error { color: #ffb1a8; background: #32212a; padding: 10px; border-radius: 6px; }
QScrollBar:horizontal { height: 9px; background: #0c111c; }
QScrollBar:vertical { width: 9px; background: #0c111c; }
QScrollBar::handle { background: #30405a; border-radius: 4px; min-width: 24px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
"""


class Dashboard(QMainWindow):
    def __init__(self, demo=False, start_backend=True):
        super().__init__()
        self.setWindowTitle("Niri Dashboard")
        self.resize(1440, 900)
        self.setMinimumSize(760, 480)
        self.setStyleSheet(STYLE)
        self.pending = None
        self.last_state = None
        self.error_kind = None
        self.backend = Backend(demo)
        self.view = GraphView(Icons())
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("NIRI  /  DASHBOARD")
        title.setStyleSheet("font-size: 19px; font-weight: 700; letter-spacing: 2px;")
        header.addWidget(title)
        badge = QLabel("ALPHA" + (" · DEMO" if demo else ""))
        badge.setStyleSheet("color: #69dfc5; padding: 5px 9px; background: #19352f; border-radius: 5px;")
        header.addWidget(badge)
        header.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find an app or window…  Ctrl+K")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(320)
        self.search.textChanged.connect(self.filter_nodes)
        self.search.returnPressed.connect(self.focus_match)
        header.addWidget(self.search)
        for label, callback in [("−", lambda: self.view.zoom(1 / 1.2)), ("+", lambda: self.view.zoom(1.2)), ("Fit  F", self.view.fit_graph), ("Fullscreen", self.toggle_fullscreen)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            header.addWidget(button)
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
        self.status.setStyleSheet("color: #69dfc5;")
        footer.addWidget(self.status)
        footer.addStretch()
        self.help = QLabel("Drag to move · Click to focus · Wheel to zoom · Drag background to pan")
        self.help.setObjectName("muted")
        footer.addWidget(self.help)
        self.zoom_label = QLabel("100%")
        footer.addWidget(self.zoom_label)
        layout.addLayout(footer)
        self.setCentralWidget(root)
        self.view.move_requested.connect(lambda wid, ws, before: self.command("move", wid, ws, before))
        self.view.focus_requested.connect(lambda wid: self.command("focus", wid))
        self.view.interaction_finished.connect(self.apply_pending)
        self.view.hint.connect(self.set_hint)
        self.view.zoom_changed.connect(lambda percent: self.zoom_label.setText(f"{percent}%"))
        self.backend.state.connect(self.receive_state)
        self.backend.health.connect(self.receive_health)
        self.backend.finished_action.connect(self.action_finished)
        self.shortcuts = []
        for key, callback in [("Ctrl+K", self.search.setFocus), ("F11", self.toggle_fullscreen), ("Ctrl+0", self.view.fit_graph)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        if start_backend:
            self.backend.start()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def set_hint(self, message):
        self.help.setText(message or "Drag to move · Click to focus · Wheel to zoom · Drag background to pan")

    def command(self, kind, *args):
        if self.view.busy or not self.view.connected:
            return
        self.view.busy = True
        self.status.setText("Moving window…" if kind == "move" else "Focusing window…")
        self.error.hide()
        self.error_kind = None
        self.backend.submit(kind, *args)

    def action_finished(self, success, message):
        self.view.busy = False
        if not success:
            self.error_kind = "action"
            self.error.setText(f"Action could not finish: {message}. The graph reflects Niri’s actual state.")
            self.error.show()
        self.status.setText(message if success else "Action failed")
        self.apply_pending()

    def receive_health(self, connected, message):
        self.view.connected = connected
        if not self.view.busy:
            self.status.setText(message if connected else "Disconnected · retrying…")
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
        self.last_state = self.pending
        self.pending = None
        self.view.render(self.last_state)
        self.filter_nodes()
        data = self.last_state
        count = sum(bool(o.get("logical")) for o in data["outputs"].values())
        self.summary.setText(f"{count} monitors   /   {len(data['workspaces'])} workspaces   /   {len(data['windows'])} windows     ·     Your entire desktop, connected")

    def filter_nodes(self):
        query = self.search.text().strip().casefold()
        for node in self.view.nodes.values():
            haystack = f"{node.label} {node.window.get('app_id') or ''} {node.window.get('title') or ''}".casefold()
            node.setOpacity(1 if not query or query in haystack else 0.25)

    def focus_match(self):
        query = self.search.text().strip()
        if query:
            node = next((n for n in self.view.nodes.values() if n.opacity() == 1), None)
            if node:
                self.command("focus", node.window["id"])

    def closeEvent(self, event):
        self.view.cancel_drag()
        self.backend.stop()
        if self.backend.isRunning():
            # Keep the event loop responsive while bounded IPC finishes.
            event.ignore()
            self.hide()
            QTimer.singleShot(100, self.close)
        else:
            event.accept()


def main():
    parser = argparse.ArgumentParser(description="A connected map of your Niri desktop")
    parser.add_argument("--demo", action="store_true", help="Interactive sample desktop; does not contact Niri")
    parser.add_argument("--fullscreen", action="store_true", help="Fill the dashboard's current monitor")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setApplicationName("niridashboard")
    app.setDesktopFileName("niridashboard")
    dashboard = Dashboard(demo=args.demo)
    dashboard.showFullScreen() if args.fullscreen else dashboard.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
