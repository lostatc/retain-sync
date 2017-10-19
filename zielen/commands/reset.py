"""A class for the 'reset' command.

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

from zielen.exceptions import (
    RemoteError, AvailableSpaceError, FileTransferError)
from zielen.io import rec_clone
from zielen.commandbase import Command, unlock


class ResetCommand(Command):
    """Run the "reset" command.

    Attributes:
        profile: The currently selected profile.
        local_dir: A LocalSyncDir object representing the local directory.
        remote_dir: A RemoteSyncDir object representing the remote directory.
        keep_remote: The "--keep-remote" option was given.
        no_retrieve: The "--no-retrieve" option was given.
    """
    def __init__(self, profile_input: str, keep_remote=False,
                 no_retrieve=False) -> None:
        super().__init__()
        self.profile = self.select_profile(profile_input)
        self.keep_remote = keep_remote
        self.no_retrieve = no_retrieve

    @unlock
    def main(self) -> None:
        """Run the command.

        Raises:
            RemoteError: The remote directory could not be found.
        """
        self.setup_profile()

        if not self.no_retrieve:
            # Check if there is enough space locally to accommodate remote
            # files.
            if self.remote_dir.disk_usage() > self.local_dir.space_avail():
                raise AvailableSpaceError(
                    "not enough local space to accommodate remote files")

            # Retrieve remote files.
            try:
                rec_clone(
                    self.remote_dir.safe_path, self.local_dir.path,
                    files=self.remote_dir.get_paths(),
                    msg="Retrieving files...",
                    rm_source=not self.keep_remote)
            except FileNotFoundError:
                if not os.path.isdir(self.remote_dir.util_dir):
                    raise RemoteError(
                        "the remote directory could not be found")
                else:
                    raise

            if not self.keep_remote:
                # Check that the remote directory contains only empty
                # directories and the util directory.
                if self.remote_dir.scan_paths(dirs=False, memoize=False):
                    raise FileTransferError("some files were not retrieved")

                # Close the database connection, and then remove the
                # contents of the remote directory. If the database
                # connection is not closed, the util directory will not be
                # able to be deleted.
                self.remote_dir.close()
                try:
                    for entry in os.scandir(self.remote_dir.path):
                        if entry.is_dir:
                            shutil.rmtree(entry.path)
                        else:
                            os.remove(entry.path)
                except FileNotFoundError:
                    pass

        # Remove non-user-created symlinks from the local directory. These
        # are symlinks that point to the remote directory.
        local_symlinks = self.local_dir.scan_paths(
            files=False, dirs=False).keys()
        for rel_path in local_symlinks:
            full_path = os.path.join(self.local_dir.path, rel_path)
            link_dest = os.readlink(full_path)
            if not os.path.isabs(link_dest):
                link_dest = os.path.join(os.path.dirname(full_path), link_dest)
            if os.path.commonpath([
                    link_dest,
                    self.remote_dir.safe_path]) == self.remote_dir.safe_path:
                os.remove(full_path)

        self.remote_dir.rm_exclude_file(self.profile.id)
        shutil.rmtree(self.profile.path)
