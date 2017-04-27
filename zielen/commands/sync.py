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
import time
from typing import Iterable, Set, NamedTuple


from zielen.io import rec_clone, symlink_tree, is_unsafe_symlink
from zielen.userdata import TrashDir
from zielen.util import timestamp_path
from zielen.profile import ProfileExcludeFile
from zielen.basecommand import Command
from zielen.exceptions import ServerError

DeletedPaths = NamedTuple(
    "DeletedPaths",
    [("local", Set[str]), ("remote", Set[str]), ("trash", Set[str])])

SelectedPaths = NamedTuple(
    "SelectedPaths",
    [("remaining_space", int), ("paths", Set[str])])

UpdatedPathsBase = NamedTuple(
    "UpdatedPaths",
    [("local", Set[str]), ("remote", Set[str])])


class UpdatedPaths(UpdatedPathsBase):
    __slots__ = ()

    @property
    def all(self) -> Set[str]:
        return self.local | self.remote


class SyncCommand(Command):
    """Redistribute files between the local and remote directories.

    Attributes:
        profile: The currently selected profile.
        local_dir: A LocalSyncDir object representing the local directory.
        dest_dir: A DestSyncDir object representing the destination directory.
        connection: A Connection object representing the remote connection.
    """
    def __init__(self, profile_input: str) -> None:
        super().__init__()
        self.profile = self.select_profile(profile_input)

    def main(self) -> None:
        """Run the command.

        Raises:
            ServerError: The connection to the remote directory was lost.
        """
        self.setup_profile()

        # Copy exclude pattern file to the remote.
        try:
            shutil.copy(self.profile.ex_file.path, os.path.join(
                self.dest_dir.ex_dir, self.profile.info_file.vals["ID"]))
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")

        # Expand globbing patterns.
        self.profile.ex_file.glob(self.local_dir.path)

        # Scan the local and remote directories.
        file_paths = (
            self.local_dir.get_paths(dirs=False).keys()
            | self.dest_dir.get_paths(dirs=False).keys())
        dir_paths = (
            self.local_dir.get_paths(files=False, symlinks=False).keys()
            | self.dest_dir.get_paths(files=False, symlinks=False).keys())

        # Get the paths of files that have been added, deleted or modified
        # since the last sync.
        new_paths = self._compute_added()
        del_paths = self._compute_deleted()
        mod_paths = self._compute_modified()

        # Add new files to both databases.
        new_file_paths = (new_paths.all - dir_paths)
        new_dir_paths = (new_paths.all - file_paths)
        self.dest_dir.db_file.add_paths(new_file_paths, new_dir_paths)
        if self.profile.cfg_file.vals["InflatePriority"]:
            self.profile.db_file.add_inflated(new_file_paths, new_dir_paths)
        else:
            self.profile.db_file.add_paths(new_file_paths, new_dir_paths)

        # Sync deletions between the local and remote directories.
        self._rm_local_files(del_paths.local)
        self._rm_remote_files(del_paths.remote)
        self._trash_files(del_paths.trash)

        # Handle syncing conflicts.
        updated_paths = self._handle_conflicts(
            mod_paths.local | new_paths.local,
            mod_paths.remote | new_paths.remote)

        # Update the remote directory with modified local files.
        self._update_remote(updated_paths.local)

        # At this point, the differences between the two directories have been
        # resolved.

        # Calculate which excluded files are still in the remote directory.
        remote_excluded_files = (
            self.profile.ex_file.matches
            & self.dest_dir.get_paths(rel=True).keys())

        # Decide which files and directories to keep in the local directory.
        remaining_space, selected_dirs = self._prioritize_dirs(
            self.profile.cfg_file.vals["StorageLimit"])
        if self.profile.cfg_file.vals["SyncExtraFiles"]:
            remaining_space, selected_files = self._prioritize_files(
                remaining_space, exclude=selected_dirs)
        else:
            selected_files = set()

        # Copy the selected files as well as any excluded files still in the
        # remote directory to the local directory and replace all others
        # with symlinks.
        self._update_local(
            selected_dirs | selected_files | remote_excluded_files)

        # Remove excluded files that are still in the remote directory.
        self._rm_excluded_files(remote_excluded_files)

        # The sync is now complete. Update the time of the last sync in the
        # info file.
        self.profile.db_file.conn.commit()
        self.dest_dir.db_file.conn.commit()
        self.profile.info_file.vals["LastSync"] = time.time()
        self.profile.info_file.write()

    def _prioritize_files(self, space_limit: int,
                          exclude=None) -> SelectedPaths:
        """Calculate which files will stay in the local directory.

        Args:
            space_limit: The amount of space remaining in the directory
                (in bytes). This assumes that all files currently exist in the
                directory as symlinks.
            exclude: An iterable of paths of files and directories to not
                consider when selecting files.

        Returns:
            A named tuple containing a set of paths of files to keep in the
            local directory and the amount of space remaining (in bytes) until
            the storage limit is reached.
        """
        if exclude is None:
            exclude = []

        local_files = self.profile.db_file.get_tree(directory=False)
        file_stats = self.dest_dir.get_paths(
            rel=True, dirs=False,
            exclude=self.profile.ex_file.matches)
        adjusted_priorities = []

        # Adjust directory priorities for size.
        for file_path, file_data in local_files.items():
            for exclude_path in exclude:
                if (file_path == exclude_path
                        or file_path.startswith(
                            exclude_path.rstrip(os.sep) + os.sep)):
                    break
            else:
                # The file is not included in the list of excluded paths.
                file_size = file_stats[file_path].st_blocks * 512
                file_priority = file_data.priority
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
        prioritized_files = [
            (path, size) for path, priority, size in adjusted_priorities]

        # Calculate which directories will stay in the local directory.
        selected_files = set()
        # This assumes that all symlinks have a disk usage of one block.
        symlink_size = os.stat(self.local_dir.path).st_blksize
        remaining_space = space_limit
        for file_path, file_size in prioritized_files:
            new_remaining_space = remaining_space - file_size + symlink_size
            if new_remaining_space > 0:
                selected_files.add(file_path)
                remaining_space = new_remaining_space

        return SelectedPaths(remaining_space, selected_files)

    def _prioritize_dirs(self, space_limit: int) -> SelectedPaths:
        """Calculate which directories will stay in the local directory.

        Args:
            space_limit: The amount of space remaining in the directory
                (in bytes).
        Returns:
            A tuple containing a list of paths of directories to keep in the
            local directory and the amount of space remaining (in bytes) until
            the storage limit is reached.
        """
        local_files = self.profile.db_file.get_tree(directory=False)
        local_dirs = self.profile.db_file.get_tree(directory=True)
        dir_stats = self.dest_dir.get_paths(
            rel=True, exclude=self.profile.ex_file.matches)
        adjusted_priorities = []

        # Calculate the sizes of each directory and adjust directory priorities
        # for size.
        for dir_path, dir_data in local_dirs.items():
            dir_priority = dir_data.priority
            dir_size = 0
            for sub_path in self.dest_dir.db_file.get_tree(start=dir_path):
                # Get the size of the files in the remote directory, as
                # symlinks in the local directory are not followed.
                dir_size += dir_stats[sub_path].st_blocks * 512

            if self.profile.cfg_file.vals["AccountForSize"]:
                try:
                    adjusted_priorities.append((
                        dir_path, dir_priority / dir_size, dir_size))
                except ZeroDivisionError:
                    adjusted_priorities.append((dir_path, 0, dir_size))
            else:
                adjusted_priorities.append((dir_path, dir_priority, dir_size))

        # Sort directories by priority.
        adjusted_priorities.sort(key=lambda x: x[1], reverse=True)
        prioritized_dirs = [
            path for path, priority, size in adjusted_priorities]
        dir_sizes = {
            path: size for path, priority, size in adjusted_priorities}

        # Select which directories will stay in the local directory.
        selected_dirs = set()
        selected_subdirs = set()
        selected_files = set()
        # Set the initial remaining space assuming that no files will stay
        # in the local directory an that they'll all be symlinks,
        # which should have a disk usage of one block. For evey file that is
        # selected, one block will be added back to the remaining space.
        symlink_size = os.stat(self.local_dir.path).st_blksize
        remaining_space = space_limit - len(local_files) * symlink_size
        for dir_path in prioritized_dirs:
            dir_size = dir_sizes[dir_path]

            if dir_path in selected_subdirs:
                # The current directory is a subdirectory of a directory
                # that has already been selected. Skip it.
                continue

            if dir_size > self.profile.cfg_file.vals["StorageLimit"]:
                # The current directory alone is larger than the storage limit.
                # Skip it.
                continue

            # Find all subdirectories of the current directory that are
            # already in the set of selected files.
            contained_files = set()
            contained_dirs = set()
            subdirs_size = 0
            for subpath, subpath_data in self.profile.db_file.get_tree(
                    start=dir_path).items():
                if subpath_data.directory:
                    contained_dirs.add(subpath)
                else:
                    contained_files.add(subpath)
                if subpath in selected_dirs:
                    subdirs_size += dir_sizes[subpath]

            new_remaining_space = (
                remaining_space
                - dir_size
                + subdirs_size
                + len(contained_files - selected_files) * symlink_size)
            if new_remaining_space > 0:
                # Add the current directory to the set of selected files and
                # remove all of its subdirectories from the set.
                selected_subdirs |= contained_dirs
                selected_files |= contained_files
                selected_dirs -= contained_dirs
                selected_dirs.add(dir_path)
                remaining_space = new_remaining_space

        return SelectedPaths(remaining_space, selected_dirs)

    def _update_local(self, update_paths: Iterable[str]) -> None:
        """Update the local directory with remote files.

        Args:
            update_paths: The paths of files and directories to copy from the
                remote directory to the local one. All other files in the local
                directory are replaced with symlinks.
        """
        update_paths = set(update_paths)

        # Create a set including all the files and directories contained in
        # each directory from the input.
        all_update_paths = set()
        for path in update_paths:
            all_update_paths |= self.profile.db_file.get_tree(
                start=path).keys()

        # Don't include excluded files or files not in the local database
        # (e.g. unsafe symlinks).
        all_paths = (self.local_dir.get_paths(
            rel=True, exclude=self.profile.ex_file.matches).keys()
                     & self.profile.db_file.get_tree().keys())

        stale_paths = list(all_paths - all_update_paths)

        # Sort the file paths so that a directory's contents always come
        # before the directory.
        stale_paths.sort(key=lambda x: x.count(os.sep), reverse=True)

        # Remove old, unneeded files to make room for new ones.
        for stale_path in stale_paths:
            full_stale_path = os.path.join(self.local_dir.path, stale_path)
            try:
                os.remove(full_stale_path)
            except IsADirectoryError:
                try:
                    os.rmdir(full_stale_path)
                except OSError:
                    # The directory has other files in it. It should be
                    # ignored.
                    pass

        try:
            symlink_tree(
                self.dest_dir.safe_path, self.local_dir.path,
                self.dest_dir.db_file.get_tree(directory=False),
                self.dest_dir.db_file.get_tree(directory=True))

            rec_clone(
                self.dest_dir.safe_path, self.local_dir.path,
                files=update_paths,
                msg="Updating local files...")
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")

    def _update_remote(self, update_paths: Iterable[str]) -> None:
        """Update the remote directory with local files.

        Args:
            update_paths: The relative paths of local files to update the
                remote directory with.
        Raises:
            ServerError: The remote directory is unmounted.
        """
        update_paths = set(update_paths)
        update_files = set(
            update_paths - self.local_dir.get_paths(
                rel=True, files=False, symlinks=False).keys())
        update_dirs = set(
            update_paths - self.local_dir.get_paths(
                rel=True, dirs=False).keys())

        # Copy modified local files to the remote directory.
        try:
            rec_clone(
                self.local_dir.path, self.dest_dir.safe_path,
                files=update_paths, msg="Updating remote files...")
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")

        # Update the time of the last sync for files that have been modified.
        self.dest_dir.db_file.add_paths(
            update_files, update_dirs, replace=True)

    def _handle_conflicts(
            self, local_paths: Iterable[str], remote_paths: Iterable[str]
            ) -> UpdatedPaths:
        """Handle sync conflicts between local and remote files.

        Conflicts are handled by renaming the file that was modified least
        recently to signify to the user that there was a conflict. These files
        aren't treated specially and are synced just like any other file.

        Args:
            local_paths: The relative paths of local files that have been
                modified since the last sync.
            remote_paths: The relative paths of remote files that have been
                modified since the last sync.

        Returns:
            A named tuple containing two sets of relative paths of files
            that have been modified since the last sync: local ones and
            remote ones.
        """
        local_paths = set(local_paths)
        remote_paths = set(remote_paths)
        conflict_paths = local_paths & remote_paths
        local_mtimes = {
            path: data.st_mtime for path, data
            in self.local_dir.get_paths(rel=True).items()}
        remote_mtimes = {
            path: data.st_mtime for path, data
            in self.dest_dir.get_paths(rel=True).items()}

        new_local_files = set()
        old_local_files = set()
        new_remote_files = set()
        old_remote_files = set()

        for path in conflict_paths:
            new_path = timestamp_path(path, keyword="conflict")
            path_data = self.profile.db_file.get_path(path)
            if path_data and path_data.directory:
                # Conflicts are resolved on a file-by-file basis.
                continue
            elif local_mtimes[path] < remote_mtimes[path]:
                os.rename(
                    os.path.join(self.local_dir.path, path),
                    os.path.join(self.local_dir.path, new_path))
                old_local_files.add(path)
                new_local_files.add(new_path)
            elif remote_mtimes[path] < local_mtimes[path]:
                try:
                    os.rename(
                        os.path.join(self.dest_dir.safe_path, path),
                        os.path.join(self.dest_dir.safe_path, new_path))
                except FileNotFoundError:
                    raise ServerError(
                        "the connection to the remote directory was lost")
                old_remote_files.add(path)
                new_remote_files.add(new_path)

        # Update the databases with the paths of files that have been
        # renamed.
        self.profile.db_file.rm_paths(old_local_files)
        self.profile.db_file.add_paths(new_local_files, [])
        self.dest_dir.db_file.rm_paths(old_remote_files)
        self.dest_dir.db_file.add_paths(new_remote_files, [])

        local_mod_paths = local_paths - old_local_files | new_local_files
        remote_mod_paths = remote_paths - old_remote_files | new_remote_files
        return UpdatedPaths(local_mod_paths, remote_mod_paths)

    def _compute_added(self) -> UpdatedPaths:
        """Compute paths of files that have been added since the last sync.

        This method excludes the paths of local symlinks that are absolute
        or point to files outside the local directory. A file is considered
        to be new if it is not in the local database.

        Returns:
            A named tuple containing two sets of relative paths of files
            that have been added since the last sync: local ones and
            remote ones.
        """
        new_local_paths = {
            path for path in self.local_dir.get_paths(rel=True).keys()
            if not self.profile.db_file.get_path(path)
            and not is_unsafe_symlink(
                os.path.join(self.local_dir.path, path), self.local_dir.path)}
        new_local_paths -= self.profile.ex_file.all_matches
        new_remote_paths = {
            path for path in self.dest_dir.get_paths(rel=True).keys()
            if not self.profile.db_file.get_path(path)}

        return UpdatedPaths(new_local_paths, new_remote_paths)

    def _compute_modified(self) -> UpdatedPaths:
        """Compute paths of files that have been modified since the last sync.

        This method excludes the paths of directories and the paths of files
        that are new since the last sync. A file is considered to be
        modified if its mtime is more recent than the time of the last sync
        and it is in the database. Additionally, remote files are considered
        to be modified if the time they were last updated by a sync (stored
        in the remote database) is more recent than the time of the last sync.

        Returns:
            A named tuple containing two sets of relative paths of files
            that have been modified since the last sync: local ones and
            remote ones.
        """
        last_sync = self.profile.info_file.vals["LastSync"]

        local_mtimes = (
            (path, data.st_mtime) for path, data in self.local_dir.get_paths(
                rel=True, dirs=False).items())
        remote_mtimes = (
            (path, data.st_mtime) for path, data in self.dest_dir.get_paths(
                rel=True, dirs=False).items())

        # Only include file paths that are in the database to exclude files
        # that are new since the last sync.
        local_mod_paths = {
            path for path, mtime in local_mtimes
            if mtime > last_sync and self.profile.db_file.get_path(path)
            and not is_unsafe_symlink(
                os.path.join(self.local_dir.path, path), self.local_dir.path)}
        remote_mod_paths = {
            path for path, mtime in remote_mtimes
            if mtime > last_sync and self.profile.db_file.get_path(path)}

        remote_mod_paths |= self.dest_dir.db_file.get_tree(
            directory=False, min_lastsync=last_sync).keys()

        return UpdatedPaths(local_mod_paths, remote_mod_paths)

    def _compute_deleted(self) -> DeletedPaths:
        """Compute files that need to be deleted to sync the two directories.

        A file needs to be deleted if it is found in the local database but
        not in either the local or remote directory. A file moved to the
        trash if it needs to be deleted from the remote directory but is not
        found in any of the local trash directories.

        Returns:
            A named tuple containing three sets of relative file paths: local
            files to be deleted, remote files to be deleted and remote files to
            be moved to the trash.
        """
        local_paths = self.local_dir.get_paths(rel=True).keys()
        remote_paths = self.dest_dir.get_paths(rel=True).keys()
        known_paths = self.profile.db_file.get_tree().keys()

        # Compute files that need to be deleted, not including the files
        # under selected directories.
        local_del_paths = known_paths - remote_paths
        remote_del_paths = known_paths - local_paths
        for path in local_del_paths.copy():
            sub_paths = set(self.profile.db_file.get_tree(start=path).keys())
            sub_paths.remove(path)
            local_del_paths -= sub_paths
        for path in remote_del_paths.copy():
            sub_paths = set(self.dest_dir.db_file.get_tree(start=path).keys())
            sub_paths.remove(path)
            remote_del_paths -= sub_paths

        # Compute files to be moved to the trash.
        trash_paths = set()
        if not self.profile.cfg_file.vals["DeleteAlways"]:
            local_trash_dir = TrashDir(self.profile.cfg_file.vals["TrashDirs"])
            for path in remote_del_paths:
                dest_path = os.path.join(self.dest_dir.safe_path, path)
                try:
                    if not local_trash_dir.check_file(dest_path):
                        trash_paths.add(path)
                except FileNotFoundError:
                    # This is needed in case the previous sync was
                    # interrupted and there are files in the remote
                    # directory that have been moved to the trash but not
                    # yet removed from the database.
                    trash_paths.add(path)
            remote_del_paths -= trash_paths

        return DeletedPaths(local_del_paths, remote_del_paths, trash_paths)

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

        rm_files = set()
        for excluded_path in excluded_paths:
            for pattern_file in pattern_files:
                if excluded_path not in pattern_file.matches:
                    break
            else:
                # The file was not found in one of the exclude pattern
                # files. Remove it from the remote directory and both
                # databases.
                rm_files.add(excluded_path)

        rm_files &= self.dest_dir.db_file.get_tree().keys()
        try:
            self._rm_remote_files(rm_files)
        except FileNotFoundError:
            raise ServerError(
                "the connection to the remote directory was lost")

    def _rm_local_files(self, paths: Iterable[str]) -> None:
        """Delete local files and remove them from both databases.

        If the files are excluded, don't delete them, but still remove them
        from both databases.

        Args:
            paths: The relative paths of files to remove.
        """
        for path in paths:
            if path in self.profile.ex_file.all_matches:
                continue
            full_path = os.path.join(self.local_dir.path, path)
            try:
                os.remove(full_path)
            except IsADirectoryError:
                shutil.rmtree(full_path)
            except FileNotFoundError:
                # This could happen if a previous sync was interrupted.
                pass

        self.profile.db_file.rm_paths(paths)
        self.dest_dir.db_file.rm_paths(paths)

    def _rm_remote_files(self, paths: Iterable[str]) -> None:
        """Delete remote files and remove them from both databases.

        Args:
            paths: The relative paths of files to remove.
        """
        for path in paths:
            full_path = os.path.join(self.dest_dir.safe_path, path)
            try:
                os.remove(full_path)
            except IsADirectoryError:
                shutil.rmtree(full_path)
            except FileNotFoundError:
                # This could happen if a previous sync was interrupted.
                pass

        self.profile.db_file.rm_paths(paths)
        self.dest_dir.db_file.rm_paths(paths)

    def _trash_files(self, paths: Iterable[str]) -> None:
        """Move files in the remote directory to the trash.

        This involves moving the file to the trash directory and removing its
        entry from both databases.

        Args:
            paths: The relative paths of files to mark for deletion.
        """
        os.makedirs(self.dest_dir.trash_dir, exist_ok=True)
        trash_filenames = {
            entry.name for entry in os.scandir(self.dest_dir.trash_dir)}
        old_paths = list(paths)
        old_filenames = [os.path.basename(path) for path in old_paths]

        new_filenames = []
        for old_filename in old_filenames:
            new_filename = old_filename
            filename_counter = 0
            name, extension = os.path.splitext(new_filename)
            while new_filename in trash_filenames:
                filename_counter += 1
                new_filename = (
                    name
                    + "({})".format(filename_counter)
                    + extension)
            new_filenames.append(new_filename)

        for old_path, new_filename in zip(old_paths, new_filenames):
            try:
                os.rename(
                    os.path.join(self.dest_dir.safe_path, old_path),
                    os.path.join(self.dest_dir.trash_dir, new_filename))
            except FileNotFoundError:
                # This could happen if a previous sync was interrupted.
                pass

        self.profile.db_file.rm_paths(old_paths)
        self.dest_dir.db_file.rm_paths(old_paths)
