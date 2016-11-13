"""This is a collection of miscellaneous utilities."""

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
import readline

def err(*args, **kwargs):
    """Print to standard error."""
    print(*args, file=sys.stderr, **kwargs)

def env(var):
    """Return a default value if environment variable is unset."""
    try:
        return os.environ[var]
    except KeyError:
        if var == "XDG_CONFIG_HOME":
            return os.path.join(os.environ["HOME"], ".config")
        elif var == "XDG_DATA_HOME":
            return os.path.join(os.environ["HOME"], ".local/share")

def rinput(prompt, prefill=""):
    """Prompt the user for input with a pre-populated input buffer."""
    readline.set_startup_hook(lambda: readline.insert_text(prefill))
    result = input(prompt)
    readline.set_startup_hook()
    return result
