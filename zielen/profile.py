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
import weakref
import getpass
import sqlite3
import datetime
import textwrap
import readline  # This is not unused. Importing it adds features to input().
import collections
from typing import (
    Any, Iterable, Generator, Dict, NamedTuple, Optional, Union, Set, List)

import pkg_resources

from zielen import XDG_DATA_HOME, PROGRAM_DIR, PROFILES_DIR
from zielen.container import JSONFile, ConfigFile, SyncDBFile
from zielen.io import rec_scan
from zielen.utils import DictProperty, secure_string
from zielen.exceptions import FileParseError

PathData = NamedTuple(
    "PathData", [("directory", bool), ("priority", float)])


class Profile:
    """Get information about a profile and its contents.

    Attributes:
        name: The name of the profile.
        path: The path of the profile directory.
        mnt_dir: The path of the remote mountpoint.
        cfg_path: The path of the configuration file.
        ex_path: The path of the exclude file.
        _ex_file: An object for the exclude pattern file.
        _info_file: An object for the JSON file for profile metadata.
        _db_file: An object for the file priority database.
        _cfg_file: An object for the profile's configuration file.
    """
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = os.path.join(PROFILES_DIR, self.name)
        self.mnt_dir = os.path.join(self.path, "mnt")
        self._ex_file = ProfileExcludeFile(
            os.path.join(self.path, "exclude"))
        self._info_file = ProfileInfoFile(os.path.join(self.path, "info.json"))
        self._db_file = ProfileDBFile(
            os.path.join(self.path, "local.db"))
        self._cfg_file = ProfileConfigFile(
            os.path.join(self.path, "config"), profile_obj=self)

        # Import methods from content classes.
        self.cfg_path = self._cfg_file.path
        self.ex_path = self._ex_file.path
        self.ex_matches = self._ex_file.matches
        self.ex_all_matches = self._ex_file.all_matches
        self.add_paths = self._db_file.add_paths
        self.add_inflated = self._db_file.add_inflated
        self.rm_paths = self._db_file.rm_paths
        self.get_path_info = self._db_file.get_path_info
        self.get_tree = self._db_file.get_tree
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

    def generate(
            self, add_remote: bool, exclude_path=None,
            template_path=None) -> None:
        """Generate files for storing persistent data."""
        os.makedirs(self.path, exist_ok=True)

        self._ex_file.generate(exclude_path)
        self._info_file.generate(self.name, add_remote)

        try:
            self._db_file.create()
        except FileExistsError:
            pass

        if template_path:
            template_file = ProfileConfigFile(
                template_path, add_remote=add_remote)
            template_file.read()
            template_file.check_all(check_empty=False, context="template file")
            self._cfg_file.raw_vals = template_file.raw_vals

        self._cfg_file.add_remote = add_remote
        self._cfg_file.prompt()
        if template_path:
            # This final check is necessary for cases where a template was
            # used that contained values dependent on other unspecified
            # values for validity checking (e.g. 'RemoteDir' and 'RemoteHost').
            self._cfg_file.check_all(context="template file")
            self._cfg_file.write(template_path)
        else:
            # TODO: Get the path of the master config template from
            # setup.py instead of hardcoding it.
            self._cfg_file.write(os.path.join(
                sys.prefix, "share/zielen/config-template"))

    def write(self) -> None:
        """Write data to persistent storage."""
        self._info_file.write()
        self._db_file.conn.commit()


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
        return datetime.datetime.strptime(
            timestamp, "%Y-%m-%dT%H:%M:%S.%f").replace(
            tzinfo=datetime.timezone.utc).timestamp()

    @staticmethod
    def _convert_timestamp(epoch: float) -> str:
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
        # Use strftime() instead of isoformat() because the latter
        # doesn't print the decimal point if the microsecond is 0,
        # which would prevent it from being parsed by strptime().
        self._info_file.vals["LastSync"] = self._convert_timestamp(value)

    @property
    def last_adjust(self) -> float:
        """The time of the last priority adjustment in epoch time."""
        return self._convert_epoch(self._info_file.vals["LastSync"])

    @last_adjust.setter
    def last_adjust(self, value: float) -> None:
        # Use strftime() instead of isoformat() because the latter
        # doesn't print the decimal point if the microsecond is 0,
        # which would prevent it from being parsed by strptime().
        self._info_file.vals["LastSync"] = self._convert_timestamp(value)

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
        return self._info_file.vals["InitOpts"]["add_remote"]

    @add_remote.setter
    def add_remote(self, value: bool) -> None:
        self._info_file.vals["InitOpts"]["add_remote"] = value

    @property
    def local_path(self) -> str:
        """The absolute path of the local directory."""
        return os.path.expanduser(
            os.path.normpath(self._cfg_file.vals["LocalDir"]))

    @property
    def remote_host(self) -> Optional[str]:
        """The hostname, ip address or domain name of the remote machine.

        'None' refers to the local machine.
        """
        value = self._cfg_file.vals["RemoteHost"]
        if value in self._cfg_file.HOST_SYNONYMS:
            return None
        else:
            return value

    @property
    def remote_user(self) -> str:
        """The name of the user on the remote machine."""
        return self._cfg_file.vals["RemoteUser"]

    @property
    def port(self) -> str:
        """The port number for the connection."""
        return self._cfg_file.vals["Port"]

    @property
    def remote_path(self) -> str:
        """The absolute path of the remote directory."""
        return os.path.expanduser(
            os.path.normpath(self._cfg_file.vals["RemoteDir"]))

    @property
    def storage_limit(self) -> int:
        """The number of bytes of data to keep in the local directory."""
        num, unit = re.findall(
            r"^([0-9]+)\s*([KMG](?:B|iB)?)$",
            self._cfg_file.vals["StorageLimit"])[0]
        if unit in ["K", "KiB"]:
            return int(num) * 1024
        elif unit in ["M", "MiB"]:
            return int(num) * 1024**2
        elif unit in ["G", "GiB"]:
            return int(num) * 1024**3
        elif unit == "KB":
            return int(num) * 1000
        elif unit == "MB":
            return int(num) * 1000**2
        elif unit == "GB":
            return int(num) * 1000**3

    @property
    def sync_interval(self) -> int:
        """The number of seconds the daemon will wait between syncs."""
        return int(self._cfg_file.vals["SyncInterval"]) * 60

    @property
    def sshfs_options(self) -> str:
        """The mount options to pass to sshfs."""
        return self._cfg_file.vals["SshfsOptions"]

    @property
    def trash_dirs(self) -> List[str]:
        dirs = self._cfg_file.vals["TrashDirs"].split(":")
        for index, element in enumerate(dirs.copy()):
            dirs[index] = os.path.expanduser(
                os.path.normpath(element))
        return dirs

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
    def disable_trash(self) -> bool:
        """Permanently delete remote files that were deleted locally."""
        return self._convert_bool(self._cfg_file.vals["DisableTrash"])

    @property
    def sync_extra_files(self) -> bool:
        """Fill the remaining space with individual files."""
        return self._convert_bool(self._cfg_file.vals["SyncExtraFiles"])

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
                #
                # Lines with a leading slash are patterns that match relative to the root of
                # the sync directory. Lines without a leading slash are patterns that match the
                # ends of file paths anywhere in the tree.
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
        self._matches.update({start_path: set()})
        self._all_matches.update({start_path: set()})

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
                    for entry in rec_scan(match_path):
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

    def generate(self, name: str, add_remote=False) -> None:
        """Generate info for a new profile.

        Args:
            name: The name of the profile to use for the unique ID.
            add_remote: The '--add-remote' command-line option is set.
        """
        unique_id = uuid.uuid4().hex
        version = float(pkg_resources.get_distribution("zielen").version)
        self.vals.update({
            "Status": "partial",
            "LastSync": None,
            "LastAdjust": None,
            "Version": version,
            "ID": unique_id,
            "InitOpts": {
                "add_remote": add_remote
                }
            })
        self.write()


class ProfileDBFile(SyncDBFile):
    """Manipulate a profile database for keeping track of files.

    Attributes:
        path: The path of the profile database file.
        conn: The sqlite connection object for the database.
        cur: The sqlite cursor object for the connection.
    """
    def create(self) -> None:
        """Create a new empty database.

        Raises:
            FileExistsError: The database file already exists.
        """
        if os.path.isfile(self.path):
            raise FileExistsError("the database file already exists")

        self.conn = sqlite3.connect(
            self.path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level="DEFERRED")
        self.conn.create_function("gen_salt", 0, lambda: secure_string(8))

        self.cur = self.conn.cursor()
        self.cur.arraysize = 20

        with self._transact():
            self.cur.executescript("""\
                PRAGMA foreign_keys = ON;
                PRAGMA journal_mode = WAL;

                CREATE TABLE nodes (
                    id          INTEGER NOT NULL,
                    path        TEXT    NOT NULL,
                    directory   BOOL    NOT NULL,
                    priority    REAL    NOT NULL,
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

        self.cur.executemany("""\
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
                  priority=0, replace=False) -> None:
        """Add new file paths to the database if not already there.

        A file path is automatically marked as a directory when sub-paths are
        added to the database. The purpose of the separate parameter for
        directory paths is to distinguish empty directories from files.

        Args:
            files: The paths of regular files to add to the database.
            dirs: The paths of directories to add to the database.
            priority: The starting priority of the file paths.
            replace: Replace existing rows instead of ignoring them.
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
                    "priority": priority})
                insert_closure_vals.append({
                    "path_id": path_id,
                    "parent_id": parent_id})

            # If there are any hash collisions with paths already in the
            # database, generate salt and continue the loop to regenerate
            # the path IDs.
            self.cur.executemany("""\
                INSERT INTO collisions (path, salt)
                SELECT :path, gen_salt()
                FROM nodes
                WHERE id = :path_id
                AND path != :path;
                """, insert_nodes_vals)
            if self.cur.rowcount <= 0:
                break

        if replace:
            # Remove paths from the database if they already exist.
            self.cur.executemany("""\
                DELETE FROM nodes
                WHERE id = :path_id
                """, rm_vals)

        # Insert new values into both tables.
        self.cur.executemany("""\
            INSERT INTO nodes (id, path, directory, priority)
            VALUES (:path_id, :path, :directory, :priority);
            """, insert_nodes_vals)
        self.cur.executemany("""\
            INSERT INTO closure (ancestor, descendant, depth)
            SELECT ancestor, :path_id, c.depth + 1
            FROM closure AS c
            WHERE descendant = :parent_id
            UNION ALL SELECT :path_id, :path_id, 0;
            """, insert_closure_vals)
        self._mark_directory(parents)
        self._update_priority(parents)

    def add_inflated(self, files: Iterable[str], dirs: Iterable[str],
                     replace=False) -> None:
        """Add new file paths to the database with an inflated priority.

        Args:
            files: The paths of regular files to add to the database.
            dirs: The paths of directories to add to the database.
            replace: Replace existing rows instead of ignoring them.
        """
        self.cur.execute("""\
            SELECT MAX(priority) FROM nodes
            WHERE directory = 0;
            """)
        max_priority = self.cur.fetchone()[0]
        self.add_paths(files, dirs, priority=max_priority, replace=replace)

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

        self.cur.executemany("""\
            DELETE FROM nodes
            WHERE id IN (
                SELECT n.id
                FROM nodes AS n
                JOIN closure AS c
                ON (n.id = c.descendant)
                WHERE c.ancestor = :path_id);
            """, rm_vals)
        self.cur.execute("""
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
            A named tuple containing a bool representing whether the file is a
            directory and the file priority.
        """
        # Clear the query result set.
        self.cur.fetchall()

        path_id = self._get_path_id(path)
        self.cur.execute("""\
            SELECT directory, priority
            FROM nodes
            WHERE id = :path_id;
            """, {"path_id": path_id})

        result = self.cur.fetchone()
        if result:
            return PathData(*result)

    def get_tree(self, start=None, directory=None) -> Dict[str, PathData]:
        """Get the paths of files in the database.

        Args:
            start: A relative directory path. Results are restricted to just
                paths under this directory path.
            directory: Restrict results to just directory paths (True) or just
                file paths (False).

        Returns:
            A dict containing file paths as keys and named tuples as values.
            These named tuples contain a bool representing whether the file
            is a directory and the file priority.
        """
        start_id = self._get_path_id(start) if start else None
        self.cur.execute("""\
            SELECT n.path, n.directory, n.priority
            FROM nodes AS n
            JOIN closure AS c
            ON (n.id = c.descendant)
            WHERE (:start_id IS NULL OR c.ancestor = :start_id)
            AND (:directory IS NULL OR n.directory = :directory);
            """, {"start_id": start_id, "directory": directory})

        # As long as self.cur.arraysize is greater than 1, fetchmany() should
        # be more efficient than fetchall().
        return {
            path: PathData(directory, priority)
            for array in iter(self.cur.fetchmany, [])
            for path, directory, priority in array}

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

        self.cur.executemany("""\
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
        self.cur.execute("""\
            UPDATE nodes
            SET priority = priority * :adjustment;
            """, {"adjustment": adjustment})


class ProfileConfigFile(ConfigFile):
    """The profile's configuration file.

    The default values for some options are stored in the code. This allows
    the user to comment those values out to return them to their default
    values, and it also allows for new values to be added in the future
    without requiring users to update their config files. These values are
    not commented out by default, however, so that the defaults can be
    changed in the future without affecting existing users.

    Attributes:
        _instances: A weakly-referenced set of instances of this class.
        TRUE_VALS: A list of strings that are recognized as boolean true.
        FALSE_VALS: A list of strings that are recognized as boolean false.
        HOST_SYNONYMS: A list of strings that are synonyms for 'localhost'.
        _req_keys: A list of config keys that must be included in the config
            file.
        _opt_keys: A list of config keys that may be commented out or omitted.
        _all_keys: A list of all keys that are recognized in the config file.
        _prompt_keys: A subset of config keys that the user needs to be
            prompted for values for.
        _bool_keys: A subset of config keys that must have boolean values.
        _connect_keys: A subset of config keys that only need values when
            the remote directory is on another machine.
        _defaults: A dictionary of default string values for optional config
            keys.
        _subs: A dictionary of string values to substitute in if the user
            leaves a prompt blank.
        _prompt_msgs: The messages to use when prompting the user for config
            values.
        path: The path of the configuration file.
        profile: The Profile object that the config file belongs to.
        add_remote: Switch the requirements of 'LocalDir' and 'RemoteDir'.
        raw_vals: A dictionary of raw config value strings.
        vals: A dict property of parsed config values.
    """
    _instances = weakref.WeakSet()
    TRUE_VALS = ["yes", "true"]
    FALSE_VALS = ["no", "false"]
    HOST_SYNONYMS = ["localhost", "127.0.0.1"]
    _req_keys = [
        "LocalDir", "RemoteHost", "RemoteUser", "Port", "RemoteDir",
        "StorageLimit"
        ]
    _opt_keys = [
        "SyncInterval", "SshfsOptions", "TrashDirs", "PriorityHalfLife",
        "DisableTrash", "SyncExtraFiles", "InflatePriority", "AccountForSize"
        ]
    _all_keys = _req_keys + _opt_keys
    _prompt_keys = [
        "LocalDir", "RemoteHost", "RemoteUser", "Port", "RemoteDir",
        "StorageLimit"
        ]
    _bool_keys = [
        "DisableTrash", "SyncExtraFiles", "InflatePriority", "AccountForSize"
        ]
    _connect_keys = ["RemoteUser", "Port"]
    _defaults = {
        "SyncInterval": "20",
        "SshfsOptions": (
            "reconnect,ServerAliveInterval=5,ServerAliveCountMax=3"),
        "TrashDirs": os.path.join(XDG_DATA_HOME, "Trash/files"),
        "PriorityHalfLife": "120",
        "DisableTrash": "no",
        "SyncExtraFiles": "yes",
        "InflatePriority": "yes",
        "AccountForSize": "yes"
        }
    _subs = {
        "RemoteHost":   HOST_SYNONYMS[0],
        "RemoteUser":   getpass.getuser(),
        "Port":         "22"
        }
    _prompt_msgs = {
        "LocalDir":     "Local directory path",
        "RemoteHost":   "Hostname, IP address or domain name of the remote",
        "RemoteUser":   "Your user name on the server",
        "Port":         "Port number for the connection",
        "RemoteDir":    "Remote directory path",
        "StorageLimit": "Amount of data to keep synced locally"
        }

    def __init__(self, path: str, profile_obj=None, add_remote=None) -> None:
        super().__init__(path)
        self.profile = profile_obj
        self.add_remote = add_remote
        self._instances.add(self)

    def _check_value(self, key: str, value: str) -> Optional[str]:
        """Check the syntax of a config option and return an error message.

        Args:
            key: The name of the config option to check.
            value: The value of the config option to check.

        Returns:
            A string corresponding to the syntax error (if any).
        """
        # Check if required values are blank.
        if key in self._req_keys and not value:
            return "must not be blank"

        # Check boolean values.
        if key in self._bool_keys and value:
            if value.lower() not in (self.TRUE_VALS + self.FALSE_VALS):
                return "must have a boolean value"

        if key == "LocalDir":
            if not re.search("^~?/", value):
                return "must be an absolute path"

            value = os.path.expanduser(os.path.normpath(value))
            if (os.path.commonpath([value, PROGRAM_DIR])
                    in [value, PROGRAM_DIR]):
                return "must not contain zielen config files"

            overlap_profiles = []
            for instance in self._instances:
                # Check if value overlaps with the 'LocalDir' of another
                # profile.
                if (not instance.profile
                        or not os.path.isfile(instance.path)
                        or not self.profile
                        or instance.profile.name == self.profile.name):
                    # Do not include instances that do not belong to a
                    # profile, instances that do not have a config file in
                    # the filesystem or the current instance.
                    continue
                name = instance.profile.name
                if not instance.raw_vals:
                    instance.read()
                other_value = os.path.expanduser(
                    os.path.normpath(instance.vals["LocalDir"]))
                common = os.path.commonpath([other_value, value])
                if common in [other_value, value]:
                    overlap_profiles.append(name)

            if overlap_profiles:
                # Print a comma-separated list of conflicting profile names
                # after the error message.
                suffix = "s" if len(overlap_profiles) > 1 else ""
                return ("overlaps with the profile{0} {1}".format(
                    suffix,
                    ", ".join("'{}'".format(x) for x in overlap_profiles)))
            elif os.path.exists(value):
                if os.path.isdir(value):
                    if not os.access(value, os.W_OK):
                        return "must be a directory with write access"
                    elif self.add_remote and os.stat(value).st_size > 0:
                        return "must be an empty directory"
                else:
                    return "must be a directory"
            else:
                if self.add_remote:
                    check_path = value
                    while os.path.dirname(check_path) != check_path:
                        if os.access(check_path, os.W_OK):
                            break
                        check_path = os.path.dirname(check_path)
                    else:
                        return "must be a directory with write access"
                else:
                    return "must be an existing directory"
        elif key == "RemoteHost":
            if not value:
                return "must not be blank"
            if re.search("\s+", value):
                return "must not contain spaces"
        elif key == "RemoteUser":
            if not value:
                return "must not be blank"
            if re.search("\s+", value):
                return "must not contain spaces"
        elif key == "Port":
            if not value:
                return "must not be blank"
            if (not re.search("^[0-9]+$", value)
                    or not 65535 > int(value) > 1):
                return "must be an integer in the range 1-65535"
        elif key == "RemoteDir":
            # In order to keep the interactive interface responsive, we don't
            # do any checking of the remote directory that requires connecting
            # over ssh.
            if not re.search("^~?/", value):
                return "must be an absolute path"
            value = os.path.expanduser(os.path.normpath(value))
            if self.raw_vals["RemoteHost"] in self.HOST_SYNONYMS:
                if os.path.exists(value):
                    if os.path.isdir(value):
                        if not os.access(value, os.W_OK):
                            return "must be a directory with write access"
                        elif (self.add_remote is False
                                and os.stat(value).st_size > 0):
                            return "must be an empty directory"
                    else:
                        return "must be a directory"
                else:
                    if self.add_remote:
                        return "must be an existing directory"
                    else:
                        try:
                            os.makedirs(value)
                        except PermissionError:
                            return "must be in a directory with write access"

        elif key == "StorageLimit":
            if not re.search(r"^[0-9]+\s*[KMG](B|iB)?$", value):
                return "must be an integer followed by a unit (e.g. 10GB)"
        elif key == "SyncInterval":
            if not re.search("^[0-9]+$", value):
                return "must be an integer"
        elif key == "SshfsOptions":
            if value:
                if re.search("\s+", value):
                    return "must not contain spaces"
        elif key == "TrashDirs":
            if value:
                if re.search("(^|:)(?!~?/)", value):
                    return "only accepts absolute paths"
        elif key == "PriorityHalfLife":
            if not re.search("^[0-9]+$", value):
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
        missing_keys = set(self._req_keys) - self.raw_vals.keys()
        unrecognized_keys = self.raw_vals.keys() - set(self._all_keys)
        for key in missing_keys:
            parse_errors.append(
                "{0}: missing required option '{1}'".format(context, key))
        for key in unrecognized_keys:
            parse_errors.append(
                "{0}: unrecognized option '{1}'".format(context, key))

        # Check values for valid syntax.
        for key, value in self.raw_vals.items():
            # If the remote directory is on the local machine, then certain
            # options should not be checked.
            if (self.raw_vals["RemoteHost"] in self.HOST_SYNONYMS
                    and key in self._connect_keys):
                continue

            if check_empty or not check_empty and value:
                err_msg = self._check_value(key, value)
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
        msg_printed = False
        for key in self._prompt_keys:
            # If the remote directory is on the local machine, then the user
            # should not be prompted for certain settings.
            if (self.raw_vals.get("RemoteHost") in self.HOST_SYNONYMS
                    and key in self._connect_keys):
                self.vals[key] = ""
                continue

            if key in self._subs:
                # Add the default value to the end of the prompt message.
                self._prompt_msgs[key] += " ({}): ".format(self._subs[key])
            else:
                self._prompt_msgs[key] += ": "

            # We don't use a defaultdict for this so that we can know if a
            # config file has been read based on whether raw_vals is empty.
            if not self.raw_vals.get(key):
                if not msg_printed:
                    print(textwrap.dedent("""\
                    Please enter values for the following settings. Leave blank to accept the
                    default value if one is given in parentheses.
                    """))
                    msg_printed = True
                while True:
                    usr_input = input(self._prompt_msgs[key]).strip()
                    if not usr_input and key in self._subs:
                        usr_input = self._subs[key]
                    err_msg = self._check_value(key, usr_input)
                    if err_msg:
                        print("Error: this value " + err_msg, file=sys.stderr)
                    else:
                        break
                self.vals[key] = usr_input
        print()
