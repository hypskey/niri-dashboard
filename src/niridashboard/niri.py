"""Bounded, synchronous Niri IPC. Called exclusively by the background worker."""
import json
import os
import socket


def run_niri_ipc(request):
    path = os.environ.get("NIRI_SOCKET")
    if not path:
        raise RuntimeError("No Niri session found. Start inside Niri, or use --demo.")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(path)
        connection.sendall((json.dumps(request) + "\n").encode())
        with connection.makefile("r", encoding="utf-8") as stream:
            line = stream.readline(8 * 1024 * 1024)
            if not line:
                raise RuntimeError("Niri closed the connection")
            response = json.loads(line)
    if "Err" in response:
        raise RuntimeError(str(response["Err"]))
    return response["Ok"]


def action(name, **fields):
    return run_niri_ipc({"Action": {name: fields}})


def get_windows():
    return run_niri_ipc("Windows")["Windows"]


def get_workspaces():
    return run_niri_ipc("Workspaces")["Workspaces"]


def get_outputs():
    return run_niri_ipc("Outputs")["Outputs"]


def snapshot():
    return {"windows": get_windows(), "workspaces": get_workspaces(), "outputs": get_outputs()}


def position(window):
    return (window.get("layout") or {}).get("pos_in_scrolling_layout")


def ordered(windows):
    return sorted(windows, key=lambda w: (*(position(w) or [10**9, 0]), w["id"]))


def focus_window(window_id):
    return action("FocusWindow", id=window_id)


def close_window(window_id):
    return action("CloseWindow", id=window_id)


def move_window_to_workspace(window_id, workspace_id):
    return action("MoveWindowToWorkspace", window_id=window_id,
                  reference={"Id": workspace_id}, focus=False)


def insert_window(window_id, workspace_id, before_id=None):
    """Place a single window in its own column, before an anchor or at the end.

    Re-read after each structural change: Niri's column indices are transient.
    A failed sequence is not atomic; the worker always refreshes actual state.
    """
    windows = get_windows()
    window = next((w for w in windows if w["id"] == window_id), None)
    if window is None:
        raise RuntimeError("That window has closed.")
    if not any(w["id"] == workspace_id for w in get_workspaces()):
        raise RuntimeError("That workspace no longer exists.")
    if before_id == window_id:
        return
    if before_id is not None and not any(w["id"] == before_id and w["workspace_id"] == workspace_id for w in windows):
        raise RuntimeError("The destination changed. Please try again.")
    previous = next((w["id"] for w in windows if w.get("is_focused")), None)
    try:
        if window.get("is_floating"):
            action("MoveWindowToTiling", id=window_id)
        if window["workspace_id"] != workspace_id:
            move_window_to_workspace(window_id, workspace_id)
        windows = get_windows()
        window = next(w for w in windows if w["id"] == window_id)
        pos = position(window)
        if pos is None:
            raise RuntimeError("Niri did not provide a tiled position for this window.")
        siblings = [w for w in windows if w["workspace_id"] == workspace_id and position(w) and position(w)[0] == pos[0]]
        if len(siblings) > 1:
            action("ConsumeOrExpelWindowRight", id=window_id)
        windows = get_windows()
        window = next(w for w in windows if w["id"] == window_id)
        source = position(window)[0]
        peers = [w for w in windows if w["workspace_id"] == workspace_id and position(w)]
        if before_id is None:
            target = max(position(w)[0] for w in peers)
        else:
            anchor = next((w for w in peers if w["id"] == before_id), None)
            if anchor is None:
                raise RuntimeError("The destination changed during the move.")
            target = position(anchor)[0]
            if source < target:
                target -= 1
        if source != target:
            focus_window(window_id)
            # Avoid acting on an unrelated column if the window vanished.
            focused = next((w for w in get_windows() if w.get("is_focused")), None)
            if not focused or focused["id"] != window_id:
                raise RuntimeError("Window focus changed; ordering was cancelled.")
            action("MoveColumnToIndex", index=max(1, target))
    finally:
        if previous is not None:
            remaining = get_windows()
            if any(w["id"] == previous for w in remaining):
                focus_window(previous)


APP_ID = "niridashboard"
OVERLAY_TITLE = "niridashboard-overlay"


def is_overlay(window):
    return window.get("app_id") == APP_ID and window.get("title") == OVERLAY_TITLE


def overlay_context(data, focused_output=None):
    """Read-only selection, including focused empty workspaces."""
    focused = next((w for w in data["windows"] if w.get("is_focused") and not is_overlay(w)), None)
    workspace = next((w for w in data["workspaces"] if w.get("is_focused")), None)
    if workspace is None and focused:
        workspace = next((w for w in data["workspaces"] if w["id"] == focused.get("workspace_id")), None)
    if workspace is None and focused_output:
        workspace = next((w for w in data["workspaces"] if w.get("is_active") and w.get("output") == focused_output), None)
    if workspace is None:
        raise RuntimeError("Could not determine the focused workspace.")
    output = workspace.get("output")
    logical = data["outputs"].get(output, {}).get("logical")
    if not logical:
        raise RuntimeError("The focused monitor is no longer connected.")
    return {"window_id": focused["id"] if focused else None, "workspace_id": workspace["id"],
            "output": output, "logical": logical}


def capture_overlay_context():
    data = snapshot()
    try:
        return overlay_context(data)
    except RuntimeError:
        output = run_niri_ipc("FocusedOutput")["FocusedOutput"]
        return overlay_context(data, output.get("name") if output else None)


def place_overlay(window_id, context, cancelled, pid):
    """Only the owned overlay may be positioned; existing windows are untouched."""
    def perform(name, **fields):
        if cancelled.is_set():
            return False
        action(name, **fields)
        return True

    if cancelled.is_set():
        return
    windows = get_windows()
    window = next((w for w in windows if w["id"] == window_id and is_overlay(w) and w.get("pid") == pid), None)
    if not window:
        raise RuntimeError("The overlay window disappeared.")
    if not window.get("is_floating"):
        raise RuntimeError("Install the supplied Niri overlay window rule before using the overlay.")
    workspace = next((w for w in get_workspaces() if w["id"] == context["workspace_id"]), None)
    if not workspace or not workspace.get("is_active") or workspace.get("output") != context["output"]:
        raise RuntimeError("The focused workspace changed while opening. Toggle again.")
    if window.get("workspace_id") != workspace["id"]:
        perform("MoveWindowToWorkspace", window_id=window_id, reference={"Id": workspace["id"]}, focus=False)
    logical = context["logical"]
    width, height = round(logical["width"] * .9), round(logical["height"] * .9)
    perform("SetWindowWidth", id=window_id, change={"SetFixed": width})
    perform("SetWindowHeight", id=window_id, change={"SetFixed": height})
    perform("MoveFloatingWindow", id=window_id,
            x={"SetFixed": round(logical["width"] * .05)},
            y={"SetFixed": round(logical["height"] * .05)})
    perform("FocusWindow", id=window_id)


def restore_overlay_focus(context, restore=True):
    """Never move a workspace or pick an arbitrary fallback window."""
    if context and restore and context.get("window_id") is not None:
        windows = get_windows()
        if any(w["id"] == context["window_id"] and not is_overlay(w) for w in windows):
            focus_window(context["window_id"])
