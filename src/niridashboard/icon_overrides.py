"""Best-effort, login-session storage for manual Niri window icon assignments."""
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QObject, Signal


def default_override_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Path(runtime) / "niridashboard" / "icon-overrides.json" if runtime else None


class IconOverrides(QObject):
    changed = Signal()

    def __init__(self, path=None, enabled=True, parent=None):
        super().__init__(parent)
        self.enabled = enabled
        self.path = Path(path) if path else default_override_path()
        self.values = {}
        if self.enabled:
            self.load()

    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            self.values = {int(window_id): icon_id for window_id, icon_id in raw.items()
                           if str(window_id).isdigit() and int(window_id) > 0 and isinstance(icon_id, str)
                           and icon_id}
        except (AttributeError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
            pass

    def get(self, window_id):
        return self.values.get(window_id)

    def set(self, window_id, icon_id):
        if not isinstance(window_id, int) or window_id <= 0 or not isinstance(icon_id, str) or not icon_id:
            return
        if self.values.get(window_id) == icon_id:
            return
        self.values[window_id] = icon_id
        self._save()
        self.changed.emit()

    def reset(self, window_id):
        if window_id not in self.values:
            return
        self.values.pop(window_id)
        self._save()
        self.changed.emit()

    def prune(self, active_ids):
        active_ids = set(active_ids)
        stale = set(self.values) - active_ids
        if not stale:
            return
        for window_id in stale:
            self.values.pop(window_id, None)
        self._save()

    def _save(self):
        if not self.enabled or self.path is None:
            return
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".icon-overrides-", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump({str(window_id): icon_id for window_id, icon_id in self.values.items()}, stream,
                              sort_keys=True)
                    stream.write("\n")
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
