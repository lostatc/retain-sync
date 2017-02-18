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
import sys
import re
import atexit
import shutil
import sqlite3
from textwrap import dedent

from zielen.exceptions import (
    UserInputError, ServerError, AvailableSpaceError)
from zielen.basecommand import Command
from zielen.io.profile import Profile, ProfileConfigFile
from zielen.io.userdata import LocalSyncDir, DestSyncDir
from zielen.io.transfer import rclone
from zielen.util.connect import SSHConnection


class InitializeCommand(Command):
    """Create a new profile for a pair of directories to sync.

    Attributes:
        profile_input: A string representing the selected profile.
        profile: The currently selected profile.
        exclude: The path to a file containing exclude patterns.
        template: The path to a template configuration file.
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
            UserInputError: The command-line arguments were invalid.
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
            raise UserInputError("profile name must not contain spaces")
        elif not re.search(r"^[a-zA-Z0-9_-]+$", self.profile_input):
            raise UserInputError(
                "profile name must not contain special symbols")

        # Check the arguments of command-line options.
        if self.exclude:
            if not os.path.isfile(self.exclude):
                raise UserInputError(
                    "argument for '--exclude' is not a valid file")
        if self.template:
            if not os.path.isfile(self.template):
                raise UserInputError(
                    "argument for '--template' is not a valid file")

        self.profile = Profile(self.profile_input)
        atexit.register(cleanup_profile)
        if os.path.isfile(self.profile.info_file.path):
            self.profile.info_file.read()

        # Check if the profile has already been initialized.
        if self.profile.info_file.vals["Status"] == "initialized":
            raise UserInputError("this profile already exists")

        # Lock profile if not already locked.
        self.lock()

        # Check whether an interrupted initialization is being resumed.
        if self.profile.info_file.vals["Status"] == "partial":
            # Resume an interrupted initialization.
            print("Resuming initialization...\n")
            atexit.register(self.print_interrupt_msg)

            self.profile.cfg_file.read()
            self.profile.cfg_file.check_all()

            # The user doesn't have to specify the same command-line arguments
            # when they're resuming and initialization.
            self.add_remote = (
                self.profile.info_file.vals["InitOpts"]["add_remote"])

            # TODO: Remove these repetitive assignments.
            self.local_dir = LocalSyncDir(
                self.profile.cfg_file.vals["LocalDir"])
            if self.profile.cfg_file.vals["RemoteHost"]:
                self.dest_dir = DestSyncDir(self.profile.mnt_dir)
                self.connection = SSHConnection(
                    self.profile.cfg_file.vals["RemoteHost"],
                    self.profile.cfg_file.vals["RemoteUser"],
                    self.profile.cfg_file.vals["Port"],
                    self.profile.cfg_file.vals["RemoteDir"],
                    self.profile.cfg_file.vals["SshfsOptions"])
            else:
                self.dest_dir = DestSyncDir(
                    self.profile.cfg_file.vals["RemoteDir"])
        else:
            # Start a new initialization.
            atexit.register(delete_profile)

            # Parse template file if one was given.
            if self.template:
                template_file = ProfileConfigFile(
                    self.template, add_remote=self.add_remote)
                template_file.read()
                template_file.check_all(
                    check_empty=False, context="template file")
                self.profile.cfg_file.raw_vals = template_file.raw_vals

            # Prompt user interactively for unset config values.
            self.profile.cfg_file.add_remote = self.add_remote
            self.profile.cfg_file.prompt()
            # This final check is necessary for cases where a template was used
            # that contained values dependent on other unspecified values for
            # validity checking (e.g. 'RemoteDir' and 'RemoteHost').
            if self.template:
                self.profile.cfg_file.check_all(context="template file")

            # Write config values to file.
            if self.template:
                self.profile.cfg_file.write(self.template)
            else:
                # TODO: Get the path to the master config template from
                # setup.py instead of hardcoding it.
                self.profile.cfg_file.write(os.path.join(
                    sys.prefix, "share/zielen/config-template"))

            # TODO: Remove these repetitive assignments.
            self.local_dir = LocalSyncDir(
                self.profile.cfg_file.vals["LocalDir"])
            if self.profile.cfg_file.vals["RemoteHost"]:
                self.dest_dir = DestSyncDir(self.profile.mnt_dir)
                self.connection = SSHConnection(
                    self.profile.cfg_file.vals["RemoteHost"],
                    self.profile.cfg_file.vals["RemoteUser"],
                    self.profile.cfg_file.vals["Port"],
                    self.profile.cfg_file.vals["RemoteDir"],
                    self.profile.cfg_file.vals["SshfsOptions"])
                self.connection.check_remote(self.add_remote)
            else:
                self.dest_dir = DestSyncDir(
                    self.profile.cfg_file.vals["RemoteDir"])

            # Generate the exclude pattern file.
            self.profile.ex_file.generate(self.exclude)

            # The profile is now partially initialized. If the
            # initialization is interrupted from this point, it can be
            # resumed.
            self.profile.info_file.generate(
                self.profile.name, add_remote=self.add_remote)
            atexit.register(self.print_interrupt_msg)
            atexit.unregister(delete_profile)

        self._setup_remote()

        # The profile is now fully initialized. Update the info file.
        if self.profile.cfg_file.vals["RemoteHost"]:
            atexit.unregister(self.connection.unmount)
        self.profile.info_file.raw_vals["Status"] = "initialized"
        self.profile.info_file.update_synctime()
        self.profile.info_file.update_adjusttime()
        self.profile.info_file.write()
        atexit.unregister(self.print_interrupt_msg)

        # Advise user to start/enable the daemon.
        print(dedent("""
            Run 'systemctl --user start zielen@{0}.service' to start the daemon.
            Run 'systemctl --user enable zielen@{0}.service' to start the daemon
            automatically on login.""".format(self.profile.name)))

    def _setup_remote(self):
        """Set up the remote directory and transfer files."""
        if self.profile.cfg_file.vals["RemoteHost"]:
            atexit.register(self.connection.unmount, self.dest_dir.path)
            self.connection.mount(self.dest_dir.path)

        os.makedirs(self.dest_dir.ex_dir, exist_ok=True)
        user_symlinks = set(self.local_dir.list_files(
            rel=True, files=False, symlinks=True))

        if self.add_remote:
            try:
                # Expand exclude globbing patterns.
                self.profile.ex_file.glob(self.dest_dir.safe_path)
            except FileNotFoundError:
                raise ServerError(
                    "the connection to the remote directory was lost")

            # Check that there is enough local space to accommodate remote
            # files.
            if self.dest_dir.total_size() > self.local_dir.space_avail():
                raise AvailableSpaceError(
                    "not enough local space to accommodate remote files")
        else:
            # Expand exclude globbing patterns.
            self.profile.ex_file.glob(self.local_dir.path)

            # Check that there is enough remote space to accommodate local
            # files.
            if self.local_dir.total_size() > self.dest_dir.space_avail():
                raise AvailableSpaceError(
                    "not enough space in remote to accommodate local files")

            # Copy local files to the server.
            try:
                rclone(
                    self.local_dir.path, self.dest_dir.safe_path,
                    exclude=self.profile.ex_file.rel_files | user_symlinks,
                    msg="Moving files to remote...")
            except FileNotFoundError:
                raise ServerError(
                    "the connection to the remote directory was lost")

        remote_files = set(self.dest_dir.list_files(rel=True))

        # Generate the local file priority database.
        if not os.path.isfile(self.profile.db_file.path):
            self.profile.db_file.create()
        self.profile.db_file.add_files(remote_files)

        # Generate the remote file priority database.
        try:
            if not os.path.isfile(self.dest_dir.db_file.path):
                self.dest_dir.db_file.create()
            self.dest_dir.db_file.add_files(remote_files)
        except sqlite3.OperationalError:
            raise ServerError(
                "the connection to the remote directory was lost")

        # Overwrite local files with symlinks to the corresponding files in the
        # remote dir.
        self.dest_dir.symlink_tree(
            self.local_dir.path,
            exclude=self.dest_dir.db_file.list_files(deleted=True),
            overwrite=True)

        # Copy exclude pattern file to remote directory for use when remote dir
        # is shared.
        try:
            shutil.copy(self.profile.ex_file.path, os.path.join(
                self.dest_dir.ex_dir, self.profile.info_file.vals["ID"]))
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")
