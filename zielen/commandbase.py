"""Base class for program commands.

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
import abc
import atexit
import os
import socket
import sys
import textwrap


from zielen import PROFILES_DIR
from zielen.userdata import LocalSyncDir, DestSyncDir
from zielen.connect import SSHConnection
from zielen.profile import Profile
from zielen.exceptions import InputError, StatusError


class Command(abc.ABC):
    """Base class for program commands.

    Attributes:
        profiles: A dictionary of Profile instances.
        profile: The currently selected profile.
        local_dir: A LocalSyncDir object representing the local directory.
        dest_dir: A DestSyncDir object representing the destination directory.
        connection: A Connection object representing the remote connection.
        _lock_socket: A unix domain socket used for locking a profile.
    """
    def __init__(self) -> None:
        os.makedirs(PROFILES_DIR, exist_ok=True)
        self.profiles = {
            entry.name: Profile(entry.name)
            for entry in os.scandir(PROFILES_DIR)
            if entry.is_dir(follow_symlinks=False)}
        self.profile = None
        self.local_dir = None
        self.dest_dir = None
        self.connection = None
        self._lock_socket = None

    @abc.abstractmethod
    def main(self) -> None:
        """Run the command."""

    def select_profile(self, input_str: str) -> Profile:
        """Select the proper profile based on a name or local dir path.

        Returns:
            A Profile object for the selected profile.

        Raises:
            InputError: The input doesn't refer to any profile.
        """
        # Check if input is the name of an existing profile.
        if input_str in self.profiles:
            return self.profiles[input_str]
        # Check if input is the path of an initialized directory.
        input_path = os.path.abspath(input_str)
        if os.path.exists(input_path):
            for name, profile in self.profiles.items():
                if not profile.cfg.raw_vals:
                    profile.cfg.read()
                if os.path.samefile(
                        input_path, profile.cfg.vals["LocalDir"]):
                    return profile
        raise InputError(
            "argument is not a profile name or local directory path")

    def setup_profile(self):
        """Perform some initial setup and assignments.

        Raises:
            InputError: The selected profile is only partially initialized.
        """
        self.profile.read()
        self.lock()

        # Warn if profile is only partially initialized.
        if self.profile.status == "partial":
            atexit.register(self.print_interrupt_msg)
            raise InputError("invalid profile")

        self.local_dir = LocalSyncDir(self.profile.local_path)
        if self.profile.remote_host:
            self.connection = SSHConnection(
                self.profile.remote_host, self.profile.remote_user,
                self.profile.port, self.profile.remote_path,
                self.profile.sshfs_options)
            if not os.path.isdir(self.profile.mnt_dir):
                # Unmount if mountpoint is broken.
                self.connection.unmount(self.profile.mnt_dir)
            if not os.path.ismount(self.profile.mnt_dir):
                self.connection.mount(self.profile.mnt_dir)
            self.dest_dir = DestSyncDir(self.profile.mnt_dir)
        else:
            self.dest_dir = DestSyncDir(self.profile.remote_path)

    def lock(self) -> None:
        """Lock the profile if not already locked.

        This prevents multiple operations from running on the same profile at
        the same time. The lock is released automatically whenever the program
        exits, even via SIGKILL.

        Raises:
            StatusError: The program is already locked for this profile.
        """
        self._lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            # We can't use the profile ID here because during
            # initialization, the info file hasn't been generated yet.
            instance_id = "-".join([
                "zielen", str(os.getuid()), self.profile.name])
            self._lock_socket.bind("\0" + instance_id)
        except socket.error:
            raise StatusError(
                "another operation on this profile is already taking place")

    @staticmethod
    def print_interrupt_msg() -> None:
        """Warn the user that the profile is only partially initialized."""
        print(
            "Initialization was interrupted.\nPlease run 'zielen init' to "
            "complete it or 'zielen reset' to cancel it.", file=sys.stderr)
