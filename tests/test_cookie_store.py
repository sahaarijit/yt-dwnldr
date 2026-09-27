from yt_dwnldr.cookie_store import REFRESH_INTERVAL_SECONDS, RENEW_MIN_GAP_SECONDS, CookieStore


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_store():
    clock = FakeClock()
    reads = []

    def read_cookies():
        reads.append(clock.now)
        return f"cookies-{len(reads)}"

    return CookieStore(read_cookies=read_cookies, initial="cookies-0", clock=clock), clock, reads


def test_latest_keeps_cookies_until_the_interval_passes():
    store, clock, reads = make_store()
    clock.now = REFRESH_INTERVAL_SECONDS - 1
    assert store.latest().text == "cookies-0"
    assert reads == []


def test_latest_rereads_chrome_once_the_interval_passes():
    store, clock, _ = make_store()
    clock.now = REFRESH_INTERVAL_SECONDS
    cookies = store.latest()
    assert (cookies.version, cookies.text) == (2, "cookies-1")


def test_renew_rereads_chrome_when_caller_holds_the_current_version():
    store, clock, _ = make_store()
    clock.now = RENEW_MIN_GAP_SECONDS
    assert store.renew(stale_version=1).text == "cookies-1"


def test_renew_reuses_cookies_another_worker_already_renewed():
    store, clock, reads = make_store()
    clock.now = RENEW_MIN_GAP_SECONDS
    store.renew(stale_version=1)
    clock.now += RENEW_MIN_GAP_SECONDS
    assert store.renew(stale_version=1).text == "cookies-1"
    assert len(reads) == 1


def test_renew_does_not_reread_within_the_minimum_gap():
    store, clock, reads = make_store()
    clock.now = RENEW_MIN_GAP_SECONDS - 1
    assert store.renew(stale_version=1).version == 1
    assert reads == []
