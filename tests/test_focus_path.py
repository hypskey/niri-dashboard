from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QPainter
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
            path.write_text('[focus_path]\nglow=false\nflow=true\nflow_speed=2.5\n')
            settings = DashboardSettings.load(path)
            self.assertFalse(settings.focus_path_glow)
            self.assertFalse(hasattr(settings, 'focus_path_flow'))
            for value in ('1', '"false"'):
                path.write_text(f'[focus_path]\nglow={value}\n')
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
            circle = self.view.nodes[target['id']].icon_circle_rect(
                self.view.settings)
            self.assertEqual(route.endpoint,
                             self.view.nodes[target['id']].pos() +
                             QPointF(circle.left(), circle.center().y()))
            row = next(row for row in self.view.rows if row['workspace']['id'] == target['workspace_id'])
            self.assertEqual(route.root, QPointF(
                row['start'] - self.view.settings.layout_scaled(110) +
                self.view.settings.layout_scaled(20),
                self.view.settings.layout_scaled(67)))
            self.assertEqual(route.junctions[-1], QPointF(route.root.x(), route.endpoint.y()))
            self.assertEqual(route.path.elementCount(), 3)
        for window in state['windows']:
            window['is_focused'] = False
        self.view.render(state)
        self.assertIsNone(self.view.focus_path)
        self.assertFalse(any(isinstance(item, FocusPath) for item in self.view.scene().items()))

    def test_route_has_no_animation_items_or_timer(self):
        route = self.view.focus_path
        self.assertEqual(route.childItems(), [])
        self.assertFalse(hasattr(self.view, 'flow_timer'))
        self.assertFalse(hasattr(route, 'tracer_item'))

    @staticmethod
    def frame(glow=True):
        route = FocusPath(QPointF(20, 20), [QPointF(20, 120)], QPointF(220, 120),
                          '#308050', '#101010',
                          replace(DashboardSettings(), focus_path_glow=glow))
        image = QImage(240, 140, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        route.paint(painter, None)
        painter.end()
        return image

    def test_glow_switch_preserves_sharp_core(self):
        plain = self.frame(glow=False)
        glowing = self.frame(glow=True)
        self.assertEqual(plain.pixelColor(20, 60).alpha(), 255)
        self.assertEqual(plain.pixelColor(25, 60).alpha(), 0)
        self.assertGreater(glowing.pixelColor(25, 60).alpha(), 0)
