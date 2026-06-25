import gzip


from pathlib import Path


ABLETON_LIVE_PROJECT_SUFFIX = ".als"


def read_project_file(path: Path) -> bytes:
    """Reads the contents of an Ableton Live project file by decompressing it."""
    with open(path, "rb") as f:
        contents = f.read()
        try:
            contents = gzip.decompress(contents)
        except gzip.BadGzipFile:
            pass
    return contents


def write_project_file(path: Path, contents: bytes):
    with open(path, "wb") as f:
        f.write(gzip.compress(contents))
