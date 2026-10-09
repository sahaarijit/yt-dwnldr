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

from yt_dwnldr.catalog import Batch, Video, expand, has_youtube_login, is_youtube_link
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


def worker_count(value: str) -> int:
    if not value.isdigit() or not MIN_WORKERS <= int(value) <= MAX_WORKERS:
        raise argparse.ArgumentTypeError(f"must be a whole number from {MIN_WORKERS} to {MAX_WORKERS}")
    return int(value)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="yt-dwnldr", description="Download videos and playlists from YouTube and other sites as mp4 files.")
    parser.add_argument("links_file", type=Path, help="text file of links, separated by commas or new lines")
    parser.add_argument("--workers", type=worker_count, default=DEFAULT_WORKERS, help="videos to download at once (1 to 8)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder to save into")
    parser.add_argument("--chrome-profile", help='Chrome profile folder to read the login from, such as "Profile 1"')
    return parser.parse_args(argv)


def open_cookie_store(chrome_profile: str | None, has_youtube_links: bool, console: Console) -> CookieStore:
    cookie_jar = read_chrome_cookies(chrome_profile)
    if has_youtube_links and not has_youtube_login(cookie_jar):
        print_login_warning(console)
    return CookieStore(
        read_cookies=lambda: cookie_text(read_chrome_cookies(chrome_profile)),
        initial=cookie_text(cookie_jar),
    )


def read_batches(links: list[str], cookies: str, console: Console) -> list[Batch]:
    with YoutubeDL(base_options(cookies)) as ydl, console.status(f"Reading {len(links)} links from YouTube"):
        return [expand(ydl, link) for link in links]


# A failed conversion can leave an empty file behind, and an empty file is not a finished download.
def is_saved(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


# A video can sit in several playlists. It downloads once, and every other playlist folder gets a copy.
def plan_downloads(batches: list[Batch], paths: dict[Video, Path]) -> Plan:
    plan = Plan()
    same_video: dict[str, list[Video]] = {}
    for video in (video for batch in batches for video in batch.videos):
        same_video.setdefault(video.key, []).append(video)

    for videos in same_video.values():
        if not videos[0].is_available:
            plan.unavailable.extend(videos)
            continue
        saved = [video for video in videos if is_saved(paths[video])]
        missing = [video for video in videos if not is_saved(paths[video])]
        plan.skipped.extend(saved)
        if saved:
            plan.copies_now.extend((paths[saved[0]], video) for video in missing)
        elif missing:
            plan.downloads.append(missing[0])
            plan.copies_after_download[missing[0].key] = missing[1:]
    return plan


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
        for twin in copies.get(video.key, []):
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


def run(links_file: Path, workers: int, out_dir: Path, chrome_profile: str | None, console: Console) -> int:
    if not links_file.is_file():
        console.print(f"[red]Links file not found:[/] {links_file}")
        return EXIT_BAD_INPUT
    links = read_links(links_file)
    if not links:
        console.print(f"[red]No links found in[/] {links_file}")
        return EXIT_BAD_INPUT

    out_dir.mkdir(parents=True, exist_ok=True)
    has_youtube_links = any(is_youtube_link(link) for link in links)
    cookie_store = open_cookie_store(chrome_profile, has_youtube_links, console)
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


def main() -> None:
    args = parse_args(sys.argv[1:])
    try:
        sys.exit(run(args.links_file, args.workers, args.out.expanduser(), args.chrome_profile, Console()))
    except KeyboardInterrupt:
        sys.exit(EXIT_INTERRUPTED)
