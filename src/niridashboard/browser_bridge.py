"""Shared loopback browser protocol and hostname resolution (no Qt dependencies)."""
import re

BRIDGE_PORT = 47831
MAX_MESSAGE = 131072
TOKEN = r"[0-9a-f]{32}:[0-9]+"
TITLE_PREFIX = re.compile(r"^\[ND:(" + TOKEN + r")\] ")
DOMAINS = {
    "chatgpt.com": "chatgpt", "youtube.com": "youtube",
    "calendar.google.com": "google_calendar", "mail.google.com": "gmail",
    "github.com": "github", "reddit.com": "reddit",
}


def site_for_hostname(hostname):
    host = hostname.lower().rstrip(".") if isinstance(hostname, str) else ""
    return next((site for domain, site in DOMAINS.items()
                 if host == domain or host.endswith("." + domain)), None)


def validate_windows(value):
    if not isinstance(value, dict) or len(value) > 1000:
        raise ValueError("Invalid browser snapshot")
    for token, host in value.items():
        if not re.fullmatch(TOKEN, token) or not isinstance(host, str):
            raise ValueError("Invalid browser window")
        if len(host) > 253 or (host and not re.fullmatch(r"[a-zA-Z0-9.:-]+", host)):
            raise ValueError("Expected a hostname, not a URL")
    return value

