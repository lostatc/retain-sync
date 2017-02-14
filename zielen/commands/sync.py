"""A class for the 'sync' command.

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
import shutil
import atexit
from typing import Iterable, Tuple, Set

from zielen.exceptions import UserInputError, ServerError
from zielen.basecommand import Command
from zielen.util.connect import SSHConnection
from zielen.util.misc import timestamp_path
from zielen.io.profile import ProfileExcludeFile
from zielen.io.userdata import TrashDir, LocalSyncDir, DestSyncDir
from zielen.io.transfer import rclone


class SyncCommand(Command):
    """Redistribute files between the local and remote directories.

    Attributes:
        profile:    The currently selected profile.
        local_dir:  A LocalSyncDir object representing the local directory.
        dest_dir:   A DestSyncDir object representing the destination
                    directory.
        connection: A Connection object representing the remote connection.
    """
    def __init__(self, profile_in: str) -> None:
        super().__init__()
        self.profile = self.select_profile(profile_in)
        self.local_dir = None
        self.dest_dir = None
        self.connection = None

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
            atexit.register(self.interrupt_msg)
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

        # Update the remote directory with modified local files. Update
        # symlinks in the local directory so that, if the current sync
        # operation gets interrupted, those files don't get deleted from the
        # remote directory on the next sync operation.
        self._update_remote(local_mod_files)
        self.dest_dir.symlink_tree(
            self.local_dir.path,
            exclude=self.dest_dir.db_file.list_files(deleted=True))

        # Add modified files to the local database, inflating their priority
        # values if that option is set in the config file.
        if self.profile.cfg_file.vals["InflatePriority"]:
            self.profile.db_file.add_inflated(
                local_mod_files | remote_mod_files)
        else:
            self.profile.db_file.add_files(local_mod_files | remote_mod_files)

        # At this point, the differences between the two directories have been
        # resolved.

        # Calculate which excluded files are still in the remote directory.
        remote_excluded_files = (
            self.profile.ex_file.rel_files
            & set(self.dest_dir.list_files(rel=True, dirs=True)))

        # Decide which files and directories to keep in the local directory.
        retain_dirs, remaining_space = self._prioritize_dirs(
            self.profile.cfg_file.vals["StorageLimit"])
        if self.profile.cfg_file.vals["SyncExtraFiles"]:
            retain_files, remaining_space = self._prioritize_files(
                remaining_space, exclude_paths=retain_dirs)
        else:
            retain_files = set()

        # Copy the selected files as well as any excluded files still in the
        # remote directory to the local directory and replace all others
        # with symlinks.
        self._update_local(retain_dirs | retain_files | remote_excluded_files)

        # Remove excluded files that are still in the remote directory.
        self._rm_excluded_files(remote_excluded_files)

        # The sync is now complete. Update the time of the last sync in the
        # info file.
        self.profile.info_file.update_synctime()
        self.profile.info_file.write()

    def _rm_excluded_files(self, excluded_paths: Iterable[str]) -> None:
        """Remove excluded files from the remote directory.

        Remove files from the remote directory only if they've been excluded
        by each client. Also remove them from both databases.

        Args:
            excluded_paths: The paths of excluded files to remove.
        """
        # Expand globbing patterns for each client's exclude pattern file.
        pattern_files = []
        for entry in os.scandir(self.dest_dir.ex_dir):
            pattern_file = ProfileExcludeFile(entry.path)
            pattern_file.glob(self.local_dir.path)
            pattern_files.append(pattern_file)

        all_files = self.profile.db_file.get_paths()

        rm_files = set()
        for excluded_path in excluded_paths:
            for pattern_file in pattern_files:
                if excluded_path not in pattern_file.rel_files:
                    break
            else:
                # The file was not found in one of the exclude pattern
                # files. Remove it from the remote directory and both
                # databases.
                if excluded_path not in all_files:
                    # The current path is a directory. Add all the
                    # directory's files to the set instead of the directory
                    # itself.
                    for filepath in all_files:
                        if (os.path.commonpath([filepath, excluded_path])
                                == excluded_path):
                            rm_files.add(filepath)
                else:
                    rm_files.add(excluded_path)

        # This doesn't accept directory paths, only file paths.
        self._rm_remote_files(rm_files)

    def _update_local(self, retain_files: Iterable[str]) -> None:
        """Update the local directory with remote files.

        Args:
            retain_files:   The paths of files and directories to copy from
                            the remote directory to the local one. All other
                            files in the local directory are replaced with
                            symlinks.
        """
        retain_files = set(retain_files)
        all_files = set(self.local_dir.list_files(
            rel=True, dirs=True, exclude=self.profile.ex_file.rel_files))
        stale_files = list(all_files - retain_files)

        # Sort the file paths so that a directory's contents always comes
        # before the directory.
        stale_files.sort(reverse=True)

        for path in stale_files:
            try:
                os.remove(os.path.join(self.local_dir.path, path))
            except IsADirectoryError:
                shutil.rmtree(os.path.join(self.local_dir.path, path))

        self.dest_dir.symlink_tree(
            self.local_dir.path,
            exclude=self.dest_dir.db_file.list_files(deleted=True))

        try:
            rclone(
                self.dest_dir.safe_path, self.local_dir.path,
                files=retain_files,
                exclude=self.dest_dir.db_file.list_files(deleted=True),
                msg="Updating local files...")
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")

    def _prioritize_files(
            self, space_limit=int, exclude_paths=None) -> Tuple[Set[str], int]:
        """Calculate which files will stay in the local directory.

        Args:
            exclude_paths:  An iterable of paths of files and directories to
                            not consider when selecting files.
            space_limit:    The amount of space remaining in the directory
                            (in bytes).

        Returns:
            A tuple containing a list of paths of files to keep in the local
            directory and the amount of space remaining (in bytes) until the
            storage limit is reached.
        """
        file_priorities = self.profile.db_file.get_priorities()
        adjusted_priorities = []
        for file_path, file_priority in file_priorities:
            for exclude_path in exclude_paths:
                if (os.path.commonpath([file_path, exclude_path])
                        == exclude_path):
                    break
            else:
                # The file is not included in the list of excluded paths.
                file_size = os.stat(
                    os.path.join(self.dest_dir.path, file_path)).st_size
                if self.profile.cfg_file.vals["AccountForSize"]:
                    try:
                        adjusted_priorities.append((
                            file_path, file_priority / file_size, file_size))
                    except ZeroDivisionError:
                        adjusted_priorities.append((file_path, 0, file_size))
                else:
                    adjusted_priorities.append((
                        file_path, file_priority, file_size))

        # Sort directories by priority.
        adjusted_priorities.sort(key=lambda x: x[1], reverse=True)
        selected_files = [
            (path, size) for path, priority, size in adjusted_priorities]

        # Calculate which directories will stay in the local directory.
        remaining_space = space_limit
        for file_path, file_size in selected_files.copy():
            remaining_space -= file_size
            if remaining_space < 0:
                # There is not enough room for the current directory.
                # Remove it from the list.
                selected_files.remove((file_path, file_size))
                remaining_space += file_size

        selected_files = {path for path, size in selected_files}
        return selected_files, remaining_space

    def _prioritize_dirs(self, space_limit: int) -> Tuple[Set[str], int]:
        """Calculate which directories will stay in the local directory.

        Args:
            space_limit:    The amount of space remaining in the directory
                            (in bytes).
        Returns:
            A tuple containing a list of paths of directories to keep in the
            local directory and the amount of space remaining (in bytes) until
            the storage limit is reached.
        """
        file_priorities = self.profile.db_file.get_priorities()
        dir_paths = self.local_dir.list_files(
            rel=True, files=False, dirs=True,
            exclude=self.profile.ex_file.rel_files)
        dir_priorities = []

        # Calculate the priorities of each directory. A directory priority is
        # calculated by finding the sum of the priorities of its files and
        # dividing by the directory size.
        for dir_path in dir_paths:
            dir_priority = 0.0
            dir_size = 0
            for file_path, file_priority in file_priorities:
                if os.path.commonpath([file_path, dir_path]) == dir_path:
                    dir_priority += file_priority
                    dir_size += os.stat(
                        os.path.join(self.dest_dir.path, file_path)).st_size
            if self.profile.cfg_file.vals["AccountForSize"]:
                try:
                    dir_priorities.append((
                        dir_path, dir_priority / dir_size, dir_size))
                except ZeroDivisionError:
                    dir_priorities.append((dir_path, 0, dir_size))
            else:
                dir_priorities.append((dir_path, dir_priority, dir_size))

        # Sort directories by priority.
        dir_priorities.sort(key=lambda x: x[1], reverse=True)
        selected_dirs = [
            (path, size) for path, priority, size in dir_priorities]

        # Calculate which directories will stay in the local directory.
        while True:
            remaining_space = space_limit
            for dir_path, dir_size in selected_dirs.copy():
                if dir_size > self.profile.cfg_file.vals["StorageLimit"]:
                    # This directory alone is larger than the storage limit.
                    # Remove it from the list.
                    selected_dirs.remove((dir_path, dir_size))
                    continue

                remaining_space -= dir_size
                if remaining_space < 0:
                    # There is not enough room for the current directory.
                    # Remove it from the list.
                    selected_dirs.remove((dir_path, dir_size))
                    remaining_space += dir_size
                else:
                    # Remove any subdirectories of the current directory
                    # from the list. This prevents directories from being
                    # counted more than once when calculating the total size.
                    for subdir_path, subdir_size in selected_dirs.copy():
                        if (dir_path != subdir_path
                                and os.path.commonpath([subdir_path, dir_path])
                                == dir_path):
                            selected_dirs.remove((subdir_path, subdir_size))
                            break
                    else:
                        continue

                    # The list of directories has been modified. Start over
                    # from the beginning.
                    break
            else:
                # The directories that remain in the list are the ones that
                # will stay in the local directory.
                break

        selected_dirs = {path for path, size in selected_dirs}
        return selected_dirs, remaining_space

    def _update_remote(self, local_mod_files: Iterable[str]) -> None:
        """Update the remote directory with modified local files.

        Raises:
            ServerError:    The remote directory is unmounted.
        """
        local_mod_files = set(local_mod_files)

        # Copy modified local files to the remote directory, excluding symbolic
        # links.
        try:
            rclone(
                self.local_dir.path, self.dest_dir.safe_path,
                files=local_mod_files & set(
                    self.local_dir.list_files(rel=True)),
                msg="Updating remote files...")
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")

        # Add new files to the database and update the time of the last sync
        # for existing ones.
        self.dest_dir.db_file.add_files(local_mod_files)

    def _handle_conflicts(
            self, local_in: Iterable[str], remote_in: Iterable[str]
            ) -> Tuple[Set[str], Set[str]]:
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
        local_in = set(local_in)
        remote_in = set(remote_in)

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
        # ones. If you do, and the current sync operation is interrupted, then
        # those files will be deleted on the next sync operation. The new file
        # paths are added to the database once the differences between the two
        # directories have been resolved.
        self.profile.db_file.rm_files(local_in - local_out)
        self.profile.db_file.rm_files(remote_in - remote_out)

        # Update file paths in the remote database.
        self.dest_dir.db_file.add_files(remote_out - remote_in)
        self.dest_dir.db_file.rm_files(remote_in - remote_out)

        return local_out, remote_out

    def _compute_changes(self) -> Tuple[Set[str], Set[str]]:
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
        local_mtimes = self.local_dir.list_mtimes(
            rel=True, exclude=self.profile.ex_file.rel_files)

        local_mod_files = {
            path for path, time in local_mtimes
            if time > last_sync or not self.profile.db_file.check_exists(path)}
        remote_mod_files = self.dest_dir.db_file.list_files(
            deleted=False, min_lastsync=last_sync)

        return local_mod_files, remote_mod_files

    def _compute_deletions(self) -> Tuple[Set[str], Set[str], Set[str]]:
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
        known_files = {
            path for path, priority in self.profile.db_file.get_priorities()}

        local_del_files = known_files - remote_files
        remote_del_files = known_files - local_files
        if not self.profile.cfg_file.vals["DeleteAlways"]:
            trash_dir = TrashDir(self.profile.cfg_file.vals["TrashDirs"])
        remote_trash_files = set()
        for path in remote_del_files:
            dest_path = os.path.join(self.dest_dir.safe_path, path)
            if (self.profile.cfg_file.vals["DeleteAlways"]
                    or os.path.isfile(dest_path)
                    and not trash_dir.check_file(dest_path)):
                remote_trash_files.add(path)
        remote_del_files -= remote_trash_files

        return local_del_files, remote_del_files, remote_trash_files

    def _rm_local_files(self, file_paths: Iterable[str]) -> None:
        """Delete local files and remove them from both databases.

        Args:
            file_paths: The relative paths of files to remove. These can not
                        be directory paths.
        """
        deleted_files = []

        # Make sure that the database always gets updated with whatever files
        # have been deleted.
        try:
            for path in file_paths:
                os.remove(os.path.join(self.local_dir.path, path))
                deleted_files.append(path)
        finally:
            # If a deletion from another client was already synced to the
            # server, then that file path will have already been removed
            # from the remote database.
            self.profile.db_file.rm_files(deleted_files)

    def _rm_remote_files(self, file_paths: Iterable[str]) -> None:
        """Delete remote files and remove them from the local database.

        Args:
            file_paths: The relative paths of files to remove. These can not
                        be directory paths.
        """
        deleted_files = []

        # Make sure that the database always gets updated with whatever files
        # have been deleted.
        try:
            for path in file_paths:
                try:
                    os.remove(os.path.join(self.dest_dir.safe_path, path))
                except FileNotFoundError:
                    raise ServerError(
                        "the connection to the remote directory was lost")
                deleted_files.append(path)
        finally:
            self.profile.db_file.rm_files(deleted_files)
            self.dest_dir.db_file.rm_files(deleted_files)

    def _trash_files(self, file_paths: Iterable[str]) -> None:
        """Mark files in the remote directory for deletion.

        This involves renaming the file to signify its state to the user and
        updating its entry in the remote database to signify its state to the
        program.

        Args:
            file_paths: The relative paths of files to mark for deletion. These
                        can not be directory paths.
        """
        new_paths = [
            timestamp_path(path, keyword="deleted") for path in file_paths]
        old_renamed_files = []
        new_renamed_files = []

        # Make sure that the database always gets updated with whatever files
        # have been renamed.
        try:
            for old_path, new_path in zip(file_paths, new_paths):
                try:
                    os.rename(
                        os.path.join(self.dest_dir.safe_path, old_path),
                        os.path.join(self.dest_dir.safe_path, new_path))
                except FileNotFoundError:
                    raise ServerError(
                        "the connection to the remote directory was lost")
                old_renamed_files.append(old_path)
                new_renamed_files.append(new_path)
        finally:
            self.profile.db_file.rm_files(old_renamed_files)
            self.dest_dir.db_file.rm_files(old_renamed_files)
            self.dest_dir.db_file.add_files(new_renamed_files, deleted=True)
