"""Classes for files in the profile directory.

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
import sys
import glob
import uuid
import getpass
import sqlite3
import datetime
import textwrap
import readline  # This is not unused. Importing it adds features to input().
import collections
from typing import (
    Any, Iterable, Generator, Dict, NamedTuple, Optional, Union, Set, List)

import pkg_resources

from zielen.paths import get_xdg_data_home, get_profiles_dir
from zielen.containerbase import JSONFile, ConfigFile, SyncDBFile
from zielen.io import scan_tree
from zielen.utils import (
    DictProperty, secure_string, set_no_autocomplete, set_path_autocomplete)
from zielen.exceptions import FileParseError

PathData = NamedTuple(
    "PathData", [("directory", bool), ("priority", float), ("local", bool)])


class Profile:
    """Get information about a profile and its contents.

    Attributes:
        name: The name of the profile.
        path: The path of the profile directory.
        cfg_path: The path of the configuration file.
        exclude_path: The path of the exclude file.
        _exclude_file: An object for the exclude pattern file.
        _info_file: An object for the JSON file for profile metadata.
        _db_file: An object for the file priority database.
        _cfg_file: An object for the profile's configuration file.
    """
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = os.path.join(get_profiles_dir(), self.name)
        self._exclude_file = ProfileExcludeFile(
            os.path.join(self.path, "exclude"))
        self._info_file = ProfileInfoFile(os.path.join(self.path, "info.json"))
        self._db_file = ProfileDBFile(
            os.path.join(self.path, "local.db"))
        self._cfg_file = ProfileConfigFile(os.path.join(self.path, "config"))

        # Import methods from content classes.
        self.cfg_path = self._cfg_file.path
        self.exclude_path = self._exclude_file.path
        self.exclude_matches = self._exclude_file.matches
        self.all_exclude_matches = self._exclude_file.all_matches
        self.add_paths = self._db_file.add_paths
        self.add_inflated = self._db_file.add_inflated
        self.update_paths = self._db_file.update_paths
        self.rm_paths = self._db_file.rm_paths
        self.get_path_info = self._db_file.get_path_info
        self.get_paths = self._db_file.get_paths
        self.increment = self._db_file.increment
        self.adjust_all = self._db_file.adjust_all

    def read(self) -> None:
        """Load data from persistent storage."""
        # The order here is important. If a file is not found, 
        # all subsequent files will not be read. The info file should be 
        # read first. 
        self._info_file.read()
        self._cfg_file.read()
        self._cfg_file.check_all()
        self._exclude_file.reset()

    def generate(
            self, init_options: Dict[str, Any], exclude_path=None,
            template_path=None) -> None:
        """Generate files for storing persistent data."""
        os.makedirs(self.path, exist_ok=True)

        self._exclude_file.generate(exclude_path)
        self._info_file.generate(self.name, init_options)

        try:
            self._db_file.create()
        except FileExistsError:
            pass

        if template_path:
            template_file = ProfileConfigFile(template_path)
            template_file.read()
            template_file.check_all(check_empty=False, context="template file")
            self._cfg_file.raw_vals = template_file.raw_vals

        self._cfg_file.prompt()

        if template_path:
            self._cfg_file.write(template_path)
        else:
            # TODO: Get the path of the master config template from
            # setup.py instead of hardcoding it.
            self._cfg_file.write(os.path.join(
                sys.prefix, "share/zielen/config-template"))

    def write(self) -> None:
        """Write data to persistent storage."""
        self._info_file.write()
        self._db_file.commit()

    @property
    def status(self) -> str:
        """A short string describing the status of the profile.

        "initialized": Fully initialized.
        "partial": Partially initialized.
        """
        return self._info_file.vals["Status"]

    @status.setter
    def status(self, value: str) -> None:
        self._info_file.vals["Status"] = value

    @staticmethod
    def _convert_epoch(timestamp: str) -> float:
        """Convert a human-readable timestamp to epoch time."""
        return datetime.datetime.strptime(
            timestamp, "%Y-%m-%dT%H:%M:%S.%f").replace(
            tzinfo=datetime.timezone.utc).timestamp()

    @staticmethod
    def _convert_timestamp(epoch: float) -> str:
        """Convert an epoch timestamp to a human-readable one."""
        # Use strftime() instead of isoformat() because the latter
        # doesn't print the decimal point if the microsecond is 0,
        # which would prevent it from being parsed by strptime().
        return datetime.datetime.utcfromtimestamp(
            epoch).strftime("%Y-%m-%dT%H:%M:%S.%f")

    @property
    def last_sync(self) -> float:
        """The time of the last sync in epoch time."""
        return self._convert_epoch(self._info_file.vals["LastSync"])

    @last_sync.setter
    def last_sync(self, value: float) -> None:
        self._info_file.vals["LastSync"] = self._convert_timestamp(value)

    @property
    def last_adjust(self) -> float:
        """The time of the last priority adjustment in epoch time."""
        return self._convert_epoch(self._info_file.vals["LastAdjust"])

    @last_adjust.setter
    def last_adjust(self, value: float) -> None:
        self._info_file.vals["LastAdjust"] = self._convert_timestamp(value)

    @property
    def version(self) -> str:
        """The version of the program that the profile was initialized by."""
        return self._info_file.vals["Version"]

    @version.setter
    def version(self, value: str) -> str:
        self._info_file.vals["Version"] = value

    @property
    def id(self) -> str:
        """A UUID to identify the profile.

        This is specifically to identify it among all profiles that share a
        remote directory.
        """
        return self._info_file.vals["ID"]

    @id.setter
    def id(self, value: str) -> str:
        self._info_file.vals["ID"] = value

    @property
    def add_remote(self) -> bool:
        """Whether the '--add-remote' flag was given at initialization."""
        return self._info_file.vals["InitOptions"]["add_remote"]

    @add_remote.setter
    def add_remote(self, value: bool) -> None:
        self._info_file.vals["InitOptions"]["add_remote"] = value

    @property
    def local_path(self) -> str:
        """The absolute path of the local directory."""
        return os.path.expanduser(
            os.path.normpath(self._cfg_file.vals["LocalDir"]))

    @property
    def remote_path(self) -> str:
        """The absolute path of the remote directory."""
        return os.path.expanduser(
            os.path.normpath(self._cfg_file.vals["RemoteDir"]))

    @property
    def storage_limit(self) -> int:
        """The number of bytes of data to keep in the local directory."""
        num, prefix, unit = re.findall(
            r"^([0-9]+)\s*([kKMG])(B|iB)?$",
            self._cfg_file.vals["StorageLimit"])[0]

        if unit == "iB" or not unit:
            base = 1024
        elif unit == "B":
            base = 1000

        if prefix in ["k", "K"]:
            exponent = 1
        elif prefix == "M":
            exponent = 2
        elif prefix == "G":
            exponent = 3

        return int(num) * base**exponent

    @property
    def sync_interval(self) -> int:
        """The number of seconds the daemon will wait between syncs."""
        return int(self._cfg_file.vals["SyncInterval"]) * 60

    @property
    def cleanup_period(self) -> Optional[int]:
        """The number of seconds before files in the trash are deleted."""
        value = self._cfg_file.vals["TrashCleanupPeriod"]
        if value.startswith("-"):
            return None
        else:
            return int(value) * 60 * 60 * 24

    @property
    def priority_half_life(self) -> int:
        """The half-life of file priorities in seconds."""
        return int(self._cfg_file.vals["PriorityHalfLife"]) * 60**2

    def _convert_bool(self, value: str) -> bool:
        """Convert a string to a bool."""
        if value in self._cfg_file.TRUE_VALS:
            return True
        elif value in self._cfg_file.FALSE_VALS:
            return False

    @property
    def use_trash(self) -> bool:
        """Permanently delete remote files that were deleted locally."""
        return self._convert_bool(self._cfg_file.vals["UseTrash"])

    @property
    def inflate_priority(self) -> bool:
        """Inflate the priority of new local files."""
        return self._convert_bool(self._cfg_file.vals["InflatePriority"])

    @property
    def account_for_size(self) -> bool:
        """Take file size into account when prioritizing files."""
        return self._convert_bool(self._cfg_file.vals["AccountForSize"])


class ProfileExcludeFile:
    """Manipulate a file containing exclude patterns for the profile.

    A copy of the exclude pattern file for each client is kept in the remote
    directory so that each client can determine if every other client has
    excluded a given file.

    Attributes:
        comment_regex: Regex that denotes a comment line.
        path: The path of the exclude pattern file.
        _matches: A dict of relative paths of files that match the globbing
            patterns for each input path.
        _all_matches: A dict of relative paths of files that match the globbing
            patterns and all files under them for each input path.
    """
    comment_regex = re.compile(r"^\s*#")

    def __init__(self, path: str) -> None:
        self.path = path
        self._matches = {}
        self._all_matches = {}
        
    def reset(self) -> None:
        """Clear cached information."""
        self._matches.clear()
        self._all_matches.clear()

    def generate(self, infile=None) -> None:
        """Generate a new file with comments.

        Args:
            infile: If supplied, copy lines from this file into the new one.
        """
        with open(self.path, "w") as outfile:
            outfile.write(textwrap.dedent("""\
                # This file contains patterns representing files and directories to exclude
                # from syncing.
                #
                # The patterns follow shell globbing rules as described in zielen(1).
                """))
            if infile == "-":
                for line in sys.stdin.read():
                    outfile.write(line)
            elif infile:
                with open(infile) as infile:
                    for line in infile:
                        outfile.write(line)

    def _readlines(self) -> Generator[str, None, None]:
        """Yield lines that are not comments.

        Yields:
            Each line in the file that's not a comment.
        """
        with open(self.path) as file:
            for line in file:
                if not self.comment_regex.search(line):
                    yield line

    def _glob(self, start_path: str) -> None:
        """Create a set of all file paths that match the globbing patterns.

        Args:
            start_path: The directory to search in for files that match the
                patterns.
        """
        self._matches[start_path] = set()
        self._all_matches[start_path] = set()

        for line in self._readlines():
            # This assumes that cases where the user may accidentally leave
            # leading/trailing whitespace are more common than cases where they
            # may actually need it. This also strips trailing newlines.
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                glob_str = os.path.join(start_path, line.lstrip("/"))
            else:
                # Glob patterns without a leading slash search the whole tree.
                glob_str = os.path.join(start_path, "**", line)

            for match_path in glob.glob(glob_str, recursive=True):
                rel_match_path = os.path.relpath(match_path, start_path)
                self._matches[start_path].add(rel_match_path)
                self._all_matches[start_path].add(rel_match_path)
                try:
                    for entry in scan_tree(match_path):
                        self._all_matches[start_path].add(
                            os.path.relpath(entry.path, start_path))
                except NotADirectoryError:
                    pass

    def matches(self, start_path: str) -> Set[str]:
        """Get the paths of files that match globbing patterns.

        Args:
            start_path: The path to search for matches in.

        Returns:
            The relative paths of files in the specified directory that match
            the globbing patterns.
        """
        if start_path not in self._matches:
            self._glob(start_path)

        return self._matches[start_path]

    def all_matches(self, start_path: str) -> Set[str]:
        """Get the paths of files that match globbing patterns with children.

        Args:
            start_path: The path to search for matches in.

        Returns:
            The relative paths of files in the specified directory that match
            the globbing patterns and all of their children.
        """
        if start_path not in self._all_matches:
            self._glob(start_path)

        return self._all_matches[start_path]


class ProfileInfoFile(JSONFile):
    """Parse a JSON-formatted file for profile metadata.

    Args:
        path: The path of the JSON file.

    Attributes:
        vals: A dict of values from the file.
    """
    def __init__(self, path) -> None:
        super().__init__(path)
        self.vals = collections.defaultdict(lambda: None)

    def generate(self, name: str, init_options: Dict[str, Any]) -> None:
        """Generate info for a new profile.

        Args:
            name: The name of the profile to use for the unique ID.
            add_remote: The '--add-remote' command-line option is set.
        """
        unique_id = uuid.uuid4().hex
        version = pkg_resources.get_distribution("zielen").version
        self.vals.update({
            "Status": "partial",
            "LastSync": None,
            "LastAdjust": None,
            "Version": version,
            "ID": unique_id,
            "InitOptions": {}
            })
        self.vals["InitOptions"].update(init_options)
        self.write()


class ProfileDBFile(SyncDBFile):
    """Manipulate a profile database for keeping track of files.

    Attributes:
        path: The path of the profile database file.
        _conn: The sqlite connection object for the database.
        _cur: The sqlite cursor object for the connection.
    """
    def create(self) -> None:
        """Create a new empty database.

        Raises:
            FileExistsError: The database file already exists.
        """
        if os.path.isfile(self.path):
            raise FileExistsError("the database file already exists")

        self._conn = sqlite3.connect(
            self.path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level="DEFERRED")
        self._conn.create_function("gen_salt", 0, lambda: secure_string(8))

        self._cur = self._conn.cursor()
        self._cur.arraysize = 20

        with self._transact():
            self._cur.executescript("""\
                PRAGMA foreign_keys = ON;
                PRAGMA journal_mode = WAL;

                CREATE TABLE nodes (
                    id          INTEGER NOT NULL,
                    path        TEXT    NOT NULL,
                    directory   BOOL    NOT NULL,
                    priority    REAL    NOT NULL,
                    local       BOOL    NOT NULL,
                    PRIMARY KEY (id) ON CONFLICT IGNORE
                );

                CREATE TABLE closure (
                    ancestor    INT     NOT NULL,
                    descendant  INT     NOT NULL,
                    depth       INT     DEFAULT 0,
                    PRIMARY KEY (ancestor, descendant) ON CONFLICT IGNORE,
                    FOREIGN KEY (ancestor)
                        REFERENCES nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (descendant)
                        REFERENCES nodes(id) ON DELETE CASCADE
                ) WITHOUT ROWID;

                CREATE TABLE collisions (
                    path        TEXT    NOT NULL,
                    salt        TEXT    NOT NULL,
                    PRIMARY KEY (path) ON CONFLICT IGNORE
                );
                """)

    def _update_priority(self, paths: Iterable[str]) -> None:
        """Update the priority values of directories.

        Directories are checked in leaf-to-trunk order. The priority value
        of a directory is set to the sum of the priority values of all its
        immediate children. For every directory that's checked, all of its
        ancestors up the tree are also checked.

        Args:
            paths: The relative paths of the directories to update the priority
                values of.
        """
        # A deque is used here because a list cannot be appended to while it is
        # being iterated over.
        path_queue = collections.deque(paths)
        check_paths = set()
        while len(path_queue) > 0:
            path = path_queue.pop()
            check_paths.add(path)
            parent = os.path.dirname(path)
            if parent:
                path_queue.appendleft(parent)

        # Sort paths by depth.
        nodes_values = []
        for path in sorted(
                check_paths, key=lambda x: x.count(os.sep), reverse=True):
            path_id = self._get_path_id(path)
            nodes_values.append({"path_id": path_id})

        self._cur.executemany("""\
            UPDATE nodes
            SET priority = (
                SELECT COALESCE(SUM(n.priority), 0)
                FROM nodes AS n
                JOIN closure AS c
                ON (n.id = c.descendant)
                WHERE c.ancestor = :path_id
                AND c.depth = 1)
            WHERE id = :path_id;
            """, nodes_values)

    def add_paths(self, files: Iterable[str], dirs: Iterable[str],
                  priority=0, local=True) -> None:
        """Add new file paths to the database if not already there.

        A file path is automatically marked as a directory when sub-paths are
        added to the database. The purpose of the separate parameter for
        directory paths is to distinguish empty directories from files.

        Args:
            files: The paths of regular files to add to the database.
            dirs: The paths of directories to add to the database.
            priority: The starting priority of the file paths.
            local: The paths are the paths of files that have been kept in the
                local directory.
        """
        # Sort paths by depth. A file can't be added to the database until its
        # parent directory has been added.
        files = set(files)
        dirs = set(dirs)
        paths = list(files | dirs)
        paths.sort(key=lambda x: x.count(os.sep))

        while True:
            parents = set()
            insert_nodes_vals = []
            insert_closure_vals = []
            rm_vals = []
            for path in paths:
                path_id = self._get_path_id(path)
                parent = os.path.dirname(path)
                if parent:
                    parents.add(parent)
                    parent_id = self._get_path_id(parent)
                else:
                    parent_id = path_id

                rm_vals.append({
                    "path_id": path_id})
                insert_nodes_vals.append({
                    "path": path,
                    "path_id": path_id,
                    "directory": bool(path in dirs),
                    "priority": priority,
                    "local": local})
                insert_closure_vals.append({
                    "path_id": path_id,
                    "parent_id": parent_id})

            # If there are any hash collisions with paths already in the
            # database, generate salt and continue the loop to regenerate
            # the path IDs.
            self._cur.executemany("""\
                INSERT INTO collisions (path, salt)
                SELECT :path, gen_salt()
                FROM nodes
                WHERE id = :path_id
                AND path != :path;
                """, insert_nodes_vals)
            if self._cur.rowcount <= 0:
                break

        # Insert new values into both tables.
        self._cur.executemany("""\
            INSERT INTO nodes (id, path, directory, priority, local)
            VALUES (:path_id, :path, :directory, :priority, :local);
            """, insert_nodes_vals)
        self._cur.executemany("""\
            INSERT INTO closure (ancestor, descendant, depth)
            SELECT ancestor, :path_id, c.depth + 1
            FROM closure AS c
            WHERE descendant = :parent_id
            UNION ALL SELECT :path_id, :path_id, 0;
            """, insert_closure_vals)
        self._mark_directory(parents)
        self._update_priority(parents)

    def add_inflated(self, files: Iterable[str], dirs: Iterable[str]) -> None:
        """Add new file paths to the database with an inflated priority.

        Args:
            files: The paths of regular files to add to the database.
            dirs: The paths of directories to add to the database.
        """
        self._cur.execute("""\
            SELECT MAX(priority) FROM nodes
            WHERE directory = 0;
            """)
        max_priority = self._cur.fetchone()[0]
        self.add_paths(files, dirs, priority=max_priority)

    def update_paths(
            self, paths: Iterable[str], directory=None, priority=None,
            local=None) -> None:
        """Update information associated with file paths in the database.

        Args:
            paths: The paths to update.
            directory: The paths are the paths of directories. Use None to
                leave the value unchanged.
            priority: The starting priority of the file paths. Use None to
                leave the value unchanged.
            local: The paths are the paths of files that have been kept in the
                local directory. Use None to leave the value unchanged.
        """
        update_vals = []
        for path in paths:
            path_id = self._get_path_id(path)

            update_vals.append({
                "path_id": path_id,
                "directory": directory,
                "priority": priority,
                "local": local})

        if directory is not None:
            self._cur.executemany("""\
                UPDATE nodes
                SET directory = :directory
                WHERE id = :path_id;
                """, update_vals)

        if priority is not None:
            self._cur.executemany("""\
                UPDATE nodes
                SET priority = :priority
                WHERE id = :path_id;
                """, update_vals)

        if local is not None:
            self._cur.executemany("""\
                UPDATE nodes
                SET local = :local
                WHERE id = :path_id;
                """, update_vals)

        parents = {
            os.path.dirname(path) for path in paths if os.path.dirname(path)}
        self._update_priority(parents)

    def rm_paths(self, paths: Iterable[str]) -> None:
        """Remove file paths from the database.

        If the path is the path of a directory, then all paths under it are
        removed as well.

        Args:
            paths: The file paths to remove.
        """
        # A generator expression can't be used here because recursive use of
        # cursors is not allowed.
        rm_vals = [{
            "path_id": self._get_path_id(path)}
            for path in paths]
        parents = {
            os.path.dirname(path) for path in paths if os.path.dirname(path)}

        self._cur.executemany("""\
            DELETE FROM nodes
            WHERE id IN (
                SELECT n.id
                FROM nodes AS n
                JOIN closure AS c
                ON (n.id = c.descendant)
                WHERE c.ancestor = :path_id);
            """, rm_vals)
        self._cur.execute("""
            DELETE FROM collisions
            WHERE path NOT IN (
                SELECT path
                FROM nodes);
            """)
        self._update_priority(parents)

    def get_path_info(self, path: str) -> PathData:
        """Get data associated with a file path.

        Args:
            path: The file path to search the database for.

        Returns:
            A named tuple containing a bool representing whether the file is
            a directory, the file priority and a bool representing whether
            the file has been kept in the local directory.
        """
        # Clear the query result set.
        self._cur.fetchall()

        path_id = self._get_path_id(path)
        self._cur.execute("""\
            SELECT directory, priority, local
            FROM nodes
            WHERE id = :path_id;
            """, {"path_id": path_id})

        result = self._cur.fetchone()
        if result:
            return PathData(*result)

    def get_paths(
            self, root=None, directory=None, local=None
            ) -> Dict[str, PathData]:
        """Get the paths of files in the database.

        Args:
            root: A relative directory path. Results are restricted to just
                paths under this directory path.
            directory: Restrict results to just directory paths (True) or just
                file paths (False). None means no restrictions.
            local: Restrict results to just the paths that have been kept in
                the local directory (True) or just paths that have not been
                kept in the local directory (False). None means no
                restrictions.

        Returns:
            A dict containing file paths as keys and named tuples as values.
            These named tuples contain a bool representing whether the file
            is a directory, the file priority and a bool representing whether
            the file has been kept in the local directory.
        """
        start_id = self._get_path_id(root) if root else None
        self._cur.execute("""\
            SELECT n.path, n.directory, n.priority, n.local
            FROM nodes AS n
            JOIN closure AS c
            ON (n.id = c.descendant)
            WHERE (:start_id IS NULL OR c.ancestor = :start_id)
            AND (:directory IS NULL OR n.directory = :directory)
            AND (:local IS NULL OR n.local = :local);
            """, {
                "start_id": start_id, "directory": directory, "local": local})

        # As long as self._cur.arraysize is greater than 1, fetchmany() should
        # be more efficient than fetchall().
        return {
            path: PathData(directory, priority, local)
            for array in iter(self._cur.fetchmany, [])
            for path, directory, priority, local in array}

    def increment(self, paths: Iterable[str],
                  increment: Union[int, float]) -> None:
        """Increment the priority of some paths by some value.

        Args:
            paths: The paths to increment the priority of.
            increment: The value to increment the paths by.
        """
        # A generator expression can't be used here because recursive use of
        # cursors is not allowed.
        increment_vals = [{
            "path_id": self._get_path_id(path),
            "increment": increment}
            for path in paths]
        parents = {
            os.path.dirname(path) for path in paths if os.path.dirname(path)}

        self._cur.executemany("""\
            UPDATE nodes
            SET priority = priority + :increment
            WHERE id = :path_id;
            """, increment_vals)
        self._update_priority(parents)

    def adjust_all(self, adjustment: Union[int, float]) -> None:
        """Multiply the priorities of all file paths by a constant.

        Args:
            adjustment: The constant to multiply file priorities by.
        """
        self._cur.execute("""\
            UPDATE nodes
            SET priority = priority * :adjustment;
            """, {"adjustment": adjustment})


class ProfileConfigFile(ConfigFile):
    """The profile's configuration file.

    The default values for some options are stored in this class. This
    allows the user to comment those values out to return them to their
    default values, and it also allows for new values to be added in the
    future without requiring users to update their config files. These
    values are not commented out by default, however, so that the defaults
    can be changed in the future without affecting existing users.

    Attributes:
        TRUE_VALS: A list of strings that are recognized as boolean true.
        FALSE_VALS: A list of strings that are recognized as boolean false.
        _required_keys: A list of config keys that must be included in the
            config file.
        _optional_keys: A list of config keys that may be commented out or
            omitted.
        _all_keys: A list of all keys that are recognized in the config file.
        _bool_keys: A subset of config keys that must have boolean values.
        _defaults: A dictionary of default string values for optional config
            keys.
        _prompt_messages: The messages to use when prompting the user for config
            values.
        path: The path of the configuration file.
        profile: The Profile object that the config file belongs to.
        add_remote: Switch the requirements of 'LocalDir' and 'RemoteDir'.
        raw_vals: A dictionary of raw config value strings.
        vals: A dict property of parsed config values.
    """
    TRUE_VALS = ["yes", "true"]
    FALSE_VALS = ["no", "false"]
    _required_keys = [
        "LocalDir", "RemoteDir", "StorageLimit"
        ]
    _optional_keys = [
        "SyncInterval", "PriorityHalfLife", "UseTrash", "TrashCleanupPeriod",
        "InflatePriority", "AccountForSize"
        ]
    _all_keys = _required_keys + _optional_keys
    _bool_keys = [
        "UseTrash", "InflatePriority", "AccountForSize"
        ]
    _defaults = {
        "SyncInterval": "20",
        "PriorityHalfLife": "120",
        "UseTrash": "yes",
        "TrashCleanupPeriod": "30",
        "InflatePriority": "yes",
        "AccountForSize": "yes"
        }
    _prompt_messages = {
        "LocalDir":     "Enter the path of the local sync directory.",
        "RemoteDir":    "Enter the path of the remote sync directory.",
        "StorageLimit": "Enter the amount of data to keep in the local "
                        "directory. This accepts KB, MB, GB, KiB, MiB and "
                        "GiB as units. "
        }

    _autocomplete_funcs = {
        "LocalDir": set_path_autocomplete,
        "RemoteDir": set_path_autocomplete,
        "StorageLimit": set_no_autocomplete
        }

    def check_value(self, key: str, value: str) -> Optional[str]:
        """Check the syntax of a config option and return an error message.

        Args:
            key: The name of the config option to check.
            value: The value of the config option to check.

        Returns:
            A string corresponding to the syntax error (if any).
        """
        # Check if required values are blank.
        if key in self._required_keys and not value:
            return "must not be blank"

        # Check boolean values.
        if key in self._bool_keys and value:
            if value.lower() not in (self.TRUE_VALS + self.FALSE_VALS):
                return "must have a boolean value"

        if key == "LocalDir":
            if not re.search("^~?/", value):
                return "must be an absolute path"
        elif key == "RemoteDir":
            if not re.search("^~?/", value):
                return "must be an absolute path"
        elif key == "StorageLimit":
            if not re.search(r"^[0-9]+\s*[kKMG](B|iB)?$", value):
                return "must be an integer followed by a unit (e.g. 10GB)"
        elif key == "SyncInterval":
            if not re.search("^[0-9]+$", value):
                return "must be an integer"
        elif key == "PriorityHalfLife":
            if not re.search("^[0-9]+$", value):
                return "must be an integer"
        elif key == "TrashCleanupPeriod":
            if not re.search(r"^-?[0-9]+$", value):
                return "must be an integer"

    def check_all(self, check_empty=True, context="config file") -> None:
        """Check that file is valid and syntactically correct.

        Args:
            check_empty: Check empty/unset values.
            context: The context to show in the error messages.

        Raises:
            FileParseError: There were missing, unrecognized or invalid options
                in the config file.
        """
        parse_errors = []

        # Check that all key names are valid.
        missing_keys = set(self._required_keys) - self.raw_vals.keys()
        unrecognized_keys = self.raw_vals.keys() - set(self._all_keys)
        for key in missing_keys:
            parse_errors.append(
                "{0}: missing required option '{1}'".format(context, key))
        for key in unrecognized_keys:
            parse_errors.append(
                "{0}: unrecognized option '{1}'".format(context, key))

        # Check values for valid syntax.
        for key, value in self.raw_vals.items():
            if check_empty or not check_empty and value:
                err_msg = self.check_value(key, value)
                if err_msg:
                    parse_errors.append(
                        "{0}: '{1}' {2}".format(context, key, err_msg))

        if parse_errors:
            raise FileParseError(*parse_errors)

    @DictProperty
    def vals(self, key: str) -> Any:
        """Get defaults if corresponding raw values are unset."""
        if key in self.raw_vals:
            return self.raw_vals[key]
        elif key in self._defaults:
            return self._defaults[key]

    @vals.setter
    def vals(self, key: str, value: str) -> None:
        """Set individual config values."""
        self.raw_vals[key] = value

    def prompt(self) -> None:
        """Prompt the user interactively for unset required values."""
        prompt_keys = [
            key for key in self._required_keys
            if key not in self.raw_vals.keys() or not self.raw_vals[key]]
        if not prompt_keys:
            return

        for key in prompt_keys:
            self._autocomplete_funcs[key]()
            while True:
                print("\n".join(
                    textwrap.wrap(self._prompt_messages[key], width=79)))
                user_input = input("> ").strip()
                print()
                error_message = self.check_value(key, user_input)
                if error_message:
                    print(
                        "Error: this value " + error_message, file=sys.stderr)
                else:
                    break
                print()
            self.vals[key] = user_input
