"""Small, local catalog of icons that can be assigned to individual windows."""
from dataclasses import dataclass
from pathlib import Path
import re


ICON_ASSET_DIRECTORY = Path(__file__).resolve().parents[2] / "assets" / "icons"


@dataclass(frozen=True)
class CatalogIcon:
    id: str
    name: str
    keywords: tuple[str, ...]
    icon_names: tuple[str, ...]
    asset: str | None = None

    @property
    def asset_path(self):
        """Bundled icon artwork, when this catalog entry has it."""
        return ICON_ASSET_DIRECTORY / self.asset if self.asset else None


CATALOG = (
    CatalogIcon("whatsapp", "WhatsApp", ("chat", "message", "web"), ("whatsapp", "whatsapp-desktop"), "whatsapp.svg"),
    CatalogIcon("youtube", "YouTube", ("video", "watch", "media"), ("youtube", "youtube-7"), "youtube-rendered.png"),
    CatalogIcon("chatgpt", "ChatGPT", ("openai", "ai", "assistant", "chat"), ("chatgpt", "openai"), "openai.svg"),
    CatalogIcon("proton-mail", "Proton Mail", ("mail", "email", "proton", "privacy"), ("protonmail", "proton-mail"), "proton-mail.svg"),
    CatalogIcon("reddit", "Reddit", ("community", "social", "web"), ("reddit", "reddit-alien"), "reddit.svg"),
    CatalogIcon("github", "GitHub", ("code", "git", "repository"), ("github",), "github.svg"),
    CatalogIcon("gmail", "Gmail", ("mail", "email", "google", "workspace"), ("gmail", "gmail-offline"), "google-gmail.png"),
    CatalogIcon("google-calendar", "Google Calendar", ("google", "calendar", "workspace", "schedule"), ("google-calendar", "google_calendar"), "google-calendar.png"),
    CatalogIcon("google-chat", "Google Chat", ("google", "chat", "workspace", "message"), ("google-chat", "google_chat"), "google-chat.png"),
    CatalogIcon("google-drive", "Google Drive", ("google", "drive", "workspace", "files"), ("google-drive", "google_drive"), "google-drive.png"),
    CatalogIcon("google-docs", "Google Docs", ("google", "docs", "workspace", "document"), ("google-docs", "google_docs"), "google-docs.png"),
    CatalogIcon("google-sheets", "Google Sheets", ("google", "sheets", "workspace", "spreadsheet"), ("google-sheets", "google_sheets"), "google-sheets.png"),
    CatalogIcon("google-slides", "Google Slides", ("google", "slides", "workspace", "presentation"), ("google-slides", "google_slides"), "google-slides.png"),
    CatalogIcon("google-maps", "Google Maps", ("google", "maps", "location", "navigation"), ("google-maps", "google_maps"), "google-maps.png"),
    CatalogIcon("google-meet", "Google Meet", ("google", "meet", "workspace", "video", "call"), ("google-meet", "google_meet"), "google-meet.png"),
    CatalogIcon("google-keep", "Google Keep", ("google", "keep", "workspace", "notes"), ("google-keep", "google_keep"), "google-keep.png"),
    CatalogIcon("codex-pet-01", "Codex Pet 01", ("codex", "openai", "pet", "worker"), ("codex",), "codex/pet-bsod.png"),
    CatalogIcon("codex-pet-02", "Codex Pet 02", ("codex", "openai", "pet", "worker"), ("codex",), "codex/pet-codex.png"),
    CatalogIcon("codex-pet-03", "Codex Pet 03", ("codex", "openai", "pet", "worker"), ("codex",), "codex/pet-dewey.png"),
    CatalogIcon("codex-pet-04", "Codex Pet 04", ("codex", "openai", "pet", "worker"), ("codex",), "codex/pet-fireball.png"),
    CatalogIcon("codex-pet-05", "Codex Pet 05", ("codex", "openai", "pet", "worker"), ("codex",), "codex/pet-null-signal.png"),
    CatalogIcon("codex-pet-06", "Codex Pet 06", ("codex", "openai", "pet", "worker"), ("codex",), "codex/pet-rocky.png"),
    CatalogIcon("codex-pet-07", "Codex Pet 07", ("codex", "openai", "pet", "worker"), ("codex",), "codex/pet-seedy.png"),
    CatalogIcon("codex-pet-08", "Codex Pet 08", ("codex", "openai", "pet", "worker"), ("codex",), "codex/pet-stacky.png"),
    CatalogIcon("python", "Python", ("code", "programming", "development"), ("python", "text-x-python"), "python.svg"),
    CatalogIcon("docker", "Docker", ("containers", "development"), ("docker", "folder-docker"), "docker.svg"),
    CatalogIcon("ssh", "SSH", ("server", "remote", "terminal"), ("ssh", "network-server", "utilities-terminal"), "terminal.svg"),
    CatalogIcon("terminal", "Terminal", ("shell", "console", "kitty"), ("utilities-terminal", "terminal", "kitty"), "terminal.svg"),
    CatalogIcon("folder", "Folder / project", ("files", "directory", "project"), ("folder", "folder-visiting"), "folder.svg"),
    CatalogIcon("nuke", "Nuke", ("compositing", "vfx", "foundry"), ("nuke",), "foundry-nuke.png"),
    CatalogIcon("firefox", "Firefox", ("browser", "web", "mozilla"), ("firefox", "firefox-icon"), "firefox.svg"),
    CatalogIcon("zen", "Zen Browser", ("browser", "web", "firefox"), ("zen-browser", "zen"), "zen.svg"),
)


class IconCatalog:
    def __init__(self, entries=CATALOG):
        self.base_entries = tuple(entries)
        self.entries = self.base_entries
        self.by_id = {entry.id: entry for entry in self.entries}

    def refresh_assets(self):
        """Discover local artwork without replacing curated catalog entries."""
        entries = list(self.base_entries)
        by_id = {entry.id: entry for entry in entries}
        used_assets = {entry.asset for entry in entries if entry.asset}
        extensions = {".svg": 0, ".svgz": 1, ".png": 2,
                      ".webp": 3, ".jpg": 4, ".jpeg": 5}
        try:
            files = [path for path in ICON_ASSET_DIRECTORY.rglob("*")
                     if path.is_file() and path.suffix.lower() in extensions]
        except OSError:
            files = []
        files.sort(key=lambda path: (path.relative_to(ICON_ASSET_DIRECTORY).with_suffix("").as_posix().casefold(),
                                     extensions[path.suffix.lower()]))
        for path in files:
            relative = path.relative_to(ICON_ASSET_DIRECTORY)
            if relative.as_posix() in used_assets:
                continue
            parts = [re.sub(r"[^a-z0-9]+", "-", part.casefold()).strip("-")
                     for part in (*relative.parts[:-1], path.stem)]
            icon_id = "-".join(part for part in parts if part)
            if not icon_id or icon_id in by_id:
                continue
            name = re.sub(r"[-_]+", " ", path.stem).strip().title()
            entry = CatalogIcon(icon_id, name, tuple(parts[:-1]), (path.stem,),
                                relative.as_posix())
            entries.append(entry)
            by_id[icon_id] = entry
        self.entries = tuple(entries)
        self.by_id = by_id

    def get(self, icon_id):
        return self.by_id.get(icon_id)

    def search(self, query=""):
        words = tuple(word for word in (query or "").casefold().split() if word)
        if not words:
            return self.entries
        return tuple(entry for entry in self.entries
                     if all(word in " ".join((entry.id, entry.name.casefold(), *entry.keywords))
                            for word in words))


DEFAULT_CATALOG = IconCatalog()
DEFAULT_CATALOG.refresh_assets()
