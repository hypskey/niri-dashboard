# Niri Dashboard — alpha

A mouse-operated graph of the live Niri desktop. Monitor branches contain
vertical workspace rows and horizontal app nodes. The persistent dashboard and
the temporary Quick Overlay share one Niri model, controller, action worker,
icons, and graph implementation. The overlay is a normal floating Qt window;
its canvas uses the same solid Noctalia background as the main dashboard, sized
around the graph with a desktop margin.

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
application or polling worker. NiriDashboard uses the active workspace on DP-3, retains the previously focused
window for restoration, and fits the complete
desktop graph. Use the same shortcut or Escape to hide it. Selecting an app
focuses that app and hides the overlay. A right-click on an app requests its
normal close action.

Every open app has a numbered hint. Type the number while the overlay is
focused to select it; ambiguous prefixes wait briefly (for example, `1` waits
when `10` is also present). Escape clears a pending number first, and a second
Escape closes the overlay.

## Appearance and settings

Colors come from `~/.config/gtk-4.0/noctalia.css` (`@define-color` values).
The file is watched and palette updates apply without restarting the app. The
persistent dashboard uses Noctalia's window background; the overlay canvas
uses the same solid background as the main dashboard. Missing or invalid
colors use built-in fallback colors.

Non-color settings are read once at startup from
`~/.config/niridashboard/config.toml`. Missing or invalid entries use defaults:

```toml
[font]
family = "Sans Serif"
normal_text_size = 10
output_label_size = 15
workspace_number_size = 11
application_title_size = 9
window_title_size = 8
hint_badge_font_size = 9

[graph]
icon_size = 38
node_width = 108
node_height = 100
workspace_step = 136
workspace_row = 144
branch_gap = 60
graph_padding = 32

[appearance]
global_scale = 1.0
background_opacity = 1.0

[ui]
show_hud = true
show_pet = true

[focus_path]
glow = true

[overlay]
opacity = 1.0
max_width_percent = 86
max_height_percent = 86
min_width = 360
min_height = 220
```

`global_scale` uniformly adjusts UI density for fonts, application icons,
cards, graph strokes, the pet, status HUD, and icon picker. Values are clamped
to `0.6`–`2.0`; `1.0` is the native size. It does not change the camera zoom:
the graph still opens fitted, wheel zoom remains manual, and `F`, `Ctrl+0`, or
a double-click on empty graph space restores the fitted 100% view.

`background_opacity` controls only the main dashboard background.

`opacity` controls only the overlay background: `0.0` is fully transparent,
`1.0` is solid (default), and `0.8` is 80% opaque. Nodes, icons, connections, and
text remain opaque. The color continues to follow Noctalia.

Overlay limits are percentages of the focused monitor (10–100); minimum sizes
are logical pixels (width: 200–7680, height: 150–4320). The overlay still fits the
graph automatically within these limits. Lower the percentages for a smaller
overlay; raise the minimum sizes to give a small graph a larger window. Maximum
limits take precedence over configured minimums, subject to Qt's 200 × 150 minimum.
Invalid values use the defaults above. Restart the resident dashboard after editing.

The focused route uses the Noctalia accent with two soft, static glow strokes.
`glow = false` removes the glow and endpoint halo, leaving a sharp accent route.

## Interacting with the graph

- Drag an app node to a workspace on any monitor to move it. Drop before an app
  to insert before its column, or after the final app to append. Empty
  workspaces accept drops too.
- Click an app node to focus it. Ctrl+click or Ctrl+tap requests a normal close;
  a second Ctrl+click/tap on the same card within 600 ms force-closes its
  process. Right-click still requests a normal close. Force-close refuses a
  process shared by other windows, so it cannot take down every browser window.
  Hover to read the full title and position.
- Middle-click or Alt+click/tap an app node to assign a session-only custom icon. Type to search,
  use arrow keys to choose an icon, Enter to assign it, or Escape to cancel.
  “Reset to default icon” removes the assignment. Empty-space middle-drag still
  pans the graph.
- Wheel to zoom. Drag the background, middle-drag, or Space+drag to pan. Near an
  edge, dragging an app pans the graph automatically.
- Press `F` to fit the graph, `Ctrl+0` to fit the persistent view, and `F11` to
  toggle persistent-dashboard fullscreen. `Escape` cancels a drag and hides the
  overlay when it is open.

The filled workspace junction marks the active workspace. A colored app border
marks the focused window; amber dots mark urgent windows. The dashboard shows
existing workspaces, including trailing empty workspaces. It does not create
workspaces or manage monitor configuration.

## Pet attention cues

The resident dashboard listens locally for desktop notifications sent through
`org.freedesktop.Notifications` (`dbus-monitor` must be installed). A cue appears
only when it can be attributed to one open Niri window. The pet shows that
app's name and its existing numeric window hint for nine seconds. Ordinary
cues clear when the window is focused or disappears; browser cues also clear
if its active tab changes. Codex prompts can appear even when its terminal is
already focused.
Repeats are limited to one cue per window every 75 seconds (12 seconds for
Codex prompts),
with at least six seconds between cues. While a cue is visible, the pet stays
awake and in place, but still blinks and moves her tail. Clicking the pet clears
the cue.

The first filter recognizes Google Chat, Gmail, Proton Mail, WhatsApp, and
ChatGPT notifications for browser windows, plus a small set of native mail/chat
apps and Codex/terminal notifications. Multiple browser windows are resolved
using active-tab hostnames from the optional local Zen/Firefox extension; if a
notification could belong to several windows, the pet stays quiet. A
site-specific notification can still point to the only open browser window
when its alert came from a background tab. Folder and window-title changes
never trigger a cue. With several browser windows, background-tab alerts that
cannot be correlated are ignored. Kitty reports Codex alerts under the Kitty
app name, so the listener matches the local notification sender PID to Niri's
terminal PID and checks for a running Codex child process. The window's Codex
icon/title can also identify it when present. Codex terminal
cues require a desktop notification; a terminal title change alone is
intentionally insufficient.

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
- `appearance.py`: Noctalia palette parsing/watching and validated TOML settings.
- `hints.py`: stable app-number assignments and multi-digit prefix selection.
- `bin/niridashboard`: launch wrapper using `.venv` when present.
- `tests/`: offscreen behavior, overlay, paint, and Niri action regressions.

Snapshots poll every 150 ms after the previous request finishes. All Niri I/O
runs on the worker thread; unchanged snapshots do not redraw, and state updates
wait while a drag or action is in progress. A warm overlay opens immediately
from the latest cached snapshot and reconciles with the next worker snapshot.
`niridashboard status` reports the latest activation-stage timings. Overlay
windows are excluded by their app ID and exact title before the graph is
rendered.

## Tests

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
niri validate -c examples/overlay.kdl
```

## Session icon overrides

Manual icon assignments belong to a specific Niri window ID, so two Zen or Kitty
windows can use different icons. They are stored best-effort in
`$XDG_RUNTIME_DIR/niridashboard/icon-overrides.json`; dashboard restarts in the
same login retain them, while logout/reboot clears them naturally. Assignments for
windows no longer reported by Niri are removed on a later refresh.

The initial searchable catalog includes WhatsApp, YouTube, Gmail, GitHub, ChatGPT,
Python, Docker, SSH, Terminal, Folder / project, Nuke, Firefox, and Zen Browser.
It prefers installed icon-theme artwork and supplies a local monogram fallback when
an icon theme has no matching logo.

To add a manual logo, place a self-contained SVG or a high-resolution PNG in
`assets/icons/`. Its filename becomes its searchable name and stable ID. New files
are discovered at startup; while the dashboard is running, press the small refresh
button at the bottom-right of the icon picker to add them without restarting.
Curated catalog entries keep their existing names and artwork.

`tests/live_smoke.py` is an optional real-compositor check using temporary test
windows and empty workspaces; it restores the original focus when complete.

For URL-based website icons in Zen/Firefox (including ChatGPT conversation titles),
see the optional [local active-tab extension setup](browser-extension/README.md).
Without it, existing title-based icons continue to work.

The quick overlay currently targets DP-3 and applies a 20% enlargement after its
existing sizing calculation, capped at 96% of the display to keep it on-screen.
