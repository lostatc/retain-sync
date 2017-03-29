"""A collection of miscellaneous utilities.

Copyright © 2016-2017 Garrett Powell <garrett@gpowell.net>

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

import sys
import os
import subprocess
import atexit
import shutil
import readline
import pwd
import hashlib
import datetime
import collections
from typing import Callable, Collection, Iterable, Generator


def err(*args, **kwargs) -> None:
    """Print to standard error."""
    print(*args, file=sys.stderr, **kwargs)


def env(var: str) -> str:
    """Return a default value if environment variable is unset."""
    defaults = {
        "XDG_CONFIG_HOME":  os.path.join(os.getenv("HOME"), ".config"),
        "XDG_DATA_HOME":    os.path.join(os.getenv("HOME"), ".local/share"),
        "XDG_RUNTIME_DIR":  os.path.join("/run/user", str(os.getuid())),
        "USER":             pwd.getpwuid(os.getuid()).pw_name
        }
    defaults = collections.defaultdict(lambda: None, defaults)
    return os.getenv(var, defaults[var])


def tty_input(prompt: str) -> str:
    """Read user input from the tty device.

    Args:
        prompt: The string to serve as the command-line input prompt.
    """
    # TODO: figure out how to use readline while taking input from tty
    with open("/dev/tty") as file:
        sys.stdin = file
        usr_in = input(prompt)
    sys.stdin = sys.__stdin__
    return usr_in


def prefill_input(prompt: str, prefill: str) -> str:
    """Prompt the user for input with a prepopulated input buffer.

    Args:
        prompt: The string to serve as the command-line input prompt.
        prefill: The string to prefill the input buffer with.
    """
    readline.set_startup_hook(lambda: readline.insert_text(prefill))
    usr_input = input(prompt)
    readline.set_startup_hook()
    return usr_input


def rec_scan(path: str) -> Generator[os.DirEntry, None, None]:
    """Recursively scan a directory tree and yield an os.DirEntry object.

    Args:
        path: The path of the directory to scan.
    """
    for entry in os.scandir(path):
        yield entry
        if entry.is_dir(follow_symlinks=False):
            yield from rec_scan(entry.path)


def symlink_tree(src_dir: str, dest_dir: str,
                 src_files: Iterable[str], src_dirs: Iterable[str],
                 exclude=None, overwrite=False) -> None:
    """Recursively copy a directory as a tree of symlinks.

    This function does not look in the source directory. Instead, the caller
    is expected to provide the paths of all files and directories in the
    source. Files and directories need to be passed in separately to
    distinguish files from empty directories.

    Args:
        src_dir: The absolute path of the directory to source files from.
        dest_dir: The absolute path of the directory to create symlinks in.
        src_dirs: The relative paths of the directories to copy to the
            destination.
        src_files: The relative paths of the files to symlink in the
            destination.
        exclude: The relative paths of files/directories to not symlink.
        overwrite: Overwrite existing files in the destination directory
            with symlinks.
    """
    exclude = set() if exclude is None else set(exclude)
    src_dirs = set(src_dirs)
    src_files = set(src_files)
    src_paths = list(src_dirs | src_files)

    # Sort paths by depth from trunk to leaf.
    src_paths.sort(key=lambda x: x.count(os.sep))

    os.makedirs(dest_dir, exist_ok=True)
    for src_path in src_paths:
        full_src_path = os.path.join(src_dir, src_path)
        full_dest_path = os.path.join(dest_dir, src_path)
        common = {
            os.path.commonpath([ex_path, src_path]) for ex_path in exclude}
        if common & exclude:
            continue
        if src_path in src_dirs:
            try:
                os.mkdir(full_dest_path)
            except FileExistsError:
                pass
        elif src_path in src_files:
            try:
                os.symlink(full_src_path, full_dest_path)
            except FileExistsError:
                if overwrite:
                    os.remove(full_dest_path)
                    os.symlink(full_src_path, full_dest_path)


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


def progress_bar(
        coverage: float, msg="", r_align=True) -> Callable[[float], None]:
    """Create a function for updating a progress bar.

    Args:
        coverage: The percentage of the width of the terminal window that the
            progress bar should cover.
        msg: A message to be printed opposite the progress bar.
        r_align: Align the progress bar to the right edge of the screen as
            opposed to the left.
    """
    coverage = float(coverage)

    def update(percent: float) -> None:
        """Update a progress bar.

        Args:
            percent: Fill the bar to this percentage.
        """
        percent = float(percent)
        if percent > 1 or percent < 0:
            raise ValueError("expected a number between 0 and 1")
        term_width = shutil.get_terminal_size()[0]
        bar_length = int(round(term_width * coverage))
        filled_length = int(round(bar_length * percent))
        empty_length = bar_length - filled_length
        percent_str = str(round(percent*100)).rjust(3)
        bar_str = "[{0}] {1}%".format(
            "#"*filled_length + "-"*empty_length, percent_str)

        # Truncate input message so that it doesn't overlap with the bar.
        nonlocal msg
        trunc_length = term_width - len(bar_str) - 1
        msg = msg[:trunc_length]

        if r_align:
            print(msg + bar_str.rjust(term_width - len(msg)),
                  flush=True, end="\r")
        else:
            print(bar_str + msg.rjust(term_width - len(bar_str)),
                  flush=True, end="\r")
    return update


def b2sum(path: str) -> str:
    """Get the BLAKE2 checksum of a file, reading one block at a time.

    Args:
        path: The path of the file to find the checksum of.
    """
    blake2_hash = hashlib.blake2b()
    block_size = os.stat(path).st_blksize
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(block_size), b""):
            blake2_hash.update(chunk)
    return blake2_hash.hexdigest()


def timestamp_path(path: str, keyword="") -> str:
    """Return a timestamped version of a file path.

    Example:
        >>> timestamp_path("/home/guido/notes.txt", keyword="conflict")
        "/home/guido/notes_conflict-20170219-145503.txt"

    Args:
        path: The file path on which to base the new file path.
        keyword: A string to include in the new file path before the
            timestamp.
    """
    keyword += "-" if keyword else keyword
    name, extension = os.path.splitext(path)
    return (
        name
        + "_"
        + keyword
        + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        + extension)


def print_table(data: Collection, headers: Collection) -> None:
    """Print input values in a formatted table.

    All values in the table are left-aligned, and columns are as wide as
    their longest value.

    Args:
        data: The values used to fill the body of the table. Each item in this
            collection represents a row in the table.
        headers: The values to use as column headings.
    """
    column_lengths = []
    for content, header in zip(zip(*data), headers):
        column = [str(item) for item in [*content, header]]
        column_lengths.append(len(max(column, key=len)))

    # Print the table header.
    print(" | ".join([
        "{0:<{1}}".format(name, width)
        for name, width in zip(headers, column_lengths)]))

    # Print the separator between the header and body.
    print("-+-".join(["-"*length for length in column_lengths]))

    # Print the table body.
    for row in data:
        print(" | ".join([
             "{0:<{1}}".format(field, width)
             for field, width in zip(row, column_lengths)]))


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
