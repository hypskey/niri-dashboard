import copy
import os
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsLineItem
from niridashboard import niri
from niridashboard.backend import Backend, demo_state
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

    def test_extract_only_dragged_window_from_stack(self):
        model = ModelNiri([window(1, col=1), window(2, col=1, row=2), window(3, col=2, focused=True)])
        self.move(model, 2, 1, 1)
        self.assertEqual(self.ids(model), [2, 1, 3])
        self.assertEqual(niri.position(model.windows[0])[0], 2)

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
        self.assertEqual(route.endpoint, self.view.nodes[target['id']].pos() + QPointF(27, 27))
        self.assertEqual(route.path.elementCount(), 3)
        self.assertEqual(len(route.junctions), 1)
        self.assertTrue(normal_lines)
        self.assertTrue(all(item.pen().color().name().lower() == neutral for item in normal_lines))
        del lines, normal_lines

        refreshed = demo_state()
        self.dashboard.receive_state(refreshed)
        self.assertEqual(self.view.focus_path.endpoint, self.view.nodes[1].pos() + QPointF(27, 27))

        second_workspace = demo_state()
        target = next(window for window in second_workspace["windows"] if window["workspace_id"] == 5)
        for window in second_workspace["windows"]:
            window["is_focused"] = window["id"] == target["id"]
        self.dashboard.receive_state(second_workspace)
        self.assertEqual(len(self.view.focus_path.junctions), 2)
        self.assertGreater(self.view.focus_path.junctions[-1].y(), 141)

    def test_right_click_closes_target_without_focusing(self):
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.RightButton, pos=self.center(2))
        self.assertEqual(self.dashboard.backend.commands.get_nowait(), ("close", 2))
        self.assertEqual(self.focuses, [])
        self.assertEqual(self.moves, [])

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

    def test_dragging_to_hidden_workspace_target_keeps_view_transform_stable(self):
        target = next(target for target in self.view.trailing_targets if target["workspace"]["id"] == 3)
        self.view.fit_graph()
        initial_scale = self.view.transform().m11()
        initial_rect = QRectF(self.view.sceneRect())
        self.view.pressed = self.view.nodes[1]
        self.view.origin = QPointF(self.view.pressed.pos())
        self.view.offset = QPointF()
        self.view.dragging = True
        self.view.drag_scene_rect = QRectF(self.view.sceneRect())
        self.view.drag_transform = self.view.transform()

        self.view.update_drag(self.view.mapFromScene(target["rect"].center()))
        self.view.fit_graph()
        self.view.resize(self.view.width() - 17, self.view.height() - 13)
        self.app.processEvents()

        self.assertAlmostEqual(self.view.transform().m11(), initial_scale)
        self.assertIsNotNone(self.view.marker)
        self.view.cancel_drag()
        self.assertEqual(self.view.sceneRect(), initial_rect)
        self.assertAlmostEqual(self.view.transform().m11(), initial_scale)

    def help_text(self):
        return self.dashboard.help.text()

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
