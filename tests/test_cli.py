import argparse

import pytest
from rich.console import Console

from yt_dwnldr.catalog import Batch, Video
from yt_dwnldr import cli
from yt_dwnldr.cli import EXIT_BAD_INPUT, Plan, plan_downloads, run, worker_count
from yt_dwnldr.cookie_store import Cookies


def test_worker_count_accepts_range():
    assert worker_count("1") == 1
    assert worker_count("8") == 8


@pytest.mark.parametrize("value", ["0", "9", "three"])
def test_worker_count_rejects_outside_range(value):
    with pytest.raises(argparse.ArgumentTypeError):
        worker_count(value)


def video(video_id, folder="f", prefix="", title="t"):
    return Video(video_id=video_id, title=title, folder=folder, prefix=prefix)


def paths_for(tmp_path, videos, saved=()):
    paths = {item: tmp_path / item.folder / f"{item.prefix}{item.video_id}.mp4" for item in videos}
    for item in saved:
        paths[item].parent.mkdir(parents=True, exist_ok=True)
        paths[item].write_bytes(b"video")
    return paths


def test_plan_downloads_new_videos(tmp_path):
    first, second = video("a"), video("b")
    plan = plan_downloads([Batch("p", "P", [first, second], True)], paths_for(tmp_path, [first, second]))
    assert plan.downloads == [first, second]


def test_plan_skips_videos_already_on_disk(tmp_path):
    saved = video("a")
    plan = plan_downloads([Batch("p", "P", [saved], True)], paths_for(tmp_path, [saved], saved=[saved]))
    assert (plan.downloads, plan.skipped) == ([], [saved])


def test_plan_downloads_a_shared_video_once_and_copies_it_later(tmp_path):
    in_first, in_second = video("a", folder="HLD", prefix="038 - "), video("a", folder="Micro", prefix="004 - ")
    batches = [Batch("p1", "HLD", [in_first], True), Batch("p2", "Micro", [in_second], True)]
    plan = plan_downloads(batches, paths_for(tmp_path, [in_first, in_second]))
    assert plan.downloads == [in_first]
    assert plan.copies_after_download == {"a": [in_second]}


def test_plan_copies_a_shared_video_right_away_when_one_copy_is_saved(tmp_path):
    in_first, in_second = video("a", folder="HLD", prefix="038 - "), video("a", folder="Micro", prefix="004 - ")
    batches = [Batch("p1", "HLD", [in_first], True), Batch("p2", "Micro", [in_second], True)]
    paths = paths_for(tmp_path, [in_first, in_second], saved=[in_first])
    plan = plan_downloads(batches, paths)
    assert plan.downloads == []
    assert plan.copies_now == [(paths[in_first], in_second)]


def test_plan_marks_videos_without_a_title_as_unavailable(tmp_path):
    gone = video("a", title=None)
    plan = plan_downloads([Batch("p", "P", [gone], True)], paths_for(tmp_path, [gone]))
    assert (plan.downloads, plan.unavailable) == ([], [gone])


def test_missing_links_file_is_bad_input(tmp_path):
    assert run(tmp_path / "nope.txt", 3, tmp_path, None, Console(quiet=True)) == EXIT_BAD_INPUT


def test_links_file_without_links_is_bad_input(tmp_path):
    links_file = tmp_path / "links.txt"
    links_file.write_text("# nothing here\n")
    assert run(links_file, 3, tmp_path, None, Console(quiet=True)) == EXIT_BAD_INPUT


def fake_round(results_per_round):
    rounds = iter(results_per_round)
    queues_seen = []

    def download_round(queue, workers, out_dir, cookie_store, copies, paths, screen):
        queues_seen.append([item.video_id for item in queue])
        results = next(rounds)
        for item in queue:
            screen.started(item)
            if results[item.video_id]:
                screen.finished(item, 0)
            else:
                screen.failed(item, "stale login")
        return False

    return download_round, queues_seen


class FakeCookieStore:
    def __init__(self):
        self.renewals = 0

    def latest(self):
        return Cookies(version=1, text="")

    def renew(self, stale_version):
        self.renewals += 1
        return self.latest()


def run_rounds(monkeypatch, results_per_round, videos):
    download_round, queues_seen = fake_round(results_per_round)
    monkeypatch.setattr(cli, "download_round", download_round)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    store = FakeCookieStore()
    plan = Plan(downloads=videos)
    outcome = cli.download_with_retry_rounds(plan, {}, 1, None, store, Console(quiet=True))
    return outcome, queues_seen, store


def test_failed_video_is_retried_in_a_later_round(monkeypatch):
    first, second = video("a"), video("b")
    outcome, queues_seen, store = run_rounds(monkeypatch, [{"a": True, "b": False}, {"b": True}], [first, second])
    assert queues_seen == [["a", "b"], ["b"]]
    assert (outcome.downloaded, outcome.failures, store.renewals) == (2, [], 1)


def test_retry_rounds_stop_after_the_limit(monkeypatch):
    stuck = video("a")
    always_fails = [{"a": False}] * (cli.RETRY_ROUNDS + 1)
    outcome, queues_seen, _ = run_rounds(monkeypatch, always_fails, [stuck])
    assert len(queues_seen) == cli.RETRY_ROUNDS + 1
    assert outcome.failures == [(stuck, "stale login")]
