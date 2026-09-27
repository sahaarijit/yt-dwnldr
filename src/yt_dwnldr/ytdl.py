import io

from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser
from yt_dlp.utils import DownloadError

BROWSER = "chrome"
ERROR_PREFIX = "ERROR: "
ERROR_HINTS = {
    "not a bot": " (YouTube is limiting requests, retry later with fewer --workers)",
}


# Without a logger, yt-dlp prints straight to the terminal and tears the live display.
class SilentLogger:
    def debug(self, message: str) -> None:
        pass

    info = warning = error = debug


# Each yt-dlp instance that reads Chrome itself asks the macOS Keychain again, so the tool reads Chrome and hands out the text.
def read_chrome_cookies(chrome_profile: str | None) -> YoutubeDLCookieJar:
    return extract_cookies_from_browser(BROWSER, chrome_profile)


def cookie_text(cookie_jar: YoutubeDLCookieJar) -> str:
    buffer = io.StringIO()
    cookie_jar.save(buffer)
    return buffer.getvalue()


def base_options(cookies: str) -> dict:
    return {
        "cookiefile": io.StringIO(cookies),
        "logger": SilentLogger(),
        "noprogress": True,
    }


def error_reason(error: DownloadError) -> str:
    first_line = str(error).splitlines()[0].removeprefix(ERROR_PREFIX)
    hint = next((hint for marker, hint in ERROR_HINTS.items() if marker in first_line), "")
    return first_line + hint
