"""A class for the 'sync' command.

Copyright © 2016-2018 Garrett Powell <garrett@gpowell.net>

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
from typing import Iterable, Set, NamedTuple, Tuple, List

from zielen.commandbase import Command, unlock
from zielen.filelogic import FilesManager

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
    """Run the "sync" command.

    Attributes:
        profile: The currently selected profile.
    """
    def __init__(self, profile_input: str) -> None:
        super().__init__()
        self.profile = self.select_profile(profile_input)

    @unlock
    def main(self) -> None:
        """Run the command."""
        self.setup_profile()
        fm = FilesManager(self.local_dir, self.remote_dir, self.profile)
        self.remote_dir.add_exclude_file(self.profile.exclude_path, self.profile.id)

        # Scan the local and remote directories.
        file_paths = (
            self.local_dir.scan_paths(dirs=False).keys()
            | self.remote_dir.scan_paths(dirs=False).keys())
        dir_paths = (
            self.local_dir.scan_paths(files=False, symlinks=False).keys()
            | self.remote_dir.scan_paths(files=False, symlinks=False).keys())

        # Get the paths of files that have been added, deleted or modified
        # since the last sync.
        new_paths = fm.compute_added()
        del_paths = fm.compute_deleted()
        mod_paths = fm.compute_modified()

        # Add new files to both databases, and inflate the priority of new
        # local files.
        new_local_files = (new_paths.local - dir_paths)
        new_local_dirs = (new_paths.local - file_paths)
        new_file_paths = (new_paths.all - dir_paths)
        new_dir_paths = (new_paths.all - file_paths)
        if self.profile.inflate_priority:
            self.profile.add_inflated(new_local_files, new_local_dirs)
        self.remote_dir.add_paths(new_file_paths, new_dir_paths)
        self.profile.add_paths(new_file_paths, new_dir_paths)

        # Sync deletions between the local and remote directories.
        fm.rm_local_files(del_paths.local)
        fm.rm_remote_files(del_paths.remote)
        fm.trash_files(del_paths.trash)

        # Handle syncing conflicts.
        updated_paths = fm.handle_conflicts(
            mod_paths.local | new_paths.local,
            mod_paths.remote | new_paths.remote)

        # Add any new files that have been created in the process of
        # handling conflicts to both databases.
        if self.profile.inflate_priority:
            self.profile.add_inflated(updated_paths.local, [])
        self.remote_dir.add_paths(updated_paths.all, [])
        self.profile.add_paths(updated_paths.all, [])

        # Update the remote directory with modified local files.
        fm.update_remote(updated_paths.local)

        # At this point, the differences between the two directories have been
        # resolved.

        # Calculate which excluded files are still in the remote directory.
        remote_excluded_files = (
            self.profile.all_exclude_matches(self.local_dir.path)
            & self.remote_dir.scan_paths().keys())

        # Decide which files and directories to keep in the local directory.
        remaining_space = self.profile.storage_limit - fm.get_excluded_size()
        remaining_space, selected_dirs = fm.prioritize_dirs(remaining_space)
        remaining_space, selected_files = fm.prioritize_files(
            remaining_space, exclude=selected_dirs)

        # Copy the selected files as well as any excluded files still in the
        # remote directory to the local directory and replace all others
        # with symlinks.
        fm.update_local(selected_dirs | selected_files | remote_excluded_files)

        # Remove excluded files that are still in the remote directory.
        fm.rm_excluded_files(remote_excluded_files)

        # Clean up the remote trash directory.
        if self.profile.cleanup_period:
            fm.cleanup_trash()

        # The sync is now complete. Update the time of the last sync in the
        # info file.
        self.remote_dir.write()
        self.profile.last_sync = time.time()
        self.profile.write()
