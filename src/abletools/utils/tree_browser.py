import importlib.util
import os
import sys
import textwrap


from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence, Tuple


from abletools.utils.process_utils import FILE_MANAGER_NAME, reveal_in_file_manager
from abletools.utils.tree import DetailLine, TreeItem, TreeRow, flatten, get_children, get_display_name, get_name_width
from abletools.utils.tui_utils import Style, clip, text_width


# Python on Windows does not include curses, but it can be installed with 'pip install windows-curses'
HAS_CURSES = importlib.util.find_spec("_curses") is not None
if TYPE_CHECKING or HAS_CURSES:
    import curses


MIN_WIDTH = 40
MIN_HEIGHT = 10

ESCAPE = 27
TAB = 9
ENTER_KEYS = (10, 13)


@dataclass
class BrowserAction:
    """Something the user can do to the selected item by pressing a key."""
    # the key that runs the action, e.g. 'c'
    key: str = field()
    # what the action does, shown in the footer, e.g. 'convert'
    label: str = field()
    # runs the action and returns a message for the footer; the action may change the tree
    run: Callable[[TreeItem], Optional[str]] = field()
    # whether the action can be used on an item
    applies: Callable[[TreeItem], bool] = field(default=lambda item: True)
    # shown in the footer while the action is running
    busy_message: str = field(default="Working...")


def can_browse() -> bool:
    """Whether the tree browser can be shown, i.e. curses is installed and we are running in a terminal."""
    return HAS_CURSES and sys.stdin.isatty() and sys.stdout.isatty()


def browse_tree(root: TreeItem, title: str, filter_name: Optional[str] = None, flagged_only: bool = False, actions: Sequence[BrowserAction] = (),
                on_check: Optional[Callable[[TreeItem], None]] = None):
    """Shows a tree in an interactive browser until the user quits.

    :param root: The root of the tree.
    :param title: The text shown at the top of the browser.
    :param filter_name: What flagged items are called, e.g. 'unused only'. If this is None, the tree cannot be filtered.
    :param flagged_only: Whether the tree starts off filtered.
    :param actions: Things the user can do to the selected item.
    :param on_check: Called after an item is ticked or unticked, e.g. to update other items that depend on it.
    """
    # stop curses from waiting a second after the escape key is pressed
    os.environ.setdefault("ESCDELAY", "25")
    browser = TreeBrowser(root, title, filter_name,
                          flagged_only, actions, on_check)
    curses.wrapper(browser.run)


class TreeBrowser:
    def __init__(self, root: TreeItem, title: str, filter_name: Optional[str], flagged_only: bool, actions: Sequence[BrowserAction] = (),
                 on_check: Optional[Callable[[TreeItem], None]] = None):
        self.root = root
        self.title = title
        self.filter_name = filter_name
        self.actions = actions
        self.on_check = on_check
        self.flagged_only = flagged_only and filter_name is not None
        # which panel the arrow keys move around in
        self.details_focused = False
        # the index of the selected row
        self.cursor = 0
        # the index of the first visible row
        self.top = 0
        # the index of the first visible details line
        self.details_top = 0
        # a message shown in the footer until the next key press
        self.message: Optional[str] = None

        self.rows: List[TreeRow] = []
        self._parents: Dict[int, TreeItem] = {}
        self._find_parents(root)
        # wrapped details lines by item id and width
        self._details: Dict[Tuple[int, int], List[DetailLine]] = {}
        self._styles: Dict[Style, int] = {}
        self._refresh_rows()

    def run(self, screen: "curses.window"):
        self.screen = screen
        try:
            curses.curs_set(0)
        except curses.error:
            # some terminals can't hide the cursor
            pass
        self._init_styles()

        while True:
            self._draw()
            key = self._read_key()
            self.message = None
            if not self._handle_key(key):
                return

    def _read_key(self) -> int:
        """Waits for a key press. Returns -1 for key sequences that curses didn't recognise."""
        key = self.screen.getch()
        if key != ESCAPE:
            return key

        # curses usually turns the sequences sent by special keys (e.g. '\x1b[A' for the up arrow) into a single key code,
        # but not if the terminal sends a sequence that its terminfo entry doesn't list.
        # Read the rest of the sequence so that it isn't mistaken for the escape key followed by some letters.
        self.screen.nodelay(True)
        sequence = ""
        char = self.screen.getch()
        while char != -1:
            sequence += chr(char)
            char = self.screen.getch()
        self.screen.nodelay(False)

        if sequence == "":
            return ESCAPE
        # terminals send either '[' or 'O' before the arrow keys, depending on their mode
        keys = {"A": curses.KEY_UP, "B": curses.KEY_DOWN, "C": curses.KEY_RIGHT, "D": curses.KEY_LEFT,
                "H": curses.KEY_HOME, "F": curses.KEY_END, "1~": curses.KEY_HOME, "4~": curses.KEY_END,
                "5~": curses.KEY_PPAGE, "6~": curses.KEY_NPAGE}
        if sequence[0] in "[O":
            return keys.get(sequence[1:], -1)
        return -1

    def _handle_key(self, key: int) -> bool:
        """Responds to a key press. Returns False if the browser should close."""
        if key in (ord("q"), ord("Q")):
            return False
        if key == ESCAPE:
            if not self.details_focused:
                return False
            self.details_focused = False
        elif key == TAB or key == curses.KEY_BTAB:
            self.details_focused = not self.details_focused
        elif key == ord("f") and self.filter_name is not None:
            self.flagged_only = not self.flagged_only
            self._refresh_rows(self._selected())
        elif key == ord("o"):
            self._reveal()
        elif self._find_action(key) is not None:
            self._run_action(self._find_action(key))
        elif key == ord(" ") and self._selected().checked is not None:
            self._toggle_checked(self._selected())
        elif self.details_focused:
            self._handle_details_key(key)
        else:
            self._handle_tree_key(key)
        return True

    def _handle_tree_key(self, key: int):
        page = max(self._get_layout()[0] - 1, 1)
        item = self._selected()
        has_children = len(get_children(item, self.flagged_only)) > 0

        if key in (curses.KEY_UP, ord("k")):
            self._move_to(self.cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move_to(self.cursor + 1)
        elif key == curses.KEY_PPAGE:
            self._move_to(self.cursor - page)
        elif key == curses.KEY_NPAGE:
            self._move_to(self.cursor + page)
        elif key in (curses.KEY_HOME, ord("g")):
            self._move_to(0)
        elif key in (curses.KEY_END, ord("G")):
            self._move_to(len(self.rows) - 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            # expand, or step into the item if it is already expanded, or tick the item if it can be ticked
            if has_children and not item.expanded:
                self._set_expanded(item, True)
            elif has_children:
                self._move_to(self.cursor + 1)
            elif item.checked is not None:
                self._toggle_checked(item)
        elif key in (curses.KEY_LEFT, ord("h")):
            # collapse, or step out to the parent if the item is already collapsed
            parent = self.rows[self.cursor].parent
            if has_children and item.expanded:
                self._set_expanded(item, False)
            elif parent is not None:
                self._move_to(parent)
        elif key in ENTER_KEYS or key in (curses.KEY_ENTER, ord(" ")):
            if has_children:
                self._set_expanded(item, not item.expanded)

    def _handle_details_key(self, key: int):
        page = max(self._get_layout()[1] - 1, 1)
        if key in (curses.KEY_UP, ord("k")):
            self.details_top -= 1
        elif key in (curses.KEY_DOWN, ord("j")):
            self.details_top += 1
        elif key == curses.KEY_PPAGE:
            self.details_top -= page
        elif key == curses.KEY_NPAGE:
            self.details_top += page
        elif key in (curses.KEY_HOME, ord("g")):
            self.details_top = 0
        elif key in (curses.KEY_END, ord("G")):
            self.details_top = sys.maxsize
        elif key in (curses.KEY_LEFT, ord("h")):
            self.details_focused = False
        # _draw_details() keeps details_top in range
        self.details_top = max(self.details_top, 0)

    def _selected(self) -> TreeItem:
        return self.rows[self.cursor].item

    def _move_to(self, index: int):
        index = max(0, min(index, len(self.rows) - 1))
        if index != self.cursor:
            self.cursor = index
            self.details_top = 0

    def _set_expanded(self, item: TreeItem, expanded: bool):
        item.expanded = expanded
        self._refresh_rows(item)

    def _toggle_checked(self, item: TreeItem):
        item.checked = not item.checked
        if self.on_check is not None:
            self.on_check(item)
        self._tree_changed(item)

    def _find_action(self, key: int) -> Optional[BrowserAction]:
        for action in self.actions:
            if key == ord(action.key) and action.applies(self._selected()):
                return action
        return None

    def _run_action(self, action: Optional[BrowserAction]):
        if action is None:
            return
        item = self._selected()
        # actions can take a while, so show that something is happening
        self.message = action.busy_message
        self._draw()
        self.message = action.run(item)
        self._tree_changed(item)

    def _tree_changed(self, selected: TreeItem):
        """Updates everything that depends on the tree after an action or a tick may have changed it."""
        self._parents.clear()
        self._find_parents(self.root)
        self._details.clear()
        self._refresh_rows(selected)

    def _reveal(self):
        path = self._selected().path
        if path is None:
            return
        if not os.path.exists(path):
            self.message = "This file no longer exists."
            return
        reveal_in_file_manager(path)
        self.message = f"Revealed in {FILE_MANAGER_NAME}."

    def _refresh_rows(self, selected: Optional[TreeItem] = None):
        """Flattens the tree again after it changed, keeping the selected item (or its closest visible ancestor) selected."""
        self.rows = flatten(self.root, self.flagged_only)
        self.name_width = get_name_width(
            self.rows, [self._get_prefix(row) for row in self.rows])
        self.status_width = max(text_width(row.item.status)
                                for row in self.rows)

        indices = {id(row.item): i for i, row in enumerate(self.rows)}
        while selected is not None and id(selected) not in indices:
            selected = self._parents.get(id(selected))
        self.cursor = indices[id(selected)] if selected is not None else 0

    def _find_parents(self, item: TreeItem):
        for child in item.children:
            self._parents[id(child)] = item
            self._find_parents(child)

    def _get_layout(self) -> Tuple[int, int]:
        """Returns the height of the tree panel and the height of the details panel."""
        height, _ = self.screen.getmaxyx()
        # leave space for the header, the details title and the footer
        body_height = height - 3
        details_height = max(body_height * 2 // 5, 3)
        return body_height - details_height, details_height

    def _draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < MIN_HEIGHT or width < MIN_WIDTH:
            self._put(0, 0, "The terminal is too small. Press q to quit.")
            self.screen.refresh()
            return

        tree_height, details_height = self._get_layout()
        self._draw_header(width)
        self._draw_tree(1, tree_height, width)
        self._draw_details(1 + tree_height, details_height, width)
        self._draw_footer(height - 1, width)
        self.screen.refresh()

    def _draw_header(self, width: int):
        position = f" {self.cursor + 1}/{len(self.rows)} "
        self._put(0, 0, " " * width, curses.A_REVERSE)
        self._put(0, 1, clip(self.title, width - len(position) - 2),
                  curses.A_REVERSE | curses.A_BOLD)
        self._put(0, width - len(position), position, curses.A_REVERSE)

    def _draw_tree(self, y: int, height: int, width: int):
        # scroll so that the selected row is visible
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + height:
            self.top = self.cursor - height + 1
        self.top = max(min(self.top, len(self.rows) - height), 0)

        # long names shouldn't push the statuses off the screen
        name_width = min(self.name_width, width // 2)
        for i, row in enumerate(self.rows[self.top:self.top + height]):
            self._draw_row(y + i, row, self.top + i ==
                           self.cursor, name_width, width)

    def _draw_row(self, y: int, row: TreeRow, selected: bool, name_width: int, width: int):
        item = row.item
        highlight = curses.A_REVERSE if selected else 0
        if selected:
            self._put(y, 0, " " * width, highlight)

        prefix = self._get_prefix(row)
        x = self._put(y, 0, prefix, self._styles[Style.DIM] | highlight)
        name_style = Style.BOLD if row.depth == 0 else Style.DEFAULT
        x = self._put(y, x, get_display_name(item),
                      self._styles[name_style] | highlight)

        if item.status or item.note:
            x = max(x, name_width) + 2
            x = self._put(y, x, item.status.ljust(self.status_width),
                          self._styles[item.style] | highlight)
            self._put(y, x + 2, item.note,
                      self._styles[Style.DIM] | highlight)

    def _draw_details(self, y: int, height: int, width: int):
        lines = self._get_details(width - 2)
        self.details_top = min(self.details_top, max(len(lines) - height, 0))

        # the title doubles as a divider between the tree and the details
        title = " Details "
        if len(lines) > height:
            last = min(self.details_top + height, len(lines))
            title += f"({self.details_top + 1}-{last} of {len(lines)}) "
        title_style = curses.A_REVERSE if self.details_focused else self._styles[Style.DIM]
        self._put(y, 0, "─" * width, self._styles[Style.DIM])
        self._put(y, 2, title, title_style | curses.A_BOLD)

        for i, (text, style) in enumerate(lines[self.details_top:self.details_top + height]):
            self._put(y + 1 + i, 1, text, self._styles[style])

    def _draw_footer(self, y: int, width: int):
        if self.message is not None:
            self._put(y, 1, self.message, curses.A_BOLD)
            return

        hints: List[Tuple[str, str]] = [("↑↓", "move")]
        if self.details_focused:
            hints += [("←/tab", "back to tree")]
        else:
            hints += [("←→", "collapse/expand"), ("tab", "scroll details")]
        item = self._selected()
        if item.checked is not None:
            hints.append(("space/→", "untick" if item.checked else "tick"))
        hints += [(action.key, action.label)
                  for action in self.actions if action.applies(item)]
        if self.filter_name is not None:
            hints.append(
                ("f", "show all" if self.flagged_only else self.filter_name))
        if item.path is not None:
            hints.append(("o", f"show in {FILE_MANAGER_NAME}"))
        hints.append(("q", "quit"))

        x = 1
        for key, label in hints:
            if x + text_width(f"{key} {label}") >= width:
                break
            x = self._put(y, x, key, curses.A_BOLD)
            x = self._put(y, x + 1, label, self._styles[Style.DIM]) + 3

    def _get_prefix(self, row: TreeRow) -> str:
        """Returns the tree lines in front of an item, with an arrow showing whether it is expanded."""
        has_children = len(get_children(row.item, self.flagged_only)) > 0
        marker = ("▾" if row.item.expanded else "▸") if has_children else "─"
        if row.depth == 0:
            return (marker if has_children else " ") + " "
        return row.guides + ("└─" if row.is_last else "├─") + marker + " "

    def _get_details(self, width: int) -> List[DetailLine]:
        """Returns the details of the selected item, wrapped to fit the width of the screen."""
        item = self._selected()
        key = (id(item), width)
        if key not in self._details:
            lines = item.details() if item.details is not None else [
                (item.name, Style.BOLD)]
            wrapped: List[DetailLine] = []
            for text, style in lines:
                # keep the indentation of wrapped lines, plus a little extra
                indent = " " * (len(text) - len(text.lstrip()))
                parts = textwrap.wrap(
                    text, width, subsequent_indent=indent + "  ")
                wrapped.extend((part, style) for part in parts or [""])
            self._details[key] = wrapped
        return self._details[key]

    def _init_styles(self):
        self._styles = {style: curses.A_NORMAL for style in Style}
        self._styles[Style.BOLD] = curses.A_BOLD
        self._styles[Style.DIM] = curses.A_DIM
        if not curses.has_colors():
            return

        curses.start_color()
        try:
            # use the terminal's own background color
            curses.use_default_colors()
            background = -1
        except curses.error:
            background = curses.COLOR_BLACK

        colors = {Style.RED: curses.COLOR_RED, Style.GREEN: curses.COLOR_GREEN, Style.YELLOW: curses.COLOR_YELLOW,
                  Style.BLUE: curses.COLOR_BLUE, Style.CYAN: curses.COLOR_CYAN}
        for pair, (style, color) in enumerate(colors.items(), start=1):
            curses.init_pair(pair, color, background)
            self._styles[style] = curses.color_pair(pair)

    def _put(self, y: int, x: int, text: str, attributes: int = 0) -> int:
        """Draws text clipped to the width of the screen. Returns the column after the text."""
        height, width = self.screen.getmaxyx()
        if y >= height or x >= width:
            return x
        text = clip(text, width - x)
        try:
            self.screen.addstr(y, x, text, attributes)
        except (curses.error, UnicodeEncodeError):
            # curses raises an error after drawing in the bottom right corner because the cursor can't move past it
            pass
        return x + text_width(text)
