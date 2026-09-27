from http.cookiejar import Cookie, CookieJar

from yt_dwnldr.catalog import (
    SINGLES_FOLDER,
    has_youtube_login,
    is_playlist_link,
    playlist_link,
    playlist_videos,
    single_video,
)


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


def test_link_with_list_parameter_is_a_playlist():
    assert is_playlist_link("https://www.youtube.com/playlist?list=PL1")
    assert is_playlist_link("https://www.youtube.com/watch?v=abc&list=PL1")
    assert not is_playlist_link("https://www.youtube.com/watch?v=abc")


def test_watch_link_with_list_becomes_plain_playlist_link():
    assert playlist_link("https://www.youtube.com/watch?v=abc&list=PL1&index=3") == "https://www.youtube.com/playlist?list=PL1"


def test_login_cookie_on_youtube_counts_as_signed_in():
    assert has_youtube_login(jar(cookie("SAPISID", ".youtube.com")))


def test_other_cookies_do_not_count_as_signed_in():
    assert not has_youtube_login(jar(cookie("PREF", ".youtube.com"), cookie("SAPISID", ".example.com")))


def test_playlist_videos_are_numbered_in_order():
    info = {"title": "Low Level Design", "entries": iter([{"id": "a", "title": "Intro"}, {"id": "b", "title": "SOLID"}])}
    videos = playlist_videos(info)
    assert [video.name for video in videos] == ["001 - Intro", "002 - SOLID"]
    assert {video.folder for video in videos} == {"Low Level Design"}


def test_single_video_goes_to_singles_folder_without_number():
    video = single_video({"id": "abc", "title": "Talk"})
    assert (video.folder, video.name, video.url) == (SINGLES_FOLDER, "Talk", "https://www.youtube.com/watch?v=abc")


def test_unavailable_video_gets_a_readable_name():
    info = {"title": "System Design", "entries": iter([{"id": "a", "title": None}])}
    video = playlist_videos(info)[0]
    assert (video.is_available, video.name) == (False, "001 - (unavailable video)")
