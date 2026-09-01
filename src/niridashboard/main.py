import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from niri import get_windows


class Dashboard(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("NiriDashBoard")
        self.resize(1200, 700)

        self.last_state = None

        self.container = QWidget()
        self.main_layout = QVBoxLayout(self.container)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.container)

        self.setCentralWidget(scroll)

        # First draw.
        self.refresh_dashboard()

        # Refresh Niri state twice per second.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_dashboard)
        self.timer.start(500)

    def refresh_dashboard(self):
        windows = get_windows()

        # Build a compact representation of the current state.
        current_state = tuple(
            sorted(
                (
                    window["id"],
                    window["app_id"],
                    window["title"],
                    window["workspace_id"],
                    window["is_focused"],
                )
                for window in windows
            )
        )

        # Don't redraw if nothing changed.
        if current_state == self.last_state:
            return

        self.last_state = current_state

        self.clear_layout(self.main_layout)

        title = QLabel("NiriDashBoard")
        title.setStyleSheet(
            "font-size: 28px; font-weight: bold;"
        )
        self.main_layout.addWidget(title)

        workspaces = {}

        for window in windows:
            workspace_id = window["workspace_id"]

            if workspace_id not in workspaces:
                workspaces[workspace_id] = []

            workspaces[workspace_id].append(window)

        for workspace_id in sorted(workspaces):
            workspace_label = QLabel(
                f"Workspace {workspace_id}"
            )

            workspace_label.setStyleSheet(
                """
                font-size: 20px;
                font-weight: bold;
                margin-top: 20px;
                """
            )

            self.main_layout.addWidget(workspace_label)

            row = QHBoxLayout()

            for window in workspaces[workspace_id]:
                card = self.create_window_card(window)
                row.addWidget(card)

            row.addStretch()

            self.main_layout.addLayout(row)

        self.main_layout.addStretch()

    def create_window_card(self, window):
        card = QFrame()
        card.setFixedSize(260, 120)

        if window["is_focused"]:
            border = "3px solid white"
        else:
            border = "1px solid gray"

        card.setStyleSheet(
            f"""
            QFrame {{
                border: {border};
                border-radius: 8px;
                padding: 8px;
            }}
            """
        )

        layout = QVBoxLayout(card)

        app = QLabel(window["app_id"])
        app.setStyleSheet(
            "font-size: 16px; font-weight: bold;"
        )

        title = QLabel(window["title"])
        title.setWordWrap(True)

        window_id = QLabel(
            f"Window ID: {window['id']}"
        )

        layout.addWidget(app)
        layout.addWidget(title)
        layout.addWidget(window_id)

        return card

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

            child_layout = item.layout()

            if child_layout is not None:
                self.clear_layout(child_layout)


app = QApplication(sys.argv)

dashboard = Dashboard()
dashboard.show()

sys.exit(app.exec())
