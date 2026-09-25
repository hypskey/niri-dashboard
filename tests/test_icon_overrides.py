import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScroller

from niridashboard.backend import demo_state
from niridashboard import icon_catalog
from niridashboard.controller import DashboardController
from niridashboard.icon_catalog import CatalogIcon, DEFAULT_CATALOG, IconCatalog
from niridashboard.icon_overrides import IconOverrides
from niridashboard.icon_usage import IconUsage
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

    def test_usage_ranks_only_first_seven_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "icon-usage.json"
            usage = IconUsage(path=path)
            ids = [entry.id for entry in DEFAULT_CATALOG.entries]
            for icon_id, count in zip(ids[:9], (1, 9, 2, 8, 3, 7, 4, 6, 5)):
                for _ in range(count):
                    usage.record(icon_id)
            ordered = [entry.id for entry in usage.favorites_first(DEFAULT_CATALOG.entries)]
            self.assertEqual(ordered[:7], [ids[index] for index in (1, 3, 5, 7, 8, 6, 4)])
            self.assertEqual(ordered[7:], [icon_id for icon_id in ids if icon_id not in ordered[:7]])
            self.assertEqual(IconUsage(path=path).counts, usage.counts)
            path.write_text('{"youtube": true, "github": -1, "gmail": 3}')
            self.assertEqual(IconUsage(path=path).counts, {"gmail": 3})

    def test_picker_selection_updates_favorites_without_changing_search(self):
        dashboard = self.make_dashboard()
        with tempfile.TemporaryDirectory() as directory:
            dashboard.controller.icon_usage = IconUsage(path=Path(directory) / "usage.json")
            dashboard.open_icon_picker(1, dashboard.mapToGlobal(QPoint(10, 10)))
            picker = dashboard.icon_picker
            picker.search.setText("nuke")
            self.assertEqual([entry.id for entry in picker.entries], ["nuke"])
            picker.choose("nuke")
            self.app.processEvents()
            dashboard.open_icon_picker(1, dashboard.mapToGlobal(QPoint(10, 10)))
            picker = dashboard.icon_picker
            self.assertEqual(picker.entries[0].id, "nuke")
            picker.search.setText("mail")
            self.assertEqual([entry.id for entry in picker.entries], ["proton-mail", "gmail"])
            picker.reset_requested.emit()
            self.assertEqual(dashboard.controller.icon_usage.counts, {"nuke": 1})

    def test_local_assets_are_discovered_without_replacing_curated_icons(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "My Logo.png").write_bytes(b"image")
            (root / "My Logo.svg").write_text("<svg/>")
            (root / "youtube.svg").write_text("<svg/>")
            catalog = IconCatalog((CatalogIcon("youtube", "YouTube", (), (), "youtube-rendered.png"),))
            with patch.object(icon_catalog, "ICON_ASSET_DIRECTORY", root):
                catalog.refresh_assets()
                self.assertEqual([entry.id for entry in catalog.entries], ["youtube", "my-logo"])
                self.assertEqual(catalog.get("my-logo").asset, "My Logo.svg")
                self.assertEqual([entry.id for entry in catalog.search("my")], ["my-logo"])
                (root / "My Logo.svg").unlink()
                catalog.refresh_assets()
                self.assertEqual(catalog.get("my-logo").asset, "My Logo.png")

    def test_update_button_adds_a_new_local_logo_without_restart(self):
        dashboard = self.make_dashboard()
        dashboard.open_icon_picker(1, dashboard.mapToGlobal(QPoint(10, 10)))
        picker = dashboard.icon_picker
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            try:
                with patch.object(icon_catalog, "ICON_ASSET_DIRECTORY", root):
                    (root / "my-project.svg").write_text(
                        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
                        '<circle cx="32" cy="32" r="28" fill="red"/></svg>')
                    QTest.mouseClick(picker.update_button, Qt.MouseButton.LeftButton)
                    picker.search.setText("my project")
                    self.assertEqual([entry.id for entry in picker.entries], ["my-project"])
                    self.assertFalse(dashboard.controller.icons.catalog_icon("my-project").isNull())
                    QTest.keyClick(picker.search, Qt.Key.Key_Return)
                    self.assertEqual(dashboard.controller.icon_overrides.get(1), "my-project")
            finally:
                DEFAULT_CATALOG.refresh_assets()

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
        assigned = dashboard.controller.icons.catalog_icon("nuke")
        self.assertEqual(dashboard.view.nodes[window_id].icon.cacheKey(), assigned.cacheKey())
        self.assertNotEqual(original, assigned.cacheKey())

    def test_alt_click_opens_same_picker_without_focusing_or_dragging(self):
        dashboard = self.make_dashboard()
        focused = []
        moved = []
        dashboard.view.focus_requested.connect(focused.append)
        dashboard.view.move_requested.connect(lambda *args: moved.append(args))
        QTest.mouseClick(dashboard.view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.AltModifier,
                         self.center(dashboard, 1))
        picker = dashboard.icon_picker
        self.assertIsNotNone(picker)
        self.assertTrue(picker.search.hasFocus())
        self.assertFalse(dashboard.view.dragging)
        self.assertEqual(focused, [])
        self.assertEqual(moved, [])
        QTest.keyClicks(picker.search, "youtube")
        QTest.keyClick(picker.search, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(dashboard.controller.icon_overrides.get(1), "youtube")

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
                    "codex-pet-07", "codex-pet-08", "nuke")
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
        self.assertEqual(DEFAULT_CATALOG.get("nuke").asset, "foundry-nuke.png")
        self.assertEqual([entry.id for entry in DEFAULT_CATALOG.search("foundry")], ["nuke"])

    def test_picker_stays_compact_and_scrolls_a_large_catalog(self):
        dashboard = self.make_dashboard()
        QTest.mouseClick(dashboard.view.viewport(), Qt.MouseButton.MiddleButton,
                         pos=self.center(dashboard, 1))
        picker = dashboard.icon_picker
        self.assertTrue(picker.preview_timer.isActive())
        for _ in range(40):
            if not picker.preview_timer.isActive():
                break
            QTest.qWait(25)
        self.assertFalse(picker.preview_queue)
        self.assertEqual(
            (picker.width(), picker.height()),
            (picker.settings.scaled(320), picker.settings.scaled(300)))
        self.assertTrue(picker.results.verticalScrollBar().maximum() > 0)
        self.assertGreater(
            QScroller.grabbedGesture(picker.results.viewport()).value, 0)
        self.assertTrue(picker.results.viewport().testAttribute(
            Qt.WidgetAttribute.WA_AcceptTouchEvents))
        self.assertGreaterEqual(picker.grid.itemAt(0).widget().height(),
                                picker.settings.scaled(70))
        wheel = QWheelEvent(
            QPointF(40, 40), QPointF(40, 40), QPoint(0, 0),
            QPoint(0, -120), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate,
            False)
        self.app.sendEvent(picker.results.viewport(), wheel)
        self.assertGreater(picker.results.verticalScrollBar().value(), 0)
        picker.results.verticalScrollBar().setValue(0)
        scroller = QScroller.scroller(picker.results.viewport())
        scroller.handleInput(QScroller.Input.InputPress, QPointF(100, 160))
        QTest.qWait(30)
        scroller.handleInput(QScroller.Input.InputMove, QPointF(100, 105))
        QTest.qWait(30)
        self.assertGreater(picker.results.verticalScrollBar().value(), 0)
        scroller.handleInput(QScroller.Input.InputRelease, QPointF(100, 105))
        QTest.keyClick(picker.search, Qt.Key.Key_Down)
        self.assertEqual(picker.current, 3)
        self.assertTrue(picker.search.hasFocus())

    def test_dragging_from_an_icon_scrolls_without_highlight_then_double_tap_selects(self):
        dashboard = self.make_dashboard()
        QTest.mouseClick(dashboard.view.viewport(), Qt.MouseButton.MiddleButton,
                         pos=self.center(dashboard, 1))
        picker = dashboard.icon_picker
        first = picker.grid.itemAt(0).widget()
        QTest.mousePress(first, Qt.MouseButton.LeftButton,
                         pos=QPoint(45, 55))
        QTest.mouseMove(first, QPoint(45, 5))
        QTest.mouseRelease(first, Qt.MouseButton.LeftButton,
                           pos=QPoint(45, 5))
        self.assertGreater(picker.results.verticalScrollBar().value(), 0)
        self.assertIsNone(picker.current)
        self.assertIsNone(dashboard.controller.icon_overrides.get(1))
        self.assertTrue(picker.isVisible())
        picker.results.verticalScrollBar().setValue(0)
        QTest.mouseClick(first, Qt.MouseButton.LeftButton,
                         pos=QPoint(45, 35))
        self.assertIsNone(dashboard.controller.icon_overrides.get(1))
        self.assertEqual(picker.current, 0)
        QTest.mouseClick(first, Qt.MouseButton.LeftButton,
                         pos=QPoint(45, 35))
        self.assertEqual(dashboard.controller.icon_overrides.get(1),
                         picker.catalog.search("")[0].id)

    def test_tapping_different_icons_does_not_assign_until_same_icon_is_tapped_twice(self):
        dashboard = self.make_dashboard()
        QTest.mouseClick(dashboard.view.viewport(), Qt.MouseButton.MiddleButton,
                         pos=self.center(dashboard, 1))
        picker = dashboard.icon_picker
        first = picker.grid.itemAt(0).widget()
        second = picker.grid.itemAt(1).widget()
        QTest.mouseClick(first, Qt.MouseButton.LeftButton)
        QTest.mouseClick(second, Qt.MouseButton.LeftButton)
        self.assertIsNone(dashboard.controller.icon_overrides.get(1))
        self.assertEqual(picker.current, 1)
        QTest.mouseClick(second, Qt.MouseButton.LeftButton)
        self.assertEqual(dashboard.controller.icon_overrides.get(1), picker.entries[1].id)

    def test_fast_icon_drag_keeps_scrolling_briefly_after_release(self):
        dashboard = self.make_dashboard()
        QTest.mouseClick(dashboard.view.viewport(), Qt.MouseButton.MiddleButton,
                         pos=self.center(dashboard, 1))
        picker = dashboard.icon_picker
        first = picker.grid.itemAt(0).widget()
        QTest.mousePress(first, Qt.MouseButton.LeftButton, pos=QPoint(45, 65))
        QTest.qWait(30)
        QTest.mouseMove(first, QPoint(45, 10))
        QTest.mouseRelease(first, Qt.MouseButton.LeftButton, pos=QPoint(45, 10))
        released_at = picker.results.verticalScrollBar().value()
        self.assertGreater(released_at, 0)
        self.assertIsNone(picker.current)
        QTest.qWait(180)
        self.assertGreater(picker.results.verticalScrollBar().value(), released_at)
        self.assertIsNone(dashboard.controller.icon_overrides.get(1))


if __name__ == "__main__":
    unittest.main()
