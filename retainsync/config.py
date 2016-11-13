"""Manage the parsing and generatiion of configuration files."""

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

from retainsync.utility import err, env, rinput

class ParseConfigFile:
    """Parse a configuration file."""

    # This is regex that denotes a comment line.
    comment_reg = re.compile(r"^\s*#")

    def __init__(self, path):
        self.infile = path
        self.raw_values = {}

    def read(self):
        """Save key-value pairs in a dictionary."""
        try:
            with open(self.infile) as infile:
                for line in infile:
                    # Skip line if it is a comment.
                    if not self.comment_reg.search(line) and \
                        re.search("=", line):
                        key, value = line.partition("=")[::2]
                        self.raw_values[key.strip()] = value.strip()
        except IOError:
            err("Error: could not open config file")
            sys.exit(1)

    def write(self, path):
        """Generate a new config file based on the input file."""

        try:
            with open(self.infile, "r") as infile:
                with open(path, "w") as outfile:
                    for line in infile:
                        # Skip line if it is a comment.
                        if not self.comment_reg.search(line) and \
                            re.search("=", line):
                            key, value = line.partition("=")[::2]
                            key = key.strip()
                            value = value.strip()
                            if key not in self.all_keys:
                                continue
                            try:
                                # Substitute value in the input file with the
                                # value in self.raw_values.
                                line = key + "=" + self.raw_values[key] + "\n"
                            except KeyError:
                                pass
                        outfile.write(line)

        except IOError:
            err("Error: could not open config file")
            sys.exit(1)

class ConfigDir:
    """Get information about the main configuration directory."""

    program_dir = os.path.join(env("XDG_CONFIG_HOME"), "retain-sync")
    config_basedir = os.path.join(program_dir, "configs")

    def local_configs(self):
        """Return a list of all local configuration directories."""
        return os.listdir(self.config_basedir)

class LocalConfigDir:
    """Get information about the local configuration directory.

    One of these directories exists for each directory that has been
    initialized by the user.
    """

    def __init__(self, name):
        config_dir = os.path.join(ConfigDir.config_basedir, name)
        mnt_dir = os.path.join(config_dir, "mnt")
        config_file = os.path.join(config_dir, "config")
        exclude_file = os.path.join(config_dir, "exclude")
        priority_file = os.path.join(config_dir, "priority.csv")

class LocalConfigFile(ParseConfigFile):
    """Manipulate the local configuration file."""

    # These are keys that must be included in the config file.
    req_keys = [
        "LocalDir", "RemoteHost", "RemoteUser", "Port", "RemoteDir",
        "StorageLimit"
        ]

    # These are keys that may be commented out or excluded.
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
    true_values = ["yes", "true"]
    false_values = ["no", "false"]

    # These are values for 'RemoteHost' that refer to the local machine.
    host_synonyms = ["localhost", "127.0.0.1"]

    def __init__(self, path):
        self.infile = path
        self.raw_values = {key: "" for key in self.req_keys}
        self.values = {key: "" for key in self.req_keys}

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
                if value.lower() not in (self.true_values + self.false_values):
                    err("Error:", context, "must have a boolean value")
                    return False

        if key == "LocalDir":
            if not value:
                err("Error:", context, "may not be blank")
                return False
            elif not re.search("^~?/", value):
                err("Error:", context, "must be an absolute path")
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
                    err("Error:", context, "must be an integer in the range "
                        + "1-65535")
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
        missing_keys = self.req_keys - self.raw_values.keys()
        unrecognized_keys = self.raw_values.keys() - self.all_keys
        if unrecognized_keys or missing_keys:
            for i in missing_keys:
                err("Error: config file: missing required option '{}'".format(i))
                errors += 1
            for i in unrecognized_keys:
                err("Error: config file: unrecognized option '{}'".format(i))
                errors += 1

        # Check values for valid syntax.
        for pair in self.raw_values.items():
            if not self.check_syntax(pair, True):
                errors += 1

        if errors > 0:
            sys.exit(1)

    def mutate(self):
        """Mutate config values to be more useful."""

        # Set default values.
        self.values = self.defaults
        self.values.update(self.raw_values)

        for key, value in self.values.items():
            if key == "LocalDir":
                value = os.path.expanduser(value)
            elif key == "RemoteHost":
                if value in self.host_synonyms:
                    value = None
            elif key == "Port":
                value = int(value)
            elif key == "RemoteDir":
                value = os.path.expanduser(value)
            elif key == "StorageLimit":
                # Convert human-readable value to bytes.
                num, unit = re.findall("^([0-9]+)([KMG])$", value)[0]
                if unit == "K":
                    value = int(num) * 1024
                if unit == "M":
                    value = int(num) * 1048576
                if unit == "G":
                    value = int(num) * 1073741824
            elif key == "TrashDirs":
                # Convert colon-separated value to list.
                value = value.split(":")
                for i in range(len(value)):
                    value[i] = os.path.expanduser(value[i])
            elif key in self.bool_keys:
                if value.lower() in self.true_values:
                    value = True
                elif value.lower() in self.false_values:
                    value = False
            self.values[key] = value

    def prompt(self):
        """Prompt the user interactively for unset required values."""

        # These dictionary values are tuples containing the prompt message and
        # the default value to populate the input buffer with.
        prompt_msg = {
            "LocalDir":     ("Enter the local directory path: ", ""),
            "RemoteHost":   ("Enter the hostname, ip address or domain name "
                            + "of the server (if any): ", ""),
            "RemoteUser":   ("Enter your user name on the server "
                            + "({}): ".format(env("USER")), ""),
            "Port":         ("Enter the port number for the connection: ",
                            "22"),
            "RemoteDir":    ("Enter the remote directory path: ", ""),
            "StorageLimit": ("Enter the amount of data to keep synced locally "
                            + "(accepts K, M or G): ", ""),
            }

        prompt_keys = self.req_keys
        for key in prompt_keys:
            if not self.raw_values[key]:
                prompt, prefill = prompt_msg[key]
                while True:
                    usr_input = rinput(prompt, prefill)
                    if self.check_syntax((key, usr_input), False):
                        break
                if key == "RemoteHost":
                    if usr_input in self.host_synonyms or not usr_input:
                        # These values are irrelevant if the remote
                        # directory is on the local machine, so don't prompt
                        # for them.
                        prompt_keys.remove("RemoteUser")
                        prompt_keys.remove("Port")
                self.raw_values[key] = usr_input
