"""Logical graph nodes derived from Niri's tiled column/tile positions."""
from dataclasses import dataclass

from .niri import ordered, position


@dataclass(frozen=True)
class DashboardNode:
    members: tuple[dict, ...]

    @property
    def window(self):
        return self.members[0]

    @property
    def is_stack(self):
        return len(self.members) == 2

    @property
    def focused(self):
        return any(window.get("is_focused") for window in self.members)

    @property
    def focused_member(self):
        return next((window for window in self.members if window.get("is_focused")),
                    self.window)

    def contains(self, window_id):
        return any(window["id"] == window_id for window in self.members)


def dashboard_nodes(windows):
    """Merge only two-window Niri columns; leave larger columns unchanged."""
    ordered_windows = ordered(windows)
    columns = {}
    for window in ordered_windows:
        place = position(window)
        if place and not window.get("is_floating"):
            columns.setdefault((window.get("workspace_id"), place[0]), []).append(window)
    result = []
    seen = set()
    for window in ordered_windows:
        place = position(window)
        key = ((window.get("workspace_id"), place[0])
               if place and not window.get("is_floating") else None)
        if key in seen:
            continue
        if key is not None:
            seen.add(key)
        members = columns.get(key, ()) if key is not None else ()
        if len(members) == 2:
            result.append(DashboardNode(tuple(members)))
        elif len(members) > 2:
            result.extend(DashboardNode((member,)) for member in members)
        else:
            result.append(DashboardNode((window,)))
    return tuple(result)
