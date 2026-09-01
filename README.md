NiriDashBoard

NiriDashBoard is a visual control panel for the
Niri Wayland compositor.

It displays the complete Niri desktop topology—physical monitors, their
workspaces, and the windows inside them—on a dedicated small screen. The goal
is to make finding and moving windows immediate, without first remembering
which monitor or workspace contains them.

The problem

With several monitors and workspaces, an application can already be open but
hidden somewhere unexpected. Launching or focusing it blindly can make it
appear over the wrong screen—for example, over a Zoom meeting.

NiriDashBoard provides a persistent visual map of the desktop. A user should
be able to glance at the dashboard, locate an application, focus it, or move it
to another workspace or monitor in a few seconds.

Intended experience

Represent physical monitors using their real spatial arrangement.

Show every Niri workspace on its associated monitor, including inactive
workspaces.

Represent open windows as clear application cards rather than live content
previews.

Click a window card to focus the corresponding window.

Drag a window card to another workspace or monitor to move it there.

Keep the interface readable and comfortable on a dedicated 15-inch USB
display.

Support mouse input initially while keeping controls large and simple enough
for a future touchscreen.

Eventually support fast keyboard interaction, such as Vimium-style hints.

Current implementation

The project is an early PySide6 prototype. It currently:

queries Niri for outputs, workspaces, and windows;

refreshes the dashboard automatically every 500 ms;

draws outputs using their logical positions and dimensions;

shows all workspaces belonging to each output;

shows the windows contained in each workspace;

highlights active workspaces and the focused window; and

focuses a real window when its dashboard card is clicked.

The next major milestone is moving windows between workspaces and monitors,
ideally through drag and drop.

Longer-term direction

Once the core window-management interaction is reliable, the dashboard can be
developed into a polished, futuristic interface with application icons,
touch-friendly interactions, keyboard shortcuts, and possibly application
launching and other Niri actions.

The priority remains practical desktop control. The dashboard is not intended
to reproduce or stream the visual contents of applications such as terminals
or Neovim.

Technology

Python

PySide6 / Qt Graphics View

Niri IPC through niri msg --json

Fedora Linux with Niri/Wayland

Repository structure

src/niridashboard/main.py  Dashboard window, scene, and interactive cards
src/niridashboard/niri.py  Niri queries and actions
requirements.txt           Python dependencies

Run the prototype

The program must run inside an active Niri session with the niri command
available.

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/niridashboard/main.py

Development principles

Keep Niri communication isolated from interface code.

Treat Niri as the source of truth and redraw only when its state changes.

Build and verify functionality before spending significant time on visual
polish.

Design current mouse interactions so they can translate naturally to touch.

Preserve compatibility with real multi-monitor arrangements and inactive
workspaces.
