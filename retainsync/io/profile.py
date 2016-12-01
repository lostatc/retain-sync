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
from textwrap import dedent
from collections import defaultdict

import retainsync.config as c
from retainsync.io.program import JSONFile, ConfigFile, ProgramDir
from retainsync.util.misc import err, env, tty_input


class ProfileDir:
    """Get information about a profile directory and its contents.

    Attributes:
        name:       The name of the profile.
        path:       The path to the profile directory.
        mnt_dir:    The path to the remote mountpoint.
        ex_file:    The path to the exclude pattern file.
        info_file:  The path to the JSON file for profile metadata.
        db_file:    The path to the file priority database.
        cfg_file:   The path to the profile's configuration file.
    """
    def __init__(self, name):
        self.name = name
        self.path = os.path.join(ProgramDir.profile_basedir, self.name)
        os.makedirs(self.path, exist_ok=True)
        self.mnt_dir = os.path.join(self.path, "mnt")
        self.ex_file = ProfileExcludeFile(
            os.path.join(self.path, "exclude"))
        self.info_file = ProfileInfoFile(os.path.join(self.path, ".info.json"))
        self.db_file = ProfileDBFile(
            os.path.join(self.path, ".local.db"))
        self.cfg_file = ProfileConfigFile(os.path.join(self.path, "config"))


class ProfileExcludeFile:
    """Get file paths from the local exclude file.

    Attributes:
        path:       The path to the exclude pattern file.
        files:      A set of absolute file paths that match the globbing
                    patterns.
        rel_files:  A set of relative file paths that match the globbing
                    patterns.
    """
    # This is regex that denotes a comment line.
    comment_reg = re.compile(r"^\s*#")

    def __init__(self, path):
        self.path = path
        self.files = set()
        self.rel_files = set()

    def generate(self, infile=None):
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
                # Lines with a leading slash are patterns relative to the root of the sync
                # directory. Lines without a leading slash are patterns that search the whole
                # tree.\n"""))
            if infile == "-":
                for line in sys.stdin.read():
                    outfile.write(line)
            elif infile:
                with open(infile) as infile:
                    for line in infile:
                        outfile.write(line)

    def readlines(self):
        """Yield lines that are not comments.

        Yields:
            A string for every line in the file that's not a comment.
        """
        with open(self.path) as file:
            for line in file:
                if not self.comment_reg.search(line):
                    yield line

    def glob(self, start_path):
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
    """Parse a JSON-formatted file for profile metadata."""
    def read(self):
        """Read file into an object and make substitutions."""
        # Create an empty defaultdict if the file doesn't exist.
        self.vals = {}
        if os.path.isfile(self.path):
            super().read()
        self.vals = defaultdict(lambda: None, self.vals)
        if self.vals["LastSync"]:
            self.vals["LastSync"] = datetime.datetime.strptime(
                self.vals["LastSync"], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=datetime.timezone.utc).timestamp()

    def generate(self):
        """Generate info for a new profile.

        JSON Values:
            Status:     A short string describing the status of the profile.
                        "init": fully initialized
                        "part": partially initialized
            Locked:     A boolean used to determine if another operation is
                        already running on the profile.
            LastSync:   The date and time (UTC) of the last sync on the
                        profile.
            Version:    The version of the program that the profile was
                        initialized by.
            ID:         A unique ID consisting of the machine ID, username and
                        profile name.

        Args:
            name:   The name of the profile to use for the unique ID.
        """
        with open("/etc/machine-id") as id_file:
            unique_id = "-".join([id_file.read(8), env("USER"), c.main.name])
        version = float(pkg_resources.get_distribution("retain-sync").version)
        self.vals.update({
            "Status":   "part",
            "Locked":   True,
            "LastSync": None,
            "Version":  version,
            "ID":       unique_id
            })
        self.write()

    def update_synctime(self):
        """Update the time of the last sync."""
        # Store the timestamp as a human-readable string so that the file can
        # be edited manually.
        self.vals["LastSync"] = datetime.datetime.utcnow().strftime(
            "%Y-%m-%dT%H:%M:%S")


class ProfileDBFile:
    """Manipulate the local file database.

    Attributes:
        path:  The path to the database file.
    """

    def __init__(self, path):
        self.path = path

    def create(self):
        """Create a new empty database.

        Database Columns:
            path:       The relative path to the file.
            priority:   The priority value of the file.
        """
        self.conn = sqlite3.connect(
            self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.cur = self.conn.cursor()
        # Create adapter from python boolean to sqlite integer.
        sqlite3.register_adapter(bool, int)
        sqlite3.register_converter("boolean", lambda x: bool(int(x)))

        with self.conn:
            self.cur.execute("""\
                CREATE TABLE files (
                    path text,
                    priority real
                );
                """)

    def add_file(self, path, priority=0):
        """Add a new file path to the database if it doesn't already exist.

        Args:
            path:       The file path to add.
            priority:   The starting priority of the file path.
        """
        with self.conn:
            self.cur.execute("""\
                INSERT INTO files (path, priority)
                    SELECT ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM files WHERE path=?);
                """, (path, priority, path))

    def add_inflated(self, path):
        """Add a new file path to the database with an inflated priority.

        Args:
            path:   The file path to add.
        """
        with self.conn:
            self.cur.execute("""\
                SELECT MAX(priority) FROM files;
                """)
            max_priority = self.cur.fetchone()
            self.add_file(path, max_priority)

    def rm_file(self, path):
        """Remove a file path from the database.

        Args:
            path:   The file path to remove.
        """
        with self.conn:
            self.cur.execute("""\
                DELETE FROM files
                WHERE path=?;
                """, (path,))

    def increment(self, path):
        """Increment the priority of a file path by one.

        Args:
            path:   The file path to increment the priority of.
        """
        with self.conn:
            self.cur.execute("""\
                UPDATE files
                SET priority=priority+1
                WHERE path=?;
                """, (path,))

    def adjust_all(self, adjustment=0.99):
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
    """Manipulate the local configuration file.

    Attributes:
        path:      The path to the configuration file.
        raw_vals:  A dictionary of unmodified config value strings.
        vals:      A dictionary of modified config values.
    """

    # Define keys that must be included in the config file.
    req_keys = [
        "LocalDir", "RemoteHost", "RemoteUser", "Port", "RemoteDir",
        "StorageLimit"
        ]

    # Define keys that may be commented out or omitted.
    opt_keys = [
        "SshfsOption", "TrashDirs", "DeleteAlways", "SyncExtraFiles",
        "InflatePriority", "AccountForSize"
        ]

    # Define all keys that are recognized in the config file.
    all_keys = req_keys + opt_keys

    # Define keys that must have boolean values.
    bool_keys = [
        "DeleteAlways", "SyncExtraFiles", "InflatePriority", "AccountForSize"
        ]

    # Define default values for keys.
    defaults = {
        "SshfsOptions":     ("reconnect,ServerAliveInterval=5,"
                             "ServerAliveCountMax=3"),
        "TrashDirs":        os.path.join(env("XDG_DATA_HOME"), "Trash/files"),
        "DeleteAlways":     "no",
        "SyncExtraFiles":   "yes",
        "InflatePriority":  "yes",
        "AccountForSize":   "yes"
        }

    # These are strings that are recognized as valid boolean values
    # (case insensitive).
    true_vals = ["yes", "true"]
    false_vals = ["no", "false"]

    # These are values for 'RemoteHost' that refer to the local machine.
    host_synonyms = ["localhost", "127.0.0.1"]

    def __init__(self, path):
        self.path = path
        self.raw_vals = {key: "" for key in self.req_keys}

    def _check_syntax(self, key, value):
        """Check the syntax of a config option and return an error message.

        Args:
            key:    The name of the config option to check.
            value:  The value of the config option to check.

        Returns:
            An unformatted string corresponding to the syntax error (if any).
        """
        # Check for boolean values.
        if key in self.bool_keys:
            if value:
                if value.lower() not in (self.true_vals + self.false_vals):
                    return "Error: {} must have a boolean value"

        if key == "LocalDir":
            value = os.path.expanduser(os.path.normpath(value))
            if not value:
                return "Error: {} must not be blank"
            elif not re.search("^~?/", value):
                return "Error: {} must be an absolute path"
            overlap_profiles = ProgramDir.check_overlap(value)
            if os.path.commonpath([value, ProgramDir.path]) == value:
                return "Error: {} must not contain retain-sync config files"
            elif overlap_profiles:
                if len(overlap_profiles) > 1:
                    suffix = "s"
                else:
                    suffix = ""
                # Print a comma-separated list of quoted conflicting
                # profile names after the error message.
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
                    elif c.cmd_args["add_remote"] and os.listdir(value):
                        return "Error: {} must be an empty directory"
                else:
                    return "Error: {} must be a directory"
            else:
                if c.cmd_args["add_remote"]:
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
            if value:
                if (not re.search("^[0-9]+$", value)
                        or int(value) < 1
                        or int(value) > 65535):
                    return "Error: {} must be an integer in the range 1-65535"
        elif key == "RemoteDir":
            # In order to keep the interactive interface responsive, we don't
            # check the validity of the remote directory here because of the
            # delay connecting over ssh would cause.
            value = os.path.expanduser(os.path.normpath(value))
            if not value:
                return "Error: {} must not be blank"
            elif not re.search("^~?/", value):
                return "Error: {} must be an absolute path"
        elif key == "StorageLimit":
            if not value:
                return "Error: {} must not be blank"
            elif not re.search("^[0-9]+[KMG]$", value):
                return ("Error: {} must be an integer followed by a unit "
                        "(e.g. 10G)")
        elif key == "SshfsOptions":
            if value:
                if re.search("\s+", value):
                    return "Error: {} must not contain spaces"
        elif key == "TrashDirs":
            if value:
                if re.search("(^|:)(?!~?/)", value):
                    return "Error: {} only accepts absolute paths"

    def check_all(self, check_empty=True, context="config file"):
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
        for key, value in self.raw_vals.items():
            if check_empty or not check_empty and value:
                err_msg = self._check_syntax(key, value)
                if err_msg:
                    print(err_msg.format("{0}: '{1}'".format(context, key)))
                    errors += 1

        if errors > 0:
            sys.exit(1)

    @property
    def vals(self):
        """Create a new dict with more computer-friendly config values."""

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
                # Convert human-readable value to bytes.
                try:
                    num, unit = re.findall("^([0-9]+)([KMG])$", value)[0]
                    if unit == "K":
                        value = int(num) * 2**10
                    if unit == "M":
                        value = int(num) * 2**20
                    if unit == "G":
                        value = int(num) * 2**30
                except IndexError:
                    pass
            elif key == "TrashDirs":
                # Convert colon-separated strings to list.
                value = value.split(":")
                for index, element in enumerate(value):
                    value[index] = os.path.expanduser(element)
            elif key in self.bool_keys:
                if value is str:
                    if value.lower() in self.true_vals:
                        value = True
                    elif value.lower() in self.false_vals:
                        value = False
            output[key] = value

        return output

    def prompt(self):
        """Prompt the user interactively for unset required values."""

        # These dictionary values contain the prompt messages to use.
        prompt_msg = {
            "LocalDir":     "Enter the local directory path: ",
            "RemoteHost":   ("Enter the hostname, ip address or domain name "
                             "of the server (if any): "),
            "RemoteUser":   ("Enter your user name on the server "
                             "({}): ".format(env("USER"))),
            "Port":         "Enter the port number for the connection (22): ",
            "RemoteDir":    "Enter the remote directory path: ",
            "StorageLimit": ("Enter the amount of data to keep synced locally "
                             "(accepts K, M or G): ")
            }

        prompt_keys = self.req_keys
        for key in prompt_keys:
            if not self.raw_vals[key]:
                while True:
                    usr_input = tty_input(prompt_msg[key]).strip()
                    err_msg = self._check_syntax(key, usr_input)
                    if err_msg:
                        print(err_msg.format("this value"))
                    else:
                        break
                if key == "RemoteHost":
                    if usr_input in self.host_synonyms or not usr_input:
                        # These values are irrelevant if the remote
                        # directory is on the local machine, so don't prompt
                        # for them.
                        prompt_keys.remove("RemoteUser")
                        prompt_keys.remove("Port")
                self.raw_vals[key] = usr_input
        print()
