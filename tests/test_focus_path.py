import copy
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from niridashboard.appearance import DashboardSettings
from niridashboard.backend import demo_state
from niridashboard.focus_path import FocusPath
from niridashboard.graph import GraphView
from niridashboard.icons import Icons


class FocusPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = GraphView(Icons())
        self.view.resize(1200, 700)
        self.view.render(demo_state())
        self.view.show()
        self.app.processEvents()

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    def test_config_options_defaults_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[focus_path]\nglow=false\nflow=false\nflow_speed=2.5\n')
            settings = DashboardSettings.load(path)
            self.assertFalse(settings.focus_path_glow)
            self.assertFalse(settings.focus_path_flow)
            self.assertEqual(settings.focus_path_flow_speed, 2.5)
            for value in ('true', 'nan', 'inf', '-1', '0', '6', '"fast"'):
                path.write_text(f'[focus_path]\nglow=1\nflow="false"\nflow_speed={value}\n')
                self.assertEqual(DashboardSettings.load(path), DashboardSettings())
            path.write_text('focus_path = "invalid"')
            self.assertEqual(DashboardSettings.load(path), DashboardSettings())

    def test_focus_changes_keep_one_correct_route_and_no_stale_items(self):
        state = demo_state()
        # Includes first/later rows and columns, multiple monitors and rapid changes.
        for target in state['windows'] * 3:
            for window in state['windows']:
                window['is_focused'] = window['id'] == target['id']
            self.view.render(state)
            route = self.view.focus_path
            self.assertEqual(sum(isinstance(item, FocusPath) for item in self.view.scene().items()), 1)
            self.assertEqual(route.endpoint, self.view.nodes[target['id']].pos() + QPointF(27, 27))
            row = next(row for row in self.view.rows if row['workspace']['id'] == target['workspace_id'])
            self.assertEqual(route.root, QPointF(row['start'] - 90, 67))
            self.assertEqual(route.junctions[-1], QPointF(route.root.x(), route.endpoint.y()))
            self.assertEqual(route.path.elementCount(), 3)
        for window in state['windows']:
            window['is_focused'] = False
        self.view.render(state)
        self.assertIsNone(self.view.focus_path)
        self.assertFalse(self.view.flow_timer.isActive())
        self.assertFalse(any(isinstance(item, FocusPath) for item in self.view.scene().items()))

    def test_timer_only_updates_paint_state_and_stops_while_hidden(self):
        route = self.view.focus_path
        transform, rect = self.view.transform(), self.view.sceneRect()
        data = copy.deepcopy(self.view.data)
        with patch.object(self.view, 'render') as render, patch.object(self.view, 'fit_graph') as fit:
            QTest.qWait(130)
            render.assert_not_called()
            fit.assert_not_called()
        self.assertGreater(route.distance, 0)
        self.assertIs(route, self.view.focus_path)
        self.assertEqual(self.view.data, data)
        self.assertEqual(self.view.transform(), transform)
        self.assertEqual(self.view.sceneRect(), rect)
        self.view.hide()
        distance = route.distance
        QTest.qWait(70)
        self.assertEqual(route.distance, distance)
        self.assertFalse(self.view.flow_timer.isActive())
        self.view.show()
        self.assertTrue(self.view.flow_timer.isActive())
        self.view.settings = replace(self.view.settings, focus_path_flow=False)
        self.view.render(data)
        self.assertFalse(self.view.flow_timer.isActive())
        self.assertIsNotNone(self.view.focus_path)

    def test_cached_static_route_still_displays_changing_tracer(self):
        self.view.flow_timer.stop()
        route = self.view.focus_path
        frames = []
        for distance in (0, 18):
            route.set_distance(distance)
            self.view.updateScene(list(route.dirty_rects))
            self.app.processEvents()
            frames.append(self.view.viewport().grab().toImage())
        self.assertNotEqual(*frames)

    @staticmethod
    def frame(glow=True, flow=True, distance=0):
        route = FocusPath(QPointF(20, 20), [QPointF(20, 120)], QPointF(220, 120),
                          '#308050', '#101010',
                          replace(DashboardSettings(), focus_path_glow=glow, focus_path_flow=flow), distance)
        image = QImage(240, 140, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        route.paint(painter, None)
        if route.tracer_item is not None:
            route.tracer_item.paint(painter, None)
        painter.end()
        return image

    def test_rasterized_tracer_moves_down_then_right_with_one_phase(self):
        before = self.frame(glow=False, distance=0)
        after = self.frame(glow=False, distance=8)
        # The first dash moves down the trunk by 8 pixels. Another dash, using
        # the SAME phase after the 100-pixel corner, moves right along the branch.
        self.assertGreater(before.pixelColor(20, 24).red(), after.pixelColor(20, 24).red())
        self.assertGreater(after.pixelColor(20, 40).red(), before.pixelColor(20, 40).red())
        self.assertGreater(before.pixelColor(68, 120).red(), after.pixelColor(68, 120).red())
        self.assertGreater(after.pixelColor(84, 120).red(), before.pixelColor(84, 120).red())

    def test_glow_and_flow_switches_preserve_sharp_core(self):
        plain = self.frame(glow=False, flow=False)
        glowing = self.frame(glow=True, flow=False)
        self.assertEqual(plain.pixelColor(20, 60).alpha(), 255)
        self.assertEqual(plain.pixelColor(25, 60).alpha(), 0)
        self.assertGreater(glowing.pixelColor(25, 60).alpha(), 0)
        self.assertEqual(glowing, self.frame(glow=True, flow=False, distance=20))
        self.assertNotEqual(glowing, self.frame(glow=True, flow=True))
