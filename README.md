# yt-dwnldr

Download YouTube videos and playlists as mp4 files from the terminal.

The tool downloads videos in parallel, skips existing files, and saves each video into a folder by playlist.

## Requirements

- **uv.** Python package and project manager (`brew install uv`).
- **Google Chrome.** Optional. Needed only for age-restricted or private videos your account can view.

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
   ```

3. **Run.**

   ```bash
   uv run yt-dwnldr links.txt
   ```

Files save to `~/Downloads/yt-dwnldr/` by default. Completed videos are skipped on future runs.

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

- **Missing login warning.** Sign into YouTube in Chrome. If you use multiple profiles, pass `--chrome-profile`.
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
