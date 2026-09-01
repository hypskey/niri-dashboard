import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QMainWindow,
)

from niri import (
    focus_window,
    get_outputs,
    get_windows,
    get_workspaces,
)

class WindowCard(QGraphicsRectItem):
    def __init__(self, window_id, width, height, pen):
        super().__init__(0, 0, width, height)

        self.window_id = window_id
        self.setPen(pen)

        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        focus_window(self.window_id)
        super().mousePressEvent(event)

class Dashboard(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("NiriDashBoard")
        self.resize(1400, 800)

        self.scene = QGraphicsScene()

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(self.view.renderHints())
        self.setCentralWidget(self.view)

        self.last_state = None

        self.refresh_dashboard()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_dashboard)
        self.timer.start(500)

    def refresh_dashboard(self):
        windows = get_windows()
        workspaces = get_workspaces()
        outputs = get_outputs()

        current_state = (
            repr(windows),
            repr(workspaces),
            repr(outputs),
        )

        if current_state == self.last_state:
            return

        self.last_state = current_state

        self.draw_dashboard(windows, workspaces, outputs)

    def draw_dashboard(self, windows, workspaces, outputs):
        self.scene.clear()

        # Scale Niri desktop coordinates down to dashboard coordinates.
        scale = 0.22

        min_x = min(
            output["logical"]["x"]
            for output in outputs.values()
            if output["logical"] is not None
        )

        min_y = min(
            output["logical"]["y"]
            for output in outputs.values()
            if output["logical"] is not None
        )

        margin = 80

        for output_name, output in outputs.items():
            logical = output["logical"]

            if logical is None:
                continue

            x = (logical["x"] - min_x) * scale + margin
            y = (logical["y"] - min_y) * scale + margin

            width = logical["width"] * scale
            height = logical["height"] * scale

            # Monitor body.
            monitor = self.scene.addRect(
                x,
                y,
                width,
                height,
                QPen(Qt.GlobalColor.white, 3),
                QBrush(Qt.GlobalColor.black),
            )

            # Monitor name.
            title = self.scene.addText(
                f"{output_name} — {output['model']}"
            )

            title.setDefaultTextColor(Qt.GlobalColor.white)
            title.setPos(x + 12, y + 8)

            # Find workspaces belonging to this monitor.
            output_workspaces = [
                workspace
                for workspace in workspaces
                if workspace["output"] == output_name
            ]

            # Sort workspaces by their Niri index.
            output_workspaces.sort(
                key=lambda workspace: workspace["idx"]
            )

            if not output_workspaces:
                continue

            header_height = 65

            available_height = height - header_height

            workspace_height = (
                available_height / len(output_workspaces)
            )

            for index, workspace in enumerate(output_workspaces):
                workspace_y = (
                    y
                    + header_height
                    + index * workspace_height
                )

                if workspace["is_active"]:
                    workspace_pen = QPen(
                        Qt.GlobalColor.white,
                        3,
                    )
                else:
                    workspace_pen = QPen(
                        Qt.GlobalColor.gray,
                        1,
                    )

                self.scene.addRect(
                    x + 8,
                    workspace_y,
                    width - 16,
                    workspace_height - 5,
                    workspace_pen,
                )

                workspace_name = workspace["name"]

                if workspace_name:
                    workspace_text = (
                        f"WS {workspace['id']} "
                        f"— {workspace_name}"
                    )
                else:
                    workspace_text = (
                        f"WS {workspace['id']}"
                    )

                if workspace["is_active"]:
                    workspace_text += "  [ACTIVE]"

                workspace_label = self.scene.addText(
                    workspace_text
                )

                workspace_label.setDefaultTextColor(
                    Qt.GlobalColor.white
                    if workspace["is_active"]
                    else Qt.GlobalColor.lightGray
                )

                workspace_label.setPos(
                    x + 18,
                    workspace_y + 4,
                )

                workspace_windows = [
                    window
                    for window in windows
                    if window["workspace_id"]
                    == workspace["id"]
                ]

                window_y = workspace_y + 30

                for window in workspace_windows:
                    self.draw_window_card(
                        window,
                        x + 18,
                        window_y,
                        width - 36,
                    )

                    window_y += 65

        self.scene.setSceneRect(
            self.scene.itemsBoundingRect().adjusted(
                -40,
                -40,
                40,
                40,
            )
        )

        self.view.fitInView(
            self.scene.sceneRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def draw_window_card(self, window, x, y, width):
        card_height = 52

        if window["is_focused"]:
            pen = QPen(Qt.GlobalColor.white, 3)
        else:
            pen = QPen(Qt.GlobalColor.gray, 1)

        card = WindowCard(
            window["id"],
            width,
            card_height,
            pen,
        )


        card.setPos(x, y)
        card.setZValue(5)
        self.scene.addItem(card)


        app_text = self.scene.addText(
            window["app_id"]
        )

        app_text.setDefaultTextColor(
            Qt.GlobalColor.white
        )

        app_text.setPos(
            x + 8,
            y
        )

        app_text.setZValue(10)

        app_text.setAcceptedMouseButtons(
            Qt.MouseButton.NoButton
        )

        title = window["title"]

        if len(title) > 45:
            title = title[:42] + "..."

        title_text = self.scene.addText(
            title
        )

        title_text.setDefaultTextColor(
            Qt.GlobalColor.lightGray
        )

        title_text.setPos(
            x + 8,
            y + 22
        )

        title_text.setZValue(10)

        title_text.setAcceptedMouseButtons(
            Qt.MouseButton.NoButton
        )


app = QApplication(sys.argv)

dashboard = Dashboard()
dashboard.show()

sys.exit(app.exec())
