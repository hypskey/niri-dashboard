import sys

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

        windows = get_windows()

        # Group windows by workspace.
        workspaces = {}

        for window in windows:
            workspace_id = window["workspace_id"]

            if workspace_id not in workspaces:
                workspaces[workspace_id] = []

            workspaces[workspace_id].append(window)

        # Main widget inside a scroll area.
        container = QWidget()
        main_layout = QVBoxLayout(container)

        title = QLabel("NiriDashBoard")
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        main_layout.addWidget(title)

        # One row per workspace.
        for workspace_id in sorted(workspaces):
            workspace_label = QLabel(f"Workspace {workspace_id}")
            workspace_label.setStyleSheet(
                "font-size: 20px; font-weight: bold; margin-top: 20px;"
            )

            main_layout.addWidget(workspace_label)

            row = QHBoxLayout()

            for window in workspaces[workspace_id]:
                card = self.create_window_card(window)
                row.addWidget(card)

            row.addStretch()
            main_layout.addLayout(row)

        main_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)

        self.setCentralWidget(scroll)

    def create_window_card(self, window):
        card = QFrame()
        card.setFixedSize(260, 120)

        if window["is_focused"]:
            border = "3px solid #ffffff"
        else:
            border = "1px solid #666666"

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
        app.setStyleSheet("font-size: 16px; font-weight: bold;")

        title = QLabel(window["title"])
        title.setWordWrap(True)

        window_id = QLabel(f"Window ID: {window['id']}")

        layout.addWidget(app)
        layout.addWidget(title)
        layout.addWidget(window_id)

        return card


app = QApplication(sys.argv)

dashboard = Dashboard()
dashboard.show()

sys.exit(app.exec())
