"""Perform operations on sync directories.

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
import sqlite3
import datetime
from typing import Tuple

from retainsync.util.misc import rec_scan


class SyncDir:
    """Perform operations on a sync directory.

    Attributes:
        path:   The directory path without a trailing slash.
        tpath:  The directory path including a trailing slash.
    """

    def __init__(self, path: str) -> None:
        self.path = path.rstrip("/")
        self.tpath = os.path.join(path, "")

    def list_files(self, rel=False) -> str:
        """Get the paths of files in the directory.

        Yields:
            An absolute file path for each file in the directory.
        """
        for entry in rec_scan(self.path):
            if not entry.is_dir(follow_symlinks=False):
                if rel:
                    yield os.path.relpath(entry.path, self.path)
                else:
                    yield entry.path

    def list_mtimes(self, rel=False) -> Tuple[str, float]:
        """Get the paths and mtimes of files in the directory.

        Yields:
            An absolute path and an mtime for each file in the directory.
        """
        for entry in rec_scan(self.path):
            if not entry.is_dir(follow_symlinks=False):
                mtime = entry.stat(follow_symlinks=False).st_mtime
                if rel:
                    yield os.path.relpath(entry.path, self.path), mtime
                else:
                    yield entry.path, mtime

    def list_dirs(self, rel=False) -> str:
        """Get the paths of subdirectories in the directory.

        Yields:
            An absolute file path for each directory in the directory.
        """
        for entry in rec_scan(self.path):
            if entry.is_dir(follow_symlinks=False):
                if rel:
                    yield os.path.relpath(entry.path, self.path)
                else:
                    yield entry.path

    def total_size(self) -> int:
        """Get the total size of the directory and all of its contents.

        Returns:
            The total size of the directory in bytes.
        """
        total_size = 0
        for entry in rec_scan(self.path):
            total_size += entry.stat(follow_symlinks=False).st_size
        return total_size

    def space_avail(self) -> int:
        """Get the available space in the filesystem the directory is in.

        Returns:
            The amount of free space in bytes.
        """
        fs_stats = os.statvfs(self.path)
        return fs_stats.f_bsize * fs_stats.f_bavail

    def symlink_tree(self, destdir: str, overwrite=False) -> None:
        """Recursively copy the directory as a tree of symlinks.

        Args:
            destdir:    The directory to create symlinks in.
            overwrite:  Overwrite existing files in the destination directory
                        with symlinks.
        """
        os.makedirs(destdir, exist_ok=True)
        for entry in rec_scan(self.path):
            destfile = os.path.join(
                destdir, os.path.relpath(entry.path, self.path))
            if entry.is_dir(follow_symlinks=False):
                os.makedirs(destfile, exist_ok=True)
            else:
                try:
                    os.symlink(entry.path, destfile)
                except FileExistsError:
                    if overwrite:
                        os.remove(destfile)
                        os.symlink(entry.path, destfile)


class LocalSyncDir(SyncDir):
    """Perform operations on a local sync directory."""
    def  __init__(self, path):
        super().__init__(path)
        os.makedirs(path)


class DestSyncDir(SyncDir):
    """Perform operations on a remote sync directory.

    Attributes:
        prgm_dir:   Contains special program files.
        safe_path:  Defined relative to prgm_dir in order to prevent access
                    when prgm_dir is missing.
        ex_dir:     Contains copies of each client's exclude pattern file.
        db_file:    Contains a list of deleted files in the remote.
    """
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.prgm_dir = os.path.join(self.path, ".retain-sync")
        self.safe_path = os.path.join(self.prgm_dir, "..")
        self.ex_dir = os.path.join(self.prgm_dir, "exclude")
        self.db_file = DestDBFile(os.path.join(self.prgm_dir, "remote.db"))


class DestDBFile:
    """Manipulate the remote file database.

    Attributes:
        path:   The path to the database file.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    def create(self) -> None:
        """Create a new empty database.

        Database Columns:
            path:       The relative path to the file.
            lastsync:   The date and time (UTC) that the file was last updated
                        by a sync in seconds since the epoch.
            trash:      A boolean representing whether the file is considered
                        to be in the trash.
        """
        self.conn = sqlite3.connect(
            self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.cur = self.conn.cursor()
        # Create adapter from python boolean to sqlite integer.
        sqlite3.register_adapter(bool, int)
        sqlite3.register_converter("boolean", lambda x: bool(int(x)))

        with self.conn:
            self.cur.execute("""\
                CREATE TABLE files (
                    path text,
                    lastsync real,
                    deleted boolean
                );
                """)

    def add_file(self, path: str) -> None:
        """Add a new file path to the database.

        Args:
            path:   The file path to add.
        """
        with self.conn:
            self.cur.execute("""\
                INSERT INTO files (path)
                    SELECT ?
                WHERE NOT EXISTS (SELECT 1 FROM files WHERE path=?);
                """, (path, path))

    def rm_file(self, path: str) -> None:
        """Remove a file path from the database.
        Args:
            path:   The file path to remove.
        """
        with self.conn:
            self.cur.execute("""\
                DELETE FROM files
                WHERE path=?;
                """, (path,))

        def set_trash(self, path: str, boolean: bool) -> None:
            """Mark a file path as being in the trash or not.
            Args:
                path:       The file path to set.
                boolean:    The boolean value to set the 'trash' column to.
            """
            if type(boolean) is not bool:
                raise TypeError("Expected boolean")

            with self.conn:
                self.cur.execute("""\
                    UPDATE files
                    SET trash=?
                    WHERE path=?;
                    """, (boolean, path))

        def update_synctime(self, path: str) -> None:
            """Update the time of the last sync.

            Args:
                path:   The file path to set.
            """
            utc_now = datetime.datetime.utcnow().replace(
                tzinfo=datetime.timezone.utc).timestamp()
            with self.conn:
                self.cur.execute("""\
                    UPDATE files
                    SET lastsync=?
                    WHERE path=?;
                    """, (utc_now, path))
