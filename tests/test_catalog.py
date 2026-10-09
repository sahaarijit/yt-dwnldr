from http.cookiejar import Cookie, CookieJar

from yt_dwnldr.catalog import (
    SINGLES_FOLDER,
    expand,
    has_youtube_login,
    is_youtube_link,
    playlist_videos,
    resolve,
    single_video,
)

YOUTUBE_ENTRY_URL = "https://www.youtube.com/watch?v={}"


def cookie(name, domain):
    return Cookie(
        version=0, name=name, value="x", port=None, port_specified=False, domain=domain,
        domain_specified=True, domain_initial_dot=True, path="/", path_specified=True, secure=True,
        expires=None, discard=False, comment=None, comment_url=None, rest={},
    )


def jar(*cookies):
    cookie_jar = CookieJar()
    for item in cookies:
        cookie_jar.set_cookie(item)
    return cookie_jar


def youtube_entry(video_id, title):
    return {"id": video_id, "title": title, "ie_key": "Youtube", "url": YOUTUBE_ENTRY_URL.format(video_id)}


class FakeYoutubeDL:
    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def extract_info(self, link, download, process):
        self.asked.append(link)
        return self.pages[link]


def test_youtube_links_are_spotted():
    assert is_youtube_link("https://www.youtube.com/watch?v=abc")
    assert is_youtube_link("https://youtu.be/abc")
    assert not is_youtube_link("https://www.instagram.com/reels/abc/")


def test_login_cookie_on_youtube_counts_as_signed_in():
    assert has_youtube_login(jar(cookie("SAPISID", ".youtube.com")))


def test_other_cookies_do_not_count_as_signed_in():
    assert not has_youtube_login(jar(cookie("PREF", ".youtube.com"), cookie("SAPISID", ".example.com")))


def test_resolve_follows_a_pointer_to_the_real_page():
    playlist = {"_type": "playlist", "title": "P", "entries": []}
    ydl = FakeYoutubeDL({"watch-link": {"_type": "url", "url": "playlist-link"}, "playlist-link": playlist})
    assert resolve(ydl, "watch-link") is playlist
    assert ydl.asked == ["watch-link", "playlist-link"]


def test_playlist_videos_are_numbered_in_order():
    info = {"title": "Low Level Design", "extractor_key": "YoutubeTab",
            "entries": iter([youtube_entry("a", "Intro"), youtube_entry("b", "SOLID")])}
    videos = playlist_videos(info)
    assert [video.name for video in videos] == ["001 - Intro", "002 - SOLID"]
    assert {video.folder for video in videos} == {"Low Level Design"}
    assert videos[0].url == YOUTUBE_ENTRY_URL.format("a")


def test_youtube_video_without_a_title_is_unavailable():
    info = {"title": "System Design", "extractor_key": "YoutubeTab", "entries": iter([youtube_entry("a", None)])}
    video = playlist_videos(info)[0]
    assert (video.is_available, video.name) == (False, "001 - (unavailable video)")


def test_other_site_video_without_a_title_uses_its_id():
    info = {"title": "Clips", "extractor_key": "Generic",
            "entries": iter([{"id": "clip1", "webpage_url": "https://example.com/clip1"}])}
    video = playlist_videos(info)[0]
    assert (video.is_available, video.name, video.site) == (True, "001 - clip1", "Generic")


def test_single_video_keeps_its_own_site_and_address():
    info = {"id": "DeE", "title": "Video by someone", "extractor_key": "Instagram",
            "webpage_url": "https://www.instagram.com/reel/DeE/"}
    video = single_video(info, "https://www.instagram.com/reel/DeE/?igsh=x")
    assert (video.folder, video.name, video.site, video.url) == (
        SINGLES_FOLDER, "Video by someone", "Instagram", "https://www.instagram.com/reel/DeE/",
    )


def test_same_id_on_two_sites_gives_two_keys():
    on_youtube = single_video({"id": "abc", "title": "t", "extractor_key": "Youtube"}, "y")
    on_vimeo = single_video({"id": "abc", "title": "t", "extractor_key": "Vimeo"}, "v")
    assert on_youtube.key != on_vimeo.key


def test_expand_treats_a_playlist_result_as_a_playlist():
    playlist = {"_type": "playlist", "title": "P", "extractor_key": "YoutubeTab", "entries": iter([youtube_entry("a", "A")])}
    batch = expand(FakeYoutubeDL({"link": playlist}), "link")
    assert (batch.is_playlist, batch.title, len(batch.videos)) == (True, "P", 1)


def test_expand_treats_any_other_result_as_one_video():
    reel = {"id": "DeE", "title": "Reel", "extractor_key": "Instagram", "webpage_url": "https://www.instagram.com/reel/DeE/"}
    batch = expand(FakeYoutubeDL({"link": reel}), "link")
    assert (batch.is_playlist, [video.name for video in batch.videos]) == (False, ["Reel"])


def embedded_entry(formats):
    return {"id": "html5_video-1", "title": "HTML Video (1)", "extractor_key": "Generic", "formats": formats}


def test_embedded_video_uses_its_mp4_file_address():
    entry = embedded_entry([{"ext": "ogv", "url": "https://x/v.ogg"}, {"ext": "mp4", "url": "https://x/v.mp4"}])
    info = {"title": "Page", "extractor_key": "Generic", "entries": iter([entry])}
    assert playlist_videos(info)[0].url == "https://x/v.mp4"


def test_embedded_video_without_mp4_uses_the_first_file():
    entry = embedded_entry([{"ext": "webm", "url": "https://x/v.webm"}])
    info = {"title": "Page", "extractor_key": "Generic", "entries": iter([entry])}
    assert playlist_videos(info)[0].url == "https://x/v.webm"


def test_entry_with_no_address_at_all_is_unavailable():
    info = {"title": "Page", "extractor_key": "Generic", "entries": iter([embedded_entry([])])}
    assert playlist_videos(info)[0].is_available is False
