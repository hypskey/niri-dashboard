"""Opt-in real Niri test. Only moves disposable test windows; restores focus.

Run inside Niri: PYTHONPATH=src .venv/bin/python tests/live_smoke.py
Needs two empty workspaces on different outputs. Never run as a unit test.
"""
import os
import subprocess
import sys
import time
import uuid
from niridashboard import niri


def wait_for(predicate, message):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError(message)


def client(prefix):
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication([])
    app.setApplicationName("niridashboard-test")
    app.setDesktopFileName("niridashboard-test")
    widgets = []
    for i in range(3):
        widget = QLabel(f"Temporary dashboard integration test {i + 1}")
        widget.setWindowTitle(f"{prefix}-{i}")
        widget.resize(320, 160)
        widget.show()
        widgets.append(widget)
    sys.exit(app.exec())


def main():
    initial = niri.snapshot()
    previous = next((w["id"] for w in initial["windows"] if w.get("is_focused")), None)
    occupied = {w["workspace_id"] for w in initial["windows"]}
    empty = [w for w in initial["workspaces"] if w["id"] not in occupied and w.get("output")]
    pair = next(((a, b) for a in empty for b in empty if a["output"] != b["output"]), None)
    if pair is None:
        raise RuntimeError("This check needs empty workspaces on two monitors.")
    first, second = pair
    prefix = f"Dashboard-test-{uuid.uuid4().hex[:8]}"
    process = subprocess.Popen([sys.executable, __file__, "--client", prefix])
    try:
        test_windows = wait_for(lambda: [w for w in niri.get_windows() if (w.get("title") or "").startswith(prefix)] if len([w for w in niri.get_windows() if (w.get("title") or "").startswith(prefix)]) == 3 else None, "Test windows did not open")
        ids = [w["id"] for w in sorted(test_windows, key=lambda w: w["title"])]
        for wid in ids:
            niri.insert_window(wid, first["id"])
        def order(ws):
            return [w["id"] for w in niri.ordered([w for w in niri.get_windows() if w["workspace_id"] == ws and w["id"] in ids])]
        assert order(first["id"]) == ids, order(first["id"])
        niri.insert_window(ids[2], first["id"], ids[0])
        assert order(first["id"]) == [ids[2], ids[0], ids[1]], order(first["id"])
        niri.insert_window(ids[2], first["id"])
        assert order(first["id"]) == ids, order(first["id"])
        print("PASS: reorder left, right, and append")
        niri.insert_window(ids[0], second["id"])
        assert order(second["id"]) == [ids[0]], order(second["id"])
        niri.insert_window(ids[1], second["id"], ids[0])
        assert order(second["id"]) == [ids[1], ids[0]], order(second["id"])
        print("PASS: cross-monitor move and insertion")
        niri.action("ConsumeOrExpelWindowRight", id=ids[1])
        windows = niri.get_windows()
        stacked = [w for w in windows if w["id"] in ids[:2]]
        assert len({niri.position(w)[0] for w in stacked}) == 1, stacked
        niri.insert_window(ids[1], second["id"], ids[0])
        windows = niri.get_windows()
        extracted = [w for w in windows if w["id"] in ids[:2]]
        assert len({niri.position(w)[0] for w in extracted}) == 2, extracted
        assert order(second["id"]) == [ids[1], ids[0]]
        print("PASS: extract one window from stacked column")
        niri.action("MoveWindowToFloating", id=ids[1])
        niri.insert_window(ids[1], first["id"], ids[2])
        assert order(first["id"]) == [ids[1], ids[2]]
        assert not next(w for w in niri.get_windows() if w["id"] == ids[1])["is_floating"]
        print("PASS: floating window converted and inserted")
    finally:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        wait_for(lambda: not any((w.get("title") or "").startswith(prefix) for w in niri.get_windows()), "Test windows did not close")
        if previous is not None and any(w["id"] == previous for w in niri.get_windows()):
            niri.focus_window(previous)
        print("Temporary windows closed; original focus restored")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--client":
        client(sys.argv[2])
    else:
        main()
