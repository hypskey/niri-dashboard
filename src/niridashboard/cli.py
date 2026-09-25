"""Parse control commands before loading the GUI for fast keybinding invocation."""
import argparse
import json
import sys
from .ipc import send_command, socket_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Niri Dashboard and quick overlay")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "serve", "toggle-overlay", "quit", "status"])
    parser.add_argument("--dashboard", action="store_true", help="Show the persistent window in resident mode")
    parser.add_argument("--demo", action="store_true", help="Isolated sample desktop, without Niri actions")
    parser.add_argument("--fullscreen", action="store_true", help="Start the persistent dashboard fullscreen")
    args = parser.parse_args(argv)
    try:
        if args.command in ("toggle-overlay", "quit", "status"):
            result = send_command(args.command, socket_path(args.demo))
            print(json.dumps(result) if isinstance(result, dict) else result)
            return 0
        return run_gui(args)
    except (RuntimeError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


def run_gui(args):
    import signal
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .controller import DashboardController
    from .main import Dashboard
    from .overlay import OverlayWindow
    from .ipc import create_server

    path = socket_path(args.demo)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("niridashboard")
    app.setDesktopFileName("niridashboard")
    app.setQuitOnLastWindowClosed(False)
    controller = None
    overlay = None
    stopping = False

    def shutdown():
        nonlocal stopping
        if stopping:
            return
        stopping = True
        overlay.shutdown()
        # Finish overlay restoration in the same queue before requesting stop.
        controller.task(lambda: None, lambda ok, result: controller.stop())

    def handle(command, ipc_latency_ms=0):
        if command == "status":
            cue = controller.attention.current
            return {"pid": __import__("os").getpid(), "connected": controller.connected,
                    "overlay": overlay.phase, "overlay_window_id": overlay.window_id,
                    "output": (overlay.context or {}).get("output"), "last_open_ms": overlay.last_open_ms,
                    "timings_ms": dict(overlay.timings_ms),
                    "error": overlay.failure, "polling_workers": int(controller.backend.isRunning()),
                    "attention": ({"window_id": cue.window_id, "label": cue.label,
                                   "number": cue.number} if cue else None),
                    "last_attention_event": controller.attention.last_event}
        if command == "quit":
            QTimer.singleShot(0, shutdown)
            return "Stopping NiriDashboard"
        if stopping:
            raise RuntimeError("NiriDashboard is stopping.")
        if not controller.connected:
            raise RuntimeError(controller.health_message)
        return {"accepted": True, "overlay": overlay.toggle(ipc_latency_ms)}

    # Acquire session ownership before starting any Niri polling.
    server = create_server(path, handle)
    try:
        controller = DashboardController(demo=args.demo)
        controller.stopped.connect(app.quit)
        overlay = OverlayWindow(controller)
        dashboard = None
        if args.command == "run" or args.dashboard:
            dashboard = Dashboard(demo=args.demo, controller=controller)
            dashboard.showFullScreen() if args.fullscreen else dashboard.show()
            if args.command == "run":
                # Legacy direct launch keeps close-to-quit behavior.
                app.lastWindowClosed.connect(shutdown)
        signal.signal(signal.SIGTERM, lambda *_: shutdown())
        signal.signal(signal.SIGINT, lambda *_: shutdown())
        heartbeat = QTimer()
        heartbeat.start(200)
        heartbeat.timeout.connect(lambda: None)
        return app.exec()
    finally:
        server.shutdown()
        if controller is not None:
            controller.backend.stop()
            controller.backend.wait()
