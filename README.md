# Niri Dashboard — alpha

A mouse-operated node graph of your entire Niri desktop, in one window on one
monitor. Each monitor is a colored branch, workspaces connect vertically, and
application logos connect horizontally. No live window previews or touchscreen
controls.

## Run

Requires Python 3.10+, PySide6, and an active Niri session. The alpha targets
Niri 26.04 and uses `$NIRI_SOCKET` directly. Your desktop's installed icon themes
and `.desktop` entries supply application logos, including Flatpak exports.
Unknown apps get a readable initials icon.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/niridashboard/main.py
```

Use `--fullscreen` to fill the dashboard's current monitor. To explore without
contacting Niri, run the interactive sample desktop:

```sh
python src/niridashboard/main.py --demo
```

You can also run `PYTHONPATH=src python -m niridashboard`.

## Use

- **Move an app:** drag its logo to a workspace on any monitor. A colored insertion
  marker shows the destination. Drop before an app to insert before its column,
  or after the final app to append. Empty workspaces accept drops too.
- **Focus an app:** click its node. Hover to read its full title and position.
- **Navigate:** wheel to zoom; drag the background, middle-drag, or Space+drag to
  pan. Dragging an app near a viewport edge pans automatically.
- **Fit the whole desktop:** click Fit, press `F` while the graph is focused, or
  press `Ctrl+0`. Manual zoom/pan stays in place across state updates.
- **Find a window:** `Ctrl+K`, type an app name or title, then Enter to focus the
  first match. Other nodes dim but remain available as drop targets.
- **Cancel a drag:** `Esc`, or release outside a workspace row.
- **Fullscreen:** `F11` or the Fullscreen button.

The filled workspace junction indicates an active workspace. A colored app
border indicates the focused window. Amber dots indicate urgent windows.

## Ordering and alpha boundaries

App order follows Niri's real column and row positions. Existing stacked columns
are flattened into the horizontal graph and labeled `STACK column · row`.
Dropping next to a member inserts **before the entire column**; this alpha does
not build or reorder stacks. Dragging a member out extracts only that window
into its own column. Dropping a floating window tiles it; floating windows are
marked `~` and appear after tiled apps. Dropping near floating apps appends to
the tiled portion.

Niri's exact column-position action operates on the focused column. A move may
briefly focus the moved app before restoring the previously focused window
(normally the dashboard). Action sequences are not atomic: if a window closes or
a workspace disappears during a move, an error appears and the graph refreshes
to the actual desktop state. No undo yet.

The dashboard lists existing workspaces, including Niri's trailing empty
workspaces. It does not create named workspaces, launch apps, close windows,
manage monitor configuration, or replace your Niri overview key automatically.
Monitor branches are sorted by logical position, with equal-size nodes for
readability rather than physical monitor proportions.

## Architecture

- `src/niridashboard/main.py`: entry point, toolbar, search, connection feedback,
  and coordination of deferred updates.
- `graph.py`: Qt Graphics View scene, monitor/workspace graph, app nodes, zoom,
  pan, and drag/drop hit testing.
- `icons.py`: cached desktop-entry and icon-theme lookup with fallback artwork.
- `backend.py`: one serialized worker thread for snapshots and actions; includes
  the isolated interactive demo model.
- `niri.py`: newline-delimited JSON over the Niri Unix socket, bounded requests,
  ID-based workspace moves, and column insertion with focus restoration.
- `tests/test_dashboard.py`: offscreen mouse interaction and movement regressions.
- `tests/live_smoke.py`: opt-in real compositor integration check using temporary
  windows and empty workspaces on two outputs.

State is polled every 150 ms after the previous request finishes, without
spawning subprocesses. All IPC runs off the GUI thread. Unchanged snapshots do
not redraw; updates are deferred while dragging or executing an action. Manual
zoom is preserved. Disconnects show an error, disable app actions, and retry
automatically. Requests time out after two seconds.

IPC reference: [Niri actions](https://niri-wm.github.io/niri/niri_ipc/enum.Action.html)
and [window layout](https://niri-wm.github.io/niri/niri_ipc/struct.WindowLayout.html).

## Test

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Optional live check (opens and closes only disposable test windows, moves them
between two empty workspaces, then restores original focus):

```sh
PYTHONPATH=src .venv/bin/python tests/live_smoke.py
```
