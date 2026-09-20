import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QIcon, QPixmap
from niridashboard.backend import demo_state
from niridashboard.icons import Icons, _ICON_ASSET_CACHE, is_browser_app, site_for_title
from niridashboard.main import Dashboard


class IconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_prefers_vector_then_largest_sufficient_raster(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            svg = root / "demo.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="30" fill="#ff0000"/></svg>')
            small, large = root / "small", root / "large"
            small.mkdir()
            large.mkdir()
            for size in (32, 128):
                image = QImage(size, size, QImage.Format.Format_ARGB32)
                image.fill(0xFF00FF00)
                image.save(str((small if size == 32 else large) / "raster.png"))
            icons = Icons()
            icons.theme_directories = [root, small, large]
            _ICON_ASSET_CACHE.clear()
            self.assertEqual(icons._theme_icon_path("demo", 38), str(svg))
            svg.unlink()
            _ICON_ASSET_CACHE.clear()
            self.assertEqual(icons._theme_icon_path("raster", 38), str(large / "raster.png"))

    def test_rendered_pixmap_cache_centers_wide_artwork_in_a_square_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            image = QImage(128, 64, QImage.Format.Format_ARGB32)
            image.fill(0xFF336699)
            icon_path = Path(directory) / "wide.png"
            image.save(str(icon_path))
            icons = Icons()
            icons.entries["wide-app"] = ("Wide App", str(icon_path))
            pixmap = icons.rendered("wide-app", 38)
            self.assertEqual((pixmap.width(), pixmap.height()), (152, 152))
            self.assertEqual(pixmap.devicePixelRatio(), 4)
            self.assertIs(icons.rendered("wide-app", 38), pixmap)

    def test_recognizes_requested_sites_from_tab_titles(self):
        cases = {
            "ChatGPT - New chat": "chatgpt",
            "Video title - YouTube": "youtube",
            "Google Calendar": "google_calendar",
            "Calendar - Week view": "google_calendar",
            "Inbox (3) - Gmail": "gmail",
            "Pull requests · GitHub": "github",
            "Popular on Reddit": "reddit",
        }
        for title, site in cases.items():
            with self.subTest(title=title):
                self.assertEqual(site_for_title(title), site)
        self.assertIsNone(site_for_title("A regular browser tab"))
        self.assertTrue(is_browser_app("org.mozilla.firefox"))
        self.assertTrue(is_browser_app("com.google.Chrome"))
        self.assertFalse(is_browser_app("org.gnome.zenity"))

    def test_site_icon_override_is_browser_only_and_falls_back_when_missing(self):
        icons = Icons()
        browser = QIcon(QPixmap(8, 8))
        youtube = QIcon(QPixmap(16, 16))
        icons.cache["org.mozilla.firefox"] = ("Firefox", browser)
        icons.site_icons["youtube"] = youtube
        self.assertEqual(icons.resolve_for_window("org.mozilla.firefox", "Song - YouTube")[1].cacheKey(), youtube.cacheKey())
        self.assertEqual(icons.resolve_for_window("org.mozilla.firefox", "Unrecognized")[1].cacheKey(), browser.cacheKey())
        self.assertEqual(icons.resolve_for_window("kitty", "GitHub discussion")[1].cacheKey(), icons.resolve("kitty")[1].cacheKey())
        icons.site_icons["reddit"] = None
        self.assertEqual(icons.resolve_for_window("org.mozilla.firefox", "Reddit")[1].cacheKey(), browser.cacheKey())

    def test_browser_site_icon_changes_when_window_title_changes(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        self.addCleanup(dashboard.close)
        icons = dashboard.controller.icons
        browser = QIcon(QPixmap(8, 8))
        youtube = QIcon(QPixmap(16, 16))
        github = QIcon(QPixmap(24, 24))
        icons.cache["org.mozilla.firefox"] = ("Firefox", browser)
        icons.site_icons.update(youtube=youtube, github=github)
        state = demo_state()
        window = state["windows"][0]
        window.update(app_id="org.mozilla.firefox", title="Study video - YouTube")
        dashboard.receive_state(state)
        first = dashboard.view.nodes[window["id"]].icon.cacheKey()
        changed = demo_state()
        changed_window = changed["windows"][0]
        changed_window.update(app_id="org.mozilla.firefox", title="Niri issue · GitHub")
        dashboard.receive_state(changed)
        second = dashboard.view.nodes[changed_window["id"]].icon.cacheKey()
        self.assertEqual(first, youtube.cacheKey())
        self.assertEqual(second, github.cacheKey())
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
