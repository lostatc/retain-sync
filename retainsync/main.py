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

import os
import sys

from retainsync.config import LocalConfigFile, ConfigDir
from retainsync.input import parse_args

def main():
    # Read command-line arguments.
    cmd_args = parse_args()

    # Implement '--quiet' flag.
    if cmd_args["quiet"]:
        sys.stdout = open(os.devnull, "a")

    config = LocalConfigFile("/home/garrett/.config/retain-sync/configs/rConfig/config")
    config.read()
    config.check_all()
    config.prompt()
