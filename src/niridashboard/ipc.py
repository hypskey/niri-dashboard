"""Small local control protocol. Importing the command client does not import Qt."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import time

MAX_REQUEST = 1024


def socket_path(demo=False):
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise RuntimeError("XDG_RUNTIME_DIR is not set; run inside your desktop session.")
    root = Path(runtime)
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("XDG_RUNTIME_DIR must be a private directory owned by this user.")
    session = os.environ.get("NIRI_SOCKET", "")
    if not session and not demo:
        raise RuntimeError("NIRI_SOCKET is not set; run inside Niri (or use --demo).")
    key = hashlib.sha256((session + ("/demo" if demo else "")).encode()).hexdigest()[:16]
    return str(root / f"niridashboard-{key}.sock")


def send_command(command, path, timeout=2):
    def exchange(request):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            try:
                connection.connect(path)
            except (FileNotFoundError, ConnectionRefusedError) as error:
                raise RuntimeError("NiriDashboard is not running. Start: bin/niridashboard serve --dashboard") from error
            connection.sendall(json.dumps(request).encode() + b"\n")
            with connection.makefile("rb") as stream:
                reply = stream.readline(4096)
            if not reply.endswith(b"\n"):
                raise RuntimeError("Incomplete reply from NiriDashboard.")
            result = json.loads(reply)
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Command rejected"))
            return result["result"]

    try:
        return exchange({"command": command, "sent_ns": time.monotonic_ns()})
    except RuntimeError as error:
        # Let a resident started by an older version continue to handle toggles.
        if str(error) != "Unknown command":
            raise
        return exchange({"command": command})


def create_server(path, handler):
    from PySide6.QtCore import QTimer
    from PySide6.QtNetwork import QLocalServer

    class ControlServer(QLocalServer):
        def __init__(self):
            super().__init__()
            self.peers = set()
            self.lock = os.open(path + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if os.path.lexists(path):
                    info = os.lstat(path)
                    if info.st_uid != os.getuid() or not stat.S_ISSOCK(info.st_mode):
                        raise RuntimeError("Refusing to replace an unexpected control socket path.")
                    QLocalServer.removeServer(path)
                self.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
                if not self.listen(path):
                    raise RuntimeError(self.errorString())
            except Exception as error:
                os.close(self.lock)
                self.lock = None
                if isinstance(error, BlockingIOError):
                    raise RuntimeError("NiriDashboard is already running in this session.") from error
                raise
            self.newConnection.connect(self.accept_peers)

        def accept_peers(self):
            while self.hasPendingConnections():
                peer = self.nextPendingConnection()
                self.peers.add(peer)
                buffer = bytearray()
                timer = QTimer(peer)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda p=peer: p.abort())
                timer.start(2000)
                peer.readyRead.connect(lambda p=peer, b=buffer: self.read_request(p, b))
                peer.disconnected.connect(lambda p=peer: self.drop_peer(p))
                if peer.bytesAvailable():
                    self.read_request(peer, buffer)

        def drop_peer(self, peer):
            self.peers.discard(peer)
            peer.deleteLater()

        def read_request(self, peer, buffer):
            if peer.property("handled"):
                return
            buffer.extend(bytes(peer.readAll()))
            if len(buffer) <= MAX_REQUEST and b"\n" not in buffer:
                return
            peer.setProperty("handled", True)
            try:
                if len(buffer) > MAX_REQUEST:
                    raise ValueError("Request too large")
                request = json.loads(buffer)
                if (not isinstance(request, dict) or set(request) not in ({"command"}, {"command", "sent_ns"})
                        or request.get("command") not in ("toggle-overlay", "quit", "status")):
                    raise ValueError("Unknown command")
                sent_ns = request.get("sent_ns")
                if sent_ns is not None and (isinstance(sent_ns, bool) or not isinstance(sent_ns, int) or sent_ns < 0):
                    raise ValueError("Invalid request timestamp")
                latency_ms = max(0.0, (time.monotonic_ns() - sent_ns) / 1_000_000) if sent_ns is not None else 0.0
                result = {"ok": True, "result": handler(request["command"], latency_ms)}
            except Exception as error:
                result = {"ok": False, "error": str(error)}
            peer.write(json.dumps(result).encode() + b"\n")
            peer.disconnectFromServer()

        def shutdown(self):
            self.close()
            for peer in list(self.peers):
                peer.abort()
            if self.lock is not None:
                os.close(self.lock)
                self.lock = None

    return ControlServer()
