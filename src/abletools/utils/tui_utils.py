import os
import sys
import unicodedata


from enum import Enum
from typing import Optional, TextIO


LINE_CLEAR = '\x1b[2K'


class Style(Enum):
    """A text style. The values are the ANSI codes used when printing to a terminal."""
    DEFAULT = "0"
    BOLD = "1"
    DIM = "2"
    RED = "31"
    GREEN = "32"
    YELLOW = "33"
    BLUE = "34"
    CYAN = "36"


# https://stackoverflow.com/questions/3173320/text-progress-bar-in-terminal-with-block-characters
def print_progress_bar(iteration: int, total: int, prefix: str = "", suffix: str = "", decimals: int = 1, length: int = 100, fill: str = "█", end: str = "\r", file: TextIO = sys.stderr):
    percent = ("{0:." + str(decimals) + "f}").format(100 *
                                                     (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + "-" * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}',
          end=end, file=file, flush=True)


def print_status(message: str, file: TextIO = sys.stderr):
    """Prints a message on the current line, replacing whatever was there."""
    print(f"\r{LINE_CLEAR}{message}", end="", file=file, flush=True)


def clear_line(file: TextIO = sys.stderr):
    print(f"\r{LINE_CLEAR}", end="", file=file, flush=True)


def supports_color(file: TextIO = sys.stdout) -> bool:
    # https://no-color.org
    return file.isatty() and not os.environ.get("NO_COLOR")


def stylize(text: str, style: Style, color: bool = True) -> str:
    """Wraps text in the ANSI codes for a style, if color is enabled."""
    if not color or not text or style is Style.DEFAULT:
        return text
    return f"\x1b[{style.value}m{text}\x1b[0m"


def text_width(text: str) -> int:
    """Returns the number of terminal columns needed to show some text.

    Wide characters (e.g. Chinese or Japanese) take up two columns and combining characters (e.g. accents) take up none.
    """
    if text.isascii():
        return len(text)
    return sum(_char_width(char) for char in text)


def clip(text: str, width: int) -> str:
    """Shortens text to fit into a number of terminal columns, ending it with '…' if it had to be shortened."""
    if text_width(text) <= width:
        return text
    if width <= 0:
        return ""

    clipped = ""
    clipped_width = 0
    for char in text:
        char_width = _char_width(char)
        # leave space for the ellipsis
        if clipped_width + char_width > width - 1:
            break
        clipped += char
        clipped_width += char_width
    return clipped + "…"


def format_size(size: float) -> str:
    """Formats a number of bytes, e.g. 1234567 -> '1.2 MB'."""
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1000:
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{size:.1f} TB"


def pluralize(count: int, singular: str, plural: Optional[str] = None) -> str:
    """Formats a count followed by a word, e.g. '1 sample' or '1,234 samples'."""
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count:,} {word}"


def format_path(path: str) -> str:
    """Shortens a path by replacing the home directory with '~'."""
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def _char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
