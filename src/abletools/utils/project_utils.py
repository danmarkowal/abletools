import gzip


def read_project_file(path: str) -> bytes:
    """
    Reads the contents of an Ableton Live project file by decompressing it.
    """
    with open(path, "rb") as f:
        contents = f.read()
        try:
            contents = gzip.decompress(contents)
        except gzip.BadGzipFile:
            pass
    return contents
