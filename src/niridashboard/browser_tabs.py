"""Qt loopback WebSocket bridge; one server shared by all dashboard views."""
import json
import logging
from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocketServer
from .browser_bridge import BRIDGE_PORT, MAX_MESSAGE, TITLE_PREFIX, validate_windows
from .icons import is_browser_app


class BrowserTabs(QObject):
    changed = Signal()

    def __init__(self, parent=None, enabled=True, port=BRIDGE_PORT):
        super().__init__(parent)
        self.hostnames = {}
        self.clients = {}
        self.server = QWebSocketServer("NiriDashboard browser icons",
                                      QWebSocketServer.SslMode.NonSecureMode, self)
        self.server.setMaxPendingConnections(16)
        self.server.setHandshakeTimeout(3000)
        self.server.originAuthenticationRequired.connect(self._authorize)
        self.server.newConnection.connect(self._accept)
        if enabled and not self.server.listen(QHostAddress("127.0.0.1"), port):
            logging.getLogger(__name__).warning(
                "Browser icons bridge unavailable on 127.0.0.1:%s: %s; using title fallback",
                port, self.server.errorString())

    @staticmethod
    def _authorize(authenticator):
        origin = QUrl(authenticator.origin())
        # Ordinary websites cannot inject hostnames. Firefox assigns extension origins.
        authenticator.setAllowed(origin.scheme() == "moz-extension" and bool(origin.host()))

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if len(self.clients) >= 16:
                socket.close()
                socket.deleteLater()
                continue
            socket.setParent(self)
            socket.setMaxAllowedIncomingFrameSize(MAX_MESSAGE)
            socket.setMaxAllowedIncomingMessageSize(MAX_MESSAGE)
            expiry = QTimer(socket)
            expiry.setSingleShot(True)
            expiry.setInterval(90000)
            expiry.timeout.connect(self._expire)
            self.clients[socket] = ({}, expiry)
            socket.textMessageReceived.connect(self._receive)
            socket.binaryMessageReceived.connect(self._reject_binary)
            socket.disconnected.connect(self._disconnected)
            expiry.start()

    @Slot()
    def _expire(self):
        self.sender().parent().abort()

    @Slot(QByteArray)
    def _reject_binary(self, _data):
        self.sender().abort()

    @Slot(str)
    def _receive(self, text):
        socket = self.sender()
        try:
            if len(text.encode("utf-8")) > MAX_MESSAGE:
                raise ValueError("Oversized browser snapshot")
            # A full token -> hostname map: no URLs, titles, or browser commands.
            windows = validate_windows(json.loads(text))
        except (ValueError, TypeError):
            socket.abort()
            return
        if socket in self.clients:
            _, expiry = self.clients[socket]
            self.clients[socket] = (windows, expiry)
            expiry.start()
            self._publish()

    @Slot()
    def _disconnected(self):
        socket = self.sender()
        record = self.clients.pop(socket, None)
        if record:
            record[1].stop()
        socket.deleteLater()
        self._publish()

    def _publish(self):
        hosts, conflicts = {}, set()
        for windows, _expiry in self.clients.values():
            for token, hostname in windows.items():
                if token in hosts and hosts[token] != hostname:
                    conflicts.add(token)
                hosts[token] = hostname
        for token in conflicts:
            hosts.pop(token, None)
        if hosts != self.hostnames:
            self.hostnames = hosts
            self.changed.emit()

    def close(self):
        self.server.close()
        for socket in list(self.clients):
            socket.abort()

    def decorate(self, window):
        if not is_browser_app(window.get("app_id")):
            return window
        title = window.get("title") or ""
        match = TITLE_PREFIX.match(title)
        if not match:
            return window
        result = dict(window, title=title[match.end():])
        if match[1] in self.hostnames:
            # Empty/unknown hosts are authoritative: do not guess from their titles.
            result["browser_hostname"] = self.hostnames[match[1]]
        return result
