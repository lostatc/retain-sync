"""A class for the 'empty-trash' command.

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
import atexit

from zielen.exceptions import UserInputError
from zielen.io.userdata import LocalSyncDir, DestSyncDir
from zielen.util.connect import SSHConnection
from zielen.basecommand import Command


class EmptyTrashCommand(Command):
    """Delete all files in the remote directory marked for deletion."""
    def __init__(self, profile_input: str) -> None:
        super().__init__()
        self.profile = self.select_profile(profile_input)
        self.local_dir = None
        self.dest_dir = None
        self.connection = None

    def main(self) -> None:
        """Run the command."""
        self.profile.info_file.read()

        # Lock profile if not already locked.
        self.lock()

        # Warn if profile is only partially initialized.
        if self.profile.info_file.vals["Status"] == "partial":
            atexit.register(self.print_interrupt_msg)
            raise UserInputError("invalid profile")

        self.profile.cfg_file.read()
        self.profile.cfg_file.check_all()

        # TODO: Remove these repetitive assignments.
        self.local_dir = LocalSyncDir(self.profile.cfg_file.vals["LocalDir"])
        if self.profile.cfg_file.vals["RemoteHost"]:
            self.dest_dir = DestSyncDir(self.profile.mnt_dir)
            self.connection = SSHConnection(
                self.profile.cfg_file.vals["RemoteHost"],
                self.profile.cfg_file.vals["RemoteUser"],
                self.profile.cfg_file.vals["Port"],
                self.profile.cfg_file.vals["RemoteDir"],
                self.profile.cfg_file.vals["SshfsOptions"])
            if not os.path.isdir(self.dest_dir.path):
                # Unmount if mountpoint is broken.
                self.connection.unmount(self.dest_dir.path)
            if not os.path.ismount(self.dest_dir.path):
                self.connection.mount(self.dest_dir.path)
        else:
            self.dest_dir = DestSyncDir(
                self.profile.cfg_file.vals["RemoteDir"])

        # Remove files marked for deletion.
        files_deleted = 0
        for rel_path in self.dest_dir.db_file.list_files(deleted=True):
            try:
                os.remove(os.path.join(self.dest_dir.path, rel_path))
            except FileNotFoundError:
                # The file has already been deleted, but the remote database
                # hasn't yet been updated to reflect the change.
                pass
            else:
                files_deleted += 1
        print("{} files deleted".format(files_deleted))
