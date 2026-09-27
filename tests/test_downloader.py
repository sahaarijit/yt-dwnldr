import pytest
from yt_dlp.utils import DownloadError

from yt_dwnldr.downloader import MAX_ATTEMPTS, STAGE_AUDIO, STAGE_VIDEO, event_from_hook, run_with_retries, stage_of


def hook(vcodec, **fields):
    return {"status": "downloading", "info_dict": {"vcodec": vcodec}, **fields}


def test_stream_without_video_codec_is_audio():
    assert stage_of({"vcodec": "none"}) == STAGE_AUDIO
    assert stage_of({"vcodec": "avc1.4d401e"}) == STAGE_VIDEO


def test_event_uses_exact_total_when_known():
    event = event_from_hook("abc", hook("avc1", downloaded_bytes=50, total_bytes=200, speed=10.0, eta=15))
    assert (event.stage, event.done_bytes, event.total_bytes, event.speed, event.eta) == (STAGE_VIDEO, 50, 200, 10.0, 15)


def test_event_falls_back_to_estimated_total():
    event = event_from_hook("abc", hook("none", downloaded_bytes=5, total_bytes_estimate=90))
    assert (event.stage, event.total_bytes) == (STAGE_AUDIO, 90)


def test_event_without_any_total_or_speed():
    event = event_from_hook("abc", hook("none", downloaded_bytes=5))
    assert (event.total_bytes, event.speed, event.eta) == (None, None, None)


def failing_then(*outcomes):
    remaining = iter(outcomes)
    calls = []

    def attempt():
        calls.append(1)
        outcome = next(remaining)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return attempt, calls


def test_retry_succeeds_after_a_failure():
    attempt, calls = failing_then(DownloadError("ERROR: stale login"), 42)
    retries = []
    assert run_with_retries(attempt, before_retry=lambda: retries.append(1), is_stopped=lambda: False) == 42
    assert (len(calls), len(retries)) == (2, 1)


def test_retry_gives_up_after_max_attempts():
    attempt, calls = failing_then(*[DownloadError("ERROR: gone")] * MAX_ATTEMPTS)
    with pytest.raises(DownloadError):
        run_with_retries(attempt, before_retry=lambda: None, is_stopped=lambda: False)
    assert len(calls) == MAX_ATTEMPTS


def test_no_retry_once_stopped():
    attempt, calls = failing_then(DownloadError("ERROR: stopped"))
    with pytest.raises(DownloadError):
        run_with_retries(attempt, before_retry=lambda: None, is_stopped=lambda: True)
    assert len(calls) == 1
