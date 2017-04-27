"""Base classes for persistently storing data.

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
import os
import re
import json
import sqlite3
import contextlib
import hashlib
from typing import List, Generator, Iterable

from zielen.exceptions import FileParseError, ServerError


class ConfigFile:
    """Parse a configuration file.

    Attributes:
        COMMENT_REGEX: This is a regex object that represents a comment line.
        SEPARATOR: This is the string that separates keys from values.
        path: The path of the configuration file.
        raw_vals: A dictionary of unmodified config value strings.
    """
    COMMENT_REGEX = re.compile(r"^\s*#")
    SEPARATOR = "="

    def __init__(self, path: str) -> None:
        self.path = path
        self.raw_vals = {}

    def read(self) -> None:
        """Parse file for key-value pairs and save in a dictionary."""
        try:
            with open(self.path) as file:
                for line in file:
                    # Skip line if it is a comment.
                    if (not self.COMMENT_REGEX.search(line)
                            and self.SEPARATOR in line):
                        key, value = line.partition(self.SEPARATOR)[::2]
                        self.raw_vals[key.strip()] = value.strip()
        except OSError:
            raise FileParseError("could not open the configuration file")

    def write(self, template_path: str) -> None:
        """Generate a new config file based on the input file."""
        try:
            with open(template_path) as infile, open(
                    self.path, "w") as outfile:
                for line in infile:
                    # Skip line if it is a comment.
                    new_line = line
                    if (not self.COMMENT_REGEX.search(line)
                            and self.SEPARATOR in line):
                        key, value = line.partition(self.SEPARATOR)[::2]
                        key = key.strip()
                        if key not in self.raw_vals:
                            continue
                        # Substitute value in the input file with the value in
                        # self.raw_vals.
                        new_line = (
                            key
                            + self.SEPARATOR
                            + self.raw_vals.get(key, "")
                            + "\n")
                    outfile.write(new_line)

        except OSError:
            raise FileParseError("could not open the configuration file")


class JSONFile:
    """Parse a JSON-formatted file.

    Attributes:
        path: The path of the JSON file.
        raw_vals: A dictionary or list of values from the file.
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


class SyncDBFile:
    """Manage a database for keeping track of files in a sync directory.

    Attributes:
        path: The path of the database file.
        conn: The sqlite connection object for the database.
        cur: The sqlite cursor object for the connection.
    """
    def __init__(self, path: str) -> None:
        self.path = path
        if os.path.isfile(self.path):
            self.conn = sqlite3.connect(
                self.path,
                detect_types=sqlite3.PARSE_DECLTYPES,
                isolation_level="IMMEDIATE")
            self.cur = self.conn.cursor()
            self.cur.arraysize = 20
            self.cur.executescript("""\
                PRAGMA foreign_keys = ON;
                """)
        else:
            self.conn = None
            self.cur = None
        # Create adapter from python boolean to sqlite integer.
        sqlite3.register_adapter(bool, int)
        sqlite3.register_converter("BOOL", lambda x: bool(int(x)))

    @contextlib.contextmanager
    def _transact(self) -> Generator[None, None, None]:
        """Check if database file exists and commit the transaction on exit.

        Raises:
            ServerError: The database file wasn't found.
        """
        if not os.path.isfile(self.path):
            raise ServerError("could not connect to the database file")
        with self.conn:
            yield

    def _mark_directory(self, paths: Iterable[str]) -> None:
        """Mark paths as directories."""
        nodes_values = ({
            "path_id": self._get_path_id(path)}
            for path in paths)
        self.cur.executemany("""\
            UPDATE nodes
            SET directory = 1
            WHERE directory = 0
            AND id = :path_id;
            """, nodes_values)

    @staticmethod
    def _get_path_id(path: str) -> int:
        """Hash a file path with SHA-1 and return it as a 64-bit int.

        Args:
            path: The file path to return the hash of.

        Returns:
            The hash of the file path as a 64-bit int.
        """
        sha1_hash = hashlib.sha1()
        sha1_hash.update(path.encode())
        return int.from_bytes(
            sha1_hash.digest()[:8], byteorder="big", signed=True)
