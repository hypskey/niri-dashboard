import os
from dataclasses import replace
import threading
import tempfile
import stat
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from niridashboard.backend import Backend, demo_state
from niridashboard.controller import DashboardController
from niridashboard.graph import GraphView, COLORS
from niridashboard.main import Dashboard
from niridashboard.overlay import OverlayWindow, overlay_size
from niridashboard import niri


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, opacity=1.0):
        controller = DashboardController(demo=True, start_backend=False)
        controller.appearance.settings = replace(controller.appearance.settings, overlay_opacity=opacity)
        controller.receive_state(controller.backend.data)
        controller.connected = True
        controller.health_message = "Demo"
        jobs = []
        controller.task = lambda function, callback: jobs.append((function, callback))
        overlay = OverlayWindow(controller)
        return controller, overlay, jobs

    def tearDown(self):
        self.app.processEvents()

    def test_overlay_background_is_opaque_and_tracks_dashboard_theme(self):
        controller, overlay, jobs = self.make_window()
        self.assertFalse(overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertFalse(overlay.view.translucent)
        for color in (controller.appearance.palette.dashboard_background, "#314159"):
            controller.appearance.palette = replace(controller.appearance.palette, dashboard_background=color)
            controller.appearance_changed.emit()
            for widget in (overlay, overlay.centralWidget(), overlay.view, overlay.view.viewport()):
                self.assertEqual(widget.palette().color(widget.palette().ColorRole.Window).name(), color)
                self.assertEqual(widget.palette().color(widget.palette().ColorRole.Window).alpha(), 255)
            image = QImage(160, 100, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            overlay.view.drawBackground(painter, QRectF(0, 0, 160, 100))
            painter.end()
            self.assertEqual(image.pixelColor(80, 50), QColor(color))
        self.assertEqual(overlay.windowTitle(), niri.OVERLAY_TITLE)
        overlay.shutdown()

    def test_overlay_opacity_paints_once_and_keeps_scene_items_opaque(self):
        for opacity in (0.0, 0.8):
            with self.subTest(opacity=opacity):
                controller = DashboardController(demo=True, start_backend=False)
                controller.appearance.settings = replace(controller.appearance.settings, overlay_opacity=opacity)
                overlay = OverlayWindow(controller)
                overlay.error.hide()
                overlay.resize(400, 300)
                overlay.centralWidget().layout().activate()
                overlay.view.scene().addRect(QRectF(0, 0, 80, 80), Qt.PenStyle.NoPen, QColor("red"))
                overlay.view.setSceneRect(-100, -100, 280, 280)
                overlay.view.fit_graph()
                self.assertEqual(overlay.windowOpacity(), 1.0)
                for color in ("#314159", "#182838"):
                    controller.appearance.palette = replace(controller.appearance.palette, dashboard_background=color)
                    controller.appearance_changed.emit()
                    image = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
                    image.fill(Qt.GlobalColor.transparent)
                    overlay.render(image)
                    self.assertAlmostEqual(image.pixelColor(2, 2).alpha(), round(opacity * 255), delta=1)
                    self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2), QColor("red"))
                    if opacity:
                        actual, expected = image.pixelColor(2, 2), QColor(color)
                        for channel in ("red", "green", "blue"):
                            self.assertAlmostEqual(getattr(actual, channel)(), getattr(expected, channel)(), delta=1)
                overlay.shutdown()
                overlay.deleteLater()

    def test_overlay_size_follows_graph_and_caps_large_graphs(self):
        logical = {"width": 1920, "height": 1080}
        self.assertEqual(overlay_size(QRectF(0, 0, 900, 450), logical), (908, 458))
        width, height = overlay_size(QRectF(0, 0, 3000, 1500), logical)
        self.assertLessEqual(width, round(1920 * .86))
        self.assertLessEqual(height, round(1080 * .86))
        self.assertAlmostEqual((width - 8) / (height - 8), 2, places=2)
        self.assertEqual(overlay_size(QRectF(), logical), (360, 220))
        width, height = overlay_size(QRectF(0, 0, 400, 1800), {"width": 800, "height": 1200})
        self.assertLessEqual(width, 688)
        self.assertLessEqual(height, 1032)

    def test_overlay_size_uses_settings_and_monitor_limits(self):
        from niridashboard.appearance import DashboardSettings
        settings = replace(DashboardSettings(), overlay_max_width_percent=60,
                           overlay_max_height_percent=50, overlay_min_width=500, overlay_min_height=300)
        logical = {"width": 1920, "height": 1080}
        self.assertEqual(overlay_size(QRectF(), logical, settings), (500, 300))
        width, height = overlay_size(QRectF(0, 0, 3000, 1800), logical, settings)
        self.assertLessEqual(width, 1152)
        self.assertLessEqual(height, 540)
        oversized = replace(settings, overlay_min_width=7000, overlay_min_height=4000)
        self.assertEqual(overlay_size(QRectF(), logical, oversized), (1152, 540))

    def test_open_sizes_cached_scene_before_mapping(self):
        controller, overlay, jobs = self.make_window()
        controller.appearance.settings = replace(controller.appearance.settings, overlay_max_width_percent=65,
                                                 overlay_max_height_percent=60)
        overlay.toggle()
        expected = overlay_size(overlay.view.sceneRect(), overlay.context["logical"], controller.appearance.settings)
        logical = overlay.context["logical"]
        expected = (min(round(expected[0] * 1.2), round(logical["width"] * .96)),
                    min(round(expected[1] * 1.2), round(logical["height"] * .96)))
        self.assertEqual(overlay.context["overlay_size"], expected)
        self.assertEqual((overlay.width(), overlay.height()), expected)
        overlay.dismiss()
        overlay.hide()

    def test_persistent_dashboard_keeps_background_and_dashboard_scene(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        self.assertFalse(dashboard.view.translucent)
        self.assertEqual(dashboard.view.backgroundBrush().color().name(), dashboard.controller.appearance.palette.dashboard_background)
        dashboard.close()

    def test_main_background_opacity_leaves_foreground_sharp(self):
        controller = DashboardController(demo=True, start_backend=False)
        controller.appearance.settings = replace(controller.appearance.settings, background_opacity=.5)
        dashboard = Dashboard(demo=True, start_backend=False, controller=controller)
        dashboard.resize(400, 300)
        dashboard.show()
        self.app.processEvents()
        image = QImage(dashboard.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        dashboard.render(image)
        self.assertTrue(dashboard.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertAlmostEqual(image.pixelColor(2, 2).alpha(), 128, delta=2)
        dashboard.close()

    def test_main_and_overlay_share_canonical_numeric_hints(self):
        controller = DashboardController(demo=True, start_backend=False)
        controller.receive_state(controller.backend.data)
        dashboard = Dashboard(demo=True, start_backend=False, controller=controller)
        overlay = OverlayWindow(controller)
        overlay.view.render(controller.latest)
        self.assertEqual(dashboard.view.hint_assignments.by_window,
                         overlay.view.hint_assignments.by_window)
        self.assertIs(dashboard.view.hint_assignments, controller.hint_assignments)
        self.assertIs(overlay.view.hint_assignments, controller.hint_assignments)
        overlay.shutdown()
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
        self.assertEqual(overlay.phase, "visible")
        overlay.toggle()
        self.assertEqual(overlay.phase, "closing")
        self.assertTrue(overlay.cancelled.is_set())
        overlay.toggle()
        self.assertTrue(overlay.desired)
        self.assertEqual(overlay.phase, "closing")
        finish, finish_callback = jobs.pop(0)
        finish()
        finish_callback(True, None)
        self.assertEqual(overlay.phase, "visible")
        self.assertTrue(overlay.desired)
        self.assertEqual(len(jobs), 0)
        overlay.dismiss()
        finish, finish_callback = jobs.pop(0)
        finish()
        finish_callback(True, None)
        overlay.close()

    def test_escape_hides_visible_overlay_and_restores_original_focus(self):
        controller, overlay, jobs = self.make_window()
        overlay.toggle()
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
        overlay.command("focus", selected)
        self.assertEqual(overlay.phase, "closing")
        self.assertEqual(len(jobs), 1)
        job, callback = jobs.pop(0)
        job()
        self.assertFalse(overlay.isVisible())
        callback(True, None)

    def test_numeric_hint_uses_mouse_focus_dismissal_path(self):
        controller, overlay, jobs = self.make_window()
        selected = controller.backend.data["windows"][1]["id"]
        overlay.toggle()
        hint = str(overlay.view.hint_assignments.by_window[selected])
        QTest.keyClicks(overlay.view, hint)
        self.assertEqual(overlay.phase, "closing")
        finish, callback = jobs.pop(0)
        finish()
        self.assertEqual(controller.backend.data["windows"][1]["is_focused"], True)
        callback(True, None)
        self.assertEqual(overlay.phase, "hidden")
        self.assertFalse(overlay.isVisible())

    def test_stack_members_have_separate_hints_and_lower_member_focuses(self):
        controller, overlay, jobs = self.make_window()
        controller.backend.data["windows"][1]["layout"]["pos_in_scrolling_layout"] = [1, 2]
        controller.receive_state(controller.backend.data)
        self.assertEqual([controller.hint_assignments.by_window[wid] for wid in (1, 2)],
                         [1, 2])
        overlay.toggle()
        self.assertIs(overlay.view.nodes[1], overlay.view.nodes[2])
        self.assertEqual(overlay.view.nodes[1].hints, {1: "1", 2: "2"})
        QTest.keyClicks(overlay.view, "2")
        self.assertEqual(overlay.phase, "closing")
        finish, callback = jobs.pop(0)
        finish()
        self.assertTrue(controller.backend.data["windows"][1]["is_focused"])
        callback(True, None)
        self.assertEqual(overlay.phase, "hidden")

    def test_keyboard_selection_works_at_every_opacity(self):
        for opacity in (1.0, 0.8, 0.0):
            for count, hint in ((3, "2"), (12, "10")):
                with self.subTest(opacity=opacity, count=count):
                    controller, overlay, jobs = self.make_window(opacity)
                    template = controller.backend.data["windows"][0]
                    controller.backend.data["windows"] = [dict(template, id=100 + i, is_focused=(i == 0))
                                                          for i in range(count)]
                    controller.receive_state(controller.backend.data)
                    overlay.toggle()
                    selected = overlay.view.hint_targets[hint]
                    QTest.keyClicks(overlay.view, hint[0])
                    if len(hint) > 1:
                        self.assertEqual(overlay.phase, "visible")
                        self.assertEqual(overlay.numeric.pending, "1")
                        QTest.keyClicks(overlay.view, hint[1:])
                    self.assertEqual(overlay.phase, "closing")
                    finish, callback = jobs.pop(0)
                    finish()
                    callback(True, None)
                    self.assertEqual(overlay.phase, "hidden")
                    focused = next(w for w in controller.backend.data["windows"] if w["is_focused"])
                    self.assertEqual(focused["id"], selected)
                    self.assertFalse(overlay.numeric.timer.isActive())
                    overlay.deleteLater()

    def test_toggle_cancels_pending_numeric_sequence(self):
        controller, overlay, jobs = self.make_window()
        overlay.toggle()
        overlay.numeric.update({1: 1, 10: 10})
        QTest.keyClicks(overlay.view, "1")
        self.assertTrue(overlay.numeric.timer.isActive())
        overlay.toggle()
        self.assertEqual(overlay.numeric.pending, "")
        self.assertFalse(overlay.numeric.timer.isActive())
        overlay.deleteLater()

    def test_persistent_view_does_not_handle_numeric_selection(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        pressed = []
        dashboard.view.numeric_pressed.connect(pressed.append)
        QTest.keyClicks(dashboard.view, "12")
        self.assertEqual(pressed, [])
        dashboard.close()

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

    def test_overlay_targets_dp3_but_retains_previous_window_for_restoration(self):
        state = demo_state()
        original = niri.overlay_context(state)
        state["outputs"]["DP-3"] = dict(state["outputs"][original["output"]])
        state["workspaces"].append({"id": 999, "idx": 1, "output": "DP-3",
                                    "is_active": True, "is_focused": False})
        context = niri.overlay_context(state, target_output="DP-3")
        self.assertEqual(context["output"], "DP-3")
        self.assertEqual(context["workspace_id"], 999)
        self.assertEqual(context["window_id"], original["window_id"])
        with self.assertRaisesRegex(RuntimeError, "not available"):
            niri.overlay_context(state, target_output="missing")

    def test_place_checks_float_rule_then_targets_only_overlay_id(self):
        state = demo_state()
        context = niri.overlay_context(state)
        context["overlay_size"] = (900, 500)
        overlay = {"id": 99, "app_id": niri.APP_ID, "title": niri.OVERLAY_TITLE,
                   "pid": os.getpid(), "workspace_id": context["workspace_id"], "is_floating": True}
        with patch.object(niri, "get_windows", return_value=[overlay]), patch.object(niri, "get_workspaces", return_value=state["workspaces"]), patch.object(niri, "action") as action:
            niri.place_overlay(99, context, threading.Event(), os.getpid())
        self.assertEqual([call.args[0] for call in action.call_args_list], ["SetWindowWidth", "SetWindowHeight", "MoveFloatingWindow", "FocusWindow"])
        self.assertTrue(all(call.kwargs.get("id") == 99 for call in action.call_args_list))

        self.assertEqual(action.call_args_list[0].kwargs["change"], {"SetFixed": 900})
        self.assertEqual(action.call_args_list[1].kwargs["change"], {"SetFixed": 500})
        placement = action.call_args_list[2].kwargs
        self.assertEqual(placement["x"], {"SetFixed": round((context["logical"]["width"] - 900) / 2)})
        self.assertEqual(placement["y"], {"SetFixed": round((context["logical"]["height"] - 500) / 2)})

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
