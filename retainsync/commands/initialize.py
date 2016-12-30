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
from textwrap import dedent

from retainsync.cmd_base import Command
from retainsync.io.program import SSHConnection, NotMountedError
from retainsync.io.profile import Profile, ProfileConfigFile
from retainsync.io.sync import LocalSyncDir, DestSyncDir
from retainsync.io.transfer import rsync_cmd
from retainsync.util.misc import err


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
        """Run the command."""
        # Define cleanup functions.
        def cleanup_profile() -> None:
            """Remove the profile directory if empty."""
            try:
                os.rmdir(self.profile.path)
            except (FileNotFoundError, OSError):
                pass

        def delete_profile() -> None:
            """Delete the profile directory."""
            try:
                shutil.rmtree(self.profile.path)
            except FileNotFoundError:
                pass

        def unmount_sshfs() -> None:
            """Unmount the sshfs mount."""
            ssh_conn.unmount(dest_dir.path)

        # Check that value of profile name is valid.
        if re.search(r"\s+", self.profile_input):
            err("Error: profile name must not contain spaces")
            sys.exit(1)
        elif not re.search(r"^[a-zA-Z0-9_-]+$", self.profile_input):
            err("Error: profile name must not contain special symbols")
            sys.exit(1)

        # Check the arguments of command-line options.
        if self.exclude:
            if self.exclude != "-" \
                    and not os.path.isfile(self.exclude):
                err("Error: argument for '--exclude' is not a valid file")
                sys.exit(1)
        if self.template:
            if not os.path.isfile(self.template):
                err("Error: argument for '--template' is not a valid file")
                sys.exit(1)

        self.profile = Profile(self.profile_input)
        atexit.register(cleanup_profile)
        self.profile.info_file.read()

        # Check if the profile has already been initialized.
        if self.profile.info_file.vals["Status"] == "initialized":
            err("Error: this profile already exists")
            sys.exit(1)

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
                        err("Error: failed creating the remote directory")
                        sys.exit(1)

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

            # Write config values to file.
            # TODO: Get the path to the master config template from setup.py
            # instead of hardcoding it.
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
                if not self.add_remote:
                    if not ssh_conn.mkdir():
                        err("Error: failed creating the remote directory")
                        sys.exit(1)

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
            atexit.register(unmount_sshfs)
            ssh_conn.mount(dest_dir.path)

        try:
            os.makedirs(dest_dir.ex_dir, exist_ok=True)
        except PermissionError:
            err("Error: remote directory must be writable")
            sys.exit(1)

        user_symlinks = set(local_dir.list_symlinks(rel=True))

        if self.add_remote:
            try:
                # Expand exclude globbing patterns.
                self.profile.ex_file.glob(dest_dir.safe_path)
            except FileNotFoundError:
                raise NotMountedError

            # Check that there is enough local space to accomodate remote
            # files.
            if dest_dir.total_size() > local_dir.space_avail():
                err("Error: not enough local space to accomodate remote files")
                sys.exit(1)
        else:
            # Expand exclude globbing patterns.
            self.profile.ex_file.glob(local_dir.path)

            # Check that there is enough remote space to accomodate local
            # files.
            if local_dir.total_size() > dest_dir.space_avail():
                err("Error: not enough space in remote to accomodate local "
                    "files")
                sys.exit(1)

            # Copy local files to the server.
            try:
                rsync_cmd(
                    ["-asHAXS", local_dir.tpath, dest_dir.safe_path],
                    exclude=self.profile.ex_file.rel_files | user_symlinks,
                    msg="Moving files to remote...")
            except FileNotFoundError:
                raise NotMountedError

        # Overwrite local files with symlinks to the corresponding files in the
        # remote dir.
        dest_dir.symlink_tree(local_dir.path, True)

        # Generate file priority database.
        if not os.path.isfile(self.profile.db_file.path):
            self.profile.db_file.create()
        for filepath in dest_dir.list_files(rel=True):
            self.profile.db_file.add_file(filepath)

        # Copy exclude pattern file to remote directory for use when remote dir
        # is shared.
        try:
            shutil.copy(self.profile.ex_file.path, os.path.join(
                dest_dir.ex_dir, self.profile.info_file.vals["ID"]))
        except FileNotFoundError:
            raise NotMountedError

        # The profile is now fully initialized. Update the info file.
        self.profile.info_file.vals["Status"] = "initialized"
        self.profile.info_file.update_synctime()
        self.profile.info_file.write()
        atexit.unregister(unmount_sshfs)
        atexit.unregister(self.interrupt_msg)

        # Advise user to start/enable the daemon.
        print(dedent("""
            Run 'systemctl --user start retain-sync@{0}.service' to start the daemon.
            Run 'systemctl --user enable retain-sync@{0}.service' to start the daemon
            automatically on login""".format(self.profile.name)))
