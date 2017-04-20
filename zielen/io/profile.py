"""Manipulate files in the profile directory.

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
import re
import glob
import datetime
import pkg_resources
import sqlite3
import weakref
import collections
import uuid
from textwrap import dedent
from typing import Any, Iterable, Generator, Dict, NamedTuple, Optional

from zielen import XDG_DATA_HOME, PROGRAM_DIR, PROFILES_DIR
from zielen.exceptions import FileParseError
from zielen.io.base import JSONFile, ConfigFile, SyncDBFile
from zielen.util.misc import err, DictProperty, rec_scan

PathData = NamedTuple(
    "PathData", [("directory", bool), ("priority", float)])


class Profile:
    """Get information about a profile and its contents.

    Attributes:
        name: The name of the profile.
        path: The path of the profile directory.
        mnt_dir: The path of the remote mountpoint.
        ex_file: An object for the exclude pattern file.
        info_file: An object for the JSON file for profile metadata.
        db_file: An object for the file priority database.
        cfg_file: An object for the profile's configuration file.
    """
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = os.path.join(PROFILES_DIR, self.name)
        os.makedirs(self.path, exist_ok=True)
        self.mnt_dir = os.path.join(self.path, "mnt")
        self.ex_file = ProfileExcludeFile(
            os.path.join(self.path, "exclude"))
        self.info_file = ProfileInfoFile(os.path.join(self.path, "info.json"))
        self.db_file = ProfileDBFile(
            os.path.join(self.path, "local.db"))
        self.cfg_file = ProfileConfigFile(
            os.path.join(self.path, "config"), profile_obj=self)


class ProfileExcludeFile:
    """Manipulate a file containing exclude patterns for the profile.

    A copy of the exclude pattern file for each client is kept in the remote
    directory so that each client can determine if every other client has
    excluded a given file.

    Attributes:
        comment_regex: Regex that denotes a comment line.
        path: The path of the exclude pattern file.
        matches: A set of relative paths of files that match the globbing
            patterns.
        all_matches: A set of relative paths of files that match the globbing
            patterns and all files under them.
    """
    comment_regex = re.compile(r"^\s*#")

    def __init__(self, path: str) -> None:
        self.path = path
        self.matches = set()
        self.all_matches = set()

    def generate(self, infile=None) -> None:
        """Generate a new file with comments.

        Args:
            infile: If supplied, copy lines from this file into the new one.
        """
        with open(self.path, "w") as outfile:
            outfile.write(dedent("""\
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

    def glob(self, start_path: str) -> None:
        """Create a set of all file paths that match the globbing patterns.

        Args:
            start_path: The directory to search in for files that match the
                patterns.
        """
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
                self.matches.add(rel_match_path)
                self.all_matches.add(rel_match_path)
                try:
                    for entry in rec_scan(match_path):
                        self.all_matches.add(
                            os.path.relpath(entry.path, start_path))
                except NotADirectoryError:
                    pass


class ProfileInfoFile(JSONFile):
    """Parse a JSON-formatted file for profile metadata.

    Attributes:
        raw_vals: A dictionary of raw string values from the file.
        vals: A dict property of parsed values from the file.
    """
    def __init__(self, path) -> None:
        super().__init__(path)
        self.raw_vals = {}

    @DictProperty
    def vals(self, key) -> Any:
        """Parse individual values from the info file.

        Returns:
            LastSync: Input value converted to the number of seconds since the
                epoch.
            LastAdjustment: Input value converted to the number of seconds
                since the epoch.
        """
        if key in self.raw_vals:
            value = self.raw_vals[key]
        else:
            value = None

        if value is not None:
            if key == "LastSync":
                value = datetime.datetime.strptime(
                    value, "%Y-%m-%dT%H:%M:%S").replace(
                        tzinfo=datetime.timezone.utc).timestamp()
            if key == "LastAdjust":
                value = datetime.datetime.strptime(
                    value, "%Y-%m-%dT%H:%M:%S").replace(
                        tzinfo=datetime.timezone.utc).timestamp()
        return value

    @vals.setter
    def vals(self, key, value) -> None:
        """Set individual values."""
        self.raw_vals[key] = value

    def generate(self, name: str, add_remote=False) -> None:
        """Generate info for a new profile.

        JSON Values:
            Status: A short string describing the status of the profile.
                "initialized": Fully initialized.
                "partial": Partially initialized.
            LastSync: The date and time (UTC) of the last sync on the profile.
            LastAdjust: The date and time (UTC) of the last priority adjustment
                on the profile.
            Version: The version of the program that the profile was
                initialized by.
            ID: A UUID to identify the profile among all profiles that share a
                remote directory.
            InitOpts: A dictionary of options given at the command line at
                initialization.

        Args:
            name: The name of the profile to use for the unique ID.
            add_remote: The '--add-remote' command-line option is set.
        """
        unique_id = uuid.uuid4().hex
        version = float(pkg_resources.get_distribution("zielen").version)
        self.raw_vals.update({
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

    def update_synctime(self) -> None:
        """Update the time of the last sync."""
        # Store the timestamp as a human-readable string so that the file can
        # be edited manually.
        self.vals["LastSync"] = datetime.datetime.utcnow().strftime(
            "%Y-%m-%dT%H:%M:%S")

    def update_adjusttime(self) -> None:
        """Update the time of the last sync."""
        # Store the timestamp as a human-readable string so that the file can
        # be edited manually.
        self.vals["LastAdjust"] = datetime.datetime.utcnow().strftime(
            "%Y-%m-%dT%H:%M:%S")


class ProfileDBFile(SyncDBFile):
    """Manipulate a profile database for keeping track of files.

    This database uses a transitive closure table to represent the file
    hierarchy. Because it uses a 64-bit hash of the file path as a primary
    key, it can't handle more than a few tens of millions of files without
    running into collision issues.

    Attributes:
        path: The path of the profile database file.
        conn: The sqlite connection object for the database.
        cur: The sqlite cursor object for the connection.
    """
    def create(self) -> None:
        """Create a new empty database.

        Database Columns:
            id: A 64-bit hash of the path as an integer. This is used as the
                primary key over the path for performance reasons.
            path: The relative path of the file.
            directory: A boolean representing whether the path is a directory.
            priority: The priority value of the file.

        Raises:
            FileExistsError: The database file already exists.
        """
        if os.path.isfile(self.path):
            raise FileExistsError("the database file already exists")

        self.conn = sqlite3.connect(
            self.path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level="IMMEDIATE")
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

        if replace:
            self.cur.executemany("""\
                DELETE FROM nodes
                WHERE id = :path_id
                """, rm_vals)
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

    def add_inflated(self, files: Iterable[str], dirs: Iterable[str]) -> None:
        """Add new file paths to the database with an inflated priority.

        Args:
            files: The paths of regular files to add to the database.
            dirs: The paths of directories to add to the database.
        """
        self.cur.execute("""\
            SELECT MAX(priority) FROM nodes
            WHERE directory = 0;
            """)
        max_priority = self.cur.fetchone()[0]
        self.add_paths(files, dirs, priority=max_priority)

    def rm_paths(self, paths: Iterable[str]) -> None:
        """Remove file paths from the database.

        If the path is the path of a directory, then all paths under it are
        removed as well.

        Args:
            paths: The file paths to remove.
        """
        rm_vals = ({
            "path_id": self._get_path_id(path)}
            for path in paths)
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
        self._update_priority(parents)

    def get_path(self, path: str) -> PathData:
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
            SELECT path, directory, priority
            FROM nodes
            WHERE id = :path_id;
            """, {"path_id": path_id})

        result = self.cur.fetchone()
        if result:
            return PathData(*result[1:])

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
            for array in iter(lambda: self.cur.fetchmany(), [])
            for path, directory, priority in array}

    def increment(self, paths: Iterable[str], increment) -> None:
        """Increment the priority of some paths by some value.

        Args:
            paths: The paths to increment the priority of.
            increment: The value to increment the paths by.
        """
        increment_vals = ({
            "path_id": self._get_path_id(path),
            "increment": increment}
            for path in paths)
        parents = {
            os.path.dirname(path) for path in paths if os.path.dirname(path)}

        self.cur.executemany("""\
            UPDATE nodes
            SET priority = priority + :increment
            WHERE id = :path_id;
            """, increment_vals)
        self._update_priority(parents)

    def adjust_all(self, adjustment) -> None:
        """Multiply the priorities of all file paths by a constant.

        Args:
            adjustment: The constant to multiply file priorities by.
        """
        self.cur.execute("""\
            UPDATE nodes
            SET priority = priority * :adjustment;
            """, {"adjustment": adjustment})


class ProfileConfigFile(ConfigFile):
    """Manipulate a profile configuration file.

    Attributes:
        _instances: A weakly-referenced set of instances of this class.
        _true_vals: A list of strings that are recognized as boolean true.
        _false_vals: A list of strings that are recognized as boolean false.
        _host_synonyms: A list of strings that are synonyms for 'localhost'.
        _req_keys: A list of config keys that must be included in the config
            file.
        _opt_keys: A list of config keys that may be commented out or omitted.
        _all_keys: A list of all keys that are recognized in the config file.
        _bool_keys: A list of config keys that must have boolean values.
        _connect_keys: A list of config keys that only matter when connecting
            over ssh.
        _defaults: A dictionary of default string values for optional config
            keys.
        _subs: A dictionary of default string values for required config
            keys.
        _prompt_msgs: The messages to use when prompting the user for required
            config values.
        path: The path of the configuration file.
        profile: The Profile object that the config file belongs to.
        add_remote: Switch the requirements of 'LocalDir' and 'RemoteDir'.
        raw_vals: A dictionary of raw config value strings.
        vals: A dict property of parsed config values.
    """
    _instances = weakref.WeakSet()
    _true_vals = ["yes", "true"]
    _false_vals = ["no", "false"]
    _host_synonyms = ["localhost", "127.0.0.1"]
    _req_keys = [
        "LocalDir", "RemoteHost", "RemoteUser", "Port", "RemoteDir",
        "StorageLimit"
        ]
    _opt_keys = [
        "SyncInterval", "SshfsOptions", "TrashDirs", "PriorityHalfLife",
        "DeleteAlways", "SyncExtraFiles", "InflatePriority", "AccountForSize "
        ]
    _all_keys = _req_keys + _opt_keys
    _bool_keys = [
        "DeleteAlways", "SyncExtraFiles", "InflatePriority", "AccountForSize"
        ]
    _connect_keys = ["RemoteUser", "Port"]
    # The reason for the distinction between self._defaults and self._subs is
    # that some optional config values have a valid reason for being blank.
    _defaults = {
        "SyncInterval":     "20",
        "SshfsOptions":     ("reconnect,ServerAliveInterval=5,"
                             "ServerAliveCountMax=3"),
        "TrashDirs":        os.path.join(XDG_DATA_HOME, "Trash/files"),
        "PriorityHalfLife": "120",
        "DeleteAlways":     "no",
        "SyncExtraFiles":   "yes",
        "InflatePriority":  "yes",
        "AccountForSize":   "yes"
        }
    _subs = {
        "RemoteHost":   _host_synonyms[0],
        "RemoteUser":   os.getenv("LOGNAME"),
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
            if value.lower() not in (self._true_vals + self._false_vals):
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
                common = os.path.commonpath([instance.vals["LocalDir"], value])
                if common in [instance.vals["LocalDir"], value]:
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
                    or int(value) < 1
                    or int(value) > 65535):
                return "must be an integer in the range 1-65535"
        elif key == "RemoteDir":
            # In order to keep the interactive interface responsive, we don't
            # do any checking of the remote directory that requires connecting
            # over ssh.
            if not re.search("^~?/", value):
                return "must be an absolute path"
            value = os.path.expanduser(os.path.normpath(value))
            if self.raw_vals["RemoteHost"] in self._host_synonyms:
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
            if not re.search("^[0-9]+\s*(K|KB|KiB|M|MB|MiB|G|GB|GiB)$", value):
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
        errors = []

        # Check that all key names are valid.
        missing_keys = set(self._req_keys) - self.raw_vals.keys()
        unrecognized_keys = self.raw_vals.keys() - set(self._all_keys)
        if unrecognized_keys or missing_keys:
            for key in missing_keys:
                errors.append(
                    "{0}: missing required option '{1}'".format(context, key))
            for key in unrecognized_keys:
                errors.append(
                    "{0}: unrecognized option '{1}'".format(context, key))

        # Check values for valid syntax.
        for key, value in self.raw_vals.items():
            # If the remote directory is on the local machine, then certain
            # options should not be checked.
            if (self.raw_vals["RemoteHost"] in self._host_synonyms
                    and key in self._connect_keys):
                continue

            if check_empty or not check_empty and value:
                err_msg = self._check_value(key, value)
                if err_msg:
                    errors.append("{0}: '{1}' ".format(context, key) + err_msg)

        if errors:
            raise FileParseError(*errors)

    @DictProperty
    def vals(self, key: str) -> Any:
        """Parse individual config values.

        Returns:
            LocalDir: Input value converted to a user-expanded, normalized
                path as a str.
            RemoteHost: 'None' if value is in self._host_synonyms, and the
                input value as a str otherwise.
            RemoteUser: Input value unmodified as a str.
            Port: Input value unmodified as a str.
            RemoteDir: Input value converted to a user-expanded, normalized
                path as a str.
            StorageLimit: Input value converted to bytes as an int.
            SyncInterval: Input value converted to seconds as an int.
            SshfsOptions: Input value unmodified as a str.
            TrashDirs: Input value converted to user-expanded, normalized paths
                as a list of strings.
            PriorityHalfLife: Input value converted to seconds as an int.
            DeleteAlways: Input value converted to a bool.
            SyncExtraFiles: Input value converted to a bool.
            InflatePriority: Input value converted to a bool.
            AccountForSize: Input value converted to a bool.
        """
        if key in self.raw_vals:
            value = self.raw_vals[key]
        elif key in self._defaults:
            value = self._defaults[key]
        else:
            value = None

        if value is not None:
            if key == "LocalDir":
                value = os.path.expanduser(os.path.normpath(value))
            elif key == "RemoteHost":
                if value in self._host_synonyms:
                    value = None
            elif key == "RemoteDir":
                value = os.path.expanduser(os.path.normpath(value))
            elif key == "StorageLimit":
                try:
                    num, unit = re.findall(
                        "^([0-9]+)\s*(K|KB|KiB|M|MB|MiB|G|GB|GiB)$", value)[0]
                    if unit in ["K", "KiB"]:
                        value = int(num) * 1024
                    elif unit in ["M", "MiB"]:
                        value = int(num) * 1024**2
                    elif unit in ["G", "GiB"]:
                        value = int(num) * 1024**3
                    elif unit == "KB":
                        value = int(num) * 1000
                    elif unit == "MB":
                        value = int(num) * 1000**2
                    elif unit == "GB":
                        value = int(num) * 1000**3
                except IndexError:
                    pass
            elif key == "SyncInterval":
                try:
                    value = int(value) * 60
                except ValueError:
                    pass
            elif key == "TrashDirs":
                value = value.split(":")
                for index, element in enumerate(value):
                    value[index] = os.path.expanduser(
                        os.path.normpath(element))
            elif key == "PriorityHalfLife":
                try:
                    value = int(value) * 60**2
                except ValueError:
                    pass
            elif key in self._bool_keys:
                if isinstance(value, str):
                    if value.lower() in self._true_vals:
                        value = True
                    elif value.lower() in self._false_vals:
                        value = False

        return value

    @vals.setter
    def vals(self, key: str, value: str) -> None:
        """Set individual config values."""
        self.raw_vals[key] = value

    def prompt(self) -> None:
        """Prompt the user interactively for unset required values."""
        msg_printed = False
        for key in self._req_keys:
            # If the remote directory is on the local machine, then the user
            # should not be prompted for certain settings.
            if (self.raw_vals.get("RemoteHost") in self._host_synonyms
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
                    print(dedent("""\
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
                        err("Error: this value " + err_msg)
                    else:
                        break
                self.vals[key] = usr_input
        print()
