"""A collection of miscellaneous utilities.

Copyright © 2016 Garrett Powell <garrett@gpowell.net>

This file is part of retain-sync.

retain-sync is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

retain-sync is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with retain-sync.  If not, see <http://www.gnu.org/licenses/>.
"""

import sys
import os
import subprocess
import atexit
import shutil
from collections import defaultdict
from types import FunctionType


def err(*args, **kwargs) -> None:
    """Print to standard error."""
    # TODO: print error message on new line if cursor is not at the beginning
    # of the line
    print(*args, file=sys.stderr, **kwargs)


def env(var: str) -> str:
    """Return a default value if environment variable is unset."""
    defaults = {
        "XDG_CONFIG_HOME":  os.path.join(os.getenv("HOME"), ".config"),
        "XDG_DATA_HOME":    os.path.join(os.getenv("HOME"), ".local/share"),
        "XDG_RUNTIME_DIR":  os.path.join("/run/user", str(os.getuid()))
        }
    defaults = defaultdict(lambda: None, defaults)
    return os.getenv(var, defaults[var])


def tty_input(prompt: str) -> str:
    """Read user input from the tty device."""
    # TODO: figure out how to use readline while taking input from tty
    with open("/dev/tty") as file:
        sys.stdin = file
        usr_in = input(prompt)
    sys.stdin = sys.__stdin__
    return usr_in


def rec_scan(path: str):
    """Recursively scan a directory tree and yield a DirEntry object."""
    for entry in os.scandir(path):
        yield entry
        if entry.is_dir(follow_symlinks=False):
            yield from rec_scan(entry.path)


def shell_cmd(input_cmd: list) -> subprocess.Popen:
    """Run a shell command and terminate it on exit."""
    cmd = subprocess.Popen(
        input_cmd, bufsize=1, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, universal_newlines=True)
    atexit.register(cmd.terminate)
    return cmd


def progress_bar(coverage, msg="", r_align=True) -> FunctionType:
    """Create a function for updating a progress bar.

    Args:
        coverage:   The percentage of the width of the terminal window that the
                    progress bar should cover.
        msg:        A message to be printed opposite the progress bar.
        r_align:    Align the progress bar to the right edge of the screen
                    instead of the left.
    """
    coverage = float(coverage)

    def update(percent) -> None:
        """Update a progress bar.

        Args:
            percent:    Fill the bar to this percentage.
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
