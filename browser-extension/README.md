# Active-tab website icons (Flatpak Zen / Firefox)

The extension connects directly to `ws://127.0.0.1:47831`, served by the resident
NiriDashboard process. No native messaging host, Python helper, shared filesystem,
cloud service, or external network connection is needed. Qt WebSockets is included
in the project's existing PySide6 dependency.

## Setup / upgrade from native messaging

1. Restart NiriDashboard using your existing resident launch command to load the
   new WebSocket server. The usual dashboard and overlay commands are unchanged.
2. In Zen open `about:debugging#/runtime/this-firefox`. Reload the NiriDashboard
   extension, or choose **Load Temporary Add-on** and select this directory's
   `manifest.json`. Version **0.2.0** uses WebSockets instead of native messaging.
3. Switch between a ChatGPT conversation, YouTube, and any unknown site. Icons
   should update without restarting the dashboard. Try two browser windows too.

Flatpak Zen's normal network permission shares the host network namespace, so
`127.0.0.1` reaches this server without filesystem access or sandbox escape helpers.
Check `flatpak info --show-permissions app.zen_browser.zen` if connection fails:
`shared=network` should be present. A custom sandbox that disables networking must
allow it for this connection. No permission changes are made by NiriDashboard.

The old `install.py` and `native_host.py` have been removed. Existing
`niridashboard.browser_tabs.json` registrations in `~/.mozilla/native-messaging-hosts`,
`~/.zen/native-messaging-hosts`, or a custom location are unused and can be deleted.
Old `$XDG_RUNTIME_DIR/niridashboard-browser` snapshots are no longer read.

Temporary extensions last until browser restart; load again afterward. Permanent
installation uses Firefox's normal signed-XPI installation process, with
`manifest.json` and `background.js` at the archive root. No online service is used
at runtime. Do not disable extension-signing protections.

## Behavior

Only a map of window tokens to active-tab hostnames is sent. No full URLs, page
contents, titles, history, or commands are transmitted. Private windows are excluded.
Known hosts select ChatGPT, YouTube, Google Calendar, Gmail, GitHub, or Reddit icons
through the existing icon cache. Unknown hosts retain the browser icon, even if
the title mentions a known site. Missing site artwork also retains the browser icon.

The existing `[ND:<session>:<window-id>] ` title preface correlates each browser
window with Niri, including identical titles and separate browser profiles. It is
hidden from dashboard labels but visible to other tools reading native titles.
Extensions that also set `titlePreface`, or Zen settings that suppress it, can
interfere with correlation.

Tab changes are event-driven with a 30 ms debounce. Connections automatically retry
with a 1–10 second backoff, publishing all current windows after reconnecting.
A 30-second heartbeat detects stale connections; the server drops silent clients
after 90 seconds. Disconnecting removes only that client's data. When the bridge
is unavailable, existing title-based detection remains the fallback.

One Qt server belongs to the shared controller, with no additional worker or Niri
polling loop. It binds **only IPv4 127.0.0.1**, accepts Firefox extension origins,
rejects ordinary web-page origins and malformed/oversized messages, and never
returns browser state to clients. Other local software is still within this trust
boundary; this is not authentication against other processes on your machine.
If the port is occupied, a warning is logged and the dashboard continues with title
fallback. Free the port and restart the resident app; do not expose it through a proxy.
Demo mode does not start the server.

For diagnostics, inspect the extension background console in `about:debugging`
and the resident app's log. `ss -ltn 'sport = :47831'` should show `127.0.0.1:47831`,
not `0.0.0.0` or `[::]`. There is no native-host registration step anymore.

## Tests

From the repository root (loopback sockets must be permitted):

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
node tests/browser_extension_test.js
```

Tests cover real Qt WebSocket connections, disconnect/reconnect and server restart,
multiple windows/profiles, tab updates, unknown-site fallback, rejected origins,
malformed messages, expiry, and the existing graph/overlay behavior. The JavaScript
test exercises the actual extension background script with browser API doubles.

References: [Flatpak network namespaces](https://github.com/flatpak/flatpak/wiki/Metadata),
[Firefox titlePreface API](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/windows/update),
[Qt WebSocket origin checks](https://doc.qt.io/qt-6/qwebsocketserver.html#originAuthenticationRequired).
