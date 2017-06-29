"""A class for the 'initialize' command.

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
import re
import sys
import time
import shutil
import atexit
import sqlite3
import textwrap

from zielen.exceptions import InputError, ServerError, AvailableSpaceError
from zielen.connect import SSHConnection
from zielen.io import rec_clone, symlink_tree, is_unsafe_symlink
from zielen.fs import FilesManager
from zielen.userdata import LocalSyncDir, DestSyncDir
from zielen.profile import Profile, ProfileConfigFile
from zielen.basecommand import Command


class InitializeCommand(Command):
    """Create a new profile for a pair of directories to sync.

    Attributes:
        profile_input: A string representing the selected profile.
        profile: The currently selected profile.
        exclude: The path of a file containing exclude patterns.
        template: The path of a template configuration file.
        add_remote: Start with a set of existing remote files.
        local_dir: A LocalSyncDir object representing the local directory.
        dest_dir: A DestSyncDir object representing the destination directory.
        connection: A Connection object representing the connection to the
            remote directory.
    """
    def __init__(self, profile_input: str, exclude=None, template=None,
                 add_remote=False) -> None:
        super().__init__()
        self.profile_input = profile_input
        self.exclude = exclude
        self.template = template
        self.add_remote = add_remote
        self.local_dir = None
        self.dest_dir = None
        self.connection = None

    def main(self) -> None:
        """Run the command.

        Raises:
            InputError: The command-line arguments were invalid.
            ServerError: The connection to the remote directory was lost.
            AvailableSpaceError: There is not enough space in the local or
                remote filesystem.
        """
        # Define cleanup functions.
        def cleanup_profile() -> None:
            """Remove the profile directory if empty."""
            try:
                os.rmdir(self.profile.path)
            except OSError:
                pass

        def delete_profile() -> None:
            """Delete the profile directory."""
            try:
                shutil.rmtree(self.profile.path)
            except FileNotFoundError:
                pass

        # Check that value of profile name is valid.
        if re.search(r"\s+", self.profile_input):
            raise InputError("profile name must not contain spaces")
        elif not re.search(r"^[\w-]+$", self.profile_input):
            raise InputError(
                "profile name must not contain special symbols")

        # Check the arguments of command-line options.
        if self.exclude:
            if not os.path.isfile(self.exclude):
                raise InputError(
                    "argument for '--exclude' is not a valid file")
        if self.template:
            if not os.path.isfile(self.template):
                raise InputError(
                    "argument for '--template' is not a valid file")

        self.profile = Profile(self.profile_input)
        atexit.register(cleanup_profile)
        try:
            self.profile.read()
        except FileNotFoundError:
            pass

        # Check if the profile has already been initialized.
        if self.profile.status == "initialized":
            raise InputError("this profile already exists")

        # Lock profile if not already locked.
        self.lock()

        # Check whether an interrupted initialization is being resumed.
        if self.profile.status == "partial":
            # Resume an interrupted initialization.
            print("Resuming initialization...\n")
            atexit.register(self.print_interrupt_msg)

            # The user doesn't have to specify the same command-line arguments
            # when they're resuming and initialization.
            self.add_remote = self.profile.add_remote

            self.local_dir = LocalSyncDir(self.profile.local_path)
            if self.profile.remote_host:
                self.dest_dir = DestSyncDir(self.profile.mnt_dir)
                self.connection = SSHConnection(
                    self.profile.remote_host, self.profile.remote_user,
                    self.profile.port, self.profile.remote_path,
                    self.profile.sshfs_options)
            else:
                self.dest_dir = DestSyncDir(self.profile.remote_path)
            fm = FilesManager(self.local_dir, self.dest_dir, self.profile)
        else:
            # Start a new initialization.
            atexit.register(delete_profile)

            # Generate all files in the profile directory.
            self.profile.generate(self.add_remote, self.exclude, self.template)

            self.local_dir = LocalSyncDir(self.profile.local_path)
            if self.profile.remote_host:
                self.dest_dir = DestSyncDir(self.profile.mnt_dir)
                self.connection = SSHConnection(
                    self.profile.remote_host, self.profile.remote_user,
                    self.profile.port, self.profile.remote_path,
                    self.profile.sshfs_options)
                self.connection.check_remote(self.add_remote)
            else:
                self.dest_dir = DestSyncDir(self.profile.remote_path)
            fm = FilesManager(self.local_dir, self.dest_dir, self.profile)

            # The profile is now partially initialized. If the
            # initialization is interrupted from this point, it can be
            # resumed.
            atexit.register(self.print_interrupt_msg)
            atexit.unregister(delete_profile)

        if self.profile.remote_host:
            atexit.register(self.connection.unmount, self.dest_dir.path)
            self.connection.mount(self.dest_dir.path)

        self.dest_dir.generate()

        # Copy files and/or create symlinks.
        if self.add_remote:
            fm.setup_from_remote()
        else:
            fm.setup_from_local()

        # Copy exclude pattern file to remote directory for use when remote dir
        # is shared.
        self.dest_dir.add_exclude_file(self.profile.ex_path, self.profile.id)

        # The profile is now fully initialized. Update the profile.
        if self.profile.remote_host:
            atexit.unregister(self.connection.unmount)
        self.dest_dir.write()
        self.profile.status = "initialized"
        self.profile.last_sync = time.time()
        self.profile.last_adjust = time.time()
        self.profile.write()
        atexit.unregister(self.print_interrupt_msg)

        print(textwrap.dedent("""
            Run the following commands to start the daemon:
            'systemctl --user start zielen@{0}.service'
            'systemctl --user enable zielen@{0}.service'""".format(
                self.profile.name)))
