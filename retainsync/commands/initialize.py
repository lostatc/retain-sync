"""A class for the 'initialize' command.

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

import os
import sys
import re
import atexit
import shutil
import sqlite3
from textwrap import dedent

from retainsync.exceptions import (
    UserInputError, ServerError, AvailableSpaceError)
from retainsync.basecommand import Command
from retainsync.io.profile import Profile, ProfileConfigFile
from retainsync.io.userdata import LocalSyncDir, DestSyncDir
from retainsync.io.transfer import rsync_cmd
from retainsync.util.ssh import SSHConnection


class InitializeCommand(Command):
    """Create a new profile for a pair of directories to sync."""
    def __init__(self, profile_input: str, exclude=None, template=None,
                 add_remote=False) -> None:
        """
        Args:
            profile_input:  A string representing the selected profile.
            profile:        A Profile object for the selected profile.
            exclude:        The path to a file containing exclude patterns.
            template:       The path to a template configuration file.
            add_remote:     Start with a set of existing remote files.
        """
        super().__init__()
        self.profile_input = profile_input
        self.profile = None
        self.exclude = exclude
        self.template = template
        self.add_remote = add_remote

    def main(self) -> None:
        """Run the command.

        Raises:
            UserInputError:         The command-line arguments were invalid.
            ServerError:            The connection to the remote directory was
                                    lost.
            AvailableSpaceError:    There is not enough space in the local or
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
            atexit.register(self.interrupt_msg)

            self.profile.cfg_file.read()
            self.profile.cfg_file.check_all()

            # The user doesn't have to specify the same command-line arguments
            # when they're resuming and initialization.
            self.add_remote = (
                self.profile.info_file.vals["InitOpts"]["add_remote"])

            local_dir = LocalSyncDir(self.profile.cfg_file.vals["LocalDir"])
            if self.profile.cfg_file.vals["RemoteHost"]:
                dest_dir = DestSyncDir(self.profile.mnt_dir)
                ssh_conn = SSHConnection(
                    self.profile.cfg_file.vals["RemoteHost"],
                    self.profile.cfg_file.vals["RemoteDir"],
                    self.profile.cfg_file.vals["SshfsOptions"],
                    self.profile.cfg_file.vals["RemoteUser"],
                    self.profile.cfg_file.vals["Port"])
                if not self.add_remote:
                    if not ssh_conn.mkdir():
                        raise ServerError(
                            "failed creating the remote directory")
            else:
                dest_dir = DestSyncDir(self.profile.cfg_file.vals["RemoteDir"])
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
            self.profile.cfg_file.check_all()

            # Write config values to file.
            if self.template:
                self.profile.cfg_file.write(self.template)
            else:
                # TODO: Get the path to the master config template from
                # setup.py instead of hardcoding it.
                self.profile.cfg_file.write(os.path.join(
                    sys.prefix, "share/retain-sync/config-template"))

            local_dir = LocalSyncDir(self.profile.cfg_file.vals["LocalDir"])
            if self.profile.cfg_file.vals["RemoteHost"]:
                dest_dir = DestSyncDir(self.profile.mnt_dir)
                ssh_conn = SSHConnection(
                    self.profile.cfg_file.vals["RemoteHost"],
                    self.profile.cfg_file.vals["RemoteDir"],
                    self.profile.cfg_file.vals["SshfsOptions"],
                    self.profile.cfg_file.vals["RemoteUser"],
                    self.profile.cfg_file.vals["Port"])
                ssh_conn.connect()
                if ssh_conn.check_exists():
                    if ssh_conn.check_isdir():
                        if not ssh_conn.check_iswritable():
                            raise UserInputError(
                                "remote directory must be writable")
                        elif (not self.add_remote
                                and not ssh_conn.check_isempty()):
                            raise UserInputError(
                                "remote directory must be empty")
                    else:
                        raise UserInputError(
                            "remote directory must be a directory")
                else:
                    if self.add_remote:
                        raise UserInputError(
                            "remote directory must be an existing directory")
                    elif not ssh_conn.mkdir():
                        raise UserInputError(
                            "remote directory must be writable")
            else:
                dest_dir = DestSyncDir(self.profile.cfg_file.vals["RemoteDir"])

            # Generate the exclude pattern file.
            self.profile.ex_file.generate(self.exclude)

            # The profile is now partially initialized. If the initilization is
            # interrupted from this point, it can be resumed.
            self.profile.info_file.generate(
                self.profile.name, add_remote=self.add_remote)
            atexit.register(self.interrupt_msg)
            atexit.unregister(delete_profile)

        if self.profile.cfg_file.vals["RemoteHost"]:
            atexit.register(ssh_conn.unmount, dest_dir.path)
            ssh_conn.mount(dest_dir.path)

        os.makedirs(dest_dir.ex_dir, exist_ok=True)
        user_symlinks = set(local_dir.list_files(
            rel=True, files=False, symlinks=True))

        if self.add_remote:
            try:
                # Expand exclude globbing patterns.
                self.profile.ex_file.glob(dest_dir.safe_path)
            except FileNotFoundError:
                raise ServerError(
                    "the connection to the remote directory was lost")

            # Check that there is enough local space to accomodate remote
            # files.
            if dest_dir.total_size() > local_dir.space_avail():
                raise AvailableSpaceError(
                    "not enough local space to accomodate remote files")
        else:
            # Expand exclude globbing patterns.
            self.profile.ex_file.glob(local_dir.path)

            # Check that there is enough remote space to accomodate local
            # files.
            if local_dir.total_size() > dest_dir.space_avail():
                raise AvailableSpaceError(
                    "not enough space in remote to accomodate local files")

            # Copy local files to the server.
            try:
                rsync_cmd(
                    ["-asHAXS", local_dir.tpath, dest_dir.safe_path],
                    exclude=self.profile.ex_file.rel_files | user_symlinks,
                    msg="Moving files to remote...")
            except FileNotFoundError:
                raise ServerError(
                    "the connection to the remote directory was lost")

        # Overwrite local files with symlinks to the corresponding files in the
        # remote dir.
        dest_dir.symlink_tree(local_dir.path, overwrite=True)

        remote_files = list(dest_dir.list_files(rel=True))

        # Generate the local file priority database.
        if not os.path.isfile(self.profile.db_file.path):
            self.profile.db_file.create()
        self.profile.db_file.add_files(remote_files)

        # Generate the remote file priority database.
        try:
            if not os.path.isfile(dest_dir.db_file.path):
                dest_dir.db_file.create()
            dest_dir.db_file.add_files(remote_files)
        except sqlite3.OperationalError:
            raise ServerError(
                "the connection to the remote directory was lost")

        # Copy exclude pattern file to remote directory for use when remote dir
        # is shared.
        try:
            shutil.copy(self.profile.ex_file.path, os.path.join(
                dest_dir.ex_dir, self.profile.info_file.vals["ID"]))
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")

        # The profile is now fully initialized. Update the info file.
        self.profile.info_file.raw_vals["Status"] = "initialized"
        self.profile.info_file.update_synctime()
        self.profile.info_file.write()
        atexit.unregister(ssh_conn.unmount, dest_dir.path)
        atexit.unregister(self.interrupt_msg)

        # Advise user to start/enable the daemon.
        print(dedent("""
            Run 'systemctl --user start retain-sync@{0}.service' to start the daemon.
            Run 'systemctl --user enable retain-sync@{0}.service' to start the daemon
            automatically on login.""".format(self.profile.name)))
