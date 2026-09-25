import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from niridashboard.appearance import DEFAULT_PALETTE, DashboardSettings
from niridashboard.backend import demo_state
from niridashboard.main import Dashboard
from niridashboard.controller import DashboardController
from niridashboard.system_status import (
    LinuxSystemMetrics, SystemSnapshot, SystemStatusWidget,
)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeMetrics:
    def __init__(self, snapshot):
        self.value = snapshot

    def snapshot(self):
        return self.value


class SystemStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_linux_metrics_use_proc_deltas_memavailable_and_cpu_sensor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / "proc"
            sys = root / "sys"
            write(proc / "stat", "cpu 20 0 20 60 0 0 0 0\n")
            write(proc / "meminfo",
                  "MemTotal:       16000 kB\nMemAvailable:    4000 kB\n")
            hwmon = sys / "class/hwmon/hwmon1"
            write(hwmon / "name", "coretemp\n")
            write(hwmon / "temp1_label", "Package id 0\n")
            write(hwmon / "temp1_input", "55000\n")

            metrics = LinuxSystemMetrics(proc, sys)
            first = metrics.snapshot()
            self.assertIsNone(first.cpu_percent)
            self.assertEqual(first.ram_percent, 75)
            self.assertEqual(first.cpu_temperature, 55)

            write(proc / "stat", "cpu 50 0 30 100 0 0 0 0\n")
            second = metrics.snapshot()
            self.assertEqual(second.cpu_percent, 50)

    def test_missing_or_invalid_temperature_is_graceful(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / "proc"
            write(proc / "stat", "cpu 1 0 1 8\n")
            write(proc / "meminfo", "MemTotal: 100 kB\nMemAvailable: 50 kB\n")
            metrics = LinuxSystemMetrics(proc, root / "sys")
            snapshot = metrics.snapshot()
            self.assertIsNone(snapshot.cpu_temperature)
            self.assertEqual(snapshot.ram_percent, 50)

    def test_widget_formats_clock_metrics_and_uses_low_frequency_timers(self):
        metrics = FakeMetrics(SystemSnapshot(42.4, 63.2, None))
        widget = SystemStatusWidget(
            DEFAULT_PALETTE, DashboardSettings(), metrics,
            clock=lambda: datetime(2026, 9, 22, 14, 5, 9))
        self.assertEqual(widget.time_text, "14:05")
        self.assertEqual(widget.seconds_text, "09")
        self.assertEqual(widget.date_text, "TUE · 22 SEP 2026")
        self.assertEqual(widget.snapshot, SystemSnapshot(42.4, 63.2, None))
        self.assertEqual(widget.clock_timer.interval(), 1000)
        self.assertEqual(widget.metrics_timer.interval(), 2000)
        self.assertTrue(widget.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents))

        widget.show()
        self.app.processEvents()
        image = widget.grab().toImage()
        visible = sum(
            image.pixelColor(x, y).alpha() > 0
            for y in range(image.height())
            for x in range(image.width())
        )
        self.assertGreater(visible, 0)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        widget.clock_timer.stop()
        widget.metrics_timer.stop()
        widget.close()

    def test_hud_is_viewport_overlay_and_does_not_affect_graph(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        dashboard.resize(1440, 900)
        dashboard.receive_state(demo_state())
        dashboard.receive_health(True, "Connected to Niri")
        dashboard.show()
        self.app.processEvents()

        hud = dashboard.system_status
        viewport = dashboard.view.viewport()
        self.assertIs(hud.parent(), viewport)
        self.assertNotIn(hud, dashboard.view.scene().items())
        margin = hud.settings.scaled(hud.ANCHOR_MARGIN)
        self.assertEqual(hud.pos().x(), margin)
        self.assertEqual(hud.pos().y(),
                         viewport.height() - hud.height() - margin)

        dashboard.view.zoom(1.15)
        state = demo_state()
        state["windows"][0]["title"] = "HUD survives graph rebuild"
        dashboard.receive_state(state)
        self.app.processEvents()
        self.assertTrue(hud.isVisible())
        self.assertEqual(hud.pos().x(), margin)
        self.assertEqual(hud.pos().y(),
                         viewport.height() - hud.height() - margin)
        self.assertGreater(dashboard.view.pet_item.dock_anchor.x(),
                           dashboard.view.mapToScene(
                               viewport.rect().center()).x())

        hud.clock_timer.stop()
        hud.metrics_timer.stop()
        dashboard.close()

    def test_hiding_hud_keeps_identical_graph_bounds_and_scale(self):
        views = []
        for show_hud in (True, False):
            controller = DashboardController(demo=True, start_backend=False)
            controller.appearance.settings = replace(
                controller.appearance.settings, show_hud=show_hud)
            dashboard = Dashboard(controller=controller)
            dashboard.resize(1440, 900)
            dashboard.show()
            dashboard.receive_state(demo_state())
            self.app.processEvents()
            self.assertEqual(dashboard.system_status is not None, show_hud)
            views.append(dashboard)
        self.assertEqual(views[0].view.graph_bounds, views[1].view.graph_bounds)
        self.assertEqual(views[0].view.sceneRect(), views[1].view.sceneRect())
        self.assertEqual(views[0].view.transform(), views[1].view.transform())
        self.assertEqual(views[0].view.mapFromScene(views[0].view.nodes[1].pos()),
                         views[1].view.mapFromScene(views[1].view.nodes[1].pos()))
        for dashboard in views:
            dashboard.close()

    def test_hiding_pet_keeps_identical_graph_bounds_and_scale(self):
        views = []
        for show_pet in (True, False):
            controller = DashboardController(demo=True, start_backend=False)
            controller.appearance.settings = replace(
                controller.appearance.settings, show_pet=show_pet)
            dashboard = Dashboard(controller=controller)
            dashboard.resize(1440, 900)
            dashboard.show()
            dashboard.receive_state(demo_state())
            self.app.processEvents()
            self.assertEqual(dashboard.view.pet_item is not None, show_pet)
            views.append(dashboard)
        self.assertEqual(views[0].view.graph_bounds, views[1].view.graph_bounds)
        self.assertEqual(views[0].view.sceneRect(), views[1].view.sceneRect())
        self.assertEqual(views[0].view.transform(), views[1].view.transform())
        self.assertEqual(views[0].view.mapFromScene(views[0].view.nodes[1].pos()),
                         views[1].view.mapFromScene(views[1].view.nodes[1].pos()))
        for dashboard in views:
            dashboard.close()


if __name__ == "__main__":
    unittest.main()
