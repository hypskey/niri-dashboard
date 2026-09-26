import copy
import os
import unittest
from dataclasses import replace
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsEllipseItem, QGraphicsLineItem
from niridashboard import niri
from niridashboard.backend import Backend, demo_state
from niridashboard.dashboard_nodes import dashboard_nodes
from niridashboard.controller import DashboardController
from niridashboard.main import Dashboard


def window(wid, workspace=1, col=1, row=1, focused=False, floating=False):
    return {"id": wid, "workspace_id": workspace, "is_focused": focused, "is_floating": floating,
            "layout": {"pos_in_scrolling_layout": None if floating else [col, row]}}


class ModelNiri:
    """Small behavioral compositor model for column movement regression tests."""
    def __init__(self, windows):
        self.windows = windows
        self.calls = []

    def query(self):
        return copy.deepcopy(self.windows)

    def normalize(self, workspace):
        peers = [w for w in self.windows if w["workspace_id"] == workspace and niri.position(w)]
        columns = sorted(set(niri.position(w)[0] for w in peers))
        for w in peers:
            w["layout"]["pos_in_scrolling_layout"][0] = columns.index(niri.position(w)[0]) + 1

    def action(self, name, **args):
        self.calls.append((name, args))
        if name == "FocusWindow":
            for w in self.windows:
                w["is_focused"] = w["id"] == args["id"]
        elif name == "MoveWindowToWorkspace":
            w = next(w for w in self.windows if w["id"] == args["window_id"])
            old = w["workspace_id"]
            target = args["reference"]["Id"]
            col = max([niri.position(p)[0] for p in self.windows if p["workspace_id"] == target and niri.position(p)] or [0]) + 1
            w["workspace_id"] = target
            w["layout"]["pos_in_scrolling_layout"] = [col, 1]
            self.normalize(old)
        elif name == "MoveColumnToWorkspace":
            focused = next(w for w in self.windows if w["is_focused"])
            old = focused["workspace_id"]
            source = niri.position(focused)[0]
            target = args["reference"]["Id"]
            column = max([niri.position(w)[0] for w in self.windows
                          if w["workspace_id"] == target and niri.position(w)] or [0]) + 1
            for member in self.windows:
                if member["workspace_id"] == old and niri.position(member) and niri.position(member)[0] == source:
                    member["workspace_id"] = target
                    member["layout"]["pos_in_scrolling_layout"][0] = column
            self.normalize(old)
        elif name == "MoveWindowToTiling":
            w = next(w for w in self.windows if w["id"] == args["id"])
            w["is_floating"] = False
            w["layout"]["pos_in_scrolling_layout"] = [99, 1]
            self.normalize(w["workspace_id"])
        elif name == "ConsumeOrExpelWindowRight":
            w = next(w for w in self.windows if w["id"] == args["id"])
            col = niri.position(w)[0]
            for peer in self.windows:
                if peer["workspace_id"] == w["workspace_id"] and niri.position(peer) and niri.position(peer)[0] > col:
                    peer["layout"]["pos_in_scrolling_layout"][0] += 1
            w["layout"]["pos_in_scrolling_layout"] = [col + 1, 1]
        elif name == "MoveColumnToIndex":
            w = next(w for w in self.windows if w["is_focused"])
            old, new = niri.position(w)[0], args["index"]
            for peer in self.windows:
                if peer["workspace_id"] != w["workspace_id"] or not niri.position(peer):
                    continue
                col = niri.position(peer)[0]
                if col == old:
                    col = new
                elif old < col <= new:
                    col -= 1
                elif new <= col < old:
                    col += 1
                peer["layout"]["pos_in_scrolling_layout"][0] = col
        else:
            raise AssertionError(name)


class MoveTests(unittest.TestCase):
    def move(self, model, wid, ws, before=None):
        with patch.object(niri, "get_windows", model.query), patch.object(niri, "get_workspaces", return_value=[{"id": 1}, {"id": 2}]), patch.object(niri, "action", model.action):
            niri.insert_window(wid, ws, before)

    def ids(self, model, ws=1):
        return [w["id"] for w in niri.ordered([w for w in model.windows if w["workspace_id"] == ws])]

    def test_reorder_both_directions_and_append(self):
        for wid, before, expected in [(3, 1, [3, 1, 2]), (1, 3, [2, 1, 3]), (1, None, [2, 3, 1])]:
            with self.subTest(wid=wid, before=before):
                model = ModelNiri([window(i, col=i, focused=i == 2) for i in range(1, 4)])
                self.move(model, wid, 1, before)
                self.assertEqual(self.ids(model), expected)
                self.assertEqual(next(w["id"] for w in model.windows if w["is_focused"]), 2)

    def test_cross_workspace_insert_and_empty(self):
        model = ModelNiri([window(1, col=1, focused=True), window(2, workspace=2, col=1), window(3, workspace=2, col=2)])
        self.move(model, 1, 2, 3)
        self.assertEqual(self.ids(model, 2), [2, 1, 3])
        self.move(model, 2, 1)
        self.assertEqual(self.ids(model, 1), [2])

    def test_two_window_column_moves_together_and_preserves_order(self):
        model = ModelNiri([window(1, col=1), window(2, col=1, row=2), window(3, col=2, focused=True)])
        self.move(model, 2, 2)
        self.assertEqual(self.ids(model, 2), [1, 2])
        self.assertEqual([niri.position(w) for w in model.windows[:2]], [[1, 1], [1, 2]])
        self.assertEqual(self.ids(model, 1), [3])
        self.assertEqual(next(w["id"] for w in model.windows if w["is_focused"]), 3)
        self.assertEqual([name for name, _args in model.calls if name == "MoveColumnToWorkspace"],
                         ["MoveColumnToWorkspace"])

    def test_two_window_column_reorders_as_one_unit(self):
        model = ModelNiri([window(1, col=1), window(2, col=1, row=2),
                           window(3, col=2, focused=True), window(4, col=3)])
        self.move(model, 2, 1, 4)
        self.assertEqual(self.ids(model), [3, 1, 2, 4])
        self.assertEqual([niri.position(w) for w in model.windows[:2]], [[2, 1], [2, 2]])
        self.assertEqual(next(w["id"] for w in model.windows if w["is_focused"]), 3)

    def test_larger_column_is_left_for_later_ui_design(self):
        windows = [window(1, col=1), window(2, col=1, row=2), window(3, col=1, row=3)]
        self.assertEqual([len(node.members) for node in dashboard_nodes(windows)], [1, 1, 1])

    def test_two_window_column_has_a_numeric_hint_for_each_member(self):
        data = demo_state()
        data["windows"][1]["layout"]["pos_in_scrolling_layout"] = [1, 2]
        order = DashboardController._hint_order(data)
        self.assertEqual(order[:3], [1, 2, 3])

    def test_floating_becomes_tiled(self):
        model = ModelNiri([window(1, floating=True), window(2, focused=True)])
        self.move(model, 1, 1, 2)
        self.assertEqual(self.ids(model), [1, 2])
        self.assertFalse(model.windows[0]["is_floating"])

    def test_stale_anchor_does_not_mutate(self):
        model = ModelNiri([window(1, focused=True)])
        with self.assertRaisesRegex(RuntimeError, "destination changed"):
            self.move(model, 1, 2, 99)
        self.assertEqual(model.calls, [])

    def test_focus_restored_after_failed_ordering(self):
        model = ModelNiri([window(1, col=1), window(2, col=2, focused=True)])
        original = model.action
        def fail(name, **args):
            if name == "MoveColumnToIndex":
                raise RuntimeError("compositor rejected ordering")
            return original(name, **args)
        with patch.object(niri, "get_windows", model.query), patch.object(niri, "get_workspaces", return_value=[{"id": 1}]), patch.object(niri, "action", fail):
            with self.assertRaisesRegex(RuntimeError, "rejected"):
                niri.insert_window(1, 1)
        self.assertTrue(model.windows[1]["is_focused"])

    def test_missing_session_explained(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "No Niri session"):
                niri.get_windows()


class GraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dashboard = Dashboard(demo=True, start_backend=False)
        self.dashboard.receive_state(demo_state())
        self.dashboard.controller.receive_health(True, "Demo")
        self.dashboard.show()
        self.app.processEvents()
        self.view = self.dashboard.view
        self.hints = []
        self.view.hint.connect(self.hints.append)
        self.moves = []
        self.focuses = []
        # Record gestures without submitting work to an unstarted worker.
        self.view.move_requested.disconnect()
        self.view.focus_requested.disconnect()
        self.view.move_requested.connect(lambda *args: self.moves.append(args))
        self.view.focus_requested.connect(self.focuses.append)

    def tearDown(self):
        self.dashboard.close()
        self.app.processEvents()

    def center(self, wid):
        node = self.view.nodes[wid]
        return self.view.mapFromScene(node.pos() + QPointF(54, 50))

    def drag(self, wid, endpoint, cancel=False):
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton, pos=self.center(wid))
        QTest.mouseMove(self.view.viewport(), endpoint, delay=10)
        if cancel:
            QTest.keyClick(self.view, Qt.Key.Key_Escape)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton, pos=endpoint)

    def test_click_and_small_jitter_focus(self):
        start = self.center(1)
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.view.viewport(), start + QPoint(1, 1))
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(1, 1))
        self.assertEqual(self.focuses, [1])
        self.assertEqual(self.moves, [])

    def test_touch_jitter_below_larger_threshold_remains_a_click(self):
        start = self.center(1)
        node = self.view.nodes[1]
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton,
                         pos=start)
        # QTest produces a mouse event, so mark this gesture as the touch path
        # after press to exercise its deliberately larger threshold.
        self.view.press_is_touch = True
        QTest.mouseMove(self.view.viewport(), start + QPoint(10, 8))
        self.assertFalse(self.view.dragging)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton,
                           pos=start + QPoint(10, 8))
        self.assertEqual(self.focuses, [1])
        self.assertEqual(self.moves, [])
        self.assertIsNotNone(node.feedback_animation)

    def test_click_has_press_and_release_feedback_without_layout_change(self):
        start = self.center(1)
        node = self.view.nodes[1]
        original_position = QPointF(node.pos())
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton,
                         pos=start)
        self.assertTrue(node.pressed_feedback)
        self.assertGreater(node.scale(), 1.0)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton,
                           pos=start)
        QTest.qWait(220)
        self.assertFalse(node.pressed_feedback)
        self.assertAlmostEqual(node.scale(), 1.0)
        self.assertEqual(node.pos(), original_position)

    def test_focused_window_draws_one_accent_route_over_neutral_pipes(self):
        state = demo_state()
        target = next(window for window in state["windows"] if window["workspace_id"] == 4 and window["layout"]["pos_in_scrolling_layout"][0] == 2)
        for window in state["windows"]:
            window["is_focused"] = window["id"] == target["id"]
        self.dashboard.receive_state(state)
        neutral = self.view.colors.neutral_pipe.lower()
        lines = [item for item in self.view.scene().items()
                 if isinstance(item, QGraphicsLineItem) and item.parentItem() is None]
        normal_lines = [item for item in lines if item.pen().widthF() in (2, 3)]
        route = self.view.focus_path
        self.assertEqual(route.accent.name(), self.view.colors.focused_route.lower())
        circle = self.view.nodes[target['id']].icon_circle_rect(self.view.settings)
        offset = QPointF(circle.left(), circle.center().y())
        self.assertEqual(route.endpoint,
                         self.view.nodes[target['id']].pos() +
                         offset)
        self.assertEqual(route.path.elementCount(), 3)
        self.assertEqual(len(route.junctions), 1)
        self.assertTrue(normal_lines)
        self.assertTrue(all(item.pen().color().name().lower() == neutral for item in normal_lines))
        del lines, normal_lines

        refreshed = demo_state()
        self.dashboard.receive_state(refreshed)
        circle = self.view.nodes[1].icon_circle_rect(self.view.settings)
        self.assertEqual(
            self.view.focus_path.endpoint,
            self.view.nodes[1].pos() +
            QPointF(circle.left(), circle.center().y()))

        second_workspace = demo_state()
        target = next(window for window in second_workspace["windows"] if window["workspace_id"] == 5)
        for window in second_workspace["windows"]:
            window["is_focused"] = window["id"] == target["id"]
        self.dashboard.receive_state(second_workspace)
        self.assertEqual(len(self.view.focus_path.junctions), 2)
        self.assertGreater(self.view.focus_path.junctions[-1].y(), 141)

    def test_pipes_meet_app_circle_edges_and_centers_at_every_ui_scale(self):
        for scale in (0.6, 1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                self.view.settings = replace(self.view.settings,
                                             global_scale=scale)
                self.view.render(demo_state())
                first, second = self.view.nodes[1], self.view.nodes[2]
                circle = first.icon_circle_rect(self.view.settings)
                first_left = first.pos().x() + circle.left()
                first_right = first.pos().x() + circle.right()
                second_left = second.pos().x() + circle.left()
                center_y = first.pos().y() + circle.center().y()
                lines = [item.line() for item in self.view.scene().items()
                         if isinstance(item, QGraphicsLineItem) and
                         item.parentItem() is None]

                def connected(x1, x2):
                    return any(
                        abs(line.x1() - x1) < .01 and
                        abs(line.x2() - x2) < .01 and
                        abs(line.y1() - center_y) < .01 and
                        abs(line.y2() - center_y) < .01
                        for line in lines)

                self.assertTrue(connected(first_right, second_left))
                self.assertTrue(any(
                    abs(line.x2() - first_left) < .01 and
                    abs(line.y1() - center_y) < .01 and
                    abs(line.y2() - center_y) < .01
                    for line in lines))
                self.assertEqual(self.view.focus_path.endpoint,
                                 QPointF(first_left, center_y))

    def test_right_click_closes_target_without_focusing(self):
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.RightButton, pos=self.center(2))
        self.assertEqual(self.dashboard.backend.commands.get_nowait(), ("close", 2))
        self.assertEqual(self.focuses, [])
        self.assertEqual(self.moves, [])

    def test_control_click_closes_target_without_focusing_or_moving(self):
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier, self.center(2))
        self.assertEqual(self.dashboard.backend.commands.get_nowait(), ("close", 2))
        self.assertEqual(self.focuses, [])
        self.assertEqual(self.moves, [])
        self.assertFalse(self.view.interacting)

    def test_double_control_click_queues_force_close_for_same_window(self):
        target = self.center(2)
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier, target)
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier, target)
        self.assertEqual(self.dashboard.backend.commands.get_nowait(), ("close", 2))
        self.assertEqual(self.dashboard.controller.pending_force_close[1], (2,))
        self.dashboard.controller.action_finished(True, "Close requested")
        self.assertEqual(self.dashboard.backend.commands.get_nowait(), ("force_close", 2))
        self.assertEqual(self.focuses, [])
        self.assertEqual(self.moves, [])

    def test_qt_double_click_event_also_requests_force_close(self):
        target = self.center(2)
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier, target)
        QTest.mouseDClick(self.view.viewport(), Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.ControlModifier, target)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.ControlModifier, target)
        self.assertEqual(self.dashboard.backend.commands.get_nowait(), ("close", 2))
        self.assertEqual(self.dashboard.controller.pending_force_close[1], (2,))

    def test_control_touch_drag_cancels_close_and_small_motion_still_closes(self):
        start = self.center(2)
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier, start)
        self.view.close_is_touch = True
        QTest.mouseMove(self.view.viewport(), start + QPoint(30, 15))
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.ControlModifier,
                           start + QPoint(30, 15))
        self.assertTrue(self.dashboard.backend.commands.empty())
        self.assertEqual(self.focuses, [])
        self.assertEqual(self.moves, [])
        self.assertFalse(self.view.interacting)

        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier, start)
        self.view.close_is_touch = True
        QTest.mouseMove(self.view.viewport(), start + QPoint(2, 2))
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.ControlModifier,
                           start + QPoint(2, 2))
        self.assertEqual(self.dashboard.backend.commands.get_nowait(), ("close", 2))

    def test_control_click_ignored_while_disconnected_or_busy(self):
        for connected, busy in [(False, False), (True, True)]:
            self.view.connected, self.view.busy = connected, busy
            QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.ControlModifier, self.center(2))
            self.assertTrue(self.dashboard.backend.commands.empty())
            self.assertEqual(self.focuses, [])

    def test_right_click_ignored_while_disconnected_or_busy(self):
        for connected, busy in [(False, False), (True, True)]:
            self.view.connected, self.view.busy = connected, busy
            QTest.mouseClick(self.view.viewport(), Qt.MouseButton.RightButton, pos=self.center(2))
            self.assertTrue(self.dashboard.backend.commands.empty())

    def test_close_uses_explicit_window_id(self):
        with patch.object(niri, "run_niri_ipc") as ipc:
            niri.close_window(42)
            ipc.assert_called_once_with({"Action": {"CloseWindow": {"id": 42}}})

    def test_demo_close_removes_only_target(self):
        backend = Backend(demo=True)
        before = {w["id"] for w in backend.data["windows"]}
        backend.demo_action("close", [2])
        self.assertEqual({w["id"] for w in backend.data["windows"]}, before - {2})

    def test_cross_monitor_drop_on_empty_workspace(self):
        row = next(r for r in self.view.rows if r["workspace"]["id"] == 8)
        self.drag(1, self.view.mapFromScene(QPointF(row["start"] + 50, row["y"] + 50)))
        self.assertEqual(self.moves, [(1, 8, None)])

    def test_drop_before_first_app(self):
        node = self.view.nodes[2]
        self.drag(3, self.view.mapFromScene(node.pos() + QPointF(5, 50)))
        self.assertEqual(self.moves, [(3, 1, 2)])

    def test_same_workspace_reorder_uses_collapsed_card_positions(self):
        row = next(r for r in self.view.rows if r["workspace"]["id"] == 1)
        endpoint = self.view.mapFromScene(QPointF(
            row["start"] + row["step"] + 5,
            row["y"] + row["node_height"] / 2))
        self.drag(1, endpoint)
        self.assertEqual(self.moves, [(1, 1, 3)])

    def test_escape_and_invalid_drop_do_nothing(self):
        self.drag(1, QPoint(10, 10), cancel=True)
        self.drag(1, QPoint(10, 10))
        self.assertEqual(self.moves, [])
        self.assertEqual(self.focuses, [])

    def test_stack_target_snaps_to_start_of_column(self):
        data = demo_state()
        data["windows"][1]["layout"]["pos_in_scrolling_layout"] = [1, 2]
        self.dashboard.receive_state(data)
        target = self.view.nodes[2]
        self.drag(3, self.view.mapFromScene(target.pos() + QPointF(5, 50)))
        self.assertEqual(self.moves, [(3, 1, 1)])

    def test_two_window_stack_is_one_node_with_half_clicks_and_whole_stack_drag(self):
        data = demo_state()
        data["windows"][1]["layout"]["pos_in_scrolling_layout"] = [1, 2]
        for member in data["windows"]:
            member["is_focused"] = member["id"] == 2
        self.dashboard.receive_state(data)
        stack = self.view.nodes[1]
        self.assertIs(stack, self.view.nodes[2])
        self.assertEqual([member["id"] for member in stack.dashboard_node.members], [1, 2])
        row = next(row for row in self.view.rows if row["workspace"]["id"] == 1)
        self.assertEqual(len(row["windows"]), 2)
        self.assertEqual(self.view.focus_path.endpoint.x(),
                         row["start"] + stack.icon_circle_rect(stack.settings).left())
        circle = stack.icon_circle_rect(stack.settings)
        for x_fraction, y_fraction, expected in ((0.70, 0.25, 1),
                                                 (0.30, 0.75, 2)):
            point = self.view.mapFromScene(
                stack.pos() + QPointF(circle.left() + circle.width() * x_fraction,
                                       circle.top() + circle.height() * y_fraction))
            QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual(self.focuses[-1], expected)
        row = next(row for row in self.view.rows if row["workspace"]["id"] == 8)
        self.drag(2, self.view.mapFromScene(QPointF(row["start"] + 50, row["y"] + 50)))
        self.assertEqual(self.moves, [(1, 8, None)])

    def test_stack_uses_full_size_icons_and_focus_dot_beside_member_name(self):
        data = demo_state()
        data["windows"][1]["layout"]["pos_in_scrolling_layout"] = [1, 2]
        dot_color = QColor(self.view.colors.focused_route)
        for focused_id, focused_index in ((1, 0), (2, 1)):
            for member in data["windows"]:
                member["is_focused"] = member["id"] == focused_id
            self.dashboard.receive_state(data)
            stack = self.view.nodes[1]
            image = QImage(stack.width, stack.height, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            with patch.object(stack.icons, "rendered", wraps=stack.icons.rendered) as rendered:
                stack.paint(painter, None)
            painter.end()
            circle = stack.icon_circle_rect(stack.settings)
            self.assertEqual([call.args[1] for call in rendered.call_args_list],
                             [stack.settings.scaled(stack.settings.icon_size)] * 2)
            for index in (0, 1):
                y = round(circle.bottom() + stack.settings.scaled(4 + 18 * index + 9))
                has_dot = any(image.pixelColor(x, y) == dot_color
                              for x in range(stack.settings.scaled(5), stack.width // 2))
                self.assertEqual(has_dot, index == focused_index)

    def test_stack_halves_keep_per_window_picker_and_close_actions(self):
        data = demo_state()
        data["windows"][1]["layout"]["pos_in_scrolling_layout"] = [1, 2]
        self.dashboard.controller.receive_state(data)
        stack = self.view.nodes[1]
        self.assertIs(stack, self.view.nodes[2])
        self.assertEqual(stack.hints, {1: "1", 2: "2"})
        circle = stack.icon_circle_rect(stack.settings)
        upper = self.view.mapFromScene(
            stack.pos() + QPointF(circle.left() + circle.width() * 0.70,
                                   circle.top() + circle.height() * 0.25))
        lower = self.view.mapFromScene(
            stack.pos() + QPointF(circle.left() + circle.width() * 0.30,
                                   circle.top() + circle.height() * 0.75))
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.MiddleButton, pos=upper)
        self.assertIsNotNone(self.dashboard.icon_picker)
        self.dashboard.icon_picker.choose("whatsapp")
        self.assertEqual(self.dashboard.controller.icon_overrides.get(1), "whatsapp")
        self.assertIsNone(self.dashboard.controller.icon_overrides.get(2))
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.MiddleButton, pos=lower)
        self.assertIsNotNone(self.dashboard.icon_picker)
        self.dashboard.icon_picker.choose("github")
        self.assertEqual(self.dashboard.controller.icon_overrides.get(1), "whatsapp")
        self.assertEqual(self.dashboard.controller.icon_overrides.get(2), "github")
        stack = self.view.nodes[1]
        self.assertEqual([member.get("icon_override") for member in stack.dashboard_node.members],
                         ["whatsapp", "github"])
        self.assertEqual([member["id"] for member in stack.dashboard_node.members], [1, 2])
        self.assertEqual(self.view.hint_targets["2"], 2)
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.MiddleButton, pos=lower)
        self.dashboard.icon_picker.reset_requested.emit()
        self.assertEqual(self.dashboard.controller.icon_overrides.get(1), "whatsapp")
        self.assertIsNone(self.dashboard.controller.icon_overrides.get(2))
        self.assertEqual([member.get("icon_override") for member in self.view.nodes[1].dashboard_node.members],
                         ["whatsapp", None])
        closes = []
        self.view.close_requested.disconnect()
        self.view.close_requested.connect(closes.append)
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.RightButton, pos=lower)
        self.assertEqual(closes, [2])

    def test_floating_target_inserts_at_tiled_end(self):
        data = demo_state()
        data["windows"][2]["is_floating"] = True
        data["windows"][2]["layout"]["pos_in_scrolling_layout"] = None
        self.dashboard.receive_state(data)
        target = self.view.nodes[3]
        self.drag(1, self.view.mapFromScene(target.pos() + QPointF(5, 50)))
        self.assertEqual(self.moves, [(1, 1, None)])

    def test_manual_zoom_survives_refresh(self):
        self.view.zoom(1.2)
        scale = self.view.transform().m11()
        data = demo_state()
        data["windows"][0]["title"] = "New title"
        self.dashboard.receive_state(data)
        self.assertAlmostEqual(self.view.transform().m11(), scale)

    def test_refresh_deferred_until_release(self):
        original = self.view.nodes[1]
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton, pos=self.center(1))
        data = demo_state()
        data["windows"][0]["title"] = "Changed while dragging"
        self.dashboard.receive_state(data)
        self.assertIs(self.view.nodes[1], original)
        QTest.keyClick(self.view, Qt.Key.Key_Escape)
        self.assertEqual(self.view.nodes[1].window["title"], "Changed while dragging")

    def test_empty_and_disconnected_outputs(self):
        self.dashboard.receive_state({"outputs": {}, "workspaces": [], "windows": []})
        self.assertEqual(self.view.rows, [])
        data = demo_state()
        data["outputs"] = {}
        self.dashboard.receive_state(data)
        self.assertEqual(len(self.view.rows), 7)

    def test_dedicated_hdmi_a5_output_is_hidden_but_dp5_remains_visible(self):
        data = demo_state()
        data["outputs"]["DP-5"] = {
            "model": "Normal display",
            "logical": {"x": 5760, "y": 0, "width": 1920, "height": 1080},
        }
        data["outputs"]["HDMI-A-5"] = {
            "model": "Dedicated dashboard",
            "logical": {"x": 7680, "y": 0, "width": 1920, "height": 1080},
        }
        data["workspaces"].append({
            "id": 99, "idx": 1, "output": "DP-5",
            "is_active": True, "is_focused": False,
        })
        data["windows"].append(window(99, workspace=99, focused=True))
        data["workspaces"].append({
            "id": 100, "idx": 1, "output": "HDMI-A-5",
            "is_active": True, "is_focused": True,
        })
        data["windows"].append(window(100, workspace=100))
        self.dashboard.receive_state(data)
        labels = [item.text() for item in self.view.scene().items()
                  if hasattr(item, "text")]
        self.assertTrue(any(label.endswith("/  DP-5") for label in labels))
        self.assertFalse(any(label.endswith("/  HDMI-A-5") for label in labels))
        self.assertIn(99, self.view.nodes)
        self.assertNotIn(100, self.view.nodes)
        workspace_ids = [row["workspace"]["id"] for row in self.view.rows]
        self.assertIn(99, workspace_ids)
        self.assertNotIn(100, workspace_ids)

    def test_manual_zoom_limit_does_not_change_default_fit(self):
        self.view.fit_graph()
        base_scale = self.view.transform().m11()
        scene_rect = QRectF(self.view.sceneRect())
        self.view.fit_graph()
        self.assertAlmostEqual(self.view.transform().m11(), base_scale)
        self.assertAlmostEqual(self.view.default_scale, base_scale)
        for _ in range(10):
            self.view.zoom(1.15)
        self.assertAlmostEqual(self.view.transform().m11(), base_scale * 1.5)
        self.assertEqual(self.view.sceneRect(), scene_rect)

    def test_full_viewport_fit_contains_dense_graph_without_chrome(self):
        data = demo_state()
        for wid in range(100, 130):
            data["windows"].append(window(wid, workspace=1, col=wid))
        data["workspaces"].extend(
            {"id": wid, "idx": wid - 90, "output": "DP-1",
             "is_active": False, "is_focused": False}
            for wid in range(101, 117))
        data["windows"].append(window(200, workspace=116, col=1))
        self.dashboard.receive_state(data)
        self.app.processEvents()
        self.assertLess(self.view.transform().m11(), 1.0)
        bounds = self.view.graph_bounds
        viewport = self.view.viewport().rect()
        for corner in (bounds.topLeft(), bounds.topRight(),
                       bounds.bottomLeft(), bounds.bottomRight()):
            point = self.view.mapFromScene(corner)
            self.assertTrue(viewport.adjusted(-1, -1, 1, 1).contains(point))
        self.assertEqual(self.dashboard.centralWidget().layout().contentsMargins().left(), 0)

    def test_unchanged_geometry_refresh_preserves_manual_zoom_and_pan(self):
        self.view.zoom(1.15)
        self.view.horizontalScrollBar().setValue(
            self.view.horizontalScrollBar().value() + 20)
        transform = QTransform(self.view.transform())
        center = self.view.mapToScene(self.view.viewport().rect().center())
        data = demo_state()
        data["windows"][0]["title"] = "Different title, same topology"
        self.dashboard.receive_state(data)
        self.app.processEvents()
        self.assertEqual(self.view.transform(), transform)
        new_center = self.view.mapToScene(self.view.viewport().rect().center())
        self.assertAlmostEqual(new_center.x(), center.x(), delta=2.0)
        self.assertAlmostEqual(new_center.y(), center.y(), delta=2.0)

    def test_global_ui_scale_changes_card_icon_and_graph_metrics(self):
        self.view.settings = replace(self.view.settings, global_scale=1.25)
        self.view.render(demo_state())
        self.assertEqual(self.view.nodes[1].width,
                         round(self.view.settings.node_width * 1.25))
        self.assertEqual(self.view.settings.scaled(self.view.settings.icon_size),
                         round(self.view.settings.icon_size * 1.25))
        expected_step = max(
            self.view.settings.layout_scaled(self.view.settings.workspace_step),
            self.view.settings.scaled(self.view.settings.node_width) +
            self.view.settings.layout_scaled(28))
        self.assertEqual(self.view.rows[0]["step"], expected_step)

    def test_empty_workspace_plus_is_centered_at_every_ui_scale(self):
        for scale in (0.6, 1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                self.view.settings = replace(
                    self.view.settings, global_scale=scale)
                self.view.render(demo_state())
                empty_row = next(row for row in self.view.rows
                                 if not row["windows"])
                plus = next(
                    item for item in self.view.scene().items()
                    if hasattr(item, "text") and item.text() == "+" and
                    empty_row["rect"].contains(item.sceneBoundingRect().center()))
                circle = next(
                    item for item in self.view.scene().items()
                    if isinstance(item, QGraphicsEllipseItem) and
                    item.sceneBoundingRect().contains(
                        plus.sceneBoundingRect().center()))
                self.assertAlmostEqual(
                    plus.sceneBoundingRect().center().x(),
                    circle.sceneBoundingRect().center().x(), delta=0.5)
                self.assertAlmostEqual(
                    plus.sceneBoundingRect().center().y(),
                    circle.sceneBoundingRect().center().y() -
                    self.view.settings.scaled_f(1.5), delta=0.5)

    def test_workspace_number_clears_junction_at_every_ui_scale(self):
        for scale in (0.6, 1.0, 1.5, 2.0):
            with self.subTest(scale=scale):
                self.view.settings = replace(
                    self.view.settings, global_scale=scale)
                self.view.render(demo_state())
                row = self.view.rows[0]
                number = min(
                    (item for item in self.view.scene().items()
                     if hasattr(item, "text") and item.text() == "01"),
                    key=lambda item: item.sceneBoundingRect().left())
                dot = min(
                    (item for item in self.view.scene().items()
                     if isinstance(item, QGraphicsEllipseItem) and
                     abs(item.sceneBoundingRect().center().y() -
                         row["y"] - self.view.nodes[1].icon_circle_rect(
                             self.view.settings).center().y()) < 2),
                    key=lambda item: item.sceneBoundingRect().left())
                self.assertLess(number.sceneBoundingRect().right(),
                                dot.sceneBoundingRect().left())

    def test_default_fit_is_idempotent_and_is_the_minimum_zoom(self):
        self.view.fit_graph()
        default = self.view.transform().m11()
        default_transform = QTransform(self.view.transform())
        self.view.fit_graph()
        self.assertEqual(self.view.transform(), default_transform)

        self.view.zoom(1 / 1.15)
        self.assertAlmostEqual(self.view.transform().m11(), default)
        self.assertTrue(self.view.auto_fit)

        self.view.zoom(1.15)
        self.assertGreater(self.view.transform().m11(), default)
        self.assertFalse(self.view.auto_fit)
        self.view.zoom(1 / 1.15)
        self.assertEqual(self.view.transform(), default_transform)
        self.assertTrue(self.view.auto_fit)

    def test_f_and_empty_double_click_restore_default_fit(self):
        self.view.fit_graph()
        default_transform = QTransform(self.view.transform())

        self.view.zoom(1.15)
        QTest.keyClick(self.view, Qt.Key.Key_F)
        self.assertEqual(self.view.transform(), default_transform)

        self.view.zoom(1.15)
        empty = self.view.mapFromScene(self.view.sceneRect().bottomRight())
        QTest.mouseDClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=empty)
        self.assertEqual(self.view.transform(), default_transform)

    def test_hides_only_trailing_empty_workspaces_and_keeps_one_on_idle_output(self):
        self.assertEqual([row["workspace"]["id"] for row in self.view.rows], [1, 2, 4, 5, 7, 8, 9])
        state = demo_state()
        state["windows"] = [window for window in state["windows"] if window["workspace_id"] != 1]
        self.dashboard.receive_state(state)
        self.assertIn(1, [row["workspace"]["id"] for row in self.view.rows])

    def test_drag_below_visible_rows_targets_real_hidden_trailing_workspace(self):
        target = next(target for target in self.view.trailing_targets if target["workspace"]["id"] == 3)
        self.view.pressed = self.view.nodes[1]
        self.view.origin = QPointF(self.view.pressed.pos())
        self.view.offset = QPointF()
        self.view.dragging = True
        self.view.update_drag(self.view.mapFromScene(target["rect"].center()))
        self.assertEqual(self.view.drop, (3, None))
        self.assertIsNotNone(self.view.marker)
        self.assertIn("create workspace", self.help_text())
        self.view.cancel_drag()
        self.assertIsNone(self.view.drop)
        self.assertIsNone(self.view.marker)

    def test_drop_on_hidden_trailing_workspace_restores_camera_then_moves(self):
        target = next(target for target in self.view.trailing_targets
                      if target["workspace"]["id"] == 3)
        self.view.fit_graph()
        initial_transform = QTransform(self.view.transform())
        initial_rect = QRectF(self.view.sceneRect())
        endpoint = self.view.mapFromScene(target["rect"].center())

        self.drag(1, endpoint)

        self.assertEqual(self.moves, [(1, 3, None)])
        self.assertEqual(self.view.transform(), initial_transform)
        self.assertEqual(self.view.sceneRect(), initial_rect)
        self.assertFalse(self.view.dragging)
        self.assertIsNone(self.view.marker)

    def test_dragging_to_hidden_workspace_target_keeps_view_transform_stable(self):
        target = next(target for target in self.view.trailing_targets if target["workspace"]["id"] == 3)
        self.view.fit_graph()
        initial_scale = self.view.transform().m11()
        initial_rect = QRectF(self.view.sceneRect())
        initial_center = self.view.mapToScene(self.view.viewport().rect().center())
        self.view.pressed = self.view.nodes[1]
        self.view.origin = QPointF(self.view.pressed.pos())
        self.view.offset = QPointF()
        self.view.dragging = True
        self.view.drag_scene_rect = QRectF(self.view.sceneRect())
        self.view.drag_transform = QTransform(self.view.transform())
        self.view.drag_center = QPointF(initial_center)
        self.view.drag_auto_fit = self.view.auto_fit

        target_point = self.view.mapFromScene(target["rect"].center())
        self.view.update_drag(target_point)
        stable_rect = QRectF(self.view.sceneRect())
        stable_center = self.view.mapToScene(self.view.viewport().rect().center())
        for _ in range(20):
            self.view.update_drag(target_point)
            self.assertEqual(self.view.sceneRect(), stable_rect)
            self.assertEqual(self.view.transform().m11(), initial_scale)
            center = self.view.mapToScene(self.view.viewport().rect().center())
            self.assertAlmostEqual(center.x(), stable_center.x(), delta=1.0)
            self.assertAlmostEqual(center.y(), stable_center.y(), delta=1.0)
        self.view.fit_graph()
        self.view.resize(self.view.width() - 17, self.view.height() - 13)
        self.app.processEvents()

        self.assertAlmostEqual(self.view.transform().m11(), initial_scale)
        self.assertIsNotNone(self.view.marker)
        self.assertEqual(
            self.view.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(
            self.view.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.cancel_drag()
        self.assertEqual(self.view.sceneRect(), initial_rect)
        self.assertAlmostEqual(self.view.transform().m11(), initial_scale)
        restored_center = self.view.mapToScene(
            self.view.viewport().rect().center())
        self.assertAlmostEqual(restored_center.x(), initial_center.x(), delta=2.0)
        self.assertAlmostEqual(restored_center.y(), initial_center.y(), delta=2.0)

    def help_text(self):
        return self.hints[-1] if self.hints else ""

    def test_workspace_labels_are_numbers_and_output_names_remain_visible(self):
        labels = [item.text() for item in self.view.scene().items()
                  if hasattr(item, "text")]
        self.assertIn("01  /  DP-1", labels)
        self.assertNotIn("Workspace 01", labels)
        self.assertNotIn("main", labels)

    def test_disconnected_cannot_issue_action(self):
        self.dashboard.receive_health(False, "Socket lost")
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=self.center(1))
        self.assertEqual(self.focuses, [])

    def test_worker_demo_move_roundtrip(self):
        backend = Backend(demo=True)
        states = []
        backend.state.connect(states.append)
        backend.start()
        try:
            backend.submit("move", 1, 8, None)
            for _ in range(40):
                QTest.qWait(25)
                if states and next(w for w in states[-1]["windows"] if w["id"] == 1)["workspace_id"] == 8:
                    break
            self.assertTrue(states)
            self.assertEqual(next(w for w in states[-1]["windows"] if w["id"] == 1)["workspace_id"], 8)
        finally:
            backend.stop()
            self.assertTrue(backend.wait(3000))

    def test_demo_move_keeps_two_window_stack_together(self):
        backend = Backend(demo=True)
        backend.data["windows"][1]["layout"]["pos_in_scrolling_layout"] = [1, 2]
        backend.demo_action("move", [2, 8, None])
        moved = [w for w in backend.data["windows"] if w["id"] in (1, 2)]
        self.assertEqual([w["workspace_id"] for w in moved], [8, 8])
        self.assertEqual([niri.position(w) for w in moved], [[1, 1], [1, 2]])

    def test_worker_recovers_after_connection_failure(self):
        backend = Backend()
        states, health = [], []
        backend.state.connect(states.append)
        backend.health.connect(lambda ok, message: health.append(ok))
        with patch("niridashboard.backend.niri.snapshot", side_effect=[RuntimeError("Disconnected"), demo_state(), demo_state()]):
            backend.start()
            try:
                for _ in range(60):
                    QTest.qWait(25)
                    if states and True in health:
                        break
                self.assertTrue(states)
                self.assertIn(False, health)
                self.assertIn(True, health)
            finally:
                backend.stop()
                self.assertTrue(backend.wait(3000))

    def test_live_action_refreshes_before_completion_even_on_action_failure(self):
        for failure in (None, RuntimeError("Window closed during move")):
            with self.subTest(failure=failure):
                backend = Backend()
                events = []
                backend.state.connect(lambda data: events.append(("state", data)))
                backend.finished_action.connect(lambda ok, message: events.append(("done", ok)))
                updated = demo_state()
                updated["windows"][0]["workspace_id"] = 8
                with patch("niridashboard.backend.niri.insert_window", side_effect=failure) as move, patch("niridashboard.backend.niri.snapshot", return_value=updated):
                    backend.submit("move", 1, 8, None)
                    backend.start()
                    try:
                        for _ in range(40):
                            QTest.qWait(25)
                            if any(event[0] == "done" for event in events):
                                break
                        move.assert_called_once_with(1, 8, None)
                        self.assertEqual(events[:2], [("state", updated), ("done", failure is None)])
                    finally:
                        backend.stop()
                        self.assertTrue(backend.wait(3000))

    def test_live_refresh_failure_disables_actions_without_reporting_success(self):
        backend = Backend()
        results, health = [], []
        backend.health.connect(lambda ok, message: health.append(ok))
        backend.finished_action.connect(lambda ok, message: results.append((ok, message)))
        with patch("niridashboard.backend.niri.focus_window") as focus, patch("niridashboard.backend.niri.snapshot", side_effect=RuntimeError("Socket lost")):
            backend.submit("focus", 1)
            backend.start()
            try:
                for _ in range(40):
                    QTest.qWait(25)
                    if results:
                        break
                focus.assert_called_once_with(1)
                self.assertIn(False, health)
                self.assertEqual(len(results), 1)
                self.assertFalse(results[0][0])
                self.assertIn("refresh failed", results[0][1])
            finally:
                backend.stop()
                self.assertTrue(backend.wait(3000))


if __name__ == "__main__":
    unittest.main()
