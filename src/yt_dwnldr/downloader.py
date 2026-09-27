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

    def pause(self) -> None:
        self._stop.wait(random.uniform(PAUSE_MIN_SECONDS, PAUSE_MAX_SECONDS))

    def _download_once(self, video: Video) -> Path:
        info = self._ydl.extract_info(video.url, extra_info=extra_fields(video))
        return Path(info["requested_downloads"][0]["filepath"])

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

    def _build_ydl(self) -> YoutubeDL:
        return YoutubeDL(base_options(self._cookies.text) | output_options(self._out_dir) | {
            "format": FORMAT,
            "merge_output_format": MERGE_FORMAT,
            "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
            "progress_hooks": [self._on_download_hook],
            "postprocessor_hooks": [self._on_postprocess_hook],
        })

    # A running download cannot be stopped from outside its thread, so the hook stops it.
    def _on_download_hook(self, hook: dict) -> None:
        if self._stop.is_set():
            raise DownloadCancelled("Stopped by user")
        if hook["status"] == "downloading":
            self._on_progress(event_from_hook(self._video_id, hook))

    def _on_postprocess_hook(self, hook: dict) -> None:
        if hook["postprocessor"] == MERGER and hook["status"] == "started":
            self._on_progress(ProgressEvent(self._video_id, STAGE_MERGING, 0, None, None, None))
