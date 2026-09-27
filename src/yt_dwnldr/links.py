from pathlib import Path

COMMENT_PREFIX = "#"
LINK_SEPARATOR = ","


def read_links(links_file: Path) -> list[str]:
    links = []
    for line in links_file.read_text().splitlines():
        if line.strip().startswith(COMMENT_PREFIX):
            continue
        links.extend(part.strip() for part in line.split(LINK_SEPARATOR))
    return list(dict.fromkeys(link for link in links if link))
