from dataclasses import dataclass
from http.cookiejar import CookieJar

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from yt_dwnldr.ytdl import error_reason

YOUTUBE_SITE = "Youtube"
YOUTUBE_DOMAINS = ("youtube.com", "youtu.be")
YOUTUBE_COOKIE_DOMAIN = "youtube.com"
LOGIN_COOKIES = {"SAPISID", "__Secure-3PAPISID", "LOGIN_INFO"}
POINTER_TYPES = {"url", "url_transparent"}
PLAYLIST_TYPE = "playlist"
MAX_POINTER_HOPS = 3
PREFERRED_EXTENSION = "mp4"
SINGLES_FOLDER = "singles"
POSITION_WIDTH = 3
FIRST_POSITION = 1
UNAVAILABLE_TITLE = "(unavailable video)"


@dataclass(frozen=True)
class Video:
    video_id: str
    site: str
    url: str
    title: str | None
    folder: str
    prefix: str

    # Two sites can use the same ID, so a video is known by its site and ID together.
    @property
    def key(self) -> str:
        return f"{self.site}:{self.video_id}"

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


def is_youtube_link(link: str) -> bool:
    return any(domain in link for domain in YOUTUBE_DOMAINS)


def has_youtube_login(cookie_jar: CookieJar) -> bool:
    return any(cookie.name in LOGIN_COOKIES and cookie.domain.endswith(YOUTUBE_COOKIE_DOMAIN) for cookie in cookie_jar)


# Only YouTube's missing title means "deleted or private". Other sites may just leave titles out of a list.
def entry_title(entry: dict, site: str) -> str | None:
    if entry.get("title") or site == YOUTUBE_SITE:
        return entry.get("title")
    return entry["id"]


# A video embedded in a page has no page of its own, only the media files the page points to.
def entry_address(entry: dict) -> str | None:
    address = entry.get("url") or entry.get("webpage_url")
    if address:
        return address
    media_files = entry.get("formats") or []
    preferred = [media["url"] for media in media_files if media.get("ext") == PREFERRED_EXTENSION]
    others = [media["url"] for media in media_files]
    return next(iter(preferred + others), None)


def playlist_videos(playlist_info: dict) -> list[Video]:
    folder = playlist_info.get("title") or playlist_info["id"]
    videos = []
    for position, entry in enumerate(playlist_info["entries"], start=FIRST_POSITION):
        site = entry.get("ie_key") or playlist_info["extractor_key"]
        address = entry_address(entry)
        videos.append(Video(
            video_id=entry["id"],
            site=site,
            url=address or "",
            # Without an address there is nothing to download, so the video counts as unavailable.
            title=entry_title(entry, site) if address else None,
            folder=folder,
            prefix=f"{position:0{POSITION_WIDTH}d} - ",
        ))
    return videos


def single_video(video_info: dict, link: str) -> Video:
    return Video(
        video_id=video_info["id"],
        site=video_info["extractor_key"],
        url=video_info.get("webpage_url") or link,
        title=video_info.get("title") or video_info["id"],
        folder=SINGLES_FOLDER,
        prefix="",
    )


# Some links lead to another page first (a watch?v=...&list=... link points at its playlist), so follow those.
def resolve(ydl: YoutubeDL, link: str) -> dict:
    info = ydl.extract_info(link, download=False, process=False)
    for _ in range(MAX_POINTER_HOPS):
        if info.get("_type") not in POINTER_TYPES:
            return info
        info = ydl.extract_info(info["url"], download=False, process=False)
    return info


def expand(ydl: YoutubeDL, link: str) -> Batch:
    try:
        info = resolve(ydl, link)
        is_playlist = info.get("_type") == PLAYLIST_TYPE
        # Playlist entries load lazily, page by page, so paging errors surface here too.
        videos = playlist_videos(info) if is_playlist else [single_video(info, link)]
    except DownloadError as error:
        return Batch(link=link, title=link, videos=[], is_playlist=False, error=error_reason(error))
    return Batch(link=link, title=info.get("title") or link, videos=videos, is_playlist=is_playlist)
