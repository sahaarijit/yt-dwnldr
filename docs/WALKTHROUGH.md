# Code walkthrough

This page walks through every file in yt-dwnldr, in the order the data flows. By the end, what every function does, and why it is there, should be clear.

For the big picture first, read [ARCHITECTURE.md](ARCHITECTURE.md).

## Before starting

**Setup.** Clone the repo and run `uv sync`. Then run the tests with `uv run pytest`. They all pass without a network connection.

**Reading order.** The files are covered from the bottom up. Each file only uses files that came before it, so no name shows up before it has been explained.

1. **`links.py`** reads the links file.
2. **`ytdl.py`** holds shared yt-dlp settings.
3. **`cookie_store.py`** keeps the login fresh.
4. **`catalog.py`** lists the videos behind each link.
5. **`layout.py`** names the files.
6. **`downloader.py`** downloads one video.
7. **`ui.py`** draws the screen.
8. **`cli.py`** ties it all together.

**A few words used below.**

- **yt-dlp** is the open-source tool that does the talking to YouTube. This project uses it as a Python library.
- **Cookies** are small pieces of data a browser keeps. YouTube uses them to recognize a signed-in account.
- **A worker** is a thread: a separate line of work that Python runs at the same time as others. Each worker downloads one video at a time.
- **A dataclass** is a simple Python record: a class that just holds a few named values.
- **Constants** are the `UPPER_CASE` names at the top of each file. Every fixed number or text lives there, so each one can be changed in one place.

---

## 1. `links.py`: read the links file

This file turns the links file into a clean list of links.

```python
from pathlib import Path

COMMENT_PREFIX = "#"
LINK_SEPARATOR = ","


def read_links(links_file: Path) -> list[str]:
    links = []
    for line in links_file.read_text().splitlines():
        if line.strip().startswith(COMMENT_PREFIX):
            continue
        links.extend(part.strip() for part in line.split(LINK_SEPARATOR))
    return list(dict.fromkeys(link for link in links if link))
```

- **The two constants.** A line that starts with `#` is a comment. Links can be separated by commas.
- **The loop.** For each line, skip it if it is a comment. Otherwise split it on commas and strip spaces from each part. A line with no commas stays one link.
- **The last line does two things, so here they are one at a time.** `link for link in links if link` drops empty entries (like the gap in `a,,b`). `dict.fromkeys(...)` drops repeated links but keeps the first one in its place. A Python dictionary cannot hold the same key twice, and it keeps keys in the order they were added. `list(...)` turns it back into a list.

---

## 2. `ytdl.py`: shared yt-dlp settings

Several files create their own copy of yt-dlp. This file holds what they all share.

```python
import io

from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser
from yt_dlp.utils import DownloadError

BROWSER = "chrome"
ERROR_PREFIX = "ERROR: "
ERROR_HINTS = {
    "not a bot": " (YouTube is limiting requests, retry later with fewer --workers)",
}
```

- **`BROWSER`** is the browser the login is read from.
- **`ERROR_PREFIX`** is the text yt-dlp puts at the start of every error. It is removed before the message is shown.
- **`ERROR_HINTS`** adds a tip to a known error. If YouTube says "confirm you're not a bot", the tip suggests slowing down.

```python
# Without a logger, yt-dlp prints straight to the terminal and tears the live display.
class SilentLogger:
    def debug(self, message: str) -> None:
        pass

    info = warning = error = debug
```

yt-dlp normally prints its own messages to the terminal. That would break the live progress bars. When yt-dlp is given a "logger" object, it sends every message there instead. This one has four methods (`debug`, `info`, `warning`, `error`), and all of them do nothing. The last line makes the other three point at the same empty method.

```python
# Each yt-dlp instance that reads Chrome itself asks the macOS Keychain again, so the tool reads Chrome and hands out the text.
def read_chrome_cookies(chrome_profile: str | None) -> YoutubeDLCookieJar:
    return extract_cookies_from_browser(BROWSER, chrome_profile)
```

This reads the cookies from one Chrome profile, using a function yt-dlp provides. It is the only place in the code that reads Chrome. On a Mac, reading Chrome can make macOS ask for Keychain permission. Reading from one place keeps that to one prompt.

```python
def cookie_text(cookie_jar: YoutubeDLCookieJar) -> str:
    buffer = io.StringIO()
    cookie_jar.save(buffer)
    return buffer.getvalue()
```

This turns the cookies into plain text. `io.StringIO()` is a piece of text in memory that behaves like a file. yt-dlp's `save` writes the cookies into it, and `getvalue()` returns them as one string. Text is easy to share between workers.

```python
def base_options(cookies: str) -> dict:
    return {
        "cookiefile": io.StringIO(cookies),
        "logger": SilentLogger(),
        "noprogress": True,
    }
```

These are the settings every yt-dlp copy starts with.

- **`cookiefile`** gives yt-dlp the cookies. yt-dlp accepts a file name here, or text that behaves like a file, so the text is wrapped in a fresh `StringIO`.
- **`logger`** is the silent logger from above.
- **`noprogress`** turns off yt-dlp's own progress line. The tool draws its own.

```python
def error_reason(error: DownloadError) -> str:
    first_line = str(error).splitlines()[0].removeprefix(ERROR_PREFIX)
    hint = next((hint for marker, hint in ERROR_HINTS.items() if marker in first_line), "")
    return first_line + hint
```

This turns a yt-dlp error into one short line for the screen.

1. **Shorten it.** Take only the first line of the error, and remove the `ERROR: ` at the start.
2. **Find a tip.** Look for a known phrase from `ERROR_HINTS`. `next(..., "")` returns the first matching tip, or an empty string if nothing matches.
3. **Return it.** Give back the message with the tip added.

---

## 3. `cookie_store.py`: keep the login fresh

YouTube keeps replacing login cookies while it is open in Chrome. A copy taken at the start of a long run goes stale, and videos that need the login start to fail. This file keeps every worker on recent cookies.

```python
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

REFRESH_INTERVAL_SECONDS = 120
RENEW_MIN_GAP_SECONDS = 15


@dataclass(frozen=True)
class Cookies:
    version: int
    text: str
```

- **`REFRESH_INTERVAL_SECONDS`**: when the last read is this old, the next request re-reads Chrome.
- **`RENEW_MIN_GAP_SECONDS`**: the shortest gap allowed between two reads, so that failures do not make the tool read Chrome over and over.
- **`Cookies`** is one read: its text, plus a version number that goes up by one each time Chrome is read. `frozen=True` means the record cannot be changed after it is made.

```python
# YouTube swaps login cookies while it is open in Chrome, so a long run keeps re-reading Chrome.
class CookieStore:
    def __init__(self, read_cookies: Callable[[], str], initial: str, clock: Callable[[], float] = time.monotonic):
        self._read_cookies = read_cookies
        self._clock = clock
        self._lock = threading.Lock()
        self._cookies = Cookies(version=1, text=initial)
        self._read_at = clock()
```

- **`read_cookies`** is the function that reads Chrome. The store does not know how. `cli.py` passes that in. This also lets the tests pass in a fake.
- **`initial`** is the first read, which `cli.py` already did.
- **`clock`** tells the time. It defaults to `time.monotonic`, a clock that only moves forward. The tests pass in a fake clock they can move by hand.
- **`self._lock`** makes sure only one worker reads Chrome at a time.

```python
    def latest(self) -> Cookies:
        with self._lock:
            if self._age() >= REFRESH_INTERVAL_SECONDS:
                self._reread()
            return self._cookies
```

Workers call `latest()` before every video. If the cookies are 2 minutes old or more, it re-reads Chrome first. Everything runs inside `with self._lock`, so two workers cannot trigger two reads at once.

```python
    def renew(self, stale_version: int) -> Cookies:
        with self._lock:
            is_already_renewed = self._cookies.version > stale_version
            if not is_already_renewed and self._age() >= RENEW_MIN_GAP_SECONDS:
                self._reread()
            return self._cookies
```

A worker calls `renew()` before it retries a failed download. It passes the version it was using.

- **Another worker already renewed.** If the store's version is newer than the one passed in, the worker gets those cookies, and Chrome is not read again.
- **Not renewed yet.** The store re-reads Chrome, as long as at least 15 seconds have passed since the last read.

```python
    def _age(self) -> float:
        return self._clock() - self._read_at

    def _reread(self) -> None:
        self._cookies = Cookies(version=self._cookies.version + 1, text=self._read_cookies())
        self._read_at = self._clock()
```

Two small helpers. `_age()` says how many seconds ago Chrome was last read. `_reread()` reads Chrome, raises the version by one, and records the time. The leading underscore on their names means they are only meant to be used inside this class.

---

## 4. `catalog.py`: list the videos behind each link

This file asks YouTube what is behind each link, without downloading anything.

```python
from dataclasses import dataclass
from http.cookiejar import CookieJar
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from yt_dwnldr.ytdl import error_reason

PLAYLIST_PARAM = "list"
PLAYLIST_URL = "https://www.youtube.com/playlist?list={}"
WATCH_URL = "https://www.youtube.com/watch?v={}"
YOUTUBE_DOMAIN = "youtube.com"
LOGIN_COOKIES = {"SAPISID", "__Secure-3PAPISID", "LOGIN_INFO"}
SINGLES_FOLDER = "singles"
POSITION_WIDTH = 3
FIRST_POSITION = 1
UNAVAILABLE_TITLE = "(unavailable video)"
```

- **The URL constants.** A link is a playlist when it has a `list=` part. Every playlist is read through its plain `playlist?list=` address, and every video is downloaded through its `watch?v=` address.
- **`LOGIN_COOKIES`** are the cookie names that only exist when a YouTube account is signed in.
- **The rest control file names.** Numbers are padded to 3 digits (`007`), playlists count from 1, and videos with no title get a readable name.

```python
@dataclass(frozen=True)
class Video:
    video_id: str
    title: str | None
    folder: str
    prefix: str

    @property
    def url(self) -> str:
        return WATCH_URL.format(self.video_id)

    # YouTube lists deleted and private videos in a playlist without a title.
    @property
    def is_available(self) -> bool:
        return self.title is not None

    @property
    def name(self) -> str:
        return f"{self.prefix}{self.title or UNAVAILABLE_TITLE}"
```

`Video` is one video in one place.

- **`video_id`** is YouTube's short ID, like `jNQXAC9IVRw`.
- **`folder`** is the playlist name, or `singles`.
- **`prefix`** is the number in front of the file name, like `007 - `. It is empty for single videos.
- **`title`** can be missing. YouTube lists deleted and private videos in a playlist without a title. `is_available` checks for exactly that.
- **`name`** is what shows on screen: the number plus the title, or "(unavailable video)".

The same YouTube video can appear in two playlists. That gives two `Video` records with the same ID but different folders and numbers. That is on purpose. Each playlist folder should get its own numbered file.

```python
@dataclass(frozen=True)
class Batch:
    link: str
    title: str
    videos: list[Video]
    is_playlist: bool
    error: str | None = None
```

`Batch` is what one line of the links file turned into: a playlist with many videos, or one single video. If YouTube could not read the link, `videos` is empty and `error` says why.

```python
def is_playlist_link(link: str) -> bool:
    return PLAYLIST_PARAM in parse_qs(urlparse(link).query)


# A watch?v=...&list=... link resolves to a pointer to the playlist, not the playlist itself.
def playlist_link(link: str) -> str:
    playlist_id = parse_qs(urlparse(link).query)[PLAYLIST_PARAM][0]
    return PLAYLIST_URL.format(playlist_id)
```

`is_playlist_link` checks for `list=` in the link. `playlist_link` pulls out the playlist ID and builds the plain playlist address. It is needed because a link like `watch?v=abc&list=xyz` makes YouTube return only a pointer to the playlist, not the playlist itself.

```python
def has_youtube_login(cookie_jar: CookieJar) -> bool:
    return any(cookie.name in LOGIN_COOKIES and cookie.domain.endswith(YOUTUBE_DOMAIN) for cookie in cookie_jar)
```

This checks whether any cookie in the jar is a login cookie for `youtube.com`. If none is, `cli.py` prints a warning.

```python
def playlist_videos(playlist_info: dict) -> list[Video]:
    folder = playlist_info["title"]
    return [
        Video(
            video_id=entry["id"],
            title=entry.get("title"),
            folder=folder,
            prefix=f"{position:0{POSITION_WIDTH}d} - ",
        )
        for position, entry in enumerate(playlist_info["entries"], start=FIRST_POSITION)
    ]


def single_video(video_info: dict) -> Video:
    return Video(video_id=video_info["id"], title=video_info["title"], folder=SINGLES_FOLDER, prefix="")
```

- **`playlist_videos`** turns a playlist into `Video` records. `enumerate(..., start=1)` counts the videos from 1. The number is formatted to 3 digits, so video 7 becomes `007 - `. Every video gets the playlist title as its folder.
- **`single_video`** makes one `Video` for a link that is not a playlist. It goes in the `singles` folder with no number.

```python
def expand(ydl: YoutubeDL, link: str) -> Batch:
    is_playlist = is_playlist_link(link)
    source = playlist_link(link) if is_playlist else link
    try:
        info = ydl.extract_info(source, download=False, process=False)
        # Playlist entries load lazily, page by page, so paging errors surface here too.
        videos = playlist_videos(info) if is_playlist else [single_video(info)]
    except DownloadError as error:
        return Batch(link=link, title=link, videos=[], is_playlist=is_playlist, error=error_reason(error))
    return Batch(link=link, title=info["title"], videos=videos, is_playlist=is_playlist)
```

`expand` turns one link into a `Batch`.

1. **Pick the address.** Decide if the link is a playlist. If it is, switch to the plain playlist address.
2. **Ask YouTube.** Ask yt-dlp about the link. `download=False` means only look. `process=False` means do not look up every video in full, which is much faster for a long playlist.
3. **Build the records.** Build the `Video` records inside the same `try`. YouTube sends a long playlist in pages, and later pages are fetched while the list is being read. So an error can happen here too.
4. **Keep going on errors.** If anything fails, return a `Batch` with the error instead of crashing. The other links still get processed.

---

## 5. `layout.py`: name the files, place the copies

This file decides where each video goes on disk.

```python
import os
import shutil
from pathlib import Path

from yt_dlp import YoutubeDL

from yt_dwnldr.catalog import Video
from yt_dwnldr.ytdl import SilentLogger

OUTPUT_TEMPLATE = "%(ytdw_folder)s/%(ytdw_prefix)s%(title)s.%(ext)s"
FINAL_EXTENSION = "mp4"


def output_options(out_dir: Path) -> dict:
    return {
        "paths": {"home": str(out_dir)},
        "outtmpl": OUTPUT_TEMPLATE,
        # Singles have an empty prefix, which yt-dlp would otherwise print as "NA".
        "outtmpl_na_placeholder": "",
    }


def extra_fields(video: Video) -> dict:
    return {"ytdw_folder": video.folder, "ytdw_prefix": video.prefix}
```

- **`OUTPUT_TEMPLATE`** is the file name pattern, in yt-dlp's format. `%(title)s` is the video title and `%(ext)s` is the file type. `ytdw_folder` and `ytdw_prefix` are two extra fields this project adds, for the playlist folder and the number.
- **`output_options`** is the yt-dlp settings for that pattern. `paths` sets the output folder. `outtmpl_na_placeholder` is set to empty text, because yt-dlp would otherwise print an empty number as `NA`.
- **`extra_fields`** fills those two fields for one video.

```python
# yt-dlp builds these names the same way it names the downloaded file, so they match.
def file_paths(videos: list[Video], out_dir: Path) -> dict[Video, Path]:
    with YoutubeDL(output_options(out_dir) | {"logger": SilentLogger()}) as ydl:
        return {
            video: Path(ydl.prepare_filename(
                {"id": video.video_id, "title": video.title, "ext": FINAL_EXTENSION} | extra_fields(video),
            ))
            for video in videos
        }
```

This works out the full file path for every video, before anything downloads. It uses yt-dlp's own `prepare_filename`, the same function yt-dlp uses when it saves the file. So both paths always match, including how yt-dlp replaces characters like `/` and `:` that file names cannot hold. That match is what lets the tool check "is this video already downloaded" just by looking for the file.

It returns a dictionary from each `Video` to its path.

```python
# A hard link shows one file in two folders without using more disk space.
def place_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        # Hard links fail across drives and on some file systems, so fall back to a real copy.
        shutil.copy2(source, target)
```

This puts a video that is already on disk into another folder.

1. **Make the folder.** Create the target folder if it does not exist.
2. **Link the file.** Make a hard link. A hard link is a second name for the same file on disk. It shows up in both folders and uses no extra space.
3. **Copy if linking fails.** Some setups do not allow hard links, for example when the two folders are on different drives. Then the tool makes a normal copy instead.

---

## 6. `downloader.py`: download one video

Each worker owns one `Downloader`. It downloads one video at a time and reports progress as it goes.

```python
import random
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadCancelled, DownloadError

from yt_dwnldr.catalog import Video
from yt_dwnldr.cookie_store import Cookies, CookieStore
from yt_dwnldr.layout import extra_fields, output_options
from yt_dwnldr.ytdl import base_options
```

The imports bring in three kinds of things. `random` and `threading` come with Python, for the random pause and the stop flag. The stop flag is a shared on/off signal that Ctrl+C turns on, and every worker can see it. `imageio_ffmpeg` and `yt_dlp` are the installed packages. The rest are the files covered above.

```python
FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b"
MERGE_FORMAT = "mp4"
NO_VIDEO_CODEC = "none"
MERGER = "Merger"
PAUSE_MIN_SECONDS = 3
PAUSE_MAX_SECONDS = 8
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 20

STAGE_VIDEO = "video"
STAGE_AUDIO = "audio"
STAGE_MERGING = "merging"
STAGE_RETRYING = "retrying"
```

- **`FORMAT`** picks the quality, in yt-dlp's format language. Read the `/` as "or else": first, the best mp4 video up to 1080p plus m4a sound. Failing that, a single mp4 file up to 1080p. Then any video up to 1080p plus any sound. Last of all, the best single file.
- **`MERGE_FORMAT`** makes the final file mp4.
- **`NO_VIDEO_CODEC`** is how yt-dlp marks a part that is sound only, with no picture.
- **`MERGER`** is the name of the yt-dlp step that joins picture and sound.
- **The pause, attempt, and retry numbers** control the short break after each video and the retries after a failure.
- **The `STAGE_` names** are the four labels shown on a progress bar.

```python
@dataclass(frozen=True)
class ProgressEvent:
    video_id: str
    stage: str
    done_bytes: int
    total_bytes: int | None
    speed: float | None
    eta: float | None


def stage_of(format_info: dict) -> str:
    return STAGE_AUDIO if format_info.get("vcodec") == NO_VIDEO_CODEC else STAGE_VIDEO


def event_from_hook(video_id: str, hook: dict) -> ProgressEvent:
    return ProgressEvent(
        video_id=video_id,
        stage=stage_of(hook["info_dict"]),
        done_bytes=hook.get("downloaded_bytes", 0),
        total_bytes=hook.get("total_bytes") or hook.get("total_bytes_estimate"),
        speed=hook.get("speed"),
        eta=hook.get("eta"),
    )
```

- **`ProgressEvent`** is one progress report: which video, which stage, how many bytes are done, the total if known, the speed, and the time left.
- **`stage_of`** says whether yt-dlp is downloading the picture or the sound. yt-dlp marks the sound part by setting its `vcodec` (picture format) to `none`.
- **`event_from_hook`** turns yt-dlp's report into a `ProgressEvent`. yt-dlp calls these reports "hooks". Sometimes yt-dlp knows the exact total size, and sometimes only an estimate, so the code takes whichever one is there.

```python
# A failure can come from login cookies YouTube just replaced, so each retry runs with fresh ones.
def run_with_retries(attempt: Callable[[], Path], before_retry: Callable[[], None], is_stopped: Callable[[], bool]) -> Path:
    attempts_left = MAX_ATTEMPTS
    while True:
        try:
            return attempt()
        except DownloadError:
            attempts_left -= 1
            if attempts_left == 0 or is_stopped():
                raise
            before_retry()
            if is_stopped():
                raise
```

This is the retry loop. It is a plain function so the tests can check it without the network.

1. **Try.** Call `attempt()`. If it works, return its result.
2. **Count.** If it fails with a download error, count one attempt used.
3. **Give up when done.** If no attempts are left, or Ctrl+C was pressed, pass the error on. A bare `raise` re-raises the same error.
4. **Get ready and loop.** Otherwise run `before_retry()` (wait and refresh the login), check for Ctrl+C once more, and go around again.

```python
class Downloader:
    def __init__(
        self,
        out_dir: Path,
        cookie_store: CookieStore,
        on_progress: Callable[[ProgressEvent], None],
        stop: threading.Event,
    ):
        self._out_dir = out_dir
        self._cookie_store = cookie_store
        self._on_progress = on_progress
        self._stop = stop
        self._video_id = ""
        self._cookies = cookie_store.latest()
        self._ydl = self._build_ydl()

    def download(self, video: Video) -> Path:
        self._video_id = video.video_id
        self._use(self._cookie_store.latest())
        return run_with_retries(
            attempt=lambda: self._download_once(video),
            before_retry=self._prepare_retry,
            is_stopped=self._stop.is_set,
        )
```

- **The constructor** keeps what it is given: the output folder, the cookie store, a function to send progress to, and the shared stop flag. It then gets the latest cookies and builds its yt-dlp copy.
- **`download`** first makes sure its yt-dlp copy has the newest cookies. Then it runs the retry loop, passing in three small functions: how to attempt, what to do before a retry, and how to check for Ctrl+C. The first one is written as a `lambda`, which is a small function with no name, written in one line.

```python
    def pause(self) -> None:
        self._stop.wait(random.uniform(PAUSE_MIN_SECONDS, PAUSE_MAX_SECONDS))

    def _download_once(self, video: Video) -> Path:
        info = self._ydl.extract_info(video.url, extra_info=extra_fields(video))
        return Path(info["requested_downloads"][0]["filepath"])
```

- **`pause`** waits a random 3 to 8 seconds. It uses `self._stop.wait(...)` instead of a normal sleep, so Ctrl+C ends the wait at once.
- **`_download_once`** does one real download. `extract_info` both looks up and downloads the video. `extra_info` passes in the folder and number fields for the file name. When it finishes, yt-dlp reports where the final file is.

```python
    def _prepare_retry(self) -> None:
        self._on_progress(ProgressEvent(self._video_id, STAGE_RETRYING, 0, None, None, None))
        self._stop.wait(RETRY_DELAY_SECONDS)
        self._use(self._cookie_store.renew(self._cookies.version))

    def _use(self, cookies: Cookies) -> None:
        if cookies.version == self._cookies.version:
            return
        self._ydl.close()
        self._cookies = cookies
        self._ydl = self._build_ydl()
```

- **`_prepare_retry`** runs between attempts. It tells the screen to show `retrying`, waits 20 seconds (or less, if Ctrl+C is pressed), and asks the cookie store for fresh cookies.
- **`_use`** switches to new cookies. If the version is the same, nothing changes. Otherwise it closes the old yt-dlp copy and builds a new one. yt-dlp reads cookies when it starts, so a new copy is the simplest way to hand it new ones.

```python
    def _build_ydl(self) -> YoutubeDL:
        return YoutubeDL(base_options(self._cookies.text) | output_options(self._out_dir) | {
            "format": FORMAT,
            "merge_output_format": MERGE_FORMAT,
            "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
            "progress_hooks": [self._on_download_hook],
            "postprocessor_hooks": [self._on_postprocess_hook],
        })
```

This builds a yt-dlp copy by joining three sets of settings with `|`: the shared ones from `ytdl.py`, the file name ones from `layout.py`, and the download ones here. The `ffmpeg_location` points yt-dlp at the ffmpeg that came with the `imageio-ffmpeg` package. The two hook lists are the functions yt-dlp calls to report progress.

```python
    # A running download cannot be stopped from outside its thread, so the hook stops it.
    def _on_download_hook(self, hook: dict) -> None:
        if self._stop.is_set():
            raise DownloadCancelled("Stopped by user")
        if hook["status"] == "downloading":
            self._on_progress(event_from_hook(self._video_id, hook))

    def _on_postprocess_hook(self, hook: dict) -> None:
        if hook["postprocessor"] == MERGER and hook["status"] == "started":
            self._on_progress(ProgressEvent(self._video_id, STAGE_MERGING, 0, None, None, None))
```

- **`_on_download_hook`** is called by yt-dlp many times a second while it downloads. First it checks the stop flag. A running download cannot be stopped from another thread, so this is where Ctrl+C takes effect: raising `DownloadCancelled` ends the download. Then it turns the report into a `ProgressEvent` and sends it on.
- **`_on_postprocess_hook`** is called when yt-dlp runs a step after the download. When the joining step starts, it sends a `merging` event.

---

## 7. `ui.py`: draw the screen

Everything on screen comes from this file. It uses the rich library.

```python
from datetime import timedelta
from threading import Lock

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.filesize import decimal
from rich.live import Live
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Column, Table
from rich.text import Text

from yt_dwnldr.catalog import Batch, Video
from yt_dwnldr.downloader import STAGE_MERGING, STAGE_RETRYING, ProgressEvent
```

Most imports are rich building blocks: `Console` prints, `Live` redraws an area in place, `Progress` draws bars, `Table` lays out columns, and `Text` holds colored text. `Lock` comes with Python. The last two lines bring in the records and stage names from the files above.

```python
NAME_MIN_WIDTH = 16
BAR_MIN_WIDTH = 10
REFRESH_PER_SECOND = 10
RIGHT_MARGIN = 1
MERGE_TOTAL = 1
FAILURE_INDENT = "    "

DONE_MARK = ("✔", "bold green")
SKIP_MARK = ("↷", "bold yellow")
FAIL_MARK = ("✗", "bold red")
HEADER_MARK = ("==>", "bold blue")

SUMMARY_ROWS = (
    ("Downloaded", "green"),
    ("Copied", "green"),
    ("Skipped", "yellow"),
    ("Unavailable", "yellow"),
)
```

- **The widths** stop names and bars from shrinking to nothing in a narrow window.
- **`RIGHT_MARGIN`** keeps the live area one column narrower than the window. The reason is explained below.
- **`MERGE_TOTAL`** is used to show a full bar while merging.
- **The marks** are the colored symbols at the start of each line.
- **`SUMMARY_ROWS`** lists the rows of the final table, with their colors.

```python
def detail_text(event: ProgressEvent) -> str:
    if event.stage in (STAGE_MERGING, STAGE_RETRYING):
        return event.stage
    size = decimal(event.done_bytes)
    if event.total_bytes:
        size = f"{size}/{decimal(event.total_bytes)}"
    parts = [event.stage, size]
    if event.speed:
        parts.append(f"{decimal(int(event.speed))}/s")
    if event.eta is not None:
        parts.append(f"{timedelta(seconds=int(event.eta))} left")
    return "  ".join(parts)


def counts_text(finished: int, active: int, total: int) -> str:
    queued = total - finished - active
    return f"{finished}/{total} videos · {active} downloading · {queued} queued"
```

- **`detail_text`** builds the gray text after a bar, like `video  1.0 MB/4.0 MB  500.0 kB/s  0:00:06 left`. Merging and retrying show just the word. `decimal` turns bytes into sizes like `4.0 MB`. `timedelta` turns seconds into `0:00:06`.
- **`counts_text`** builds the text on the Overall bar, like `12/42 videos · 3 downloading · 27 queued`.

```python
def status_line(mark: tuple[str, str], name: str, status: Text) -> Table:
    line = Table.grid(expand=True)
    line.add_column(no_wrap=True, overflow="ellipsis")
    line.add_column(justify="right", no_wrap=True)
    line.add_row(Text.assemble(mark, " ", name), status)
    return line
```

This builds one finished line: a mark and a name on the left, a status on the right. It is a table with two columns and no borders. `expand=True` stretches it to the full width, which pushes the status to the right edge. A long name is cut short with `…` instead of wrapping onto a second line.

```python
def print_login_warning(console: Console) -> None:
    console.print(Text.assemble(
        ("! ", "bold yellow"),
        ("No YouTube login found in Chrome. ", "yellow"),
        "Public videos will download. Videos that need a signed-in account will fail. "
        "Log into YouTube in Chrome, or pick a profile with --chrome-profile.",
    ))


def print_batches(console: Console, batches: list[Batch]) -> None:
    single_count = 0
    for batch in batches:
        if batch.error:
            console.print(Text.assemble(FAIL_MARK, f" Could not read {batch.link}: ", (batch.error, "red")))
        elif batch.is_playlist:
            console.print(Text.assemble(HEADER_MARK, (f" Playlist: {batch.title}", "bold"), f" ({len(batch.videos)} videos)"))
        else:
            single_count += 1
    if single_count:
        console.print(Text.assemble(HEADER_MARK, (" Single videos", "bold"), f" ({single_count})"))
```

- **`print_login_warning`** prints the yellow note when no YouTube login was found.
- **`print_batches`** prints one `==>` header per playlist, a red line for any link that could not be read, and one header for all single videos together.

```python
def print_skipped(console: Console, video: Video, reason: str) -> None:
    console.print(status_line(SKIP_MARK, video.name, Text(reason, style="yellow")))


def copied_line(video: Video) -> Table:
    return status_line(DONE_MARK, video.name, Text("Copied from another playlist", style="green"))


def print_retry_round(console: Console, round_number: int, total_rounds: int, count: int) -> None:
    console.print(Text.assemble(
        HEADER_MARK,
        (f" Retrying {count} failed {'video' if count == 1 else 'videos'}", "bold"),
        f" (round {round_number} of {total_rounds})",
    ))


def print_summary(console: Console, counts: dict[str, int], failures: list[tuple[str, str]]) -> None:
    table = Table(title="Summary", title_style="bold", show_header=False)
    for label, style in SUMMARY_ROWS:
        table.add_row(Text(label, style=style), str(counts[label]))
    table.add_row(Text("Failed", style="red"), str(len(failures)))
    console.print(table)
    for name, reason in failures:
        console.print(Text.assemble(FAIL_MARK, f" {name}: ", (reason, "red")))
```

- **`print_skipped`** prints a yellow line, for "already downloaded" or "unavailable".
- **`copied_line`** builds the green line for a video placed from another playlist.
- **`print_retry_round`** prints the header before each retry round. It says "video" for one and "videos" for more.
- **`print_summary`** prints the final table, then one red line per video that still failed.

```python
# Terminals lose track of the cursor after a line that fills the full width, which breaks the live redraw.
class RightMargin:
    def __init__(self, renderable: RenderableType):
        self._renderable = renderable

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield from console.render(self._renderable, options.update_width(options.max_width - RIGHT_MARGIN))
```

Terminals lose track of the cursor after a line that fills the full width. rich then redraws the live area in the wrong place, and old rows pile up on screen. This small wrapper draws whatever it holds one column narrower than the window. rich calls `__rich_console__` whenever it draws an object, and `update_width` sets the width to use.

```python
class Screen:
    def __init__(self, console: Console, total: int):
        self.downloaded = 0
        self.copied = 0
        self.failures: list[tuple[Video, str]] = []
        self._console = console
        self._total = total
        self._finished = 0
        self._tasks: dict[str, TaskID] = {}
        self._lock = Lock()
        self._bars = Progress(
            SpinnerColumn(style="cyan"),
            # Titles are shown as written, so "[live]" in a title is not read as a style tag.
            TextColumn(
                "{task.description}",
                markup=False,
                table_column=Column(ratio=2, min_width=NAME_MIN_WIDTH, no_wrap=True, overflow="ellipsis"),
            ),
            BarColumn(
                bar_width=None,
                complete_style="cyan",
                finished_style="cyan",
                table_column=Column(ratio=1, min_width=BAR_MIN_WIDTH),
            ),
            TextColumn("{task.percentage:>3.0f}%", style="cyan"),
            TextColumn("{task.fields[detail]}", style="dim", table_column=Column(ratio=2, no_wrap=True, overflow="ellipsis")),
            console=console,
            expand=True,
        )
        self._overall = Progress(
            TextColumn("[bold]Overall"),
            BarColumn(complete_style="green", finished_style="green"),
            TextColumn("{task.fields[counts]}"),
            console=console,
        )
        self._overall_task = self._overall.add_task("", total=total, counts=counts_text(0, 0, total))
        self._live = Live(RightMargin(Group(self._bars, self._overall)), console=console, refresh_per_second=REFRESH_PER_SECOND)

    def __enter__(self) -> "Screen":
        self._live.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._live.stop()
```

`Screen` draws the live area for one round of downloads.

- **The public counters** (`downloaded`, `copied`, `failures`) are read by `cli.py` after the round.
- **`self._tasks`** maps each video ID to its bar, so progress reports find the right bar.
- **`self._lock`** keeps two workers from changing the counters at the same time.
- **`self._bars`** is one rich progress display with a row per download. The row has five columns: spinner, name, bar, percent, and details. `markup=False` on the name matters. rich normally reads `[red]` inside text as a color instruction, and this makes it show titles exactly as written.
- **`self._overall`** is a second progress display with one row, the Overall bar.
- **`self._live`** puts both displays in one live area, inside the `RightMargin` wrapper.
- **`__enter__` and `__exit__`** start and stop the live area, so `cli.py` can write `with Screen(...) as screen:`.

```python
    def started(self, video: Video) -> None:
        with self._lock:
            self._tasks[video.video_id] = self._bars.add_task(video.name, total=None, detail="starting")
            self._refresh_overall()

    def progress(self, event: ProgressEvent) -> None:
        task_id = self._tasks[event.video_id]
        if event.stage == STAGE_MERGING:
            self._bars.update(task_id, total=MERGE_TOTAL, completed=MERGE_TOTAL, detail=detail_text(event))
            return
        self._bars.update(task_id, total=event.total_bytes, completed=event.done_bytes, detail=detail_text(event))

    def finished(self, video: Video, size: int) -> None:
        with self._lock:
            self.downloaded += 1
            self._end(video)
        self._console.print(status_line(DONE_MARK, video.name, Text(f"Downloaded {decimal(size)}", style="green")))

    def failed(self, video: Video, reason: str) -> None:
        with self._lock:
            self.failures.append((video, reason))
            self._end(video)
        self._console.print(status_line(FAIL_MARK, video.name, Text("failed", style="red")))
        self._console.print(Text(f"{FAILURE_INDENT}{reason}", style="red"))

    def copied_to(self, video: Video) -> None:
        with self._lock:
            self.copied += 1
        self._console.print(copied_line(video))

    def _end(self, video: Video) -> None:
        self._bars.remove_task(self._tasks.pop(video.video_id))
        self._finished += 1
        self._refresh_overall()

    def _refresh_overall(self) -> None:
        counts = counts_text(self._finished, len(self._tasks), self._total)
        self._overall.update(self._overall_task, completed=self._finished, counts=counts)
```

Workers call these methods as things happen.

- **`started`** adds a bar for a new download.
- **`progress`** updates a bar from a `ProgressEvent`. While merging, the bar is shown full.
- **`finished`** removes the bar and prints a green line with the file size.
- **`failed`** removes the bar and prints a red line, with the reason underneath.
- **`copied_to`** counts a copy and prints its green line.
- **`_end`** and **`_refresh_overall`** are shared by `finished` and `failed`. They remove the bar and update the Overall counts.

---

## 8. `cli.py`: tie it all together

This is where the program starts. It reads the command and runs every step in order.

```python
import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from yt_dwnldr.catalog import Batch, Video, expand, has_youtube_login
from yt_dwnldr.cookie_store import CookieStore
from yt_dwnldr.downloader import Downloader
from yt_dwnldr.layout import file_paths, place_copy
from yt_dwnldr.links import read_links
from yt_dwnldr.ui import (
    Screen,
    copied_line,
    print_batches,
    print_login_warning,
    print_retry_round,
    print_skipped,
    print_summary,
)
from yt_dwnldr.ytdl import base_options, cookie_text, error_reason, read_chrome_cookies
```

This file imports from every other file, because it is the one that connects them. From Python itself it uses `argparse` for the command line, `threading` and `concurrent.futures` for the workers, and `time` for the wait between retry rounds.

```python
DEFAULT_WORKERS = 3
MIN_WORKERS = 1
MAX_WORKERS = 8
DEFAULT_OUT = Path.home() / "Downloads" / "yt-dwnldr"
RETRY_ROUNDS = 3
RETRY_ROUND_DELAY_SECONDS = 30

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BAD_INPUT = 2
EXIT_INTERRUPTED = 130

ALREADY_DOWNLOADED = "already downloaded"
UNAVAILABLE = "unavailable on YouTube"
```

- **Workers, output folder, and retry rounds.** The defaults and limits for each.
- **The exit codes.** The number the program returns when it ends. Other programs and scripts can check it. `130` is the usual code for "stopped with Ctrl+C".
- **The two skip reasons.** The text shown on yellow lines.

```python
@dataclass
class Plan:
    downloads: list[Video] = field(default_factory=list)
    copies_now: list[tuple[Path, Video]] = field(default_factory=list)
    copies_after_download: dict[str, list[Video]] = field(default_factory=dict)
    skipped: list[Video] = field(default_factory=list)
    unavailable: list[Video] = field(default_factory=list)


@dataclass
class Outcome:
    downloaded: int = 0
    copied: int = 0
    failures: list[tuple[Video, str]] = field(default_factory=list)
    is_interrupted: bool = False
```

- **`Plan`** holds the five groups from the planning step: videos to download, copies to make now, copies to make after a download finishes, videos to skip, and unavailable videos. `copies_after_download` maps a video ID to the other playlist entries that should get a copy once that video is on disk.
- **`Outcome`** holds the totals after all rounds. `field(default_factory=list)` gives each new record its own empty list.

```python
def worker_count(value: str) -> int:
    if not value.isdigit() or not MIN_WORKERS <= int(value) <= MAX_WORKERS:
        raise argparse.ArgumentTypeError(f"must be a whole number from {MIN_WORKERS} to {MAX_WORKERS}")
    return int(value)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="yt-dwnldr", description="Download YouTube videos and playlists as mp4 files.")
    parser.add_argument("links_file", type=Path, help="text file of links, separated by commas or new lines")
    parser.add_argument("--workers", type=worker_count, default=DEFAULT_WORKERS, help="videos to download at once (1 to 8)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder to save into")
    parser.add_argument("--chrome-profile", help='Chrome profile folder to read the login from, such as "Profile 1"')
    return parser.parse_args(argv)
```

- **`worker_count`** checks `--workers`. It must be a whole number from 1 to 8. If it is not, argparse (Python's command-line reader) shows the message and stops.
- **`parse_args`** describes the command: one required links file, plus `--workers`, `--out`, and `--chrome-profile`.

```python
def open_cookie_store(chrome_profile: str | None, console: Console) -> CookieStore:
    cookie_jar = read_chrome_cookies(chrome_profile)
    if not has_youtube_login(cookie_jar):
        print_login_warning(console)
    return CookieStore(
        read_cookies=lambda: cookie_text(read_chrome_cookies(chrome_profile)),
        initial=cookie_text(cookie_jar),
    )


def read_batches(links: list[str], cookies: str, console: Console) -> list[Batch]:
    with YoutubeDL(base_options(cookies)) as ydl, console.status(f"Reading {len(links)} links from YouTube"):
        return [expand(ydl, link) for link in links]
```

- **`open_cookie_store`** reads Chrome once, warns if there is no YouTube login, and creates the cookie store. The `lambda` (a one-line function with no name, as in `downloader.py`) tells the store how to read Chrome again later, from the same profile.
- **`read_batches`** makes one yt-dlp copy and expands every link with it. A spinner with "Reading N links from YouTube" shows while it works.

```python
# A video can sit in several playlists. It downloads once, and every other playlist folder gets a copy.
def plan_downloads(batches: list[Batch], paths: dict[Video, Path]) -> Plan:
    plan = Plan()
    same_video: dict[str, list[Video]] = {}
    for video in (video for batch in batches for video in batch.videos):
        same_video.setdefault(video.video_id, []).append(video)

    for videos in same_video.values():
        if not videos[0].is_available:
            plan.unavailable.extend(videos)
            continue
        saved = [video for video in videos if paths[video].exists()]
        missing = [video for video in videos if not paths[video].exists()]
        plan.skipped.extend(saved)
        if saved:
            plan.copies_now.extend((paths[saved[0]], video) for video in missing)
        elif missing:
            plan.downloads.append(missing[0])
            plan.copies_after_download[missing[0].video_id] = missing[1:]
    return plan
```

`plan_downloads` sorts every video into the `Plan`. It is the heart of the "every playlist folder is complete" rule.

1. **Group by video ID.** The same video in two playlists lands in one group.
2. **No title means unavailable.** Every entry of that video is marked unavailable.
3. **Check the disk.** `saved` is the entries whose file already exists. `missing` is the rest. Saved entries are skipped.
4. **One copy on disk.** Each missing entry gets a copy of the saved file right away.
5. **No copy on disk.** Download the first missing entry. The others wait in `copies_after_download` until that download finishes.

```python
def download_round(
    queue: list[Video],
    workers: int,
    out_dir: Path,
    cookie_store: CookieStore,
    copies: dict[str, list[Video]],
    paths: dict[Video, Path],
    screen: Screen,
) -> bool:
    stop = threading.Event()
    thread_state = threading.local()

    def start_worker() -> None:
        thread_state.downloader = Downloader(out_dir, cookie_store, screen.progress, stop)

    def work(video: Video) -> None:
        screen.started(video)
        try:
            path = thread_state.downloader.download(video)
        except DownloadError as error:
            # Ctrl+C also reaches ffmpeg and Deno, so errors after a stop are expected, not failures.
            if not stop.is_set():
                screen.failed(video, error_reason(error))
            return
        screen.finished(video, path.stat().st_size)
        for twin in copies.get(video.video_id, []):
            place_copy(path, paths[twin])
            screen.copied_to(twin)
        thread_state.downloader.pause()

    executor = ThreadPoolExecutor(max_workers=workers, initializer=start_worker)
    futures = [executor.submit(work, video) for video in queue]
    try:
        for future in as_completed(futures):
            future.result()
    except KeyboardInterrupt:
        stop.set()
        executor.shutdown(wait=True, cancel_futures=True)
        return True
    executor.shutdown()
    return False
```

`download_round` downloads a list of videos with a pool of workers.

- **`stop`** is the shared Ctrl+C flag.
- **`thread_state`** gives each worker its own storage. Each worker keeps its own `Downloader` there.
- **`start_worker`** runs once when each worker starts. It creates that worker's `Downloader`.
- **`work`** runs once per video:
  1. **Show a bar.**
  2. **Download.** If it fails, show the failure. The one exception is after Ctrl+C, because ffmpeg and Deno also get Ctrl+C and fail on their own.
  3. **Finish up.** On success, show the green line, place any copies for other playlists, and take a short break.
- **The pool.** `ThreadPoolExecutor` runs `work` for every video, a few at a time. Each job comes back as a result holder, which Python calls a future. `as_completed` hands them back one by one as they finish. `future.result()` passes on any unexpected error, so a real bug is not hidden.
- **Ctrl+C.** Python raises `KeyboardInterrupt` here. The code sets the stop flag, cancels the waiting videos, waits for the running ones to stop, and returns `True`.

```python
# Some failures clear up on their own (a login cookie YouTube just replaced), so failed videos get more rounds.
def download_with_retry_rounds(
    plan: Plan,
    paths: dict[Video, Path],
    workers: int,
    out_dir: Path,
    cookie_store: CookieStore,
    console: Console,
) -> Outcome:
    outcome = Outcome()
    queue = plan.downloads
    for round_number in range(RETRY_ROUNDS + 1):
        if not queue:
            break
        if round_number:
            print_retry_round(console, round_number, RETRY_ROUNDS, len(queue))
            try:
                time.sleep(RETRY_ROUND_DELAY_SECONDS)
            except KeyboardInterrupt:
                outcome.is_interrupted = True
                break
            cookie_store.renew(cookie_store.latest().version)

        with Screen(console, total=len(queue)) as screen:
            outcome.is_interrupted = download_round(
                queue, workers, out_dir, cookie_store, plan.copies_after_download, paths, screen,
            )
        outcome.downloaded += screen.downloaded
        outcome.copied += screen.copied
        outcome.failures = screen.failures
        queue = [video for video, _ in screen.failures]
        if outcome.is_interrupted:
            break
    return outcome
```

`download_with_retry_rounds` runs the main pass, then up to 3 retry rounds.

1. **Stop early.** Stop when nothing is left to download.
2. **Get ready.** Before a retry round, print its header, wait 30 seconds, and force a fresh read of the login. Ctrl+C during the wait ends everything cleanly.
3. **Run the round.** Run one round inside a fresh `Screen`.
4. **Count.** Add up the counts. Keep only this round's failures, since earlier failures that later worked no longer count.
5. **Carry over.** The next round's list is exactly this round's failures.

```python
def run(links_file: Path, workers: int, out_dir: Path, chrome_profile: str | None, console: Console) -> int:
    if not links_file.is_file():
        console.print(f"[red]Links file not found:[/] {links_file}")
        return EXIT_BAD_INPUT
    links = read_links(links_file)
    if not links:
        console.print(f"[red]No links found in[/] {links_file}")
        return EXIT_BAD_INPUT

    out_dir.mkdir(parents=True, exist_ok=True)
    cookie_store = open_cookie_store(chrome_profile, console)
    batches = read_batches(links, cookie_store.latest().text, console)
    print_batches(console, batches)

    paths = file_paths([video for batch in batches for video in batch.videos], out_dir)
    plan = plan_downloads(batches, paths)
    for video in plan.skipped:
        print_skipped(console, video, ALREADY_DOWNLOADED)
    for video in plan.unavailable:
        print_skipped(console, video, UNAVAILABLE)
    for source, video in plan.copies_now:
        place_copy(source, paths[video])
        console.print(copied_line(video))

    outcome = download_with_retry_rounds(plan, paths, workers, out_dir, cookie_store, console)

    link_failures = [(batch.link, batch.error) for batch in batches if batch.error]
    video_failures = [(video.name, reason) for video, reason in outcome.failures]
    counts = {
        "Downloaded": outcome.downloaded,
        "Copied": len(plan.copies_now) + outcome.copied,
        "Skipped": len(plan.skipped),
        "Unavailable": len(plan.unavailable),
    }
    print_summary(console, counts, link_failures + video_failures)
    if outcome.is_interrupted:
        console.print("[yellow]Stopped. Run the same command again to resume.[/]")
        return EXIT_INTERRUPTED
    return EXIT_FAILED if link_failures or video_failures else EXIT_OK
```

`run` is the whole program in order.

1. **Check the links file.** If it is missing or has no links, stop with code `2`.
2. **Get ready.** Create the output folder, open the cookie store, read every link, and print the playlist headers.
3. **Plan.** Work out every file path and make the plan. Print skipped and unavailable videos, and place the copies that can be made right away.
4. **Download.** Run the main pass and the retry rounds.
5. **Report.** Collect failed links and failed videos, and print the summary. Return `130` after Ctrl+C, `1` if anything failed, and `0` otherwise.

```python
def main() -> None:
    args = parse_args(sys.argv[1:])
    try:
        sys.exit(run(args.links_file, args.workers, args.out.expanduser(), args.chrome_profile, Console()))
    except KeyboardInterrupt:
        sys.exit(EXIT_INTERRUPTED)
```

`main` is what runs when `yt-dwnldr` is typed in a terminal. The `[project.scripts]` section of `pyproject.toml` points the command at this function. It reads the arguments, turns `~` in `--out` into the home folder, runs everything, and exits with the code `run` returned. The `try` catches Ctrl+C during the early steps, before any download starts.

---

## The tests

Each source file has a test file in `tests/`. Run them all with `uv run pytest`.

| Test file | What it checks |
|---|---|
| `test_links.py` | Commas and new lines both split links. Comments, blanks, and repeats are dropped, and the order is kept. |
| `test_ytdl.py` | Error messages are shortened, and the "not a bot" tip is added. |
| `test_cookie_store.py` | Chrome is re-read only after the interval, a renew reuses cookies another worker already got, and reads are never closer than the minimum gap. It uses a fake clock and a fake reader. |
| `test_catalog.py` | Playlist links are spotted and rewritten, login cookies are found, videos are numbered in order, singles go in `singles`, and videos without a title get a readable name. |
| `test_layout.py` | File paths have the right folder and number, unsafe characters are replaced, and a placed copy has the same content. |
| `test_downloader.py` | Picture and sound streams are told apart, progress numbers are read correctly, and the retry loop retries, gives up after 3 attempts, and stops at once after Ctrl+C. |
| `test_ui.py` | The detail text, the Overall counts, and the retry header are worded correctly. |
| `test_cli.py` | `--workers` accepts only 1 to 8, the plan puts each video in the right group, a missing or empty links file stops with code `2`, and the retry rounds retry failures and stop after the limit. |

The tests never touch the network. The real download is checked by running the tool on a small public playlist.
