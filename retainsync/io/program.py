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
import shlex
import subprocess
from textwrap import indent
from typing import List

from retainsync.util.misc import err, env, shell_cmd


class NotMountedError(Exception):
    """Raised when file IO occurs on the remote mountpoint while unmounted."""


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
        # try:
        with open(self.path) as file:
            for line in file:
                # Skip line if it is a comment.
                if (not self.comment_reg.search(line)
                        and re.search("=", line)):
                    key, value = line.partition("=")[::2]
                    self.raw_vals[key.strip()] = value.strip()
        # except IOError:
        #     err("Error: could not open configuration file")
        #     sys.exit(1)

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

        except IOError:
            err("Error: could not open configuration file")
            sys.exit(1)


class JSONFile:
    """Parse a JSON-formatted file.

    Attributes:
        path:  The path to the JSON file.
        vals:  A dictionary or list of values from the file.
    """
    def __init__(self, path) -> None:
        self.path = path
        self.vals = None

    def read(self) -> None:
        """Read file into an object."""
        with open(self.path) as file:
            self.vals = json.load(file)

    def write(self) -> None:
        """Write object to a file."""
        with open(self.path, "w") as file:
            json.dump(self.vals, file, indent=4)


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
        for entry in os.scandir(cls.path):
            if entry.is_dir(follow_symlinks=False):
                profile_names.append(entry.name)
        return profile_names


class SSHConnection:
    """Run commands over ssh."""
    def __init__(self, host: str, remote_dir: str, opts: str, user: str,
                 port: str) -> None:
        self._host = host
        self._remote_dir = remote_dir
        self._mount_opts = opts
        self._user = user
        self._port = port

        self._id_str = self._host
        if self._user:
            self._id_str = self._user + "@" + self._id_str

        self._ssh_args = ["ssh", self._id_str]
        if self._port:
            self._ssh_args.extend(["-p", self._port])

    def connect(self) -> None:
        """Start an ssh master connection."""
        runtime_dir = os.path.join(env("XDG_RUNTIME_DIR"), "retain-sync")
        os.makedirs(runtime_dir, exist_ok=True)
        self._ssh_args.extend(["-S", os.path.join(runtime_dir, "%C")])
        ssh_cmd = shell_cmd(self._ssh_args + ["-NM"])

    def disconnect(self) -> None:
        """Stop the ssh master connection."""
        ssh_cmd = shell_cmd(self._cmd_str + ["-O", "exit"])
        try:
            ssh_cmd.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass

    def execute(self, remote_cmd: list) -> subprocess.Popen:
        """Run a given command in list form over ssh.

        Args:
            remote_cmd: A list containing the command to execute and all of its
                        parameters.
        Returns:
            A subprocess.Popen object for the command.
        """
        ssh_cmd = shell_cmd(self._ssh_args + ["--"] + remote_cmd)
        try:
            ssh_cmd.wait(timeout=20)
        except subprocess.TimeoutExpired:
            err("Error: ssh connection timed out")
            sys.exit(1)
        return ssh_cmd

    def mount(self, mountpoint: str) -> None:
        """Mount remote directory using sshfs."""
        sshfs_args = [
            "sshfs", self._id_str + ":" + self._remote_dir, mountpoint]
        if self._port:
            sshfs_args.extend(["-p", self._port])
        if self._mount_opts:
            sshfs_args.extend(["-o", self._mount_opts])

        os.makedirs(mountpoint, exist_ok=True)
        sshfs_cmd = shell_cmd(sshfs_args)

        try:
            stdout, stderr = sshfs_cmd.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            err("Error: ssh connection timed out")
            sys.exit(1)
        if sshfs_cmd.returncode != 0:
            err("Error: failed to mount remote directory over ssh")
            # Print the last three lines of stderr.
            print(indent("\n".join(stderr.splitlines()[-3:]), "    "))
            sys.exit(1)

    def unmount(self, mountpoint: str) -> None:
        """Unmount remote directory."""
        if os.path.ismount(mountpoint):
            unmount_cmd = shell_cmd(["fusermount", "-u", mountpoint])
            try:
                stdout, stderr = unmount_cmd.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                err("Error: timed out unmounting remote directory")
                sys.exit(1)
            if unmount_cmd.returncode != 0:
                err("Error: failed to unmount remote directory")
                # Print the last three lines of stderr.
                print(indent("\n".join(stderr.splitlines()[-3:]), "    "))
                sys.exit(1)

    def check_exists(self) -> bool:
        """Check if the remote directory exists."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self.execute(["[[", "-e", remote_dir, "]]"])
        return not bool(cmd.returncode)

    def check_isdir(self) -> bool:
        """Check if the remote directory is actually a directory."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self.execute(["[[", "-d", remote_dir, "]]"])
        return not bool(cmd.returncode)

    def check_iswritable(self) -> bool:
        """Check if the remote directory is writable."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self.execute(["[[", "-w", remote_dir, "]]"])
        return not bool(cmd.returncode)

    def check_isempty(self) -> bool:
        """Check if the remote directory is empty."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self.execute(["[[", "!", "-s", remote_dir, "]]"])
        return not bool(cmd.returncode)

    def mkdir(self) -> bool:
        """Create the remote direcory if it doesn't already exist."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self.execute(["mkdir", "-p", remote_dir])
        return not bool(cmd.returncode)
