"""Persistent selection counts for the icon picker's first seven slots."""
import json
import os
from pathlib import Path
import tempfile


def default_usage_path():
    state_home = os.environ.get("XDG_STATE_HOME")
    return (Path(state_home) if state_home else Path.home() / ".local" / "state") / "niridashboard" / "icon-usage.json"


class IconUsage:
    def __init__(self, path=None, enabled=True):
        self.path = Path(path) if path is not None else default_usage_path()
        self.enabled = enabled
        self.counts = {}
        if enabled:
            self.load()

    def load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.counts = {icon_id: count for icon_id, count in raw.items()
                               if isinstance(icon_id, str) and icon_id
                               and type(count) is int and count > 0}
        except (OSError, UnicodeError, ValueError):
            pass

    def record(self, icon_id):
        if not isinstance(icon_id, str) or not icon_id:
            return
        self.counts[icon_id] = self.counts.get(icon_id, 0) + 1
        if self.enabled:
            self._save()

    def favorites_first(self, entries, limit=7):
        entries = tuple(entries)
        popular = sorted((entry for entry in entries if self.counts.get(entry.id, 0) > 0),
                         key=lambda entry: -self.counts[entry.id])[:limit]
        popular_ids = {entry.id for entry in popular}
        return tuple(popular) + tuple(entry for entry in entries if entry.id not in popular_ids)

    def _save(self):
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".icon-usage-", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(self.counts, stream, sort_keys=True)
                    stream.write("\n")
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
