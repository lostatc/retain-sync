"""A collection of miscellaneous utilities.

Copyright © 2016-2018 Garrett Powell <garrett@gpowell.net>

This file is part of zielen.

zielen is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

zielen is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with zielen.  If not, see <http://www.gnu.org/licenses/>.
"""
import os
import re
import atexit
import glob
import collections
import shutil
import subprocess
import datetime
import random
import string
import readline
from typing import List, Tuple, Iterable

from zielen.paths import get_home_dir


def shell_cmd(input_cmd: list) -> subprocess.Popen:
    """Run a shell command and terminate it on exit.

    Args:
        input_cmd: The shell command to run, with each argument as an element
            in a list.
    """
    cmd = subprocess.Popen(
        input_cmd, bufsize=1, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, universal_newlines=True)
    atexit.register(cmd.terminate)
    return cmd


def timestamp_path(path: str, keyword="") -> str:
    """Return a timestamped version of a file path.

    Example:
        >>> timestamp_path("/home/guido/notes.txt", keyword="conflict")
        "/home/guido/notes_conflict-20170219-145503.txt"

    Args:
        path: The file path on which to base the new file path.
        keyword: A string to include in the new file path before the
            timestamp.

    Returns:
        The modified file path.
    """
    keyword += "-" if keyword else keyword
    name, extension = os.path.splitext(path)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return "{0}_{1}{2}{3}".format(name, keyword, timestamp, extension)


def get_path_ancestry(paths: Iterable[str]) -> List[str]:
    """For each path given, get all parent directories up to the root.

    Args:
        paths: The paths to get the ancestors of.

    Returns:
        A deduplicated list of paths sorted by depth from leaf to trunk.
    """
    # A deque is used here because a list cannot be appended to while it is
    # being iterated over.
    path_queue = collections.deque(paths)
    output_paths = set()
    while len(path_queue) > 0:
        path = path_queue.pop()
        output_paths.add(path)
        parent = os.path.dirname(path)
        if parent:
            path_queue.appendleft(parent)

    # Sort paths by depth.
    sorted_paths = list(sorted(
        output_paths, key=lambda x: x.count(os.sep), reverse=True))
    return sorted_paths


def secure_string(length: int) -> str:
    """Generate a securely random alphanumeric string.

    Args:
        length: The length of the string in characters/bytes.
    """
    random_string = "".join(random.SystemRandom().choice(
        string.ascii_letters + string.digits) for i in range(length))
    return random_string


def contract_user(path: str) -> str:
    """Do the opposite of os.path.expanduser.

    Args:
        path: The absolute file path to modify.

    Returns:
        A new file path with the user's home directory replaced with a tilda.
    """
    return os.path.join("~", os.path.relpath(path, get_home_dir()))


def set_path_autocomplete() -> None:
    """Enable file path autocompletion for GNU readline."""
    def autocomplete(text: str, state: int) -> str:
        expanded_path = os.path.expanduser(text)

        if os.path.isdir(expanded_path):
            possible_paths = glob.glob(os.path.join(expanded_path, "*"))
        else:
            possible_paths = glob.glob(expanded_path + "*")

        if expanded_path != text:
            possible_paths = [contract_user(path) for path in possible_paths]
        possible_paths.append(None)

        return possible_paths[state]

    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims("")
    readline.set_completer(autocomplete)


def set_no_autocomplete() -> None:
    """Disable autocompletion for GNU readline."""
    readline.set_completer(None)


class FactoryDict(collections.defaultdict):
    """A defaultdict that passes the key value into the factory function."""
    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        else:
            return self.default_factory(key)


class DictProperty:
    """A property for the getting and setting of individual dictionary keys."""
    class _Proxy:
        def __init__(self, obj, fget, fset, fdel):
            self._obj = obj
            self._fget = fget
            self._fset = fset
            self._fdel = fdel

        def __getitem__(self, key):
            if self._fget is None:
                raise TypeError("can't read item")
            return self._fget(self._obj, key)

        def __setitem__(self, key, value):
            if self._fset is None:
                raise TypeError("can't set item")
            self._fset(self._obj, key, value)

        def __delitem__(self, key):
            if self._fdel is None:
                raise TypeError("can't delete item")
            self._fdel(self._obj, key)

    def __init__(self, fget=None, fset=None, fdel=None, doc=None):
        self._fget = fget
        self._fset = fset
        self._fdel = fdel
        self.__doc__ = doc

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return self._Proxy(obj, self._fget, self._fset, self._fdel)

    def getter(self, fget):
        return type(self)(fget, self._fset, self._fdel, self.__doc__)

    def setter(self, fset):
        return type(self)(self._fget, fset, self._fdel, self.__doc__)

    def deleter(self, fdel):
        return type(self)(self._fget, self._fset, fdel, self.__doc__)


class ProgressBar:
    """An ascii progress bar for the terminal.

    Attributes:
        coverage: The percentage of the width of the terminal window that the
            progress bar should cover as a decimal between 0 and 1.
        message: A message to be printed opposite the progress bar.
        r_align: Align the progress bar to the right edge of the screen as
            opposed to the left.
        fill_char: The character that will comprise the filled portion of the
            bar.
        empty_char: The character that will comprise the empty portion of the
            bar.
    """
    def __init__(
            self, coverage: float, message="", r_align=True,
            fill_char="\u2588", empty_char="\u2591", left_char="",
            right_char="") -> None:
        self.coverage = coverage
        self.message = message
        self.r_align = r_align
        self.fill_char = fill_char
        self.empty_char = empty_char
        self.left_char = left_char
        self.right_char = right_char

    def update(self, fill_amount: float) -> None:
        """Print an updated progress bar.

        Args:
            fill_amount: Fill the bar to this percentage as a decimal between 0
                and 1.
        """
        if fill_amount > 1 or fill_amount < 0:
            raise ValueError("expected a number between 0 and 1")

        term_width = shutil.get_terminal_size()[0]
        bar_length = int(round(term_width * self.coverage))
        filled_length = int(round(bar_length * fill_amount))
        empty_length = bar_length - filled_length
        percent_str = str(round(fill_amount * 100)).rjust(3)
        bar_str = "{0}{1}{2} {3}%".format(
            self.left_char,
            self.fill_char*filled_length + self.empty_char*empty_length,
            self.right_char,
            percent_str)

        # Truncate input message so that it doesn't overlap with the bar.
        trunc_length = term_width - len(bar_str) - 1
        trunc_msg = self.message[:trunc_length]

        if self.r_align:
            print(trunc_msg + bar_str.rjust(term_width - len(trunc_msg)),
                  flush=True, end="\r")
        else:
            print(bar_str + trunc_msg.rjust(term_width - len(bar_str)),
                  flush=True, end="\r")


class BoxTable:
    """Format a table using box-drawing characters.

    This table allows for ANSI escape codes in the data. Each row must have
    the same number of columns. The contents of each row are left-aligned.
    Empty rows are converted to horizontal separators.

    Attributes:
        data: The table data, where each item is a row in the table. The first
            row makes up the table headers.
    """
    HORIZONTAL_CHAR = "\u2500"
    VERTICAL_CHAR = "\u2502"
    TOP_RIGHT_CHAR = "\u2510"
    TOP_LEFT_CHAR = "\u250c"
    BOTTOM_RIGHT_CHAR = "\u2518"
    BOTTOM_LEFT_CHAR = "\u2514"
    CROSS_CHAR = "\u253c"
    TOP_TEE_CHAR = "\u252c"
    BOTTOM_TEE_CHAR = "\u2534"
    LEFT_TEE_CHAR = "\u251c"
    RIGHT_TEE_CHAR = "\u2524"
    ANSI_REGEX = re.compile("(\x1b\\[[0-9;]+m)")
    HEADER_ANSI = ("\x1b[1m", "\x1b[0m")

    def __init__(self, data: List[Tuple[str, ...]]):
        if not all(len(row) == len(data[0]) for row in data):
            raise ValueError("each row must be the same length")
        self.data = data
        self._lengths = self._get_column_lengths()

    def _get_column_lengths(self) -> List[int]:
        """Get the length of each column in the table."""
        columns = [column for column in zip(*self.data)]
        lengths = []
        for column in columns:
            visible_column = [self.ANSI_REGEX.sub("", item) for item in column]
            lengths.append(len(max(visible_column, key=len)))
        return lengths

    def _get_separator(self) -> List[str]:
        """Get the inside portion of a separator row."""
        return [self.HORIZONTAL_CHAR * (length+2) for length in self._lengths]

    def _format_top_separator(self) -> str:
        """Format the top border of the table."""
        return (
            self.TOP_LEFT_CHAR
            + self.TOP_TEE_CHAR.join(self._get_separator())
            + self.TOP_RIGHT_CHAR)

    def _format_bottom_separator(self) -> str:
        """Format the top border of the table."""
        return (
            self.BOTTOM_LEFT_CHAR
            + self.BOTTOM_TEE_CHAR.join(self._get_separator())
            + self.BOTTOM_RIGHT_CHAR)

    def _format_inside_separator(self) -> str:
        """Format the row separator."""
        return (
            self.LEFT_TEE_CHAR
            + self.CROSS_CHAR.join(self._get_separator())
            + self.RIGHT_TEE_CHAR)

    def _format_row(self) -> str:
        """Format a row containing data."""
        for row in self.data:
            if not any(row):
                yield self._format_inside_separator()
            else:
                # str.format() can't be used for padding because it doesn't
                # ignore ANSI escape sequences.
                padding = [
                    length - len(self.ANSI_REGEX.sub("", text))
                    for text, length in zip(row, self._lengths)]
                inside = " {} ".format(self.VERTICAL_CHAR).join(
                    text + " "*spaces for text, spaces in zip(row, padding))

                yield (
                    self.VERTICAL_CHAR
                    + " " + inside + " "
                    + self.VERTICAL_CHAR)

    def format(self) -> str:
        """Format the table data into a string.

        Returns:
            The table as a string.
        """
        data_rows = self._format_row()
        table_lines = [
            self._format_top_separator(),
            next(data_rows).join(self.HEADER_ANSI),
            self._format_inside_separator(),
            *data_rows,
            self._format_bottom_separator()]

        return "\n".join(table_lines)
