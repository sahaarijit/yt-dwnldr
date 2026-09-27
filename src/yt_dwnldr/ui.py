from datetime import timedelta
from threading import Lock

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.filesize import decimal
from rich.live import Live
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Column, Table
from rich.text import Text

from yt_dwnldr.catalog import Batch, Video
from yt_dwnldr.downloader import STAGE_MERGING, STAGE_RETRYING, ProgressEvent

NAME_MIN_WIDTH = 16
BAR_MIN_WIDTH = 10
REFRESH_PER_SECOND = 10
RIGHT_MARGIN = 1
MERGE_TOTAL = 1
FAILURE_INDENT = "    "

DONE_MARK = ("✔", "bold green")
SKIP_MARK = ("↷", "bold yellow")
FAIL_MARK = ("✗", "bold red")
HEADER_MARK = ("==>", "bold blue")

SUMMARY_ROWS = (
    ("Downloaded", "green"),
    ("Copied", "green"),
    ("Skipped", "yellow"),
    ("Unavailable", "yellow"),
)


def detail_text(event: ProgressEvent) -> str:
    if event.stage in (STAGE_MERGING, STAGE_RETRYING):
        return event.stage
    size = decimal(event.done_bytes)
    if event.total_bytes:
        size = f"{size}/{decimal(event.total_bytes)}"
    parts = [event.stage, size]
    if event.speed:
        parts.append(f"{decimal(int(event.speed))}/s")
    if event.eta is not None:
        parts.append(f"{timedelta(seconds=int(event.eta))} left")
    return "  ".join(parts)


def counts_text(finished: int, active: int, total: int) -> str:
    queued = total - finished - active
    return f"{finished}/{total} videos · {active} downloading · {queued} queued"


def status_line(mark: tuple[str, str], name: str, status: Text) -> Table:
    line = Table.grid(expand=True)
    line.add_column(no_wrap=True, overflow="ellipsis")
    line.add_column(justify="right", no_wrap=True)
    line.add_row(Text.assemble(mark, " ", name), status)
    return line


def print_login_warning(console: Console) -> None:
    console.print(Text.assemble(
        ("! ", "bold yellow"),
        ("No YouTube login found in Chrome. ", "yellow"),
        "Public videos will download. Videos that need a signed-in account will fail. "
        "Log into YouTube in Chrome, or pick a profile with --chrome-profile.",
    ))


def print_batches(console: Console, batches: list[Batch]) -> None:
    single_count = 0
    for batch in batches:
        if batch.error:
            console.print(Text.assemble(FAIL_MARK, f" Could not read {batch.link}: ", (batch.error, "red")))
        elif batch.is_playlist:
            console.print(Text.assemble(HEADER_MARK, (f" Playlist: {batch.title}", "bold"), f" ({len(batch.videos)} videos)"))
        else:
            single_count += 1
    if single_count:
        console.print(Text.assemble(HEADER_MARK, (" Single videos", "bold"), f" ({single_count})"))


def print_skipped(console: Console, video: Video, reason: str) -> None:
    console.print(status_line(SKIP_MARK, video.name, Text(reason, style="yellow")))


def copied_line(video: Video) -> Table:
    return status_line(DONE_MARK, video.name, Text("Copied from another playlist", style="green"))


def print_retry_round(console: Console, round_number: int, total_rounds: int, count: int) -> None:
    console.print(Text.assemble(
        HEADER_MARK,
        (f" Retrying {count} failed {'video' if count == 1 else 'videos'}", "bold"),
        f" (round {round_number} of {total_rounds})",
    ))


def print_summary(console: Console, counts: dict[str, int], failures: list[tuple[str, str]]) -> None:
    table = Table(title="Summary", title_style="bold", show_header=False)
    for label, style in SUMMARY_ROWS:
        table.add_row(Text(label, style=style), str(counts[label]))
    table.add_row(Text("Failed", style="red"), str(len(failures)))
    console.print(table)
    for name, reason in failures:
        console.print(Text.assemble(FAIL_MARK, f" {name}: ", (reason, "red")))


# Terminals lose track of the cursor after a line that fills the full width, which breaks the live redraw.
class RightMargin:
    def __init__(self, renderable: RenderableType):
        self._renderable = renderable

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield from console.render(self._renderable, options.update_width(options.max_width - RIGHT_MARGIN))


class Screen:
    def __init__(self, console: Console, total: int):
        self.downloaded = 0
        self.copied = 0
        self.failures: list[tuple[Video, str]] = []
        self._console = console
        self._total = total
        self._finished = 0
        self._tasks: dict[str, TaskID] = {}
        self._lock = Lock()
        self._bars = Progress(
            SpinnerColumn(style="cyan"),
            # Titles are shown as written, so "[live]" in a title is not read as a style tag.
            TextColumn(
                "{task.description}",
                markup=False,
                table_column=Column(ratio=2, min_width=NAME_MIN_WIDTH, no_wrap=True, overflow="ellipsis"),
            ),
            BarColumn(
                bar_width=None,
                complete_style="cyan",
                finished_style="cyan",
                table_column=Column(ratio=1, min_width=BAR_MIN_WIDTH),
            ),
            TextColumn("{task.percentage:>3.0f}%", style="cyan"),
            TextColumn("{task.fields[detail]}", style="dim", table_column=Column(ratio=2, no_wrap=True, overflow="ellipsis")),
            console=console,
            expand=True,
        )
        self._overall = Progress(
            TextColumn("[bold]Overall"),
            BarColumn(complete_style="green", finished_style="green"),
            TextColumn("{task.fields[counts]}"),
            console=console,
        )
        self._overall_task = self._overall.add_task("", total=total, counts=counts_text(0, 0, total))
        self._live = Live(RightMargin(Group(self._bars, self._overall)), console=console, refresh_per_second=REFRESH_PER_SECOND)

    def __enter__(self) -> "Screen":
        self._live.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._live.stop()

    def started(self, video: Video) -> None:
        with self._lock:
            self._tasks[video.video_id] = self._bars.add_task(video.name, total=None, detail="starting")
            self._refresh_overall()

    def progress(self, event: ProgressEvent) -> None:
        task_id = self._tasks[event.video_id]
        if event.stage == STAGE_MERGING:
            self._bars.update(task_id, total=MERGE_TOTAL, completed=MERGE_TOTAL, detail=detail_text(event))
            return
        self._bars.update(task_id, total=event.total_bytes, completed=event.done_bytes, detail=detail_text(event))

    def finished(self, video: Video, size: int) -> None:
        with self._lock:
            self.downloaded += 1
            self._end(video)
        self._console.print(status_line(DONE_MARK, video.name, Text(f"Downloaded {decimal(size)}", style="green")))

    def failed(self, video: Video, reason: str) -> None:
        with self._lock:
            self.failures.append((video, reason))
            self._end(video)
        self._console.print(status_line(FAIL_MARK, video.name, Text("failed", style="red")))
        self._console.print(Text(f"{FAILURE_INDENT}{reason}", style="red"))

    def copied_to(self, video: Video) -> None:
        with self._lock:
            self.copied += 1
        self._console.print(copied_line(video))

    def _end(self, video: Video) -> None:
        self._bars.remove_task(self._tasks.pop(video.video_id))
        self._finished += 1
        self._refresh_overall()

    def _refresh_overall(self) -> None:
        counts = counts_text(self._finished, len(self._tasks), self._total)
        self._overall.update(self._overall_task, completed=self._finished, counts=counts)
