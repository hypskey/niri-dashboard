# Icon sources

All artwork in this directory is bundled for offline use; NiriDashboard never
downloads an icon while it is running.

| Assets | Source |
| --- | --- |
| `whatsapp.svg`, `openai.svg`, `github.svg` | Supplied locally in the repository's `icons/` directory, then copied unchanged for runtime use. |
| `foundry-nuke.png` | Supplied locally as `icons/Foundry_Nuke.png`, copied unchanged for runtime use. |
| `youtube-rendered.png` | High-resolution local rendering of the supplied `assets/icons/youtube.svg`. Qt cannot render the nested SVG directly; its artwork and colors are otherwise unchanged. |
| `reddit.svg`, `github.svg`, `python.svg`, `docker.svg` | [Simple Icons](https://simpleicons.org), CC0-1.0; the original SVGs are available from its [icon repository](https://github.com/simple-icons/simple-icons). |
| `chatgpt.svg` | The [OpenAI Blossom Symbol](https://commons.wikimedia.org/wiki/File:OpenAI_logo_2025_(symbol).svg), an authentic OpenAI mark archived by Wikimedia Commons. |
| `google-*.png` | Official Google product artwork from `https://www.gstatic.com/images/branding/product/2x/<product>_48dp.png`. |
| `codex/pet-*.png` | Frame 000 from each real pet animation in the installed Codex TUI cache: `~/.codex/cache/tui-pets/frame-cache/<pet>/.../frames/frame_000.png`. |
| `terminal.svg`, `folder.svg`, `firefox.svg` | Locally installed HighContrast icon theme artwork (`/usr/share/icons/HighContrast`), bundled to avoid a runtime dependency on the selected system theme. |
| `zen.svg` | [Zen Browser’s official source repository](https://github.com/zen-browser/desktop/blob/dev/docs/assets/zen-dark.svg). |
