"""Manage a connection with a remote computer.

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
from abc import ABCMeta, abstractmethod

from zielen.exceptions import ServerError, UserInputError
from zielen.util.misc import env, shell_cmd


class Connection(metaclass=ABCMeta):
    """Initiate a connection with a remote computer over some protocol."""
    @abstractmethod
    def mount(self, mountpoint: str) -> None:
        """Mount a remote directory in the local filesystem.

        Args:
            mountpoint: The path of the local directory on which to mount.

        Raises:
            ServerError:    The connection timed out or the mount otherwise
                            failed.
        """

    @abstractmethod
    def unmount(self, mountpoint: str) -> None:
        """Unmount a remote directory from the local filesystem.

        Args:
            mountpoint: The path of the local directory from which to unmount.

        Raises:
            ServerError:    The unmount failed.
        """

    @abstractmethod
    def check_remote(self, add_remote: bool) -> None:
        """Check the validity of the remote directory.

        Args:
            add_remote: The remote directory must exist and doesn't have to
                        be empty.

        Raises:
            UserInputError: The remote directory is invalid.
        """


class SSHConnection(Connection):
    """Initiate a connection with a remote computer over ssh."""
    def __init__(self, host: str, user: str, port: str, remote_dir: str,
                 mnt_opts: str) -> None:
        self._host = host
        self._user = user
        self._port = port
        self._remote_dir = remote_dir
        self._mnt_opts = mnt_opts

        self._id_str = user + "@" + host if user else host
        self._ssh_args = ["ssh", self._id_str]
        if self._port:
            self._ssh_args.extend(["-p", self._port])

        self._runtime_dir = os.path.join(env("XDG_RUNTIME_DIR"), "zielen")
        self._guess_env()

    def check_remote(self, add_remote: bool) -> None:
        """Check the validity of the remote directory over ssh.

        Args:
            add_remote: The remote directory must exist and doesn't have to
                        be empty.

        Raises:
            UserInputError: The remote directory is invalid.
        """
        # Initiate a master connection if not already connected.
        if "-S" not in self._ssh_args:
            self._connect()

        if self._check_exists():
            if self._check_isdir():
                if not self._check_iswritable():
                    raise UserInputError(
                        "remote directory must be writable")
                elif not add_remote and not self._check_isempty():
                    raise UserInputError(
                        "remote directory must be empty")
            else:
                raise UserInputError(
                    "remote directory must be a directory")
        else:
            if add_remote:
                raise UserInputError(
                    "remote directory must be an existing directory")
            elif not self._mkdir():
                raise UserInputError(
                    "remote directory must be writable")

    def mount(self, mountpoint: str) -> None:
        """Mount remote directory using sshfs.

        Args:
            mountpoint: The path of the local directory on which to mount.

        Raises:
            ServerError:    The connection timed out or the mount otherwise
                            failed.
        """
        sshfs_args = [
            "sshfs", self._id_str + ":" + self._remote_dir, mountpoint]
        if self._port:
            sshfs_args.extend(["-p", self._port])
        if self._mnt_opts:
            sshfs_args.extend(["-o", self._mnt_opts])

        # Create mountpoint and mount.
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
                + indent("\n".join(stderr.splitlines()[-3:]), "    "))

    def unmount(self, mountpoint: str) -> None:
        """Unmount the remote directory.

        Args:
            mountpoint: The path of the local directory from which to unmount.

        Raises:
            ServerError:    The unmount failed.
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
                    + indent("\n".join(stderr.splitlines()[-3:]), "    "))

    @staticmethod
    def _guess_env() -> bool:
        """Guess environment variables for ssh-agent."""
        if not os.environ["SSH_AUTH_SOCK"]:
            # Search for ssh-agent auth socket in it's default location.
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

    def _connect(self) -> None:
        """Start an ssh master connection and stop on program exit."""
        os.makedirs(self._runtime_dir, exist_ok=True)
        self._ssh_args.extend(["-S", os.path.join(self._runtime_dir, "%C")])
        shell_cmd(self._ssh_args + ["-NM"])

    def _execute(self, remote_cmd: list) -> subprocess.Popen:
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

    def _check_exists(self) -> bool:
        """Check if the remote directory exists."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self._execute(["[[", "-e", remote_dir, "]]"])
        return not bool(cmd.returncode)

    def _check_isdir(self) -> bool:
        """Check if the remote directory is actually a directory."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self._execute(["[[", "-d", remote_dir, "]]"])
        return not bool(cmd.returncode)

    def _check_iswritable(self) -> bool:
        """Check if the remote directory is writable."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self._execute(["[[", "-w", remote_dir, "]]"])
        return not bool(cmd.returncode)

    def _check_isempty(self) -> bool:
        """Check if the remote directory is empty."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self._execute([
            "[[", "-n", "$(find", remote_dir, "-prune", "-empty)", "]]"
            ])
        return not bool(cmd.returncode)

    def _mkdir(self) -> bool:
        """Create the remote directory if it doesn't already exist."""
        remote_dir = shlex.quote(self._remote_dir)
        cmd = self._execute(["mkdir", "-p", remote_dir])
        return not bool(cmd.returncode)
