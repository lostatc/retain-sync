"""Perform operations on the program's files and directories.

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
import re
import json
from typing import List

from retainsync.exceptions import FileParseError
from retainsync.util.misc import env


class ProgramDir:
    """Get information about the main configuration directory.

    Attributes:
        path:           The path to the program directory.
        profiles_dir:   The base directory containing profile directories.
    """

    path = os.path.join(env("XDG_CONFIG_HOME"), "retain-sync")
    profiles_dir = os.path.join(path, "profiles")

    @classmethod
    def list_profiles(cls) -> List[str]:
        """Get the names of all existing profiles.

        Returns:
            A list containing the name of each profile.
        """
        profile_names = []
        for entry in os.scandir(cls.profiles_dir):
            if entry.is_dir(follow_symlinks=False):
                profile_names.append(entry.name)
        return profile_names


class ConfigFile:
    """Parse a configuration file.

    Attributes:
        path:      The path to the configuration file.
        raw_vals:  A dictionary of unmodified config value strings.
    """

    # This is regex that denotes a comment line.
    comment_reg = re.compile(r"^\s*#")

    def __init__(self, path: str) -> None:
        self.path = path
        self.raw_vals = {}

    def read(self) -> None:
        """Parse file for key-value pairs and save in a dictionary."""
        try:
            with open(self.path) as file:
                for line in file:
                    # Skip line if it is a comment.
                    if (not self.comment_reg.search(line)
                            and re.search("=", line)):
                        key, value = line.partition("=")[::2]
                        self.raw_vals[key.strip()] = value.strip()
        except OSError:
            raise FileParseError("could not open the configuration file")

    def write(self, infile: str) -> None:
        """Generate a new config file based on the input file."""

        try:
            with open(infile) as infile:
                with open(self.path, "w") as outfile:
                    for line in infile:
                        # Skip line if it is a comment.
                        if (not self.comment_reg.search(line)
                                and re.search("=", line)):
                            key, value = line.partition("=")[::2]
                            key = key.strip()
                            value = value.strip()
                            if key not in self.all_keys:
                                continue
                            try:
                                # Substitute value in the input file with the
                                # value in self.raw_vals.
                                line = key + "=" + self.raw_vals[key] + "\n"
                            except KeyError:
                                pass
                        outfile.write(line)

        except OSError:
            raise FileParseError("could not open the configuration file")


class JSONFile:
    """Parse a JSON-formatted file.

    Attributes:
        path:       The path to the JSON file.
        raw_vals:   A dictionary or list of values from the file.
    """
    def __init__(self, path) -> None:
        self.path = path
        self.raw_vals = None

    def read(self) -> None:
        """Read file into an object."""
        with open(self.path) as file:
            self.raw_vals = json.load(file)

    def write(self) -> None:
        """Write object to a file."""
        with open(self.path, "w") as file:
            json.dump(self.raw_vals, file, indent=4)
