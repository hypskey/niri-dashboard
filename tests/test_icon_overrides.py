import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from niridashboard.backend import demo_state
from niridashboard.controller import DashboardController
from niridashboard.icon_catalog import DEFAULT_CATALOG
from niridashboard.icon_overrides import IconOverrides
from niridashboard.main import Dashboard


class IconOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_session_file_loads_resets_and_prunes_by_window_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "icon-overrides.json"
            overrides = IconOverrides(path=path)
            changes = []
            overrides.changed.connect(lambda: changes.append(dict(overrides.values)))
            overrides.set(184, "whatsapp")
            overrides.set(207, "youtube")
            self.assertEqual(json.loads(path.read_text()), {"184": "whatsapp", "207": "youtube"})
            reloaded = IconOverrides(path=path)
            self.assertEqual(reloaded.get(184), "whatsapp")
            self.assertEqual(reloaded.get(207), "youtube")
            reloaded.prune({207})
            self.assertIsNone(reloaded.get(184))
            self.assertEqual(reloaded.get(207), "youtube")
            reloaded.reset(207)
            self.assertEqual(json.loads(path.read_text()), {})
            self.assertEqual(len(changes), 2)

    def test_bad_or_unwritable_session_file_never_prevents_current_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "icon-overrides.json"
            path.write_text("not json")
            overrides = IconOverrides(path=path)
            self.assertEqual(overrides.values, {})
            overrides.path = Path(directory) / "missing" / "icon-overrides.json"
            overrides.set(4, "github")
            self.assertEqual(overrides.get(4), "github")

    def make_dashboard(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        dashboard.controller.receive_state(demo_state())
        dashboard.controller.receive_health(True, "Demo")
        dashboard.show()
        self.app.processEvents()
        self.addCleanup(dashboard.close)
        return dashboard

    def center(self, dashboard, window_id):
        node = dashboard.view.nodes[window_id]
        return dashboard.view.mapFromScene(node.pos() + node.boundingRect().center())

    def test_middle_click_opens_searchable_picker_and_enter_assigns(self):
        dashboard = self.make_dashboard()
        window_id = 1
        original = dashboard.view.nodes[window_id].icon.cacheKey()
        assigned = QIcon(QPixmap(32, 32))
        dashboard.controller.icons.catalog_icons["nuke"] = assigned

        QTest.mouseClick(dashboard.view.viewport(), Qt.MouseButton.MiddleButton,
                         pos=self.center(dashboard, window_id))
        picker = dashboard.icon_picker
        self.assertIsNotNone(picker)
        self.assertTrue(picker.search.hasFocus())
        QTest.keyClicks(picker.search, "nuke")
        self.assertEqual([entry.id for entry in picker.entries], ["nuke"])
        QTest.keyClick(picker.search, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(dashboard.controller.icon_overrides.get(window_id), "nuke")
        self.assertEqual(dashboard.view.nodes[window_id].icon.cacheKey(), assigned.cacheKey())
        self.assertNotEqual(original, assigned.cacheKey())

    def test_picker_navigation_reset_and_blank_middle_pan(self):
        dashboard = self.make_dashboard()
        window_id = 2
        dashboard.controller.icon_overrides.set(window_id, "github")
        QTest.mouseClick(dashboard.view.viewport(), Qt.MouseButton.MiddleButton,
                         pos=self.center(dashboard, window_id))
        picker = dashboard.icon_picker
        QTest.keyClick(picker.search, Qt.Key.Key_Down)
        self.assertEqual(picker.current, 3)
        picker.reset_requested.emit()
        self.app.processEvents()
        self.assertIsNone(dashboard.controller.icon_overrides.get(window_id))
        QTest.mousePress(dashboard.view.viewport(), Qt.MouseButton.MiddleButton, pos=dashboard.view.viewport().rect().bottomRight())
        self.assertTrue(dashboard.view.panning)
        QTest.mouseRelease(dashboard.view.viewport(), Qt.MouseButton.MiddleButton)
        self.assertFalse(dashboard.view.panning)

    def test_catalog_search_has_requested_entries(self):
        self.assertEqual(DEFAULT_CATALOG.search("chat")[0].id, "whatsapp")
        required = ("whatsapp", "youtube", "chatgpt", "proton-mail", "reddit", "github", "gmail",
                    "google-calendar", "google-chat", "google-drive", "google-docs", "google-sheets",
                    "google-slides", "google-maps", "google-meet", "google-keep", "codex-pet-01",
                    "codex-pet-02", "codex-pet-03", "codex-pet-04", "codex-pet-05", "codex-pet-06",
                    "codex-pet-07", "codex-pet-08")
        for icon_id in required:
            entry = DEFAULT_CATALOG.get(icon_id)
            self.assertIsNotNone(entry)
            self.assertTrue(entry.asset_path.is_file(), icon_id)
        self.assertEqual({entry.id for entry in DEFAULT_CATALOG.search("mail")}, {"gmail", "proton-mail"})
        self.assertTrue(all("google" in entry.id or entry.id == "gmail"
                            for entry in DEFAULT_CATALOG.search("google")))
        self.assertEqual(len(DEFAULT_CATALOG.search("worker")), 8)
        self.assertEqual([entry.id for entry in DEFAULT_CATALOG.search("you")], ["youtube"])
        self.assertEqual([entry.id for entry in DEFAULT_CATALOG.search("proton")], ["proton-mail"])
        self.assertEqual([entry.id for entry in DEFAULT_CATALOG.search("what")], ["whatsapp"])
        self.assertTrue({"whatsapp", "chatgpt"}.issubset(
            {entry.id for entry in DEFAULT_CATALOG.search("chat")}))
        self.assertEqual(DEFAULT_CATALOG.get("whatsapp").asset, "whatsapp.svg")
        self.assertEqual(DEFAULT_CATALOG.get("youtube").asset, "youtube-rendered.png")
        self.assertEqual(DEFAULT_CATALOG.get("chatgpt").asset, "openai.svg")

    def test_picker_stays_compact_and_scrolls_a_large_catalog(self):
        dashboard = self.make_dashboard()
        QTest.mouseClick(dashboard.view.viewport(), Qt.MouseButton.MiddleButton,
                         pos=self.center(dashboard, 1))
        picker = dashboard.icon_picker
        self.assertEqual((picker.width(), picker.height()), (320, 300))
        self.assertTrue(picker.results.verticalScrollBar().maximum() > 0)
        QTest.keyClick(picker.search, Qt.Key.Key_Down)
        self.assertEqual(picker.current, 3)
        self.assertTrue(picker.search.hasFocus())


if __name__ == "__main__":
    unittest.main()
