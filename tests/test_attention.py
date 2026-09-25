import os
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from niridashboard.attention import (AttentionManager, NotificationListener,
                                      resolve_notification,
                                      terminal_runs_codex)
from niridashboard.backend import demo_state
from niridashboard.main import Dashboard
from niridashboard.pet import PetGraphicsItem


def browser(wid, host, focused=False):
    return {"id": wid, "app_id": "app.zen_browser.zen", "title": "Conversation",
            "browser_hostname": host, "is_focused": focused}


class AttentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_notification_parser_accepts_only_notify_calls_and_split_chunks(self):
        listener = NotificationListener(enabled=False)
        self.addCleanup(listener.close)
        events = []
        listener.notification.connect(lambda *fields: events.append(fields))
        listener.feed('method call interface=org.example.Other; member=Notify\n'
                      '   string "Ignore"\n   string ""\n   string "No"\n')
        listener.feed('method call time=1 sender=:1.2 -> destination=org.freedesktop.Notifications '
                      'path=/org/freedesktop/Notifications; '
                      'interface=org.freedesktop.Notifications; member=Notify\n'
                      '   string "Google Chat"\n   uint32 0\n   string "chat"\n'
                      '   str')
        self.assertEqual(events, [])
        with patch.object(listener, "_sender_pid", return_value=12441):
            listener.feed('ing "Alice sent a message"\n')
        self.assertEqual(events, [("Google Chat", "chat", "Alice sent a message",
                                   12441)])

    def test_browser_site_requires_a_unique_window_and_never_uses_title_changes(self):
        windows = [browser(1, "chat.google.com"),
                   browser(2, "mail.google.com")]
        self.assertEqual(resolve_notification("Google Chat", "", "Alice", windows),
                         (windows[0], "Google Chat"))
        self.assertEqual(resolve_notification("Zen Browser", "", "Gmail", windows),
                         (windows[1], "Gmail"))
        self.assertIsNone(resolve_notification("Zen Browser", "", "Alice", windows))
        self.assertIsNone(resolve_notification("Zen Browser", "", "Gmail", [
            browser(1, "chatgpt.com")]))
        self.assertEqual(resolve_notification("Gmail", "", "New mail", [
            browser(1, "chatgpt.com")]),
            (browser(1, "chatgpt.com"), "Gmail"))
        self.assertIsNone(resolve_notification("Google Chat", "", "Alice", [
            browser(1, "chat.google.com"), browser(2, "chat.google.com")]))
        self.assertIsNone(resolve_notification("Gmail", "", "Alice", [
            browser(1, "mail.google.com", focused=True)]))

    def test_codex_and_native_mail_require_unambiguous_open_windows(self):
        codex = {"id": 7, "app_id": "kitty", "title": "codex / project",
                 "icon_override": "codex-pet-03", "is_focused": False,
                 "pid": 1000001}
        other = {"id": 8, "app_id": "kitty", "title": "generic terminal",
                 "is_focused": False, "pid": 1000002}
        self.assertEqual(resolve_notification("Codex", "", "Approval required",
                                              [codex, other]), (codex, "Codex"))
        self.assertIsNone(resolve_notification("Kitty", "", "Ready",
                                                [codex, other]))
        self.assertIsNone(resolve_notification("Codex", "", "Approval required",
                                                [codex, dict(codex, id=9)]))
        self.assertEqual(resolve_notification(
            "kitty", "/usr/lib64/kitty/logo/kitty.png",
            "Approval requested: command", [dict(codex, is_focused=True), other],
            sender_pid=1000001), (dict(codex, is_focused=True), "Codex"))
        self.assertEqual(resolve_notification(
            "kitty", "", "Approval requested: command", [codex, other]),
            (codex, "Codex"))
        self.assertIsNone(resolve_notification(
            "kitty", "", "Approval requested: command", [codex, other],
            sender_pid=90000))
        self.assertIsNone(resolve_notification(
            "kitty", "", "Approval requested: command", [codex, other],
            sender_pid=1000002))
        mail = {"id": 10, "app_id": "org.mozilla.Thunderbird",
                "title": "Inbox", "is_focused": False}
        self.assertEqual(resolve_notification("Thunderbird", "", "New message",
                                              [mail]), (mail, "Thunderbird"))
        self.assertIsNone(resolve_notification("Nautilus", "", "Folder changed",
                                                [dict(mail, app_id="org.gnome.Nautilus")]))

    def test_codex_process_tree_identifies_new_unmarked_kitty_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for pid, name, children in ((101, "kitty", "102 103"),
                                        (102, "kitten", ""),
                                        (103, "zsh", "104"),
                                        (104, "codex", "")):
                (root / str(pid) / "task" / str(pid)).mkdir(parents=True)
                (root / str(pid) / "comm").write_text(name)
                (root / str(pid) / "task" / str(pid) / "children").write_text(children)
            self.assertTrue(terminal_runs_codex(101, root))
            self.assertFalse(terminal_runs_codex(102, root))
        new_codex = {"id": 72, "app_id": "kitty", "pid": 171116,
                     "title": "⠴ Inspect Niri dashboard structure | niri-dashboard",
                     "is_focused": True}
        other = {"id": 2, "app_id": "kitty", "pid": 4059, "title": "~",
                 "is_focused": False}
        with patch("niridashboard.attention.terminal_runs_codex",
                   side_effect=lambda pid: pid == 171116):
            self.assertEqual(resolve_notification(
                "kitty", "", "Task finished", [other, new_codex],
                sender_pid=171116), (new_codex, "Codex"))
        with patch("niridashboard.attention.terminal_runs_codex",
                   return_value=False):
            self.assertIsNone(resolve_notification(
                "kitty", "", "Approval requested: command", [other, new_codex],
                sender_pid=171116))

    def test_manager_cooldown_expiry_focus_and_window_removal(self):
        manager = AttentionManager(enabled=False)
        self.addCleanup(manager.close)
        windows = [browser(11, "mail.google.com"),
                   browser(12, "chat.google.com")]
        manager.update_state({"windows": windows}, {11: 10, 12: 11})
        events = []
        manager.changed.connect(events.append)
        self.assertTrue(manager.receive_notification("Gmail", "", "New mail", now=100))
        self.assertEqual((manager.current.window_id, manager.current.number), (11, 10))
        self.assertFalse(manager.receive_notification("Google Chat", "", "Hello", now=101))
        manager.clear()
        self.assertFalse(manager.receive_notification("Gmail", "", "New mail", now=110))
        self.assertTrue(manager.receive_notification("Google Chat", "", "Hello", now=110))
        manager.update_state({"windows": windows}, {11: 10, 12: 12})
        self.assertEqual(manager.current.number, 12)
        manager.update_state({"windows": [windows[0]]}, {11: 10})
        self.assertIsNone(manager.current)
        self.assertFalse(manager.dismiss_timer.isActive())
        self.assertIsNone(events[-1])

    def test_title_refresh_alone_is_silent_and_tab_change_clears_attention(self):
        manager = AttentionManager(enabled=False)
        self.addCleanup(manager.close)
        window = browser(19, "chat.google.com")
        manager.update_state({"windows": [window]}, {19: 1})
        manager.update_state({"windows": [dict(window, title="A different chat")]},
                             {19: 1})
        self.assertIsNone(manager.current)
        self.assertTrue(manager.receive_notification("Google Chat", "", "Message",
                                                     now=100))
        manager.update_state({"windows": [dict(window, title="Inbox",
                                                browser_hostname="mail.google.com")]},
                             {19: 1})
        self.assertIsNone(manager.current)

    def test_attention_expires_and_new_notification_can_arrive(self):
        manager = AttentionManager(enabled=False)
        self.addCleanup(manager.close)
        manager.dismiss_timer.setInterval(15)
        manager.update_state({"windows": [browser(20, "chat.google.com"),
                                          browser(21, "mail.google.com")]},
                             {20: 1, 21: 2})
        self.assertTrue(manager.receive_notification("Google Chat", "", "Message",
                                                     now=100))
        QTest.qWait(30)
        self.assertIsNone(manager.current)
        self.assertTrue(manager.receive_notification("Gmail", "", "New mail",
                                                     now=110))

    def test_focused_codex_approval_stays_visible_but_other_cues_still_clear(self):
        manager = AttentionManager(enabled=False)
        self.addCleanup(manager.close)
        codex = {"id": 24, "app_id": "kitty", "pid": 1000003,
                 "title": "[ ! ] Action Required", "icon_override": "codex-pet-04",
                 "is_focused": True}
        other = {"id": 25, "app_id": "kitty", "pid": 1000004,
                 "title": "~", "is_focused": False}
        manager.update_state({"windows": [codex, other]}, {24: 12, 25: 13})
        self.assertTrue(manager.receive_notification(
            "kitty", "/usr/lib64/kitty/logo/kitty.png",
            "Approval requested: test", sender_pid=1000003, now=100))
        self.assertEqual((manager.current.window_id, manager.current.label,
                          manager.current.number), (24, "Codex", 12))
        manager.update_state({"windows": [codex, other]}, {24: 12, 25: 13})
        self.assertIsNotNone(manager.current)
        manager.update_state({"windows": [dict(codex, is_focused=False), other]},
                             {24: 12, 25: 13})
        self.assertIsNotNone(manager.current)
        manager.clear()
        self.assertFalse(manager.receive_notification(
            "kitty", "", "Approval requested: another action",
            sender_pid=1000003, now=108))
        self.assertTrue(manager.receive_notification(
            "kitty", "", "Approval requested: another action",
            sender_pid=1000003, now=113))

    def test_pet_attention_pauses_jump_and_sleep_but_keeps_idle_events(self):
        pet = PetGraphicsItem()
        self.addCleanup(pet.deleteLater)
        anchors = {"DP-1": QPointF(10, 10), "DP-2": QPointF(300, 10)}
        pet.set_output_anchors(anchors, "DP-1")
        pet.set_output_anchors(anchors, "DP-2")
        self.assertTrue(pet.is_jumping)
        cue = type("Cue", (), {"number": 12, "label": "Google Chat"})()
        pet.set_attention(cue)
        self.assertTrue(pet.attention_active)
        self.assertFalse(pet.is_jumping)
        self.assertFalse(pet.jump_timer.isActive())
        self.assertEqual(pet.pos(), anchors["DP-1"])
        self.assertFalse(pet.sleep_delay_timer.isActive())
        pet.start_falling_asleep()
        pet.start_jump("DP-2")
        self.assertEqual(pet.sleep_state, "awake")
        self.assertFalse(pet.is_jumping)
        self.assertTrue(pet.idle_timer.isActive())
        pet.start_idle_burst()
        self.assertTrue(pet.burst_timer.isActive())
        pet.set_attention(None)
        self.assertFalse(pet.attention_active)
        self.assertFalse(pet.burst_timer.isActive())
        self.app.processEvents()
        self.assertTrue(pet.is_jumping)
        pet.jump_timer.stop()
        pet.idle_timer.stop()
        pet.sleep_delay_timer.stop()

    def test_dashboard_bubble_uses_shared_hint_and_codex_survives_focus(self):
        dashboard = Dashboard(demo=True, start_backend=False)
        self.addCleanup(dashboard.close)
        dashboard.show()
        state = demo_state()
        target = state["windows"][1]
        target["title"] = "codex / dashboard"
        target["icon_override"] = "codex-pet-03"
        dashboard.controller.receive_state(state)
        self.app.processEvents()
        pet = dashboard.view.pet_item
        transform = dashboard.view.transform()
        scene_rect = dashboard.view.sceneRect()
        self.assertTrue(dashboard.controller.attention.receive_notification(
            "Codex", "", "Approval required", now=100))
        self.assertEqual(pet.attention_cue.number,
                         dashboard.controller.hint_assignments.by_window[target["id"]])
        self.assertEqual(dashboard.view.transform(), transform)
        self.assertEqual(dashboard.view.sceneRect(), scene_rect)
        self.assertEqual(dashboard.view.pet_item.attention_cue.label, "Codex")

        focused = deepcopy(state)
        for window in focused["windows"]:
            window["is_focused"] = window["id"] == target["id"]
        dashboard.controller.receive_state(focused)
        self.assertTrue(pet.attention_active)
        pet.idle_timer.stop()
        pet.sleep_delay_timer.stop()


if __name__ == "__main__":
    unittest.main()
