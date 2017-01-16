"""A class for the 'sync' command.

Copyright © 2016-2017 Garrett Powell <garrett@gpowell.net>

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
import atexit
from typing import Iterable, Tuple, Set

from retainsync.exceptions import UserInputError, ServerError
from retainsync.basecommand import Command
from retainsync.util.ssh import SSHConnection, ssh_env
from retainsync.util.misc import err, timestamp_path
from retainsync.io.userdata import TrashDir, LocalSyncDir, DestSyncDir


class SyncCommand(Command):
    """Redistribute files between the local and remote directories.

    Attributes:
        local_dir:  A LocalSyncDir object representing the local directory.
        dest_dir:   A DestSyncDir object representing the destination
                    directory.
        ssh_conn:   An SSHConnection object representing the ssh connection.
    """
    def __init__(self, profile_in: str) -> None:
        super().__init__()
        self.profile = self.select_profile(profile_in)
        self.local_dir = None
        self.dest_dir = None
        self.ssh_conn = None

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
            atexit.register(err, self.interrupt_msg)
            raise UserInputError("invalid profile")

        self.profile.cfg_file.read()
        self.profile.cfg_file.check_all()

        self.local_dir = LocalSyncDir(self.profile.cfg_file.vals["LocalDir"])
        if self.profile.cfg_file.vals["RemoteHost"]:
            self.dest_dir = DestSyncDir(self.profile.mnt_dir)
            ssh_env()
            self.ssh_conn = SSHConnection(
                self.profile.cfg_file.vals["RemoteHost"],
                self.profile.cfg_file.vals["RemoteDir"],
                self.profile.cfg_file.vals["SshfsOptions"],
                self.profile.cfg_file.vals["RemoteUser"],
                self.profile.cfg_file.vals["Port"])
            if not os.path.isdir(self.dest_dir.path):
                # Unmount if mountpoint is broken.
                self.ssh_conn.unmount(self.dest_dir.path)
            if not os.path.ismount(self.dest_dir.path):
                self.ssh_conn.mount(self.dest_dir.path)
        else:
            self.dest_dir = DestSyncDir(
                self.profile.cfg_file.vals["RemoteDir"])

        # Copy exclude pattern file to the remote.
        try:
            shutil.copy(self.profile.ex_file.path, os.path.join(
                self.dest_dir.ex_dir, self.profile.info_file.vals["ID"]))
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")

        # Expand globbing patterns.
        self.profile.ex_file.glob(self.local_dir.path)

        # Sync deletions between the local and remote directories.
        (local_del_files, remote_del_files,
            remote_trash_files) = self._sync_deletions()
        self._rm_local_files(local_del_files)
        self._rm_remote_files(remote_del_files)
        self._trash_files(remote_trash_files)

    def _sync_deletions(self) -> Tuple[Set[str]]:
        """Compute file paths to sync deletions across the two directories.

        Returns:
            A tuple containing three sets of relative file paths. The first is
            local files to be deleted, the second is remote files to be deleted
            and the third is remote files to be marked for deletion.
        """
        local_files = set(self.local_dir.list_files(rel=True, symlinks=True))
        remote_files = set(self.dest_dir.list_files(rel=True))
        known_files = set(self.profile.db_file.prioritize())

        local_del_files = known_files - remote_files
        remote_del_files = known_files - local_files
        if not self.profile.cfg_file.vals["DeleteAlways"]:
            trash_dir = TrashDir(self.profile.cfg_file.vals["TrashDirs"])
        remote_trash_files = {
            path for path in remote_del_files
            if self.profile.cfg_file.vals["DeleteAlways"]
            or not trash_dir.check_file(os.path.join(
                self.dest_dir.safe_path, path))}
        remote_del_files -= remote_trash_files

        return local_del_files, remote_del_files, remote_trash_files

    def _rm_local_files(self, paths: Iterable[str]) -> None:
        """Delete local files and remove them from both databases.

        Args:
            paths:  The relative paths of files to remove.
        """
        full_paths = [
            os.path.join(self.local_dir.path, path) for path in paths]
        for path in full_paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                # This could happen in a situation where the program was
                # interrupted before the database could be updated.
                pass
        # If a deletion from another client was already synced to the server,
        # then that file path will have already been removed from the remote
        # database.
        self.profile.db_file.rm_files(paths)

    def _rm_remote_files(self, paths: Iterable[str]) -> None:
        """Delete remote files and remove them from the local database.

        Args:
            paths:  The relative paths of files to remove.
        """
        full_paths = [
            os.path.join(self.dest_dir.safe_path, path) for path in paths]
        for path in full_paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                # This could happen in a situation where the program was
                # interrupted before the database could be updated.
                pass
        self.profile.db_file.rm_files(paths)
        self.dest_dir.db_file.rm_files(paths)

    def _trash_files(self, paths: Iterable[str]) -> None:
        """Mark files in the remote directory for deletion.

        Args:
            paths:  The relative paths of files to mark for deletion.
        """
        new_paths = [
            timestamp_path(path, keyword="deleted") for path in paths]
        full_paths = [
            os.path.join(self.dest_dir.safe_path, path) for path in paths]
        new_full_paths = [
            os.path.join(self.dest_dir.safe_path, path) for path in new_paths]
        for pair in zip(full_paths, new_full_paths):
            os.rename(pair[0], pair[1])
        self.profile.db_file.rm_files(paths)
        self.dest_dir.db_file.rm_files(paths)
        self.dest_dir.db_file.add_files(new_paths, deleted=True)
