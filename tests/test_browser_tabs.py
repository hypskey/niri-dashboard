import json
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket
from niridashboard.browser_bridge import site_for_hostname
from niridashboard.browser_tabs import BrowserTabs
from niridashboard.controller import DashboardController

TOKEN = "a" * 32 + ":1"
OTHER = "a" * 32 + ":2"
TITLE = "NiriDashBoard - Nautilus Transparency Setup — Zen Browser"


def window(token=TOKEN, title=TITLE):
    return {"id": 8, "app_id": "app.zen_browser.zen", "title": f"[ND:{token}] {title}"}


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hostnames_and_domain_boundaries(self):
        for host, site in [("chatgpt.com", "chatgpt"), ("www.youtube.com", "youtube"),
                           ("calendar.google.com", "google_calendar"), ("mail.google.com", "gmail"),
                           ("github.com", "github"), ("WWW.REDDIT.COM.", "reddit")]:
            self.assertEqual(site_for_hostname(host), site)
        for host in ["notchatgpt.com", "youtube.com.evil.org", "random.org", "", None]:
            self.assertIsNone(site_for_hostname(host))

    def test_live_controller_updates_and_unknown_host_overrides_title(self):
        controller = DashboardController(demo=True, start_backend=False)
        self.addCleanup(controller.stop)
        provider = self.provider(controller)
        client = self.client(provider)
        controller.browser_tabs = provider
        provider.changed.connect(controller._publish_state)
        icons = controller.icons
        def icon(color):
            pixmap = QPixmap(64, 64)
            pixmap.fill(color)
            return QIcon(pixmap)
        from PySide6.QtGui import QColor
        generic = icon(QColor("blue"))
        icons.cache["app.zen_browser.zen"] = ("Zen", generic)
        icons.site_icons.update(chatgpt=icon(QColor("green")), youtube=icon(QColor("red")))
        raw = {"windows": [window(), dict(window(OTHER), id=9)]}
        raw_signals = []
        controller.raw_state.connect(raw_signals.append)
        controller.receive_state(raw)
        def update(host):
            client.sendTextMessage(json.dumps({TOKEN: host, OTHER: "github.com"}))
            deadline = time.monotonic() + 2
            while provider.hostnames.get(TOKEN) != host and time.monotonic() < deadline:
                QTest.qWait(10)
            self.assertEqual(provider.hostnames[TOKEN], host)
            node = controller.latest["windows"][0]
            self.assertEqual(node["title"], TITLE)
            return icons.rendered(node["app_id"], 38, node["title"], node.get("browser_hostname"))
        chat = update("chatgpt.com")
        youtube = update("youtube.com")
        self.assertNotEqual(chat.cacheKey(), youtube.cacheKey())
        self.assertEqual(update("chatgpt.com").cacheKey(), chat.cacheKey())
        update("random.org")
        label, result = icons.resolve_for_window("app.zen_browser.zen", "ChatGPT", "random.org")
        self.assertEqual(result.cacheKey(), generic.cacheKey())
        self.assertEqual(icons.resolve_for_window("app.zen_browser.zen", "ChatGPT")[1].cacheKey(),
                         icons.site_icons["chatgpt"].cacheKey())
        self.assertEqual(controller.latest["windows"][1]["browser_hostname"], "github.com")
        self.assertEqual(len(raw_signals), 1)
        self.assertEqual(controller.raw, raw)
        self.assertFalse(controller.backend.isRunning())
        client.close()
        for _ in range(100):
            if not provider.hostnames:
                break
            QTest.qWait(10)
        self.assertNotIn("browser_hostname", controller.latest["windows"][0])

    def test_graph_uses_hostname_with_unchanged_conversation_title(self):
        from niridashboard.backend import demo_state
        from niridashboard.main import Dashboard
        dashboard = Dashboard(demo=True, start_backend=False)
        self.addCleanup(dashboard.close)
        icons = dashboard.controller.icons
        generic, chat, youtube = (QIcon(QPixmap(size, size)) for size in (8, 16, 24))
        icons.cache["app.zen_browser.zen"] = ("Zen", generic)
        icons.site_icons.update(chatgpt=chat, youtube=youtube)
        for hostname, expected in [("chatgpt.com", chat), ("youtube.com", youtube),
                                   ("random.example", generic)]:
            state = demo_state()
            node = state["windows"][0]
            node.update(app_id="app.zen_browser.zen", title=TITLE, browser_hostname=hostname)
            dashboard.receive_state(state)
            actual = dashboard.view.nodes[node["id"]]
            self.assertEqual(actual.icon.cacheKey(), expected.cacheKey())
            self.assertEqual(actual.window["title"], TITLE)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def provider(self, parent=None, port=0):
        provider = BrowserTabs(parent, port=port)
        self.assertTrue(provider.server.isListening(), provider.server.errorString())
        self.assertEqual(provider.server.serverAddress().toString(), "127.0.0.1")
        self.addCleanup(provider.close)
        return provider

    def client(self, provider, origin="moz-extension://test-extension", accepted=True):
        client = QWebSocket(origin)
        self.addCleanup(client.abort)
        client.open(QUrl(f"ws://127.0.0.1:{provider.server.serverPort()}"))
        if accepted:
            self.wait_for(lambda: client.state() == QAbstractSocket.SocketState.ConnectedState)
        else:
            self.wait_for(lambda: client.state() == QAbstractSocket.SocketState.UnconnectedState)
        return client

    def test_disconnect_reconnect_and_browser_restart(self):
        provider = self.provider()
        client = self.client(provider)
        client.sendTextMessage(json.dumps({TOKEN: "chatgpt.com", OTHER: "youtube.com"}))
        self.wait_for(lambda: len(provider.hostnames) == 2)
        client.close()
        self.wait_for(lambda: not provider.hostnames)
        client = self.client(provider)
        client.sendTextMessage(json.dumps({TOKEN: "reddit.com"}))
        self.wait_for(lambda: provider.hostnames.get(TOKEN) == "reddit.com")
        self.assertNotIn(OTHER, provider.hostnames)
        port = provider.server.serverPort()
        provider.close()
        self.wait_for(lambda: client.state() == QAbstractSocket.SocketState.UnconnectedState)
        restarted = self.provider(port=port)
        client = self.client(restarted)
        client.sendTextMessage(json.dumps({TOKEN: "youtube.com"}))
        self.wait_for(lambda: restarted.hostnames.get(TOKEN) == "youtube.com")

    def test_profiles_removal_conflicts_and_expiry(self):
        provider = self.provider()
        first, second = self.client(provider), self.client(provider)
        first.sendTextMessage(json.dumps({TOKEN: "chatgpt.com"}))
        second.sendTextMessage(json.dumps({OTHER: "github.com"}))
        self.wait_for(lambda: len(provider.hostnames) == 2)
        first.sendTextMessage("{}")
        self.wait_for(lambda: provider.hostnames == {OTHER: "github.com"})
        first.sendTextMessage(json.dumps({OTHER: "reddit.com"}))
        self.wait_for(lambda: not provider.hostnames)
        first.close()
        self.wait_for(lambda: provider.hostnames == {OTHER: "github.com"})
        for _, expiry in provider.clients.values():
            expiry.start(1)
        self.wait_for(lambda: not provider.hostnames)
        self.assertEqual(provider.decorate(window())["title"], TITLE)
        self.assertNotIn("browser_hostname", provider.decorate(window()))

    def test_rejects_web_origins_and_invalid_payloads(self):
        provider = self.provider()
        self.client(provider, "https://example.com", accepted=False)
        self.client(provider, "", accepted=False)
        self.assertFalse(provider.clients)
        for payload in ['null', '{"bad-token":"chatgpt.com"}',
                        json.dumps({TOKEN: "https://chatgpt.com/private"})]:
            client = self.client(provider)
            client.sendTextMessage(payload)
            self.wait_for(lambda: client.state() == QAbstractSocket.SocketState.UnconnectedState)
            self.assertFalse(provider.hostnames)

    def test_disabled_and_port_in_use_leave_title_fallback_working(self):
        first = self.provider()
        with self.assertLogs("niridashboard.browser_tabs", level="WARNING"):
            second = BrowserTabs(port=first.server.serverPort())
        self.addCleanup(second.close)
        self.assertFalse(second.server.isListening())
        self.assertNotIn("browser_hostname", second.decorate(window()))
        disabled = BrowserTabs(enabled=False)
        self.addCleanup(disabled.close)
        self.assertFalse(disabled.server.isListening())
