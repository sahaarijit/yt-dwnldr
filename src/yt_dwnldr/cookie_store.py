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


# YouTube swaps login cookies while it is open in Chrome, so a long run keeps re-reading Chrome.
class CookieStore:
    def __init__(self, read_cookies: Callable[[], str], initial: str, clock: Callable[[], float] = time.monotonic):
        self._read_cookies = read_cookies
        self._clock = clock
        self._lock = threading.Lock()
        self._cookies = Cookies(version=1, text=initial)
        self._read_at = clock()

    def latest(self) -> Cookies:
        with self._lock:
            if self._age() >= REFRESH_INTERVAL_SECONDS:
                self._reread()
            return self._cookies

    def renew(self, stale_version: int) -> Cookies:
        with self._lock:
            is_already_renewed = self._cookies.version > stale_version
            if not is_already_renewed and self._age() >= RENEW_MIN_GAP_SECONDS:
                self._reread()
            return self._cookies

    def _age(self) -> float:
        return self._clock() - self._read_at

    def _reread(self) -> None:
        self._cookies = Cookies(version=self._cookies.version + 1, text=self._read_cookies())
        self._read_at = self._clock()
