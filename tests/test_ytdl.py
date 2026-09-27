from yt_dlp.utils import DownloadError

from yt_dwnldr.ytdl import error_reason


def test_strips_prefix_and_keeps_first_line():
    error = DownloadError("ERROR: [youtube] abc: This video is unavailable\nmore detail")
    assert error_reason(error) == "[youtube] abc: This video is unavailable"


def test_adds_hint_for_bot_check():
    error = DownloadError("ERROR: [youtube] abc: Sign in to confirm you're not a bot")
    assert error_reason(error).endswith("(YouTube is limiting requests, retry later with fewer --workers)")
