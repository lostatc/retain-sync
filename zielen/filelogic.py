"""High-level file transfer operations and logic.

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
import copy
import time
import shutil
from typing import Iterable, Tuple, Set, NamedTuple

from zielen.exceptions import RemoteError, AvailableSpaceError
from zielen.profile import Profile, ProfileExcludeFile
from zielen.userdata import LocalSyncDir, RemoteSyncDir
from zielen.utils import timestamp_path
from zielen.fstools import (
    is_unsafe_symlink, symlink_tree, transfer_tree, update_mtime)

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


class PathsDiff:
    """Compare two sets of file paths.

    This class tracks two sets of file paths, the 'initial' set and the
    'resultant' set. Both sets of file paths are the same initially. All
    methods modify the second set of file paths, as the first set never
    changes.

    Args:
        starting_paths: The file paths used to populate the initial set.

    Attributes:
        _path_pairs: A set of tuples each containing a pair of file paths, with
            the first belonging to the initial set and the second belonging to
            the resultant set. For paths that are in one set and not the other,
            the other item in the tuple will be None.
        init_paths: The set of all paths that are in the initial set.
        res_paths: The set of all paths that are in the resultant set.
        mod_paths: The set of all path pairs where both paths exist and are
            different.
    """
    def __init__(self, starting_paths: Iterable[str]) -> None:
        self._path_pairs = {(path, path) for path in starting_paths}

    def rm(self, paths: Iterable[str]) -> None:
        """Remove paths from the resultant set.

        Args:
            paths: The paths to remove from the resultant set.
        """
        for rm_path in paths:
            self._path_pairs = {
                (init_path, None)
                if res_path == rm_path else (init_path, res_path)
                for init_path, res_path in self._path_pairs}

    def add(self, paths: Iterable[str]) -> None:
        """Add paths to the resultant set.

        Args:
            paths: The paths to add to the resultant set.
        """
        add_pairs = {(None, path) for path in paths}
        self._path_pairs |= add_pairs

    def rename(self, new_pairs: Iterable[Tuple[str, str]]) -> None:
        """Give paths in the initial set a new name in the resultant set.

        Args:
            new_pairs: Tuples each containing a pair of file paths, with the
                first being an existing file path in the initial set and the
                second being the new name to give it in the resultant set.
        """
        for old_path, new_path in new_pairs:
            self._path_pairs = {
                (init_path, new_path)
                if init_path == old_path else (init_path, res_path)
                for init_path, res_path in self._path_pairs}

    @property
    def init_paths(self) -> Set[str]:
        """Get all paths in the initial set.

        Returns:
            The set of file paths in the initial set.
        """
        paths = {
            old_path for old_path, new_path in self._path_pairs if old_path}
        return paths

    @property
    def res_paths(self) -> Set[str]:
        """Get all paths in the resultant set.

        Returns:
            The set of file paths in teh resultant set.
        """
        paths = {
            new_path for old_path, new_path in self._path_pairs if new_path}
        return paths

    @property
    def mod_paths(self) -> Set[Tuple[str, str]]:
        """Get all path pairs that are not the same in each set.

        Returns:
            The set of tuples each containing a path from the initial set and a
            path from the resultant set where both are different and not None.
        """
        paths = {
            (new_path, old_path) for new_path, old_path in self._path_pairs
            if new_path and old_path and new_path != old_path}
        return paths

    def __or__(self, in_object):
        """Create a new FilesDiff object that is the union of two others.

        Args:
            in_object: The FilesDiff object to get file paths from.
        """
        if isinstance(in_object, type(self)):
            new_self = copy.deepcopy(self)
            new_self._path_pairs |= in_object._path_pairs
            return new_self
        else:
            raise TypeError(
                "unsupported operand type(s) for |: '{0}' and '{1}'".format(
                    type(self), type(in_object)))


class FilesManager:
    """Manage the movement of files in the local and remote directories.

    Args:
        local_dir: A LocalSyncDir object for the local directory.
        remote_dir: A RemoteSyncDir object for the remote directory.
        profile: A Profile object for the current profile.

    Attributes:
        local_dir: A LocalSyncDir object for the local directory.
        remote_dir: A RemoteSyncDir object for the remote directory.
        profile: A Profile object for the current profile.
    """
    def __init__(
            self, local_dir: LocalSyncDir, remote_dir: RemoteSyncDir,
            profile: Profile) -> None:
        self.local_dir = local_dir
        self.remote_dir = remote_dir
        self.profile = profile

    def prioritize_files(
            self, space_limit: int, exclude=None) -> SelectedPaths:
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

        # File stats must be fetched again because files in the remote 
        # directory may have been updated by changes in the local directory,
        # changin their size. 
        local_files = self.profile.get_paths(directory=False)
        file_stats = self.remote_dir.scan_paths(dirs=False, memoize=False)
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
                if self.profile.account_for_size:
                    try:
                        adjusted_priorities.append((
                            file_path, file_priority / file_size, file_size))
                    except ZeroDivisionError:
                        adjusted_priorities.append((file_path, 0, file_size))
                else:
                    adjusted_priorities.append((
                        file_path, file_priority, file_size))

        # Sort files by priority. Files of the same priority are sorted by
        # file path so that the results of a sync are always predictable.
        # That way, multiple consecutive syncs won't prioritize files
        # differently.
        adjusted_priorities.sort(key=lambda x: x[0])
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

    def prioritize_dirs(self, space_limit: int) -> SelectedPaths:
        """Calculate which directories will stay in the local directory.

        Args:
            space_limit: The amount of space remaining in the directory
                (in bytes).
        Returns:
            A tuple containing a list of paths of directories to keep in the
            local directory and the amount of space remaining (in bytes) until
            the storage limit is reached.
        """
        # File stats must be fetched again because files in the remote 
        # directory may have been updated by changes in the local directory,
        # changin their size. 
        local_files = self.profile.get_paths(directory=False)
        local_dirs = self.profile.get_paths(directory=True)
        dir_stats = self.remote_dir.scan_paths(memoize=False)
        adjusted_priorities = []

        # Calculate the disk usage of each directory and adjust directory
        # priorities for size.
        for dir_path, dir_data in local_dirs.items():
            dir_priority = dir_data.priority
            dir_size = 0
            for sub_path in self.remote_dir.get_paths(root=dir_path):
                # Get the size of the files in the remote directory, as
                # symlinks in the local directory are not followed.
                dir_size += dir_stats[sub_path].st_blocks * 512

            if self.profile.account_for_size:
                try:
                    adjusted_priorities.append((
                        dir_path, dir_priority / dir_size, dir_size))
                except ZeroDivisionError:
                    adjusted_priorities.append((dir_path, 0, dir_size))
            else:
                adjusted_priorities.append((dir_path, dir_priority, dir_size))

        # Sort directories by priority. Directories of the same priority are
        # sorted by file path so that the results of a sync are always
        # predictable. That way, multiple consecutive syncs won't prioritize
        # files differently.
        adjusted_priorities.sort(key=lambda x: x[0])
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
        # which should each have a disk usage of one block. For evey file
        # that is selected, one block will be added back to the remaining
        # space.
        symlink_size = os.stat(self.local_dir.path).st_blksize
        remaining_space = space_limit - len(local_files) * symlink_size
        for dir_path in prioritized_dirs:
            dir_size = dir_sizes[dir_path]

            if dir_path in selected_subdirs:
                # The current directory is a subdirectory of a directory
                # that has already been selected. Skip it.
                continue

            if dir_size > self.profile.storage_limit:
                # The current directory alone is larger than the storage limit.
                # Skip it.
                continue

            # Find all subdirectories of the current directory that are
            # already in the set of selected files.
            contained_files = set()
            contained_dirs = set()
            subdirs_size = 0
            for subpath, subpath_data in self.profile.get_paths(
                    root=dir_path).items():
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
            if new_remaining_space >= 0:
                # Add the current directory to the set of selected files and
                # remove all of its subdirectories from the set.
                selected_subdirs |= contained_dirs
                selected_files |= contained_files
                selected_dirs -= contained_dirs
                selected_dirs.add(dir_path)
                remaining_space = new_remaining_space

        return SelectedPaths(remaining_space, selected_dirs)

    def update_local(self, update_paths: Iterable[str]) -> None:
        """Update the local directory with remote files.

        Args:
            update_paths: The paths of files and directories to copy from the
                remote directory to the local one. All other files in the local
                directory are replaced with symlinks.
        """
        update_paths = set(update_paths)

        # Sort the file paths so that a directory's contents always come
        # before the directory itself.
        stale_paths = list(self.compute_stale(update_paths))
        stale_paths.sort(key=lambda x: x.count(os.sep), reverse=True)

        # Remove old, unneeded files to make room for new ones.
        for stale_path in stale_paths:
            full_stale_path = os.path.join(self.local_dir.path, stale_path)
            if os.path.islink(full_stale_path):
                # The path will just be replaced with a symlink anyways.
                continue
            try:
                os.remove(full_stale_path)
            except IsADirectoryError:
                try:
                    os.rmdir(full_stale_path)
                except OSError:
                    # There are still files in the directory. This could
                    # happen if there were symbolic links in the directory
                    # that weren't deleted.
                    pass

        try:
            nonlocal_paths = symlink_tree(
                self.remote_dir.safe_path, self.local_dir.path,
                self.remote_dir.get_paths(directory=False),
                self.remote_dir.get_paths(directory=True))

            transfer_tree(
                self.remote_dir.safe_path, self.local_dir.path,
                files=update_paths,
                message="Updating local files...")
        except FileNotFoundError:
            if not os.path.isdir(self.remote_dir.util_dir):
                raise RemoteError("the remote directory could not be found")
            else:
                raise

        # Update the database with information about which paths are being
        # kept in the local directory.
        for update_path in update_paths:
            self.profile.update_paths(
                self.profile.get_paths(root=update_path).keys(), local=True)
        self.profile.update_paths(nonlocal_paths, local=False)

    def update_remote(self, update_paths: Iterable[str]) -> None:
        """Update the remote directory with local files.

        Args:
            update_paths: The relative paths of local files to update the
                remote directory with.
        Raises:
            RemoteError: The remote directory is unmounted.
        """
        # Copy modified local files to the remote directory.
        try:
            transfer_tree(
                self.local_dir.path, self.remote_dir.safe_path,
                files=update_paths, message="Updating remote files...")
        except FileNotFoundError:
            if not os.path.isdir(self.remote_dir.util_dir):
                raise RemoteError("the remote directory could not be found")
            else:
                raise

        # Update the time of the last sync for files that have been modified.
        self.remote_dir.update_paths(update_paths, lastsync=time.time())

    def _setup_dir(self, unsafe_symlinks: Set[str]) -> None:
        """Add file paths to both databases and overwrite with symlinks.

        Args:
            unsafe_symlinks: The paths of symlinks that should not be included.
        """
        remote_files = self.remote_dir.scan_paths(
            dirs=False).keys() - unsafe_symlinks
        remote_dirs = self.remote_dir.scan_paths(
            files=False, symlinks=False).keys()

        self.profile.add_paths(remote_files, remote_dirs, local=False)
        self.remote_dir.add_paths(remote_files, remote_dirs)

        # Overwrite local files with symlinks to the corresponding files in the
        # remote dir.
        symlink_tree(
            self.remote_dir.safe_path, self.local_dir.path,
            self.profile.get_paths(directory=False),
            self.profile.get_paths(directory=True),
            overwrite=True)

    def setup_from_local(self) -> None:
        """Copy initial local files to remote directory and symlink back."""
        unsafe_symlinks = {
            link_path for link_path in self.local_dir.scan_paths(
                files=False, dirs=False).keys()
            if is_unsafe_symlink(
                os.path.join(self.local_dir.path, link_path),
                self.local_dir.path)}

        # Check that there is enough remote space to accommodate local
        # files.
        if self.local_dir.disk_usage() > self.remote_dir.space_avail():
            raise AvailableSpaceError(
                "not enough space in remote to accommodate local files")

        try:
            transfer_tree(
                self.local_dir.path, self.remote_dir.safe_path,
                exclude=(
                    self.profile.all_exclude_matches(self.local_dir.path)
                    | unsafe_symlinks),
                message="Moving files to remote...")
        except FileNotFoundError:
            if not os.path.isdir(self.remote_dir.util_dir):
                raise RemoteError("the remote directory could not be found")
            else:
                raise

        self._setup_dir(unsafe_symlinks)

    def setup_from_remote(self) -> None:
        """Symlink initial remote files to the local directory."""
        unsafe_symlinks = {
            link_path for link_path in self.remote_dir.scan_paths(
                files=False, dirs=False).keys()
            if is_unsafe_symlink(
                os.path.join(self.remote_dir.path, link_path),
                self.remote_dir.path)}

        self._setup_dir(unsafe_symlinks)

    def handle_conflicts(
            self, local_paths: Iterable[str], remote_paths: Iterable[str]
            ) -> UpdatedPaths:
        """Handle sync conflicts between local and remote files.

        Conflicts are handled by renaming the file that was modified least
        recently to signify to the user that there was a conflict. Conflicts
        are resolved on a file-by-file basis, so directories do not
        experience conflicts. These new files aren't treated specially and
        are synced just like any other file.

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
            in self.local_dir.scan_paths().items()}
        remote_mtimes = {
            path: data.st_mtime for path, data
            in self.remote_dir.scan_paths().items()}

        local_diff = PathsDiff(local_paths)
        remote_diff = PathsDiff(remote_paths)

        for path in conflict_paths:
            new_path = timestamp_path(path, keyword="conflict")
            path_data = self.profile.get_path_info(path)
            if path_data and path_data.directory:
                continue
            elif local_mtimes[path] < remote_mtimes[path]:
                local_diff.rename([(path, new_path)])
            elif remote_mtimes[path] < local_mtimes[path]:
                remote_diff.rename([(path, new_path)])

        if local_diff.mod_paths:
            self.rename_local_files(local_diff.mod_paths)
        if remote_diff.mod_paths:
            self.rename_remote_files(remote_diff.mod_paths)

        return UpdatedPaths(local_diff.res_paths, remote_diff.res_paths)

    def compute_stale(self, retained_paths: Iterable[str]) -> Set[str]:
        """Compute the paths of files that are unneeded.

        This method returns the paths of local files that are not included
        in the set of input paths and are not parents or children of any
        path in the set of input paths.

        Args:
            retained_paths: The relative paths of files that are to be retained
                and do not need to be removed.

        Returns:
            The relative paths of files that are unneeded and should be removed
            to make room for new files.
        """
        retained_paths = set(retained_paths)

        # Create a set including all the files and directories contained in
        # each directory from the input.
        all_retained_paths = set()
        for path in retained_paths:
            all_retained_paths |= self.profile.get_paths(root=path).keys()

        # Don't include excluded files or files not in the local database
        # (e.g. unsafe symlinks).
        all_paths = (self.local_dir.scan_paths(
            exclude=self.profile.all_exclude_matches(self.local_dir.path)
            ).keys() & self.profile.get_paths().keys())

        # Exclude the paths that are parents of paths in the input.
        stale_paths = set()
        for path in all_paths - all_retained_paths:
            if not (self.profile.get_paths(path).keys() & all_retained_paths):
                stale_paths.add(path)

        return stale_paths

    def compute_added(self) -> UpdatedPaths:
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
            path for path in self.local_dir.scan_paths().keys()
            if not self.profile.get_path_info(path)
            and not is_unsafe_symlink(
                os.path.join(self.local_dir.path, path), self.local_dir.path)}
        new_local_paths -= self.profile.all_exclude_matches(
            self.local_dir.path)
        new_remote_paths = {
            path for path in self.remote_dir.scan_paths().keys()
            if not self.profile.get_path_info(path)}

        return UpdatedPaths(new_local_paths, new_remote_paths)

    def compute_modified(self) -> UpdatedPaths:
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
        last_sync = self.profile.last_sync

        local_mtimes = (
            (path, data.st_mtime) for path, data in self.local_dir.scan_paths(
                dirs=False).items())
        remote_mtimes = (
            (path, data.st_mtime) for path, data in self.remote_dir.scan_paths(
                dirs=False).items())

        # Only include file paths that are in the database to exclude files
        # that are new since the last sync.
        local_mod_paths = {
            path for path, mtime in local_mtimes
            if mtime > last_sync and self.profile.get_path_info(path)
            and not is_unsafe_symlink(
                os.path.join(self.local_dir.path, path), self.local_dir.path)}
        remote_mod_paths = {
            path for path, mtime in remote_mtimes
            if mtime > last_sync and self.profile.get_path_info(path)}

        remote_mod_paths |= self.remote_dir.get_paths(
            directory=False, min_lastsync=last_sync).keys()

        return UpdatedPaths(local_mod_paths, remote_mod_paths)

    def compute_deleted(self) -> DeletedPaths:
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
        local_paths = self.local_dir.scan_paths().keys()
        remote_paths = self.remote_dir.scan_paths().keys()
        known_paths = self.profile.get_paths().keys()

        # Compute files that need to be deleted, not including the files
        # under selected directories.
        local_del_paths = known_paths - remote_paths
        remote_del_paths = known_paths - local_paths
        for path in local_del_paths.copy():
            sub_paths = set(self.profile.get_paths(root=path).keys())
            sub_paths.remove(path)
            local_del_paths -= sub_paths
        for path in remote_del_paths.copy():
            sub_paths = set(self.remote_dir.get_paths(root=path).keys())
            sub_paths.remove(path)
            remote_del_paths -= sub_paths

        # Compute files to be moved to the trash.
        if self.profile.use_trash:
            trash_paths = (
                remote_del_paths & self.profile.get_paths(local=False).keys())
        else:
            trash_paths = set()
        remote_del_paths -= trash_paths

        return DeletedPaths(local_del_paths, remote_del_paths, trash_paths)

    def _rename_files(
            self, path_pairs: Iterable[Tuple[str, str]],
            parent_dir: str) -> None:
        """Move files to a new path and update the databases.

        Args:
            path_pairs: The relative paths of existing local files to be
                renamed (first) and their new paths (second).
            parent_dir: The directory in which the paths to be renamed reside.
        """
        for old_path, new_path in path_pairs:
            os.rename(
                os.path.join(parent_dir, old_path),
                os.path.join(parent_dir, new_path))

        old_paths = (old_path for old_path, new_path in path_pairs)

        # Separate paths of directories from paths of regular files based on
        # whether the old paths are entered as directories in the database.
        new_file_paths = set()
        new_dir_paths = set()
        for old_path, new_path in path_pairs:
            path_info = self.profile.get_path_info(old_path)
            if path_info and path_info.directory:
                new_dir_paths.add(new_path)
            else:
                new_file_paths.add(new_path)

        self.profile.rm_paths(old_paths)
        self.remote_dir.rm_paths(old_paths)
        self.profile.add_paths(new_file_paths, new_dir_paths)
        self.remote_dir.add_paths(new_file_paths, new_dir_paths)

    def rename_local_files(
            self, path_pairs: Iterable[Tuple[str, str]]) -> None:
        """Move local files to a new path and update the databases.

        Args:
            path_pairs: The relative paths of existing local files to be
                renamed (first) and their new paths (second).
        """
        self._rename_files(path_pairs, self.local_dir.path)

    def rename_remote_files(
            self, path_pairs: Iterable[Tuple[str, str]]) -> None:
        """Move remote files to a new path and update the databases.

        Args:
            path_pairs: The relative paths of existing local files to be
                renamed (first) and their new paths (second).
        """
        try:
            self._rename_files(path_pairs, self.remote_dir.safe_path)
        except FileNotFoundError:
            if not os.path.isdir(self.remote_dir.util_dir):
                raise RemoteError("the remote directory could not be found")
            else:
                raise

    def _rm_files(self, paths: Iterable[str], parent_dir: str) -> None:
        """Delete files and remove them from both databases.

        Args:
            paths: The relative paths of files to remove.
            parent_dir: The directory in which the paths to be deleted reside.
        """
        for path in paths:
            full_path = os.path.join(parent_dir, path)
            try:
                os.remove(full_path)
            except IsADirectoryError:
                shutil.rmtree(full_path)
            except FileNotFoundError:
                # This could happen if a previous sync was interrupted.
                pass

        self.profile.rm_paths(paths)
        self.remote_dir.rm_paths(paths)

    def rm_local_files(self, paths: Iterable[str]) -> None:
        """Delete local files and remove them from both databases.

        If the files are excluded, don't delete them, but still remove them
        from both databases.

        Args:
            paths: The relative paths of files to remove.
        """
        paths = set(paths)
        paths -= self.profile.all_exclude_matches(self.local_dir.path)
        self._rm_files(paths, self.local_dir.path)

    def rm_remote_files(self, paths: Iterable[str]) -> None:
        """Delete remote files and remove them from both databases.

        Args:
            paths: The relative paths of files to remove.
        """
        self._rm_files(paths, self.remote_dir.path)

    def rm_excluded_files(self, excluded_paths: Iterable[str]) -> None:
        """Remove excluded files from the remote directory.

        Remove files from the remote directory only if they've been excluded
        by each client. Also remove them from both databases.

        Args:
            excluded_paths: The paths of excluded files to remove.
        """
        rm_paths = self.remote_dir.check_excluded(
            excluded_paths, self.local_dir.path)
        rm_paths &= self.remote_dir.get_paths().keys()
        self.rm_remote_files(rm_paths)

    def trash_files(self, paths: Iterable[str]) -> None:
        """Move files in the remote directory to the trash.

        This involves moving the file to the trash directory and removing its
        entry from both databases.

        Args:
            paths: The relative paths of files to move to the trash.
        """
        try:
            os.mkdir(self.remote_dir.trash_dir)
        except FileExistsError:
            pass
        except FileNotFoundError:
            if not os.path.isdir(self.remote_dir.util_dir):
                raise RemoteError("the remote directory could not be found")
            else:
                raise

        trash_filenames = {
            entry.name for entry in os.scandir(self.remote_dir.trash_dir)}
        old_paths = list(paths)
        old_filenames = [os.path.basename(path) for path in old_paths]

        # Come up with a new filename if the current one collides with the
        # name of an existing file in the trash.
        new_filenames = []
        for old_filename in old_filenames:
            new_filename = old_filename
            filename_counter = 0
            name, extension = os.path.splitext(new_filename)
            while new_filename in trash_filenames:
                filename_counter += 1
                new_filename = "{0}({1}){2}".format(
                    name, filename_counter, extension)
            new_filenames.append(new_filename)

        for old_path, new_filename in zip(old_paths, new_filenames):
            abs_old_path = os.path.join(self.remote_dir.safe_path, old_path)
            abs_new_path = os.path.join(
                self.remote_dir.trash_dir, new_filename)
            try:
                os.rename(abs_old_path, abs_new_path)
                update_mtime(abs_new_path)
            except FileNotFoundError:
                # This could happen if a previous sync was interrupted.
                pass

        self.profile.rm_paths(old_paths)
        self.remote_dir.rm_paths(old_paths)

    def cleanup_trash(self) -> None:
        """Delete old files from the remote trash directory."""
        cutoff_time = time.time() - self.profile.cleanup_period
        for entry in os.scandir(self.remote_dir.trash_dir):
            if entry.stat().st_mtime <= cutoff_time:
                try:
                    shutil.rmtree(entry.path)
                except NotADirectoryError:
                    os.remove(entry.path)
