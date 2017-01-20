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
            remote_trash_files) = self._compute_deletions()
        self._rm_local_files(local_del_files)
        self._rm_remote_files(remote_del_files)
        self._trash_files(remote_trash_files)

        # Handle syncing conflicts.
        local_mod_files, remote_mod_files = self._handle_conflicts(
            *self._compute_changes())

    def _handle_conflicts(self, local_in: Set[str],
                          remote_in: Set[str]) -> Tuple[Set[str]]:
        """Handle sync conflicts between local and remote files.

        Conflicts are handled by renaming the file that was modified least
        recently to signify to the user that there was a conflict. These files
        aren't treated specially and are synced just like any other file.

        Args:
            local_in:   A set of local files that have been modified since the
                        last sync.
            remote_in:  A set of remote files that have been modified since the
                        last sync.

        Returns:
            An tuple containing an updated version of each of the input values.
        """
        conflict_files = local_in & remote_in
        local_mtimes = {}
        remote_mtimes = {}
        for path in conflict_files:
            local_mtimes.update({
                path: os.stat(
                    os.path.join(self.local_dir.path, path)).st_mtime})
            remote_mtimes.update({path: self.dest_dir.db_file.get_mtime(path)})

        local_out = local_in.copy()
        remote_out = remote_in.copy()
        for path in conflict_files:
            new_path = timestamp_path(path, keyword="conflict")
            if local_mtimes[path] < remote_mtimes[path]:
                os.rename(
                    os.path.join(self.local_dir.path, path),
                    os.path.join(self.local_dir.path, new_path))
                local_out.remove(path)
                local_out.add(new_path)
            elif remote_mtimes[path] < local_mtimes[path]:
                try:
                    os.rename(
                        os.path.join(self.dest_dir.safe_path, path),
                        os.path.join(self.dest_dir.safe_path, new_path))
                except FileNotFoundError:
                    raise ServerError(
                        "the connection to the remote directory was lost")
                remote_out.remove(path)
                remote_out.add(new_path)

        # Remove outdated file paths from the local database, but don't add new
        # ones. This is to prevent those files from being deleted on a
        # subsequent operation in a case where the current operation were
        # interrupted. The new file paths are added to the database once the
        # directories are in sync.
        self.profile.db_file.rm_files(local_in - local_out)
        self.profile.db_file.rm_files(remote_in - remote_out)

        # Update file paths in the remote database.
        self.dest_dir.db_file.add_files(remote_out - remote_in)
        self.dest_dir.db_file.rm_files(remote_in - remote_out)

        return local_out, remote_out

    def _compute_changes(self) -> Tuple[Set[str]]:
        """Compute files that have been modified since the last sync.

        For local files, this involves checking the mtime as well as looking up
        the file path in the database to catch new files that may not have had
        their mtime updated when they were copied/moved into the directory.

        For remote files, this involves checking the time that they were last
        updated by a sync, which is stored in the remote database.

        Returns:
            A tuple containing two sets of relative paths of files that have
            been modified since the last sync. The first is for local files and
            the second is for remote files.
        """
        last_sync = self.profile.info_file.vals["LastSync"]

        local_mod_files = {
            path for path, time in self.local_dir.list_mtimes(
                rel=True, exclude=self.profile.ex_file.files)
            if time > last_sync or not self.profile.db_file.check_exists(path)}
        remote_mod_files = self.dest_dir.db_file.list_files(
            deleted=False, min_lastsync=last_sync)

        return local_mod_files, remote_mod_files

    def _compute_deletions(self) -> Tuple[Set[str]]:
        """Compute files that need to be deleted to sync the two directories.

        A file needs to be deleted if it is found in the local database but not
        in either the local or remote directory.

        Returns:
            A tuple containing three sets of relative file paths. The first is
            for local files to be deleted, the second is for remote files to be
            deleted and the third is for remote files to be marked for
            deletion.
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

        This involves renaming the file to signify its state to the user and
        updating its entry in the remote database to signify its state to the
        program.

        Args:
            paths:  The relative paths of files to mark for deletion.
        """
        new_paths = [
            timestamp_path(path, keyword="deleted") for path in paths]
        full_paths = [
            os.path.join(self.dest_dir.safe_path, path) for path in paths]
        new_full_paths = [
            os.path.join(self.dest_dir.safe_path, path) for path in new_paths]
        for old_path, new_path in zip(full_paths, new_full_paths):
            os.rename(old_path, new_path)
        self.profile.db_file.rm_files(paths)
        self.dest_dir.db_file.rm_files(paths)
        self.dest_dir.db_file.add_files(new_paths, deleted=True)
