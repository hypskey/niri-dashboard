import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
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
    move_window_to_workspace,
)


class WorkspaceDropZone(QGraphicsRectItem):
    def __init__(
        self,
        workspace_id,
        x,
        y,
        width,
        height,
        pen,
    ):
        super().__init__(x, y, width, height)

        self.workspace_id = workspace_id
        self.normal_pen = pen
        self.setPen(pen)

    def set_drop_active(self, active):
        if active:
            self.setPen(QPen(Qt.GlobalColor.cyan, 4))
        else:
            self.setPen(self.normal_pen)


class WindowCard(QGraphicsRectItem):
    def __init__(
        self,
        window,
        workspace_id,
        width,
        height,
        pen,
    ):
        super().__init__(0, 0, width, height)

        self.window_id = window["id"]
        self.workspace_id = workspace_id
        self.drag_start_position = None
        self.active_drop_zone = None

        self.setPen(pen)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
            True,
        )

        app_text = QGraphicsTextItem(window["app_id"], self)
        app_text.setDefaultTextColor(Qt.GlobalColor.white)
        app_text.setPos(8, 0)
        app_text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        title = window["title"]

        if len(title) > 45:
            title = title[:42] + "..."

        title_text = QGraphicsTextItem(title, self)
        title_text.setDefaultTextColor(Qt.GlobalColor.lightGray)
        title_text.setPos(8, 22)
        title_text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def mousePressEvent(self, event):
        self.drag_start_position = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self.set_active_drop_zone(
            self.drop_zone_at(event.scenePos())
        )

    def mouseReleaseEvent(self, event):
        drop_zone = self.drop_zone_at(event.scenePos())
        moved = self.pos() != self.drag_start_position

        super().mouseReleaseEvent(event)
        self.set_active_drop_zone(None)
        self.setPos(self.drag_start_position)

        if moved:
            if (
                drop_zone is not None
                and drop_zone.workspace_id != self.workspace_id
            ):
                move_window_to_workspace(
                    self.window_id,
                    drop_zone.workspace_id,
                )
        else:
            focus_window(self.window_id)

    def drop_zone_at(self, scene_position):
        for item in self.scene().items(scene_position):
            if isinstance(item, WorkspaceDropZone):
                return item

        return None

    def set_active_drop_zone(self, drop_zone):
        if drop_zone is self.active_drop_zone:
            return

        if self.active_drop_zone is not None:
            self.active_drop_zone.set_drop_active(False)

        self.active_drop_zone = drop_zone

        if self.active_drop_zone is not None:
            self.active_drop_zone.set_drop_active(True)


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
            self.scene.addRect(
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

                workspace_zone = WorkspaceDropZone(
                    workspace["id"],
                    x + 8,
                    workspace_y,
                    width - 16,
                    workspace_height - 5,
                    workspace_pen,
                )

                self.scene.addItem(workspace_zone)

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
                        workspace["id"],
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

    def draw_window_card(
        self,
        window,
        workspace_id,
        x,
        y,
        width,
    ):
        card_height = 52

        if window["is_focused"]:
            pen = QPen(Qt.GlobalColor.white, 3)
        else:
            pen = QPen(Qt.GlobalColor.gray, 1)

        card = WindowCard(
            window,
            workspace_id,
            width,
            card_height,
            pen,
        )

        card.setPos(x, y)
        card.setZValue(5)
        self.scene.addItem(card)


app = QApplication(sys.argv)

dashboard = Dashboard()
dashboard.show()

sys.exit(app.exec())
