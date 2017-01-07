"""A class for the 'sync' command.

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
import shutil
import datetime

from retainsync.exceptions import UserInputError, ServerError
from retainsync.basecommand import Command
from retainsync.util.ssh import SSHConnection, ssh_env
from retainsync.io.userdata import TrashDir, LocalSyncDir, DestSyncDir


class SyncCommand(Command):
    """Redistribute files between the local and remote directories."""
    def __init__(self, profile_input: str) -> None:
        super().__init__()
        self.profile = self.select_profile(profile_input)

    def main(self) -> None:
        """Run the command.

        Raises:
            UserInputError: The specified profile has already been initialized.
            ServerError:    The connection to the remote directory was lost.
        """
        self.profile.info_file.read()

        # Lock profile if not already locked.
        self.lock()

        # Warn if profile is only partially initialized.
        if self.profile.info_file.vals["Status"] == "partial":
            self.interrupt_msg()
            raise UserInputError

        self.profile.cfg_file.read()
        self.profile.cfg_file.check_all()

        local_dir = LocalSyncDir(self.profile.cfg_file.vals["LocalDir"])
        if self.profile.cfg_file.vals["RemoteHost"]:
            dest_dir = DestSyncDir(self.profile.mnt_dir)
            ssh_env()
            ssh_conn = SSHConnection(
                self.profile.cfg_file.vals["RemoteHost"],
                self.profile.cfg_file.vals["RemoteDir"],
                self.profile.cfg_file.vals["SshfsOptions"],
                self.profile.cfg_file.vals["RemoteUser"],
                self.profile.cfg_file.vals["Port"])
            if not os.isdir(dest_dir.path):
                # Unmount if mountpoint is broken.
                ssh_conn.unmount(dest_dir.path)
            if not os.ismount(dest_dir.path):
                ssh_conn.mount(dest_dir.path)
        else:
            dest_dir = DestSyncDir(self.profile.cfg_file.vals["RemoteDir"])

        # Copy exclude pattern file to the remote.
        try:
            shutil.copy(self.profile.ex_file.path, os.path.join(
                dest_dir.ex_dir, self.profile.info_file.vals["ID"]))
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")

        # Expand globbing patterns.
        self.profile.ex_file.glob(local_dir.path)

        # Begin syncing local and remote directories.
        local_files = set(local_dir.list_files(rel=True, symlinks=True))
        remote_files = set(dest_dir.list_files(rel=True))
        known_files = set(self.profile.db_file.prioritize())

        local_del_files = known_files - remote_files
        remote_del_files = known_files - local_files

        # Delete files in the local directory that were deleted in the remote
        # directory since the last sync.
        for rel_path in local_del_files:
            full_path = os.path.join(local_dir.path, rel_path)
            os.remove(full_path)
            # If the file was the only file in its directory, delete the
            # directory.
            if os.path.dirname(full_path) != local_dir.path:
                try:
                    os.rmdir(os.path.dirname(full_path))
                except OSError:
                    pass
        self.profile.db_file.rm_files(list(local_del_files))

        # Delete or trash files in the remote directory that were deleted in
        # the local directory since the last sync.
        if not self.profile.cfg_file.vals["DeleteAlways"]:
            trash_dir = TrashDir(self.profile.cfg_file.vals["TrashDirs"])
        trashed_files = []
        for rel_path in remote_del_files:
            full_path = os.path.join(dest_dir.safe_path, rel_path)
            if not self.profile.cfg_file.vals["DeleteAlways"]:
                if trash_dir.check_file(full_path):
                    # The file is in the trash. Delete the corresponding file
                    # in the remote directory.
                    os.remove(full_path)
                    if os.path.dirname(full_path) != dest_dir.path:
                        try:
                            os.rmdir(os.path.dirname(full_path))
                        except OSError:
                            pass
                else:
                    # The file is not in the trash. Mark the corresponding file
                    # in the remote directory for deletion.
                    new_rel_path = (
                        os.path.splitext(rel_path)[0]
                        + datetime.datetime.now().strftime(
                            "_deleted-%Y%m%d-%H%M%S")
                        + os.path.splitext(rel_path)[1])
                    trashed_files.append(new_rel_path)
                    new_full_path = os.path.join(
                        dest_dir.safe_path, new_rel_path)
                    shutil.move(full_path, new_full_path)
        self.profile.db_file.rm_files(list(remote_del_files))
        dest_dir.db_file.rm_files(list(remote_del_files))
        dest_dir.db_file.add_files(trashed_files, deleted=True)
