# yt-dwnldr

Download videos and playlists from YouTube and other sites as mp4 files from the terminal.

The tool downloads videos in parallel, skips existing files, and saves each video into a folder by playlist.

**Supported links.** Any link [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports (YouTube, Instagram, Vimeo, X, and 1,700+ other sites), pages with embedded videos, and direct video file links. The site is detected from the link itself. Copy-protected streaming services (Netflix, Prime Video, and similar) are not supported.

## Requirements

- **uv.** Python package and project manager (`brew install uv`).
- **Google Chrome.** Optional. Needed only for videos that require a signed-in account, on any site.

## Quick start

1. **Clone and install.**

   ```bash
   git clone https://github.com/sahaarijit/yt-dwnldr.git
   cd yt-dwnldr
   uv sync
   ```

2. **Add links.** Put video or playlist URLs in a text file (such as `links.txt`), one per line or separated by commas.

   ```text
   https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxx
   https://www.youtube.com/watch?v=xxxxxxxxxxx
   https://www.instagram.com/reels/xxxxxxxxxxx/
   https://example.com/videos/clip.mp4
   ```

3. **Run.**

   ```bash
   uv run yt-dwnldr links.txt
   ```

Files save to `~/Downloads/yt-dwnldr/` by default. Playlists get their own numbered folder, and single videos go into `singles/`. Every file is saved as mp4. Sources in other formats are converted, which takes longer. Completed videos are skipped on future runs.

## Options

```bash
uv run yt-dwnldr links.txt --workers 4 --out ~/Movies/courses --chrome-profile "Profile 1"
```

| Option | Default | Description |
|---|---|---|
| `--workers` | `3` | Concurrent downloads (1 to 8). |
| `--out` | `~/Downloads/yt-dwnldr` | Output directory. |
| `--chrome-profile` | Most recent | Chrome profile folder from `chrome://version` (such as `Profile 1`). |

## Common fixes

- **Missing login warning.** Shown only when the links file has YouTube links. Sign into YouTube in Chrome. If you use multiple profiles, pass `--chrome-profile`.
- **macOS Keychain prompt.** Click **Always Allow** for "Chrome Safe Storage" to let the tool read session cookies.
- **Bot detection or rate limits.** Re-run with `--workers 1`.
- **Outdated extractor.** Update yt-dlp with `uv lock --upgrade-package yt-dlp && uv sync`.

## Tests

```bash
uv run pytest
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design details.

## License

[MIT License](LICENSE). The shortest license that works.
