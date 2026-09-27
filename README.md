# yt-dwnldr

Download YouTube videos and playlists as mp4 files from the terminal.

The links go in a text file. The tool downloads several videos at once and shows a progress bar for each one. Every video is saved as its own mp4 file, sorted into a folder per playlist, for offline viewing.

## Requirements

- **uv.** It installs Python and every other piece the tool needs, including ffmpeg. Install it with `brew install uv` if it is not installed yet.
- **Google Chrome, signed into YouTube.** This is optional. Public videos download without it. Videos that need a signed-in account (age-restricted videos, for example) only download when the Chrome account can watch them.

## One-time setup

1. Clone the repository and open the folder.

   ```bash
   git clone https://github.com/sahaarijit/yt-dwnldr.git
   cd yt-dwnldr
   ```

2. Install everything.

   ```bash
   uv sync
   ```

   This creates a `.venv` folder inside the project, with the tool and its libraries. uv also keeps two shared folders in the home directory: a download cache (`~/.cache/uv`) and its own Python (`~/.local/share/uv/python`). Nothing is installed system-wide.

## Download videos, step by step

1. **Create a links file.** Make a text file, for example `links.txt`, in any folder. Put one link per line, or separate links with commas. Lines starting with `#` are ignored.

   ```text
   # courses
   https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxx
   https://www.youtube.com/watch?v=xxxxxxxxxxx&list=PLyyyyyyyyyyyyyyyy
   https://www.youtube.com/watch?v=zzzzzzzzzzz, https://youtu.be/wwwwwwwwwww
   ```

   A link with `list=` in it is treated as the whole playlist. Any other link is treated as a single video.

2. **Run the tool** from the project folder, with the path to the links file.

   ```bash
   uv run yt-dwnldr ~/Desktop/links.txt
   ```

3. **On a Mac, allow Keychain access the first time.** macOS asks whether the tool may use "Chrome Safe Storage". Click **Always Allow**. This is how the tool reads the YouTube login from Chrome. After a Deny, public videos still download, and the tool prints a yellow warning that no login was found.

4. **Watch the progress.** Each playlist is listed first, then the downloads start.

   | On screen | Meaning |
   |---|---|
   | `==> Playlist: <name> (N videos)` | A playlist was read, with N videos in it |
   | A cyan bar with `video`, `audio` or `merging` | A download in progress. Each video downloads its picture and its sound separately, then joins them into one mp4. |
   | A cyan bar with `retrying` | The last attempt failed. The tool waits 20 seconds, reads the login from Chrome again, and tries once more. Each video gets 3 attempts in total. |
   | Green `✔ ... Downloaded 212.4 MB` | The video is saved |
   | Yellow `↷ ... already downloaded` | The file is already in its folder, so it was skipped |
   | Yellow `↷ ... unavailable on YouTube` | The video was deleted or made private, so there is nothing to download |
   | Green `✔ ... Copied from another playlist` | The same video is in two of the listed playlists. It downloaded once, and this folder got its own copy with this playlist's number. |
   | Red `✗ ... failed`, with a reason below | This attempt did not work. The others carry on. |
   | `==> Retrying N failed videos (round 1 of 3)` | After the main pass, the tool waits 30 seconds, reads the login again, and tries every failed video once more. It does this up to 3 times. |
   | `Overall` bar at the bottom | How many videos are done, downloading, and waiting |

   A summary table prints at the end. It counts videos downloaded, copied, skipped, unavailable, and failed. Only videos that still failed after every retry round are counted as failed.

5. **Find the files.** By default they go to `~/Downloads/yt-dwnldr`.

   ```text
   ~/Downloads/yt-dwnldr/
     <playlist name>/
       001 - <first video title>.mp4
       002 - <second video title>.mp4
     singles/
       <video title>.mp4
   ```

   Playlist videos are numbered in playlist order, so they sort correctly in Finder. Every playlist folder is complete. If a video is in two playlists, each folder has it under its own number. The second one is a hard link, which shows the same file in two places without using extra disk space.

## Options

```bash
uv run yt-dwnldr links.txt --workers 4 --out ~/Movies/courses --chrome-profile "Profile 1"
```

| Option | Default | What it does |
|---|---|---|
| `--workers` | `3` | How many videos download at the same time, from 1 to 8 |
| `--out` | `~/Downloads/yt-dwnldr` | The folder to save videos into. It is created if it does not exist. |
| `--chrome-profile` | the profile whose cookies changed most recently | Which Chrome profile to read the YouTube login from |

Quality is always up to 1080p.

### Finding the Chrome profile name

Without `--chrome-profile`, the tool uses whichever profile Chrome saved cookies for last. With several profiles signed into different YouTube accounts, that choice can change between runs. Passing the profile name every time keeps the tool on the same account.

1. **Open the profile.** In Chrome, open the profile that is signed into YouTube.
2. **Open the version page.** Go to `chrome://version`.
3. **Read the name.** Look at **Profile Path**. The last part of it is the name to use, such as `Default` or `Profile 1`.

## Stopping and resuming

- **To stop,** press Ctrl+C. The tool stops the active downloads, prints the summary, and exits.
- **To resume,** run the exact same command again. Finished videos are skipped. Half-finished videos continue from where they stopped.

The tool decides what is already done by looking at the files in the `--out` folder. To download a video again, delete its file and run the same command.

## Troubleshooting

| Problem | Fix |
|---|---|
| Yellow warning: no YouTube login found in Chrome | Sign into YouTube in Chrome. With several Chrome profiles, pass `--chrome-profile`. On a Mac, after a Deny on the Keychain prompt, run again and click Always Allow. |
| A video fails with "Sign in to confirm you're not a bot" | YouTube is limiting requests. Wait a while, then run again with fewer workers, such as `--workers 1`. |
| Many videos fail at once after YouTube changes something | Update yt-dlp, the library that does the downloading: `uv lock --upgrade-package yt-dlp && uv sync` |
| Nothing happens for a long time at the start | On a Mac, macOS is probably waiting on the Keychain prompt. Look for it behind other windows. |
| Videos that need a login start failing partway through a long run | YouTube keeps replacing login cookies while it is open in Chrome. The tool reads the login from Chrome again every 2 minutes, before each retry, and before each retry round. If videos still fail after all that, close the YouTube tabs in that Chrome profile while downloading, and run the same command again. Only the missing videos are tried. |

The tool exits with code `0` when everything worked, `1` when any video still failed after the retry rounds, `2` when the links file is missing or empty, and `130` after Ctrl+C.

## Development

Every change goes through a pull request into `main`. The tests run automatically on each pull request, and a pull request can only be merged once they pass.

Run the tests:

```bash
uv run pytest
```

To understand the code:

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** explains how the parts fit together, and why they were built this way.
- **[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)** goes through every file, function by function, in plain words.

## Responsible use

Download only videos with the right to keep them, for personal offline viewing. Respect the creators and YouTube's Terms of Service.

## License

Released under the [MIT License](LICENSE). The tool is free to use, change, and share, as long as the copyright notice with the author credit (sahaarijit) stays in every copy.
