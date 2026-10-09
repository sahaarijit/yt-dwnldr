from yt_dwnldr.catalog import Video
from yt_dwnldr.layout import file_paths, place_copy


def test_playlist_video_path_has_folder_and_number(tmp_path):
    video = Video(video_id="abc", site="Youtube", url="u", title="Intro: Part 1/2", folder="Low Level Design", prefix="001 - ")
    path = file_paths([video], tmp_path)[video]
    assert path.parent == tmp_path / "Low Level Design"
    assert path.name.startswith("001 - Intro")
    assert path.suffix == ".mp4"
    assert "/" not in path.name


def test_single_video_path_has_no_number(tmp_path):
    video = Video(video_id="abc", site="Instagram", url="u", title="Talk", folder="singles", prefix="")
    assert file_paths([video], tmp_path)[video] == tmp_path / "singles" / "Talk.mp4"


def test_place_copy_puts_the_same_content_in_a_new_folder(tmp_path):
    source = tmp_path / "A" / "001 - x.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    target = tmp_path / "B" / "004 - x.mp4"
    place_copy(source, target)
    assert target.read_bytes() == b"video"
    assert source.exists()
