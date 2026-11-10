import sys


from dataclasses import dataclass, field
from typing import Callable, List, Optional, TextIO, Tuple


from abletools.utils.tui_utils import Style, stylize, supports_color, text_width


# the status column starts after the longest name, but never further right than this
MAX_NAME_WIDTH = 64


# a line of text in the details panel of the tree browser
type DetailLine = Tuple[str, Style]


@dataclass
class TreeItem:
    # the text shown for this item
    name: str = field()
    # a word or two describing this item, e.g. 'unused'
    status: str = field(default="")
    # the color of the status
    style: Style = field(default=Style.DEFAULT)
    # extra information shown after the status
    note: str = field(default="")
    children: List["TreeItem"] = field(default_factory=lambda: [])
    # whether the children of this item are shown
    expanded: bool = field(default=False)
    # whether this item is shown when the tree is filtered
    flagged: bool = field(default=False)
    # the file or folder this item stands for, if any
    path: Optional[str] = field(default=None)
    # whether this item is ticked, or None if it can't be ticked
    checked: Optional[bool] = field(default=None)
    # creates the lines shown in the details panel of the tree browser
    details: Optional[Callable[[], List[DetailLine]]] = field(default=None)


@dataclass
class TreeRow:
    """An item of a flattened tree, i.e. one line of output."""
    item: TreeItem = field()
    depth: int = field()
    # the vertical lines that connect the ancestors of this item, e.g. '│       '
    guides: str = field()
    # whether this item is the last child of its parent
    is_last: bool = field()
    # the index of the parent's row
    parent: Optional[int] = field()


def get_display_name(item: TreeItem) -> str:
    """Returns the name of an item, with a tick box in front of it if it can be ticked."""
    if item.checked is None:
        return item.name
    return ("[x] " if item.checked else "[ ] ") + item.name


def get_children(item: TreeItem, flagged_only: bool) -> List[TreeItem]:
    """Returns the children of an item that are not hidden by the filter."""
    return [child for child in item.children if child.flagged or not flagged_only]


def flatten(root: TreeItem, flagged_only: bool = False) -> List[TreeRow]:
    """Returns the rows of a tree in the order they are shown, skipping the children of collapsed items."""
    rows: List[TreeRow] = []
    _add_rows(rows, root, 0, "", True, None, flagged_only)
    return rows


def get_name_width(rows: List[TreeRow], prefixes: List[str]) -> int:
    """Returns the width of the widest name (including the tree lines in front of it), which is where the status column starts.

    The root works like a heading and is often a long path, so it doesn't count unless it is the only row.
    """
    widths = [text_width(prefix + get_display_name(row.item))
              for prefix, row in zip(prefixes, rows) if row.depth > 0]
    return max(widths, default=text_width(prefixes[0] + get_display_name(rows[0].item)))


def print_tree(root: TreeItem, flagged_only: bool = False, file: TextIO = sys.stdout):
    """Prints a tree with its statuses and notes lined up in columns.

    ~/Samples/                 used     via subfolders · Song A, Song B
    ├── Drums/                 used     3 of 48 samples · Song A
    └── Vocals/                unused   12 samples · 30.1 MB
    """
    color = supports_color(file)
    rows = flatten(root, flagged_only)
    prefixes = [_get_prefix(row) for row in rows]

    name_width = min(get_name_width(rows, prefixes), MAX_NAME_WIDTH)
    status_width = max(text_width(row.item.status) for row in rows)

    for prefix, row in zip(prefixes, rows):
        item = row.item
        name = get_display_name(item)
        name_style = Style.BOLD if row.depth == 0 else Style.DEFAULT
        line = stylize(prefix, Style.DIM, color) + \
            stylize(name, name_style, color)

        if item.status or item.note:
            line += " " * \
                (max(name_width - text_width(prefix + name), 0) + 2)
            # pad the status so that the notes line up, unless there is no note
            status = item.status.ljust(
                status_width) if item.note else item.status
            line += stylize(status, item.style, color)
            if item.note:
                line += "  " + stylize(item.note, Style.DIM, color)
        print(line, file=file)


def _add_rows(rows: List[TreeRow], item: TreeItem, depth: int, guides: str, is_last: bool, parent: Optional[int], flagged_only: bool):
    rows.append(TreeRow(item, depth, guides, is_last, parent))
    if not item.expanded:
        return

    index = len(rows) - 1
    children = get_children(item, flagged_only)
    # the root has no connector, so its children don't need a guide for it
    if depth > 0:
        guides += "    " if is_last else "│   "
    for i, child in enumerate(children):
        _add_rows(rows, child, depth + 1, guides,
                  i == len(children) - 1, index, flagged_only)


def _get_prefix(row: TreeRow) -> str:
    if row.depth == 0:
        return ""
    return row.guides + ("└── " if row.is_last else "├── ")
