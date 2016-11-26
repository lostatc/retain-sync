"""Parse and generate configuration files."""

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
import re
import json
import sqlite3
from collections import defaultdict

import retainsync.config as c
from retainsync.utility import err, env, tty_input, open_db


class ConfigFile:
    """Parse a configuration file."""

    # This is regex that denotes a comment line.
    comment_reg = re.compile(r"^\s*#")

    def __init__(self, path):
        self.path = path
        self.raw_vals = {}

    def read(self):
        """Save key-value pairs in a dictionary."""
        try:
            with open(self.path) as file:
                for line in file:
                    # Skip line if it is a comment.
                    if not self.comment_reg.search(line) and \
                        re.search("=", line):
                        key, value = line.partition("=")[::2]
                        self.raw_vals[key.strip()] = value.strip()
        except IOError:
            err("Error: could not open configuration file")
            sys.exit(1)

    def write(self, infile):
        """Generate a new config file based on the input file."""

        try:
            with open(infile, "r") as infile:
                with open(self.path, "w") as outfile:
                    for line in infile:
                        # Skip line if it is a comment.
                        if not self.comment_reg.search(line) \
                            and re.search("=", line):
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

        except IOError:
            err("Error: could not open configuration file")
            sys.exit(1)

class JSONFile:
    """Parse a JSON-formatted file."""
    def __init__(self, path):
        self.path = path
        self.vals = defaultdict(lambda: None)

    def read(self):
        """Read file into an object."""
        with open(self.path) as file:
            self.vals = json.load(file)

    def write(self):
        """Write object to a file."""
        with open(self.path, "w") as file:
            json.dump(self.vals, file, indent=4)

class ProgramDir:
    """Get information about the main configuration directory."""

    path = os.path.join(env("XDG_CONFIG_HOME"), "retain-sync")
    profile_basedir = os.path.join(path, "profiles")

    @classmethod
    def list_profiles(cls):
        """Yield the names of all existing profiles."""
        for name in os.listdir(cls.profile_basedir):
            yield name

    @classmethod
    def inst_profiles(cls):
        """Create a global dictionary of profile directory objects."""
        combined_dict = {}
        for name in cls.list_profiles():
            combined_dict[name] = ProfileDir(name)
        return combined_dict

    @classmethod
    def check_overlap(cls, check_path):
        """Return a list of profiles that overlap with the given path."""
        overlap_profiles = []
        for name, profile in c.profiles.items():
            common = os.path.commonpath([profile.cfg_file.vals["LocalDir"],
                check_path])
            if os.path.samefile(common,
                profile.cfg_file.vals["LocalDir"]) \
                or os.path.samefile(common, check_path):
                overlap_profiles.append(name)
        return overlap_profiles

class ProfileDir:
    """Get information about a profile directory."""

    def __init__(self, name):
        self.name = name
        self.path = os.path.join(ProgramDir.profile_basedir, self.name)
        self.mnt_dir = os.path.join(self.path, "mnt")
        self.exclude_file = ProfExcludeFile(os.path.join(self.path, "exclude"))
        self.info_file = ProfInfoFile(os.path.join(self.path, "info.json"))
        self.priority_file = ProfPriorityFile(os.path.join(self.path, "files.db"))
        self.cfg_file = ProfConfigFile(os.path.join(self.path, "config"))
        os.makedirs(self.path, exist_ok=True)

class ProfExcludeFile:
    """Get file paths from the local exclude file."""

    def __init__(self, path):
        self.path = path

    def read(self):
        """Yield lines that are not comments."""
        with open(self.path) as infile:
            for line in infile:
                # Skip line if it is a comment.
                if not self.comment_reg.search(line):
                    yield line

    def list_files(self):
        """Expand all directories and yield file paths."""
        for filepath in self.read():
            if os.path.isdir(filepath):
                for dirpath, dirnames, filenames in os.walk(self.dir):
                    for name in filenames:
                        yield os.path.join(dirpath, name)
            else:
                yield filepath

class ProfInfoFile(JSONFile):
    """Parse a JSON-formatted file for data not found in the config file."""

    def create(self):
        """Generate file for a new profile."""
        self.vals.update({
            "Status":   "part",
            "Locked":   True,
            "LastSync": None
            })

class ProfPriorityFile:
    """Manipulate the database for keeping track of file priority."""

    def __init__(self, path):
        self.path = path

    def create(self):
        """Create new empty table."""
        with open_db(self.path) as db:
            cur = db.cursor()
            cur.execute("""\
                CREATE TABLE files (
                    file text,
                    priority real,
                );
                """)

    def add_file(self, path, priority=0):
        """Add a new file to the database with a given priority."""
        with open_db(self.path) as db:
            cur = db.cursor()
            cur.execute("""\
                INSERT INTO files (file, priority)
                VALUES (?, ?);
                """, (path, priority))

    def add_inflated(self, path):
        """Add a new file to the database with an inflated priority."""
        with open_db(self.path) as db:
            cur = db.cursor()
            cur.execute("""\
                SELECT MAX(priority) FROM files;
                """)
            max_priority = cur.fetchone()
            self.add_file(path, max_priority)

    def rm_file(self, path):
        """Remote a file from the database."""
        with open_db(self.path) as db:
            cur = db.cursor()
            cur.execute("""\
                DELETE FROM files
                WHERE file=?;
                """, path,)

    def increment(self, path):
        """Increment the priority of a file by one."""
        with open_db(self.path) as db:
            cur = db.cursor()
            cur.execute("""\
                UPDATE files
                SET priority=priority + 1
                WHERE file=?;
                """, path,)

    def adjust_all(self, adjustment=0.99):
        """Multiply the priorities of all files by a constant."""
        with open_db(self.path) as db:
            cur = db.cursor()
            cur.execute("""\
                UPDATE files
                SET priority=priority * ?;
                """, adjustment,)

class ProfConfigFile(ConfigFile):
    """Manipulate the local configuration file."""

    # These are keys that must be included in the config file.
    req_keys = [
        "LocalDir", "RemoteHost", "RemoteUser", "Port", "RemoteDir",
        "StorageLimit"
        ]

    # These are keys that may be commented out or omitted.
    opt_keys = [
        "SshfsOption", "TrashDirs", "DeleteAlways", "SyncExtraFiles",
        "InflatePriority", "AccountForSize"
        ]

    # These are all the keys that are recognized in the config file.
    all_keys = req_keys + opt_keys

    # These are keys that must have boolean values.
    bool_keys = [
        "DeleteAlways", "SyncExtraFiles", "InflatePriority", "AccountForSize"
        ]

    # These are the default values for optional keys.
    defaults = {
        "SshfsOptions":     "reconnect,ServerAliveInterval=5,"
                            + "ServerAliveCountMax=3",
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
        self.vals = {key: "" for key in self.req_keys}

    def check_syntax(self, pair, use_context=False):
        """Check syntax of a specific value."""

        key, value = pair

        # This is what to print for context in error messages.
        if use_context:
            context = "config file: '{}'".format(key)
        else:
            context = "this value"

        # Check for boolean values.
        if key in self.bool_keys:
            if value:
                if value.lower() not in (self.true_vals + self.false_vals):
                    err("Error:", context, "must have a boolean value")
                    return False

        if key == "LocalDir":
            overlap_profiles = ProgramDir.check_overlap(value)
            if not value:
                err("Error:", context, "may not be blank")
                return False
            elif not re.search("^~?/", value):
                err("Error:", context, "must be an absolute path")
                return False
            elif overlap_profiles:
                if len(overlap_profiles) > 1:
                    suffix = "s"
                else:
                    suffix = ""
                # Print a comma-separated list of quoted conflicting
                # profile names after the error message.
                err("Error:", context, "overlaps with the "
                    + "profile{0} {1}".format(suffix, ", ".join(
                    "'{}'".format(x) for x in overlap_profiles)))
                return False
            elif os.path.samefile(os.path.commonpath([value,
                ProgramDir.path]), value):
                err("Error:", context, "must not contain retain-sync "
                + "config files")
                return False
            elif c.cmd_args["add_remote"]:
                if os.path.exists(value):
                    if os.path.isdir(value):
                        if not os.access(value, os.W_OK):
                            err("Error:", context,
                                "must be a directory with write access")
                            return False
                        elif os.listdir(value):
                            err("Error:", context,
                                "must be an empty directory")
                            return False
                    else:
                        err("Error:", context, "must be an empty directory")
                        return False
            elif not c.cmd_args["add_remote"]:
                if not os.path.isdir(value):
                    err("Error:", context, "must be an existing directory")
                    return False
                elif not os.access(value, os.W_OK):
                    err("Error:", context,
                        "must be a directory with write access")
                    return False
        elif key == "RemoteHost":
            if re.search("\s+", value):
                err("Error:", context, "may not contain spaces")
                return False
        elif key == "RemoteUser":
            if re.search("\s+", value):
                err("Error:", context, "may not contain spaces")
                return False
        elif key == "Port":
            if value:
                if not re.search("^[0-9]+$", value):
                    err("Error:", context, "must be an integer in the range "
                        + "1-65535")
                    return False
                elif int(value) < 1 or int(value) > 65535:
                    err("Error:", context,
                        "must be an integer in the range 1-65535")
                    return False
        elif key == "RemoteDir":
            if not value:
                err("Error:", context, "may not be blank")
                return False
            elif not re.search("^~?/", value):
                err("Error:", context, "must be an absolute path")
                return False
        elif key == "StorageLimit":
            if not value:
                err("Error:", context, "may not be blank")
                return False
            elif not re.search("^[0-9]+[KMG]$", value):
                err("Error:", context, "must be an integer followed by a "
                    + "unit (e.g. 10G)")
                return False
        elif key == "SshfsOptions":
            if value:
                if re.search("\s+", value):
                    err("Error:", context, "may not contain spaces")
                    return False
        elif key == "TrashDirs":
            if value:
                if re.search("(^|:)(?!~?/)", value):
                    err("Error:", context, "only accepts absolute paths")
                    return False
        return True

    def check_all(self):
        """Check that file is valid and syntactically correct."""

        errors = 0

        # Check that all key names are valid.
        missing_keys = self.req_keys - self.raw_vals.keys()
        unrecognized_keys = self.raw_vals.keys() - self.all_keys
        if unrecognized_keys or missing_keys:
            for key in missing_keys:
                err("Error: config file: missing required option '{}'".format(key))
                errors += 1
            for key in unrecognized_keys:
                err("Error: config file: unrecognized option '{}'".format(key))
                errors += 1

        # Check values for valid syntax.
        for pair in self.raw_vals.items():
            if not self.check_syntax(pair, True):
                errors += 1

        if errors > 0:
            sys.exit(1)

    def mutate(self):
        """Mutate config values to be more useful.

        Do not fail if the syntax is incorrect or the value has already been mutated.
        """

        # Set default values.
        output = self.defaults
        output.update(self.raw_vals)

        for key, value in output.items():
            if key == "LocalDir":
                value = os.path.expanduser(value)
            elif key == "RemoteHost":
                if value in self.host_synonyms:
                    value = None
            elif key == "RemoteDir":
                value = os.path.expanduser(value)
            elif key == "StorageLimit":
                # Convert human-readable value to bytes.
                try:
                    num, unit = re.findall("^([0-9]+)([KMG])$", value)[0]
                    if unit == "K":
                        value = int(num) * 1024
                    if unit == "M":
                        value = int(num) * 1048576
                    if unit == "G":
                        value = int(num) * 1073741824
                except IndexError:
                    pass
            elif key == "TrashDirs":
                # Convert colon-separated value to list.
                # if value is str:
                value = value.split(":")
                for i in range(len(value)):
                    value[i] = os.path.expanduser(value[i])
            elif key in self.bool_keys:
                if value is str:
                    if value.lower() in self.true_vals:
                        value = True
                    elif value.lower() in self.false_vals:
                        value = False
            self.vals[key] = value

    def prompt(self):
        """Prompt the user interactively for unset required values."""

        # These dictionary values contain the prompt messages to use.
        prompt_msg = {
            "LocalDir":     "Enter the local directory path: ",
            "RemoteHost":   "Enter the hostname, ip address or domain name "
                            + "of the server (if any): ",
            "RemoteUser":   "Enter your user name on the server "
                            + "({}): ".format(env("USER")),
            "Port":         "Enter the port number for the connection (22): ",
            "RemoteDir":    "Enter the remote directory path: ",
            "StorageLimit": "Enter the amount of data to keep synced locally "
                            + "(accepts K, M or G): "
            }

        prompt_keys = self.req_keys
        for key in prompt_keys:
            if not self.raw_vals[key]:
                while True:
                    usr_input = tty_input(prompt_msg[key])
                    if self.check_syntax((key, usr_input), False):
                        break
                if key == "RemoteHost":
                    if usr_input in self.host_synonyms or not usr_input:
                        # These values are irrelevant if the remote
                        # directory is on the local machine, so don't prompt
                        # for them.
                        prompt_keys.remove("RemoteUser")
                        prompt_keys.remove("Port")
                self.raw_vals[key] = usr_input
