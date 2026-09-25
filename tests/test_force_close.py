"""Per-window force-close boundaries; never signal a real process."""
import os
import signal
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from niridashboard import niri
from niridashboard.backend import Backend, demo_state


class ForceCloseTests(unittest.TestCase):
    def window(self, wid=42, pid=42000, app_id="kitty"):
        return {"id": wid, "pid": pid, "app_id": app_id}

    def test_kills_only_verified_unique_window_process_by_pidfd(self):
        windows = [self.window(), self.window(43, 43000)]
        with (patch.object(niri, "get_windows", side_effect=[windows, windows]),
              patch.object(niri.os, "stat", return_value=SimpleNamespace(st_uid=os.getuid())),
              patch.object(Path, "read_text", return_value="kitty\n"),
              patch.object(niri.os, "pidfd_open", return_value=99) as opened,
              patch.object(niri.signal, "pidfd_send_signal") as sent,
              patch.object(niri.os, "close") as closed):
            niri.force_close_window(42)
        opened.assert_called_once_with(42000)
        sent.assert_called_once_with(99, signal.SIGKILL)
        closed.assert_called_once_with(99)

    def test_shared_pid_is_refused_without_signaling(self):
        windows = [self.window(), self.window(43)]
        with (patch.object(niri, "get_windows", return_value=windows),
              patch.object(niri.os, "pidfd_open") as opened):
            with self.assertRaisesRegex(RuntimeError, "shares a process"):
                niri.force_close_window(42)
        opened.assert_not_called()

    def test_rechecks_window_after_opening_pidfd(self):
        first = [self.window()]
        second = [self.window(), self.window(43)]
        with (patch.object(niri, "get_windows", side_effect=[first, second]),
              patch.object(niri.os, "stat", return_value=SimpleNamespace(st_uid=os.getuid())),
              patch.object(Path, "read_text", return_value="kitty\n"),
              patch.object(niri.os, "pidfd_open", return_value=99),
              patch.object(niri.signal, "pidfd_send_signal") as sent,
              patch.object(niri.os, "close") as closed):
            with self.assertRaisesRegex(RuntimeError, "now shares a process"):
                niri.force_close_window(42)
        sent.assert_not_called()
        closed.assert_called_once_with(99)

    def test_disappeared_and_protected_windows_are_not_killed(self):
        with patch.object(niri, "get_windows", return_value=[]):
            self.assertIsNone(niri.force_close_window(42))
        with (patch.object(niri, "get_windows", return_value=[self.window(app_id="niridashboard")]),
              patch.object(niri.os, "pidfd_open") as opened):
            with self.assertRaisesRegex(RuntimeError, "no safe client process"):
                niri.force_close_window(42)
        opened.assert_not_called()

        with (patch.object(niri, "get_windows", return_value=[self.window()]),
              patch.object(niri.os, "stat", return_value=SimpleNamespace(st_uid=os.getuid())),
              patch.object(Path, "read_text", return_value="xwayland-satel\n"),
              patch.object(niri.os, "pidfd_open") as opened):
            with self.assertRaisesRegex(RuntimeError, "shared or protected"):
                niri.force_close_window(42)
        opened.assert_not_called()

    def test_demo_force_close_removes_only_selected_window(self):
        backend = Backend(demo=True)
        before = {window["id"] for window in demo_state()["windows"]}
        backend.demo_action("force_close", [2])
        self.assertEqual({window["id"] for window in backend.data["windows"]},
                         before - {2})


if __name__ == "__main__":
    unittest.main()
