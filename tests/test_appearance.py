import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from niridashboard.appearance import (
    AppearanceProvider, DashboardSettings, DEFAULT_PALETTE, parse_noctalia_css,
)


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_noctalia_aliases_map_to_semantic_roles_and_stay_opaque(self):
        palette = parse_noctalia_css("""
            @define-color accent_bg_color #abcdef;
            @define-color accent_fg_color #101112;
            @define-color window_bg_color #101010;
            @define-color window_fg_color #f0f0f0;
            @define-color theme_unfocused_fg_color #dddddd;
            @define-color theme_selected_bg_color @accent_bg_color;
            @define-color theme_selected_fg_color @accent_fg_color;
            @define-color card_bg_color #141414;
            @define-color success_color #00ff00;
        """)
        self.assertEqual(palette.dashboard_background, "#101010")
        self.assertEqual(palette.primary_text, "#f0f0f0")
        self.assertEqual(palette.focused_background, "#abcdef")
        self.assertEqual(palette.node_background, "#141414")
        self.assertEqual(palette.pipe_colors[1], "#00ff00")
        self.assertEqual(palette.focused_route, "#abcdef")
        self.assertEqual(palette.neutral_pipe, "#8f8f8f")

    def test_invalid_theme_uses_safe_defaults(self):
        self.assertEqual(parse_noctalia_css("not valid css"), DEFAULT_PALETTE)

    def test_config_accepts_values_and_invalid_values_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[font]\nfamily="Inter"\nnormal_text_size=12\nhint_badge_font_size=200\n[graph]\nicon_size=44\nworkspace_step=-2\n')
            settings = DashboardSettings.load(path)
        self.assertEqual(settings.font_family, "Inter")
        self.assertEqual(settings.normal_text_size, 12)
        self.assertEqual(settings.hint_badge_font_size, DashboardSettings().hint_badge_font_size)
        self.assertEqual(settings.icon_size, 44)
        self.assertEqual(settings.workspace_step, DashboardSettings().workspace_step)

    def test_overlay_config_values_and_safe_fallbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[overlay]\nmax_width_percent=70\nmax_height_percent=75\nmin_width=500\nmin_height=300\n")
            settings = DashboardSettings.load(path)
            self.assertEqual((settings.overlay_max_width_percent, settings.overlay_max_height_percent,
                              settings.overlay_min_width, settings.overlay_min_height), (70, 75, 500, 300))
            for content in ('[overlay]\nmax_width_percent=true\nmax_height_percent=101\nmin_width=-1\nmin_height="large"',
                            'overlay = "invalid"', '[overlay]\nmax_width_percent=0.5\nmax_height_percent=0'):
                path.write_text(content)
                self.assertEqual(DashboardSettings.load(path), DashboardSettings())

    def test_overlay_opacity_accepts_zero_to_one_and_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for value, expected in [("0", 0.0), ("0.8", .8), ("1", 1.0),
                                    ("-0.1", 1.0), ("1.1", 1.0), ("nan", 1.0),
                                    ("inf", 1.0), ("true", 1.0), ('"0.8"', 1.0)]:
                with self.subTest(value=value):
                    path.write_text(f"[overlay]\nopacity = {value}\n")
                    self.assertEqual(DashboardSettings.load(path).overlay_opacity, expected)

    def test_main_background_opacity_clamps_to_transparent_range(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for value, expected in [("0", 0.0), ("0.65", .65), ("1", 1.0),
                                    ("-0.1", 0.0), ("1.1", 1.0), ("true", 1.0), ('"0.8"', 1.0)]:
                with self.subTest(value=value):
                    path.write_text(f"[appearance]\nbackground_opacity = {value}\n")
                    self.assertEqual(DashboardSettings.load(path).background_opacity, expected)

    def test_global_ui_scale_accepts_and_clamps_safe_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for value, expected in [("0.5", .6), ("0.8", .8), ("1", 1.0),
                                    ("1.5", 1.5), ("0.1", .6), ("2", 2.0),
                                    ("4", 2.0), ("true", 1.0), ("nan", 1.0),
                                    ('"1.2"', 1.0)]:
                with self.subTest(value=value):
                    path.write_text(f"[graph]\nglobal_scale = {value}\n")
                    self.assertEqual(DashboardSettings.load(path).global_scale,
                                     expected)

    def test_appearance_scale_takes_priority_over_legacy_graph_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[graph]\nglobal_scale=1.8\n"
                            "[appearance]\nglobal_scale=1.25\n")
            settings = DashboardSettings.load(path)
        self.assertEqual(settings.global_scale, 1.25)
        self.assertEqual(settings.scaled(40), 50)
        self.assertEqual(settings.scaled_f(2.0), 2.5)

    def test_malformed_or_missing_config_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            self.assertEqual(DashboardSettings.load(path), DashboardSettings())
            path.write_text('[font\n')
            self.assertEqual(DashboardSettings.load(path), DashboardSettings())

    def test_screen_overlay_settings_are_boolean_and_default_to_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            for value, expected in (("false", False), ("true", True),
                                    ("0", True), ('"false"', True)):
                path.write_text(f"[ui]\nshow_hud = {value}\nshow_pet = {value}\n")
                settings = DashboardSettings.load(path)
                self.assertEqual(settings.show_hud, expected)
                self.assertEqual(settings.show_pet, expected)

    def test_theme_reload_survives_atomic_file_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "noctalia.css"
            path.write_text('@define-color window_bg_color #111111;')
            provider = AppearanceProvider(theme_path=path, config_path=Path(directory) / "missing.toml")
            self.addCleanup(provider.deleteLater)
            replacement = Path(directory) / "replacement.css"
            replacement.write_text('@define-color window_bg_color #222222;')
            replacement.replace(path)
            provider.reload_theme()
            self.assertEqual(provider.palette.dashboard_background, "#222222")
            self.assertIn(str(path), provider.watcher.files())


if __name__ == "__main__":
    unittest.main()
