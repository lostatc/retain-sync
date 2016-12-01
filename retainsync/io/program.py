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
import retainsync.config as c
from retainsync.util.misc import err, env, shell_cmd


class ConfigFile:
    """Parse a configuration file.

    Attributes:
        path:      The path to the configuration file.
        raw_vals:  A dictionary of unmodified config value strings.
    """

    # This is regex that denotes a comment line.
    comment_reg = re.compile(r"^\s*#")

    def __init__(self, path):
        self.path = path
        self.raw_vals = {}

    def read(self):
        """Parse file for key-value pairs and save in a dictionary."""
        try:
            with open(self.path) as file:
                for line in file:
                    # Skip line if it is a comment.
                    if (not self.comment_reg.search(line)
                            and re.search("=", line)):
                        key, value = line.partition("=")[::2]
                        self.raw_vals[key.strip()] = value.strip()
        except IOError:
            err("Error: could not open configuration file")
            sys.exit(1)

    def write(self, infile):
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

        except IOError:
            err("Error: could not open configuration file")
            sys.exit(1)


class JSONFile:
    """Parse a JSON-formatted file.

    Attributes:
        path:  The path to the JSON file.
        vals:  A dictionary or list of values from the file.
    """
    def __init__(self, path):
        self.path = path
        self.vals = None

    def read(self):
        """Read file into an object."""
        with open(self.path) as file:
            self.vals = json.load(file)

    def write(self):
        """Write object to a file."""
        with open(self.path, "w") as file:
            json.dump(self.vals, file, indent=4)


class ProgramDir:
    """Get information about the main configuration directory.

    Attributes:
        path:               The path to the program directory.
        profile_basedir:    The base directory containing profile directories.
    """

    path = os.path.join(env("XDG_CONFIG_HOME"), "retain-sync")
    profile_basedir = os.path.join(path, "profiles")

    @classmethod
    def list_profiles(cls):
        """Get the names of all existing profiles.

        Returns:
            A list containing the name of each profile as a string.
        """
        profiles = []
        for entry in os.scandir(cls.profile_basedir):
            if entry.is_dir(follow_symlinks=False):
                profiles.append(entry.name)
        return profiles

    @classmethod
    def check_overlap(cls, check_path):
        """Get the names of profiles that overlap with the given path.

        Returns:
            A list of profile names as strings.
        """
        overlap_profiles = []
        for name, profile in c.profiles.items():
            common = os.path.commonpath([
                profile.cfg_file.vals["LocalDir"], check_path])
            if (common == profile.cfg_file.vals["LocalDir"]
                    or common == os.path.normpath(check_path)):
                overlap_profiles.append(name)
        return overlap_profiles


class SSHConnection:
    """Run commands over ssh."""

    def __init__(self):
        self._host = c.main.cfg_file.vals["RemoteHost"]
        self._user = c.main.cfg_file.vals["RemoteUser"]
        self._port = c.main.cfg_file.vals["Port"]
        self._id_str = self._host
        if self._user:
            self._id_str = self._user + "@" + self._id_str
        self._cmd_str = ["ssh", self._id_str]
        if self._port:
            self._cmd_str.extend(["-p", self._port])

    def connect(self):
        """Start an ssh master connection."""
        runtime_dir = os.path.join(env("XDG_RUNTIME_DIR"), "retain-sync")
        os.makedirs(runtime_dir, exist_ok=True)
        self._cmd_str.extend(["-S", os.path.join(runtime_dir, "%C.sock")])
        ssh_cmd = shell_cmd(self._cmd_str + ["-fNM"])
        try:
            ssh_cmd.wait(20)
        except subprocess.TimeoutExpired:
            err("Error: ssh connection timed out")
            sys.exit(1)
        if ssh_cmd.returncode != 0:
            err("Error: ssh connection failed")
            sys.exit(1)

    def disconnect(self):
        """Stop the ssh master connection."""
        shell_cmd(self._cmd_str + ["-O", "exit"])

    def execute(self, remote_cmd):
        """Run a given command in list form over ssh.

        Args:
            remote_cmd: A list containing the command to execute and all of its
                        parameters.
        Returns:
            A subprocess.Popen object for the command.
        """
        ssh_cmd = shell_cmd(self._cmd_str + ["--"] + remote_cmd)
        try:
            ssh_cmd.wait(10)
        except subprocess.TimeoutExpired:
            err("Error: ssh connection timed out")
            sys.exit(1)
        return ssh_cmd
