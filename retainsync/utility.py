"""A collection of miscellaneous utilities."""

"""
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
import sqlite3
from collections    import defaultdict
from contextlib     import contextmanager

def err(*args, **kwargs):
    """Print to standard error."""
    # TODO: print error message on new line if cursor is not at the beginning
    # of the line
    print(*args, file=sys.stderr, **kwargs)

def env(var):
    """Return a default value if environment variable is unset."""
    defaults = {
        "XDG_CONFIG_HOME":  os.path.join(os.getenv("HOME"), ".config"),
        "XDG_DATA_HOME":    os.path.join(os.getenv("HOME"), ".local/share")
        }
    defaults = defaultdict(lambda: None, defaults)
    return os.getenv(var, defaults[var])

def tty_input(prompt, prefill=""):
    """Read user input from the tty device."""
    # TODO: allow for the input buffer to be prepopulated with a default value
    # (readline doesn't work normally when sys.stdin is reassigned)
    with open("/dev/tty") as file:
        sys.stdin = file
        usr_in = input(prompt)
    sys.stdin = sys.__stdin__
    return usr_in

@contextmanager
def open_db(path):
    db = sqlite3.connect(path)
    yield db
    db.commit()
    db.close()
