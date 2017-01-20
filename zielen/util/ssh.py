"""Manage an ssh connection.

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
import shlex
import subprocess
import re
import stat
import tempfile
from textwrap import indent

from zielen.exceptions import ServerError
from zielen.util.misc import env, shell_cmd


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
        runtime_dir = os.path.join(env("XDG_RUNTIME_DIR"), "zielen")
        os.makedirs(runtime_dir, exist_ok=True)
        self._ssh_args.extend(["-S", os.path.join(runtime_dir, "%C")])
        shell_cmd(self._ssh_args + ["-NM"])

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

        Raises:
            ServerError:    The ssh connection timed out.
        """
        ssh_cmd = shell_cmd(self._ssh_args + ["--"] + remote_cmd)
        try:
            ssh_cmd.wait(timeout=20)
        except subprocess.TimeoutExpired:
            raise ServerError("ssh connection timed out")
        return ssh_cmd

    def mount(self, mountpoint: str) -> None:
        """Mount remote directory using sshfs.

        Args:
            mountpoint: The local sshfs mount point.

        Raises:
            ServerError:    The connection timed out or the mount otherwise
                            failed.
        """
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
            raise ServerError("ssh connection timed out")
        if sshfs_cmd.returncode != 0:
            # Print the last three lines of stderr.
            raise ServerError(
                "failed to mount remote directory over ssh\n"
                + indent("\n".join(stderr.splitlines()[-3:]), "    ")
                )

    def unmount(self, mountpoint: str) -> None:
        """Unmount remote directory.

        Args:
            mountpoint: The local sshfs mount point.

        Raises:
            ServerError:    The connection timed out or the unmount otherwise
                            failed.
        """
        if os.path.ismount(mountpoint):
            unmount_cmd = shell_cmd(["fusermount", "-u", mountpoint])
            try:
                stdout, stderr = unmount_cmd.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                raise ServerError("timed out unmounting remote directory")
            if unmount_cmd.returncode != 0:
                # Print the last three lines of stderr.
                raise ServerError(
                    "failed to unmount remote directory\n"
                    + indent("\n".join(stderr.splitlines()[-3:]), "    ")
                    )

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


def ssh_env() -> bool:
    """Guess environment variables for ssh-agent."""
    if not os.environ["SSH_AUTH_SOCK"]:
        # Search for ssh-agent socket in it's default location.
        for entry in os.scandir(tempfile.gettempdir()):
            if (re.search("^ssh-", entry.name)
                    and entry.is_dir
                    and entry.stat().st_uid == os.getuid()):
                for subentry in os.scandir(entry.path):
                    if (re.search(r"^agent\.[0-9]+$", subentry.name)
                            and stat.S_ISSOCK(subentry.stat().st_mode)
                            and subentry.stat().st_uid == os.getuid()):
                        os.environ["SSH_AUTH_SOCK"] = subentry.path
                        return True
        return False
    else:
        return True
