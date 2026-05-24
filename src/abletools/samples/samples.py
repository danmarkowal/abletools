import os
from dataclasses import dataclass, field

supported_files = (".wav", ".mp3", ".aiff", ".aif",
                   ".aifc", ".ogg", ".flac", ".aac", ".m4a", ".mp4", ".mov")
ignored_files = (".mid", ".alc")


# frozen makes it hashable
@dataclass(frozen=True)
class Sample:
    path: str = field()


def should_ignore(file: str) -> bool:
    is_ignored_file = file.lower().endswith(ignored_files)
    is_hidden_file = os.path.basename(file).startswith(".")
    return is_ignored_file or is_hidden_file


def is_media_file(file: str) -> bool:
    return file.lower().endswith(supported_files)
