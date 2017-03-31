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
    ServerError, AvailableSpaceError, FileTransferError)
from zielen.basecommand import Command
from zielen.io.transfer import rec_clone


class ResetCommand(Command):
    """Retrieve files from the remote and de-initialize the local directory.

    Attributes:
        profile: The currently selected profile.
        local_dir: A LocalSyncDir object representing the local directory.
        dest_dir: A DestSyncDir object representing the destination directory.
        connection: A Connection object representing the connection to the
            remote directory.
        keep_remote: Keep a copy of the files in the remote directory.
        no_retrieve: Don't copy files to the local directory.
    """
    def __init__(self, profile_input: str, keep_remote=False,
                 no_retrieve=False) -> None:
        super().__init__()
        self.profile = self.select_profile(profile_input)
        self.keep_remote = keep_remote
        self.no_retrieve = no_retrieve

    def main(self) -> None:
        """Run the command."""
        self.setup_profile()

        if not self.no_retrieve:
            # Check if there is enough space locally to accommodate remote
            # files.
            if self.dest_dir.disk_usage() > self.local_dir.space_avail():
                raise AvailableSpaceError(
                    "not enough local space to accommodate remote files")

            # Retrieve remote files.
            try:
                rec_clone(
                    self.dest_dir.safe_path, self.local_dir.path,
                    files=self.dest_dir.db_file.get_tree(deleted=False),
                    msg="Retrieving files...",
                    rm_source=not self.keep_remote)
            except FileNotFoundError:
                raise ServerError(
                    "the connection to the remote directory was lost")

            if not self.keep_remote:
                # Remove files marked for deletion from the remote directory.
                for rel_path in self.dest_dir.db_file.get_tree(deleted=True):
                    try:
                        os.remove(
                            os.path.join(self.dest_dir.safe_path, rel_path))
                    except FileNotFoundError:
                        pass

                # Close the database connection, and then remove the program
                # directory. If the database connection is not closed,
                # the program directory will not be able to be deleted.
                self.dest_dir.db_file.conn.close()
                shutil.rmtree(self.dest_dir.prgm_dir)

                # Check that the remote directory is empty.
                if self.dest_dir.get_paths(dirs=False):
                    raise FileTransferError("some files were not retrieved")

        # Remove non-user-created symlinks from the local directory.
        program_links = (self.local_dir.get_paths(
            rel=True, files=False, dirs=False).keys()
            & self.profile.db_file.get_tree())
        for rel_path in program_links.items():
            os.remove(os.path.join(self.local_dir.path, rel_path))

        # Remove exclude pattern file from the program directory if it
        # hasn't already been deleted.
        try:
            os.remove(os.path.join(
                self.dest_dir.ex_dir, self.profile.info_file.vals["ID"]))
        except FileNotFoundError:
            pass

        # Unmount the remote directory and delete the profile directory.
        if self.profile.cfg_file.vals["RemoteHost"]:
            # The directory will not unmount if the database connection is
            # still open.
            self.dest_dir.db_file.conn.close()
            self.connection.unmount(self.profile.mnt_dir)
        shutil.rmtree(self.profile.path)
