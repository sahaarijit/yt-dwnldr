import os
import shutil
from pathlib import Path

from yt_dlp import YoutubeDL

from yt_dwnldr.catalog import Video
from yt_dwnldr.ytdl import SilentLogger

OUTPUT_TEMPLATE = "%(ytdw_folder)s/%(ytdw_prefix)s%(title)s.%(ext)s"
FINAL_EXTENSION = "mp4"


def output_options(out_dir: Path) -> dict:
    return {
        "paths": {"home": str(out_dir)},
        "outtmpl": OUTPUT_TEMPLATE,
        # Singles have an empty prefix, which yt-dlp would otherwise print as "NA".
        "outtmpl_na_placeholder": "",
    }


def extra_fields(video: Video) -> dict:
    return {"ytdw_folder": video.folder, "ytdw_prefix": video.prefix}


# yt-dlp builds these names the same way it names the downloaded file, so they match.
def file_paths(videos: list[Video], out_dir: Path) -> dict[Video, Path]:
    with YoutubeDL(output_options(out_dir) | {"logger": SilentLogger()}) as ydl:
        return {
            video: Path(ydl.prepare_filename(
                {"id": video.video_id, "title": video.title, "ext": FINAL_EXTENSION} | extra_fields(video),
            ))
            for video in videos
        }


# A hard link shows one file in two folders without using more disk space.
def place_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except OSError:
        # Hard links fail across drives and on some file systems, so fall back to a real copy.
        shutil.copy2(source, target)
