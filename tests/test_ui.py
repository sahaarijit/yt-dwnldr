from yt_dwnldr.downloader import STAGE_MERGING, STAGE_RETRYING, STAGE_VIDEO, ProgressEvent
from rich.console import Console

from yt_dwnldr.ui import counts_text, detail_text, print_retry_round


def test_detail_shows_stage_size_speed_and_time_left():
    event = ProgressEvent("abc", STAGE_VIDEO, 1_000_000, 4_000_000, 500_000.0, 6)
    assert detail_text(event) == "video  1.0 MB/4.0 MB  500.0 kB/s  0:00:06 left"


def test_detail_without_total_shows_bytes_so_far():
    event = ProgressEvent("abc", STAGE_VIDEO, 2_000_000, None, None, None)
    assert detail_text(event) == "video  2.0 MB"


def test_detail_while_merging():
    assert detail_text(ProgressEvent("abc", STAGE_MERGING, 0, None, None, None)) == "merging"


def test_counts_text():
    assert counts_text(finished=12, active=3, total=42) == "12/42 videos · 3 downloading · 27 queued"


def test_detail_while_waiting_to_retry():
    assert detail_text(ProgressEvent("abc", STAGE_RETRYING, 0, None, None, None)) == "retrying"


def test_retry_round_header_uses_singular_for_one_video():
    console = Console(record=True, width=80)
    print_retry_round(console, round_number=1, total_rounds=3, count=1)
    assert "Retrying 1 failed video (round 1 of 3)" in console.export_text()
