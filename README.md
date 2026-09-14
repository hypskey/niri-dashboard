# Niri Dashboard — alpha

A mouse-operated graph of the live Niri desktop. Monitor branches contain
vertical workspace rows and horizontal app nodes. The persistent dashboard and
the temporary Quick Overlay share one Niri model, controller, action worker,
icons, and graph implementation. The overlay is a normal floating Qt window;
its canvas is transparent so the desktop remains visible behind the graph.

## Install and run

Requires Python 3.10+, PySide6, and Niri 26.04 (the app uses `$NIRI_SOCKET`).
Niri's desktop and icon entries provide app logos; unknown apps get a readable
fallback icon.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bin/niridashboard serve --dashboard
```

This starts one resident process with the persistent dashboard and a hidden
overlay ready for toggling. For a resident process without the persistent
dashboard, omit `--dashboard`. To run only the persistent view with legacy
close-to-quit behavior, use `bin/niridashboard run`. Demo mode is isolated from
Niri and its actions:

```sh
bin/niridashboard --demo
```

## Quick Overlay

Add the rule and a free shortcut from [`examples/overlay.kdl`](examples/overlay.kdl)
to your Niri config, replacing the example repository path with its absolute
path. The overlay rule must use `open-focused true` so Escape reaches the graph;
the app restores the previously focused window when it closes.

```sh
bin/niridashboard toggle-overlay
bin/niridashboard status
bin/niridashboard quit
```

The shortcut command is a small local IPC client; it does not start another Qt
application or polling worker. NiriDashboard captures the focused output and
workspace, maps and sizes the overlay on that output, and fits the complete
desktop graph. Use the same shortcut or Escape to hide it. Selecting an app
focuses that app and hides the overlay. A right-click on an app requests its
normal close action.

## Interacting with the graph

- Drag an app node to a workspace on any monitor to move it. Drop before an app
  to insert before its column, or after the final app to append. Empty
  workspaces accept drops too.
- Click an app node to focus it. Hover to read its full title and position.
- Wheel to zoom. Drag the background, middle-drag, or Space+drag to pan. Near an
  edge, dragging an app pans the graph automatically.
- Press `F` to fit the graph, `Ctrl+0` to fit the persistent view, and `F11` to
  toggle persistent-dashboard fullscreen. `Escape` cancels a drag and hides the
  overlay when it is open.

The filled workspace junction marks the active workspace. A colored app border
marks the focused window; amber dots mark urgent windows. The dashboard shows
existing workspaces, including trailing empty workspaces. It does not create
workspaces or manage monitor configuration.

App order follows Niri's column and row positions. Existing stacked columns are
flattened and labeled `STACK column · row`; this alpha does not create or
reorder stacks. Moving a stacked window extracts it into its own column. Moving
a floating app into a workspace tiles it. Niri's insertion actions are not
atomic, so if a window closes or a workspace changes during a move, the app
reports the error and refreshes from actual desktop state. No undo yet.

## Structure

- `src/niridashboard/main.py`: persistent dashboard and shared graph-window
  wiring.
- `graph.py`: Qt Graphics View scene, graph nodes, edges, zoom, pan, and
  drag-and-drop.
- `controller.py`: shared filtered/live state and serialized actions.
- `backend.py`: the single polling/action worker and isolated demo model.
- `niri.py`: bounded JSON requests to Niri, output/workspace selection,
  placement, and focus restoration.
- `overlay.py`: frameless transient view over the same graph/controller.
- `ipc.py` and `cli.py`: resident control socket and launch/toggle/status/quit
  commands.
- `icons.py`: cached icon lookup with fallback artwork.
- `bin/niridashboard`: launch wrapper using `.venv` when present.
- `tests/`: offscreen behavior, overlay, paint, and Niri action regressions.

Snapshots poll every 150 ms after the previous request finishes. All Niri I/O
runs on the worker thread; unchanged snapshots do not redraw, and state updates
wait while a drag or action is in progress. Overlay windows are excluded by
their app ID and exact title before the graph is rendered.

## Tests

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
niri validate -c examples/overlay.kdl
```

`tests/live_smoke.py` is an optional real-compositor check using temporary test
windows and empty workspaces; it restores the original focus when complete.
