"""Manipulate files in the profile directory.

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
import re
import glob
import datetime
import pkg_resources
import sqlite3
import weakref
from textwrap import dedent
from collections import defaultdict
from typing import Dict, Any, Iterable, Set

from retainsync.io.program import JSONFile, ConfigFile, ProgramDir
from retainsync.util.misc import err, env


class Profile:
    """Get information about a profile and its contents.

    Attributes:
        name:       The name of the profile.
        path:       The path to the profile directory.
        mnt_dir:    The path to the remote mountpoint.
        ex_file:    The path to the exclude pattern file.
        info_file:  The path to the JSON file for profile metadata.
        db_file:    The path to the file priority database.
        cfg_file:   The path to the profile's configuration file.
    """
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = os.path.join(ProgramDir.profiles_dir, self.name)
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

    Attributes:
        path:       The path to the exclude pattern file.
        files:      A set of absolute file paths that match the globbing
                    patterns.
        rel_files:  A set of relative file paths that match the globbing
                    patterns.
    """
    # This is regex that denotes a comment line.
    comment_reg = re.compile(r"^\s*#")

    def __init__(self, path: str) -> None:
        self.path = path
        self.files = set()
        self.rel_files = set()

    def generate(self, infile=None) -> None:
        """Generate a new file with comments.

        Args:
            infile:  If supplied, copy lines from this file into the new one.
        """
        with open(self.path, "w") as outfile:
            outfile.write(dedent("""\
                # This file contians patterns representing files and directories to exclude
                # from syncing.
                #
                # The patterns follow shell globbing rules as described in retain-sync(1).
                #
                # Lines with a leading slash are patterns that match relative to the root of
                # the sync directory. Lines without a leading slash are patterns that match
                # anywhere in the tree.
                """))
            if infile == "-":
                for line in sys.stdin.read():
                    outfile.write(line)
            elif infile:
                with open(infile) as infile:
                    for line in infile:
                        outfile.write(line)

    def readlines(self) -> str:
        """Yield lines that are not comments.

        Yields:
            Each line in the file that's not a comment.
        """
        with open(self.path) as file:
            for line in file:
                if not self.comment_reg.search(line):
                    yield line

    def glob(self, start_path: str) -> None:
        """Create a set of all file paths that match the globbing patterns.

        Args:
            start_path: Search this path for files that match the patterns.
        """
        for line in self.readlines():
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
            self.files.update(glob.glob(glob_str, recursive=True))

        # Create a set with relative file paths.
        self.rel_files = {os.path.relpath(path, start_path) for path in
                          self.files}


class ProfileInfoFile(JSONFile):
    """Parse a JSON-formatted file for profile metadata.

    Attributes:
        raw_vals:   A dictionary of raw values from the file.
        vals:       A dictionary of parsed values from the file.
    """
    def __init__(self, path) -> None:
        super().__init__(path)
        self.raw_vals = {}

    @property
    def vals(self) -> Dict[str, Any]:
        output = {}
        output = defaultdict(lambda: None)
        if self.raw_vals:
            output.update(self.raw_vals)
            if output["LastSync"]:
                output["LastSync"] = datetime.datetime.strptime(
                    output["LastSync"], "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=datetime.timezone.utc).timestamp()
        return output

    def generate(self, name: str, add_remote=False) -> None:
        """Generate info for a new profile.

        JSON Values:
            Status:     A short string describing the status of the profile.
                        "initialized": fully initialized
                        "partial": partially initialized
            Locked:     A boolean used to determine if another operation is
                        already running on the profile.
            LastSync:   The date and time (UTC) of the last sync on the
                        profile.
            Version:    The version of the program that the profile was
                        initialized by.
            ID:         A unique ID consisting of the machine ID, username and
                        profile name.
            InitOpts:   A dictionary of options given at the command line
                        at initialization.

        Args:
            name:   The name of the profile to use for the unique ID.
        """
        with open("/etc/machine-id") as id_file:
            unique_id = "-".join([id_file.read(8), env("USER"), name])
        version = float(pkg_resources.get_distribution("retain-sync").version)
        self.raw_vals.update({
            "Status":   "partial",
            "Locked":   True,
            "LastSync": None,
            "Version":  version,
            "ID":       unique_id,
            "InitOpts": {
                "add_remote": add_remote
                }
            })
        self.write()

    def update_synctime(self) -> None:
        """Update the time of the last sync."""
        # Store the timestamp as a human-readable string so that the file can
        # be edited manually.
        self.raw_vals["LastSync"] = datetime.datetime.utcnow().strftime(
            "%Y-%m-%dT%H:%M:%S")


class ProfileDBFile:
    """Manipulate a profile file database.

    Attributes:
        path:   The path to the database file.
        conn:   The sqlite connection object for the database.
        cur:    The sqlite cursor object for the connection.
    """

    def __init__(self, path) -> None:
        self.path = path
        if os.path.isfile(self.path):
            self.conn = sqlite3.connect(
                self.path, detect_types=sqlite3.PARSE_DECLTYPES)
            self.cur = self.conn.cursor()
        else:
            self.conn = None
            self.cur = None
        # Create adapter from python boolean to sqlite integer.
        sqlite3.register_adapter(bool, int)
        sqlite3.register_converter("bool", lambda x: bool(int(x)))

    def create(self) -> None:
        """Create a new empty database.

        Database Columns:
            path:       The relative path to the file.
            priority:   The priority value of the file.
        """
        if os.path.isfile(self.path):
            raise FileExistsError

        self.conn = sqlite3.connect(
            self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.cur = self.conn.cursor()

        with self.conn:
            self.cur.execute("""\
                CREATE TABLE files (
                    path text,
                    priority real
                );
                """)

    def add_files(self, paths: Iterable[str], priority=0) -> None:
        """Add new file paths to the database if they do not already exist.

        Args:
            path:       The file paths to add.
            priority:   The starting priority of the file path.
        """
        with self.conn:
            for path in paths:
                self.cur.execute("""\
                    INSERT INTO files (path, priority)
                    SELECT ?, ?
                    WHERE NOT EXISTS (SELECT 1 FROM files WHERE path=?);
                    """, (path, priority, path))

    def add_inflated(self, paths: Iterable[str]) -> None:
        """Add new file paths to the database with an inflated priority.

        Args:
            path:   The file paths to add.
        """
        with self.conn:
            self.cur.execute("""\
                SELECT MAX(priority) FROM files;
                """)
        max_priority = self.cur.fetchone()[0]
        self.add_files(paths, max_priority)

    def rm_files(self, paths: Iterable[str]) -> None:
        """Remove file paths from the database.

        Args:
            path:   The file paths to remove.
        """
        with self.conn:
            for path in paths:
                self.cur.execute("""\
                    DELETE FROM files
                    WHERE path=?;
                    """, (path,))

    def prioritize(self) -> Set[str]:
        """Get the paths of files sorted by their priorities.

        Returns:
            A list of file paths and their priorities.
        """
        with self.conn:
            self.cur.execute("""\
                SELECT path, priority
                FROM files
                ORDER BY priority DESC
                """)
        return {path for path, priority in self.cur.fetchall()}

    def increment(self, paths: Iterable[str]) -> None:
        """Increment the priority of some file paths by one.

        Args:
            path:   The file paths to increment the priority of.
        """
        with self.conn:
            for path in paths:
                self.cur.execute("""\
                    UPDATE files
                    SET priority=priority+1
                    WHERE path=?;
                    """, (path,))

    def adjust_all(self, adjustment=0.99) -> None:
        """Multiply the priorities of all file paths by a constant.

        Args:
            adjustment: The constant to multiply file priorities by.
        """
        with self.conn:
            self.cur.execute("""\
                UPDATE files
                SET priority=priority*?;
                """, (adjustment,))


class ProfileConfigFile(ConfigFile):
    """Manipulate a profile configuration file.

    Attributes:
        instances:      A weakly-referenced set of instances of this class.
        true_vals:      A list of strings that are recognized as boolean true.
        false_vals:     A list of strings that are recognized as boolean false.
        host_synonyms:  A list of strings that are synonyms for 'localhost'.
        req_keys:       A list of config keys that must be included in the
                        config file.
        opt_keys:       A list of config keys that may be commented out or
                        omitted.
        all_keys:       A list of all keys that are recognized in the config
                        file.
        bool_keys:      A list of config keys that must have boolean values.
        connect_keys:   A list of config keys that only matter when connecting
                        over ssh.
        defaults:       A dictionary of default values for optional config
                        keys.
        subs:           A dictionary of default values for required config
                        keys.
        path:           The path to the configuration file.
        profile:        The Profile object that the config file belongs to.
        add_remote:     Flip-flop the requirements of 'LocalDir' and
                        'RemoteDir'.
        raw_vals:       A dictionary of unmodified config value strings.
        vals:           A dictionary of modified config values.
    """
    instances = weakref.WeakSet()
    true_vals = ["yes", "true"]
    false_vals = ["no", "false"]
    host_synonyms = ["localhost", "127.0.0.1"]
    req_keys = [
        "LocalDir", "RemoteHost", "RemoteUser", "Port", "RemoteDir",
        "StorageLimit"
        ]
    opt_keys = [
        "SshfsOptions", "TrashDirs", "DeleteAlways", "SyncExtraFiles",
        "InflatePriority", "AccountForSize"
        ]
    all_keys = req_keys + opt_keys
    bool_keys = [
        "DeleteAlways", "SyncExtraFiles", "InflatePriority", "AccountForSize"
        ]
    connect_keys = ["RemoteUser", "Port"]
    # The reason for the distinction between self.defaults and self.subs is
    # that some optional config values have a valid reason for being blank.
    defaults = {
        "SshfsOptions":     ("reconnect,ServerAliveInterval=5,"
                             "ServerAliveCountMax=3"),
        "TrashDirs":        os.path.join(env("XDG_DATA_HOME"), "Trash/files"),
        "DeleteAlways":     "no",
        "SyncExtraFiles":   "yes",
        "InflatePriority":  "yes",
        "AccountForSize":   "yes"
        }
    subs = {
        "RemoteHost":   host_synonyms[0],
        "RemoteUser":   env("USER"),
        "Port":         "22"
        }

    def __init__(self, path: str, profile_obj=None, add_remote=None) -> None:
        super().__init__(path)
        self.profile = profile_obj
        self.add_remote = add_remote
        self.instances.add(self)

    def _check_values(self, key: str, value: str) -> str:
        """Check the syntax of a config option and return an error message.

        Args:
            key:    The name of the config option to check.
            value:  The value of the config option to check.

        Returns:
            An unformatted string corresponding to the syntax error (if any).
        """
        # Check if required values are blank.
        if key in self.req_keys and not value:
            return "Error: {} must not be blank"

        # Check boolean values.
        if key in self.bool_keys and value:
            if value.lower() not in (self.true_vals + self.false_vals):
                return "Error: {} must have a boolean value"

        if key == "LocalDir":
            if not re.search("^~?/", value):
                return "Error: {} must be an absolute path"
            value = os.path.expanduser(os.path.normpath(value))
            if os.path.commonpath([value, ProgramDir.path]) == value:
                return "Error: {} must not contain retain-sync config files"
            overlap_profiles = []
            for instance in self.instances:
                # Check if value overlaps with the 'LocalDir' of another
                # profile.
                if (not instance.profile
                        or not os.path.isfile(instance.path)
                        or instance is self):
                    # Do not include the current instance or any instances that
                    # do not belong to a profile.
                    continue
                name = instance.profile.name
                if not instance.vals:
                    instance.read()
                common = os.path.commonpath([instance.vals["LocalDir"], value])
                if common in [instance.vals["LocalDir"], value]:
                    overlap_profiles.append(name)
            if overlap_profiles:
                if len(overlap_profiles) > 1:
                    suffix = "s"
                else:
                    suffix = ""
                # Print a comma-separated list of conflicting profile names
                # after the error message.
                return (
                    "Error: {} "
                    "overlaps with the profile{0} {1}".format(
                        suffix,
                        ", ".join("'{}'".format(x) for x in overlap_profiles)))
            elif os.path.exists(value):
                if os.path.isdir(value):
                    if not os.access(value, os.W_OK):
                        return ("Error: {} must be a directory with write "
                                "access")
                    elif self.add_remote and os.stat(value).st_size > 0:
                        return "Error: {} must be an empty directory"
                else:
                    return "Error: {} must be a directory"
            else:
                if self.add_remote:
                    check_path = value
                    while os.path.dirname(check_path) != check_path:
                        if os.access(check_path, os.W_OK):
                            break
                        check_path = os.path.dirname(check_path)
                    else:
                        return ("Error: {} must be a directory with write "
                                "access")
                else:
                    return "Error: {} must be an existing directory"
        elif key == "RemoteHost":
            if re.search("\s+", value):
                return "Error: {} must not contain spaces"
        elif key == "RemoteUser":
            if re.search("\s+", value):
                return "Error: {} must not contain spaces"
        elif key == "Port":
            if (not re.search("^[0-9]+$", value)
                    or int(value) < 1
                    or int(value) > 65535):
                return "Error: {} must be an integer in the range 1-65535"
        elif key == "RemoteDir":
            # In order to keep the interactive interface responsive, we don't
            # do any checking of the remote directory that requires connecting
            # over ssh.
            if not re.search("^~?/", value):
                return "Error: {} must be an absolute path"
            value = os.path.expanduser(os.path.normpath(value))
            if self.raw_vals["RemoteHost"] in self.host_synonyms:
                if os.path.exists(value):
                    if os.path.isdir(value):
                        if not os.access(value, os.W_OK):
                            return ("Error: {} must be a directory with write "
                                    "access")
                        elif (self.add_remote is False
                                and os.stat(value).st_size > 0):
                            return "Error: {} must be an empty directory"
                    else:
                        return "Error: {} must be a directory"
                else:
                    if self.add_remote:
                        return "Error: {} must be an existing directory"
                    else:
                        try:
                            os.makedirs(value)
                        except PermissionError:
                            return ("Error: {} must be in a directory with "
                                    "write access")

        elif key == "StorageLimit":
            if not re.search("^[0-9]+\s*(K|KB|KiB|M|MB|MiB|G|GB|GiB)$", value):
                return ("Error: {} must be an integer followed by a unit "
                        "(e.g. 10GB)")
        elif key == "SshfsOptions":
            if value:
                if re.search("\s+", value):
                    return "Error: {} must not contain spaces"
        elif key == "TrashDirs":
            if value:
                if re.search("(^|:)(?!~?/)", value):
                    return "Error: {} only accepts absolute paths"

    def check_all(self, check_empty=True, context="config file") -> None:
        """Check that file is valid and syntactically correct.

        Args:
            check_empty:    Check empty/unset values.
            context:        The context to show in the error messages.
        """
        errors = 0

        # Check that all key names are valid.
        missing_keys = self.req_keys - self.raw_vals.keys()
        unrecognized_keys = self.raw_vals.keys() - self.all_keys
        if unrecognized_keys or missing_keys:
            for key in missing_keys:
                err("Error: config file: missing required option '{}'".format(
                    key))
                errors += 1
            for key in unrecognized_keys:
                err("Error: config file: unrecognized option '{}'".format(key))
                errors += 1

        # Check values for valid syntax.
        check_vals = self.raw_vals.copy()
        if self.raw_vals["RemoteHost"] in self.host_synonyms:
            # These values are irrelevant if the remote directory is on the
            # local machine.
            for key in self.connect_keys:
                del check_vals[key]
        for key, value in check_vals.items():
            if check_empty or not check_empty and value:
                err_msg = self._check_values(key, value)
                if err_msg:
                    err(err_msg.format("{0}: '{1}'".format(context, key)))
                    errors += 1

        if errors > 0:
            sys.exit(1)

    @property
    def vals(self) -> Dict[str, Any]:
        """Create a new dict with more computer-friendly config values."""
        output = {}
        if self.raw_vals:
            # Set default values.
            output = self.defaults.copy()
            output.update(self.raw_vals)

        for key, value in output.copy().items():
            if key == "LocalDir":
                value = os.path.expanduser(os.path.normpath(value))
            elif key == "RemoteHost":
                if value in self.host_synonyms:
                    value = None
            elif key == "RemoteDir":
                value = os.path.expanduser(os.path.normpath(value))
            elif key == "StorageLimit":
                try:
                    num, unit = re.findall(
                        "^([0-9]+)\s*(K|KB|KiB|M|MB|MiB|G|GB|GiB)$", value)[0]
                    if unit in ["K", "KiB"]:
                        value = int(num) * 2**10
                    elif unit in ["M", "MiB"]:
                        value = int(num) * 2**20
                    elif unit in ["G", "GiB"]:
                        value = int(num) * 2**30
                    elif unit == "KB":
                        value = int(num) * 10**3
                    elif unit == "MB":
                        value = int(num) * 10**6
                    elif unit == "GB":
                        value = int(num) * 10**9
                except IndexError:
                    pass
            elif key == "TrashDirs":
                # Convert colon-separated strings to list.
                value = value.split(":")
                for index, element in enumerate(value):
                    value[index] = os.path.expanduser(element)
            elif key in self.bool_keys:
                if isinstance(value, str):
                    if value.lower() in self.true_vals:
                        value = True
                    elif value.lower() in self.false_vals:
                        value = False
            output[key] = value

        return output

    def prompt(self) -> None:
        """Prompt the user interactively for unset required values."""

        prompt_msg = {
            "LocalDir":     "Enter the local directory path: ",
            "RemoteHost":   ("Enter the hostname, IP address or domain name "
                             "of the remote ({}): ".format(
                                self.subs["RemoteHost"])),
            "RemoteUser":   ("Enter your user name on the server "
                             "({}): ".format(self.subs["RemoteUser"])),
            "Port":         ("Enter the port number for the connection "
                             "({}): ".format(self.subs["Port"])),
            "RemoteDir":    "Enter the remote directory path: ",
            "StorageLimit": ("Enter the amount of data to keep synced "
                             "locally: ")
            }

        prompt_keys = self.req_keys.copy()
        for key in prompt_keys:
            # We don't use a defaultdict for this so that we can know if a
            # config file has been read based on whether raw_vals is empty.
            if not self.raw_vals.get(key, None):
                while True:
                    usr_input = input(prompt_msg[key]).strip()
                    if not usr_input and key in self.subs:
                        usr_input = self.subs[key]
                    err_msg = self._check_values(key, usr_input)
                    if err_msg:
                        err(err_msg.format("this value"))
                    else:
                        break
                if key == "RemoteHost" and usr_input in self.host_synonyms:
                    # These values are irrelevant if the remote
                    # directory is on the local machine.
                    for conn_key in self.connect_keys:
                        prompt_keys.remove(conn_key)
                self.raw_vals[key] = usr_input
        print()
