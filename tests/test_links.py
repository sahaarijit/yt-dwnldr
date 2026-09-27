from yt_dwnldr.links import read_links

PLAYLIST = "https://www.youtube.com/playlist?list=PL1"
VIDEO = "https://www.youtube.com/watch?v=abc"


def write(tmp_path, text):
    links_file = tmp_path / "links.txt"
    links_file.write_text(text)
    return links_file


def test_splits_on_commas_and_new_lines(tmp_path):
    links_file = write(tmp_path, f"{PLAYLIST}, {VIDEO}\nhttps://youtu.be/xyz\n")
    assert read_links(links_file) == [PLAYLIST, VIDEO, "https://youtu.be/xyz"]


def test_drops_blanks_comments_and_duplicates_keeping_order(tmp_path):
    links_file = write(tmp_path, f"# my courses\n\n{VIDEO},,\n{PLAYLIST}\n{VIDEO}\n")
    assert read_links(links_file) == [VIDEO, PLAYLIST]


def test_empty_file_gives_no_links(tmp_path):
    assert read_links(write(tmp_path, "\n# nothing\n")) == []
