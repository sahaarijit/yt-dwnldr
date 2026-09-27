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


@dataclass(frozen=True)
class Batch:
    link: str
    title: str
    videos: list[Video]
    is_playlist: bool
    error: str | None = None


def is_playlist_link(link: str) -> bool:
    return PLAYLIST_PARAM in parse_qs(urlparse(link).query)


# A watch?v=...&list=... link resolves to a pointer to the playlist, not the playlist itself.
def playlist_link(link: str) -> str:
    playlist_id = parse_qs(urlparse(link).query)[PLAYLIST_PARAM][0]
    return PLAYLIST_URL.format(playlist_id)


def has_youtube_login(cookie_jar: CookieJar) -> bool:
    return any(cookie.name in LOGIN_COOKIES and cookie.domain.endswith(YOUTUBE_DOMAIN) for cookie in cookie_jar)


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
