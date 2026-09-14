import os
import threading
import tempfile
import stat
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from niridashboard.backend import Backend, demo_state
from niridashboard.controller import DashboardController
from niridashboard.graph import GraphView, COLORS
from niridashboard.main import Dashboard
from niridashboard.overlay import OverlayWindow
from niridashboard import niri


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        controller = DashboardController(demo=True, start_backend=False)
        controller.connected = True
        controller.health_message = "Demo"
        jobs = []
        controller.task = lambda function, callback: jobs.append((function, callback))
        overlay = OverlayWindow(controller)
        return controller, overlay, jobs

    def tearDown(self):
        self.app.processEvents()

    def test_overlay_graph_paint_is_transparent_and_persistent_graph_stays_opaque(self):
        overlay = GraphView(None, translucent=True)
        persistent = GraphView(None)
        self.assertEqual(overlay.backgroundBrush().style(), Qt.BrushStyle.NoBrush)
        self.assertFalse(overlay.autoFillBackground())
        self.assertFalse(overlay.viewport().autoFillBackground())
        self.assertEqual(overlay.viewport().palette().color(overlay.viewport().palette().ColorRole.Window).alpha(), 0)

        image = QImage(160, 100, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        overlay.drawBackground(painter, QRectF(0, 0, 160, 100))
        painter.end()
        self.assertEqual(image.pixelColor(80, 50).alpha(), 0)

        persistent_image = QImage(160, 100, QImage.Format.Format_ARGB32_Premultiplied)
        persistent_image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(persistent_image)
        persistent.drawBackground(painter, QRectF(0, 0, 160, 100))
        painter.end()
        self.assertEqual(persistent_image.pixelColor(80, 50).alpha(), 255)

    def test_overlay_window_container_backgrounds_are_transparent(self):
        controller, overlay, jobs = self.make_window()
        root = overlay.centralWidget()
        for widget in (overlay, root, overlay.view, overlay.view.viewport()):
            self.assertFalse(widget.autoFillBackground())
            self.assertTrue(widget.testAttribute(Qt.WidgetAttribute.WA_NoSystemBackground))
        self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertNotIn("background:", overlay.error.styleSheet())
        self.assertEqual(overlay.windowTitle(), niri.OVERLAY_TITLE)
        overlay.shutdown()
        overlay.close()

    def test_persistent_dashboard_keeps_background_and_dashboard_scene(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        self.assertFalse(dashboard.view.translucent)
        self.assertEqual(dashboard.view.backgroundBrush().color().name(), "#f5f2ed")
        dashboard.close()

    def test_overlay_identity_filter_does_not_filter_other_niri_windows(self):
        controller = DashboardController(demo=True, start_backend=False)
        state = demo_state()
        state["windows"] += [
            {"id": 700, "app_id": niri.APP_ID, "title": niri.OVERLAY_TITLE, "pid": os.getpid()},
            {"id": 701, "app_id": niri.APP_ID, "title": "Niri Dashboard", "pid": os.getpid()},
            {"id": 702, "app_id": "other", "title": niri.OVERLAY_TITLE, "pid": os.getpid()},
        ]
        controller.receive_state(state)
        self.assertEqual([w["id"] for w in controller.raw["windows"][-3:]], [700, 701, 702])
        self.assertEqual([w["id"] for w in controller.latest["windows"][-2:]], [701, 702])

    def test_capture_context_uses_focused_output_and_logical_geometry(self):
        state = demo_state()
        state["workspaces"][3]["is_focused"] = True
        state["workspaces"][0]["is_focused"] = False
        state["windows"][0]["is_focused"] = False
        self.assertEqual(niri.overlay_context(state), {
            "window_id": None, "workspace_id": 4, "output": "DP-2",
            "logical": state["outputs"]["DP-2"]["logical"]})

    def test_rapid_open_cancel_and_reopen_do_not_leave_late_overlay(self):
        controller, overlay, jobs = self.make_window()
        overlay.toggle()
        self.assertEqual(overlay.phase, "capturing")
        overlay.toggle()
        self.assertEqual(overlay.phase, "closing")
        self.assertTrue(overlay.cancelled.is_set())
        # A second toggle during close records intent; it does not race a new mapping.
        overlay.toggle()
        self.assertTrue(overlay.desired)
        self.assertEqual(overlay.phase, "closing")
        old_capture, old_callback = jobs.pop(0)
        old_callback(True, niri.overlay_context(controller.backend.data))
        finish, finish_callback = jobs.pop(0)
        finish()
        finish_callback(True, None)
        self.assertEqual(overlay.phase, "capturing")
        self.assertTrue(overlay.desired)
        self.assertEqual(len(jobs), 1)
        overlay.dismiss()
        jobs.pop(0)[1](True, None)
        overlay.close()

    def test_escape_hides_visible_overlay_and_restores_original_focus(self):
        controller, overlay, jobs = self.make_window()
        overlay.toggle()
        capture, callback = jobs.pop(0)
        callback(True, niri.overlay_context(controller.backend.data))
        self.assertEqual(overlay.phase, "visible")
        overlay.view.escape_pressed.emit()
        self.assertEqual(overlay.phase, "closing")
        restore, callback = jobs.pop(0)
        restore()
        callback(True, None)
        self.assertEqual(overlay.phase, "hidden")
        self.assertFalse(overlay.isVisible())

    def test_focus_selection_dismisses_instead_of_restoring_previous(self):
        controller, overlay, jobs = self.make_window()
        selected = controller.backend.data["windows"][1]["id"]
        overlay.toggle()
        jobs.pop(0)[1](True, niri.overlay_context(controller.backend.data))
        overlay.command("focus", selected)
        self.assertEqual(overlay.phase, "closing")
        self.assertEqual(len(jobs), 1)
        job, callback = jobs.pop(0)
        job()
        self.assertFalse(overlay.isVisible())
        callback(True, None)

    def test_controller_uses_one_worker_for_both_presentations(self):
        controller = DashboardController(demo=True, start_backend=False)
        dashboard = Dashboard(demo=True, controller=controller)
        overlay = OverlayWindow(controller)
        self.assertIs(dashboard.backend, overlay.backend)
        self.assertIs(dashboard.controller.backend, overlay.controller.backend)
        self.assertIs(dashboard.view.icons, overlay.view.icons)
        self.assertFalse(controller.backend.isRunning())
        dashboard.close()
        overlay.close()

    def test_place_checks_float_rule_then_targets_only_overlay_id(self):
        state = demo_state()
        context = niri.overlay_context(state)
        overlay = {"id": 99, "app_id": niri.APP_ID, "title": niri.OVERLAY_TITLE,
                   "pid": os.getpid(), "workspace_id": context["workspace_id"], "is_floating": True}
        with patch.object(niri, "get_windows", return_value=[overlay]), patch.object(niri, "get_workspaces", return_value=state["workspaces"]), patch.object(niri, "action") as action:
            niri.place_overlay(99, context, threading.Event(), os.getpid())
        self.assertEqual([call.args[0] for call in action.call_args_list], ["SetWindowWidth", "SetWindowHeight", "MoveFloatingWindow", "FocusWindow"])
        self.assertTrue(all(call.kwargs.get("id") == 99 for call in action.call_args_list))

    def test_place_fails_safely_without_rule(self):
        state = demo_state()
        context = niri.overlay_context(state)
        overlay = {"id": 99, "app_id": niri.APP_ID, "title": niri.OVERLAY_TITLE,
                   "pid": os.getpid(), "workspace_id": context["workspace_id"], "is_floating": False}
        with patch.object(niri, "get_windows", return_value=[overlay]), patch.object(niri, "action") as action:
            with self.assertRaisesRegex(RuntimeError, "window rule"):
                niri.place_overlay(99, context, threading.Event(), os.getpid())
            action.assert_not_called()

    def test_demo_server_namespace_is_separate(self):
        from niridashboard.ipc import socket_path
        with tempfile.TemporaryDirectory() as runtime:
            os.chmod(runtime, 0o700)
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime, "NIRI_SOCKET": "/run/niri/demo.sock"}):
                self.assertNotEqual(socket_path(), socket_path(demo=True))


if __name__ == "__main__":
    unittest.main()
