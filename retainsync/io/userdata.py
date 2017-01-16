"""Perform operations on the user's files and directories.

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
import sqlite3
import datetime
from typing import Tuple, Iterable, List, Set

from retainsync.util.misc import rec_scan, md5sum


class TrashDir:
    """Get information about the user's local trash directory.

    Attributes:
        paths:  The paths to the trash directories.
        sizes:  A list of tuples containing the paths and sizes of every file
                in the trash.
    """
    def __init__(self, paths: Iterable[str]) -> None:
        self.paths = paths
        self._sizes = []

    @property
    def sizes(self) -> List[Tuple[str, int]]:
        """Get the sizes of every file in the trash directory.

        Returns:
            A list of file paths and sizes in bytes.
        """
        if not self._sizes:
            output = []
            for path in self.paths:
                for entry in rec_scan(path):
                    if not entry.is_dir():
                        output.append((
                            entry.path,
                            entry.stat(follow_symlinks=False).st_size))
            self._sizes = output
        return self._sizes

    def check_file(self, path: str) -> bool:
        """Check if a file is in the trash by comparing sizes and checksums."""
        overlap_files = [item[0] for item in self.sizes if
                         os.stat(path).st_size == item[1]]
        if overlap_files:
            overlap_sums = [md5sum(item) for item in overlap_files]
            if md5sum(path) in overlap_sums:
                return True
        return False


class SyncDir:
    """Perform operations on a sync directory.

    Attributes:
        path:   The directory path without a trailing slash.
        tpath:  The directory path including a trailing slash.
    """

    def __init__(self, path: str) -> None:
        self.path = path.rstrip("/")
        self.tpath = os.path.join(path, "")

    def _list_entries(self, rel=False, files=True, symlinks=False, dirs=False,
                      exclude=None):
        """Yield a DirEntry object for each file meeting certain criteria."""
        if exclude is None:
            exclude = set()
        else:
            exclude = set(exclude)

        for entry in rec_scan(self.path):
            if entry.is_file(follow_symlinks=False) and files is False:
                continue
            elif entry.is_dir(follow_symlinks=False) and dirs is False:
                continue
            elif entry.is_symlink() and symlinks is False:
                continue
            else:
                common = {
                    os.path.commonpath([path, entry.path]) for path in exclude}
                if common & exclude:
                    # File is excluded or is in an excluded directory.
                    continue
                else:
                    yield entry

    def list_files(self, rel=False, files=True, symlinks=False,
                   dirs=False, exclude=None) -> str:
        """Get the paths of files in the directory.

        Args:
            rel:        Yield relative file paths.
            files:      Include regular files.
            symlinks:   Include symbolic links.
            dirs:       Include directories.
            exclude:    A list of absolute paths of files to not include.

        Yields:
            A file path for each file in the directory that meets the criteria.
        """
        for entry in self._list_entries(
                rel=rel, files=files, symlinks=symlinks, dirs=dirs,
                exclude=exclude):
            if rel:
                yield os.path.relpath(entry.path, self.path)
            else:
                yield entry.path

    def list_mtimes(self, rel=False, files=True, symlinks=False,
                    dirs=False, exclude=None) -> Tuple[str, float]:
        """Get the paths and mtimes of files in the directory.

        Args:
            rel:        Yield relative file paths.
            files:      Include regular files.
            symlinks:   Include symbolic links.
            dirs:       Include directories.
            exclude:    A list of absolute paths of files to not include.

        Yields:
            A file path and mtime for each file in the directory that meets the
            criteria.
        """
        for entry in self._list_entries(
                rel=rel, files=files, symlinks=symlinks, dirs=dirs,
                exclude=exclude):
            mtime = entry.stat(follow_symlinks=False).st_mtime
            if rel:
                yield os.path.relpath(entry.path, self.path), mtime
            else:
                yield entry.path, mtime

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

    def symlink_tree(self, destdir: str, exclude=None,
                     overwrite=False) -> None:
        """Recursively copy the directory as a tree of symlinks.

        Args:
            destdir:    The directory to create symlinks in.
            overwrite:  Overwrite existing files in the destination directory
                        with symlinks.
            exclude:    A list of absolute paths of files to not symlink.
        """
        if exclude is None:
            exclude = []

        os.makedirs(destdir, exist_ok=True)
        for entry in rec_scan(self.path):
            destfile = os.path.join(
                destdir, os.path.relpath(entry.path, self.path))
            if entry.path in exclude:
                continue
            elif entry.is_dir(follow_symlinks=False):
                try:
                    os.mkdir(destfile)
                except FileNotFoundError:
                    # The directory's parent dir was in the exclude list.
                    pass
                except FileExistsError:
                    pass
            elif entry.is_symlink():
                continue
            else:
                try:
                    os.symlink(entry.path, destfile)
                except FileExistsError:
                    if overwrite:
                        os.remove(destfile)
                        os.symlink(entry.path, destfile)


class LocalSyncDir(SyncDir):
    """Perform operations on a local sync directory."""
    def __init__(self, path):
        super().__init__(path)
        os.makedirs(path, exist_ok=True)


class DestSyncDir(SyncDir):
    """Perform operations on a remote sync directory.

    The "destination directory" is the location in the local filesystem where
    remote files can be accessed. This distinction is important when the remote
    directory is on another computer. In that case, the destination directory
    is the mount point.

    Attributes:
        prgm_dir:   Contains special program files.
        safe_path:  Defined relative to prgm_dir in order to prevent access
                    when prgm_dir is missing.
        ex_dir:     Contains copies of each client's exclude pattern file.
        db_file:    Contains information on files in the remote.
    """
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.prgm_dir = os.path.join(self.path, ".retain-sync")
        self.safe_path = os.path.join(self.prgm_dir, "..")
        self.ex_dir = os.path.join(self.prgm_dir, "exclude")
        self.db_file = DestDBFile(os.path.join(self.prgm_dir, "remote.db"))

    def _list_entries(self, rel=False, files=True, symlinks=False, dirs=False,
                      exclude=None):
        """Extend parent method to automatically exclude program directory."""
        if exclude is None:
            exclude = []
        exclude.append(self.prgm_dir)
        yield from super()._list_entries(
            rel=rel, files=files, symlinks=symlinks, dirs=dirs,
            exclude=exclude)

    def symlink_tree(self, destdir: str, exclude=None,
                     overwrite=False) -> None:
        """Extend parent method to automatically exclude program directory."""
        if exclude is None:
            exclude = []
        exclude.append(self.prgm_dir)
        super().symlink_tree(destdir, exclude=exclude, overwrite=overwrite)


class DestDBFile:
    """Manipulate the remote file database.

    Attributes:
        path:   The path to the database file.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        if os.path.isfile(self.path):
            self.conn = sqlite3.connect(
                self.path, detect_types=sqlite3.PARSE_DECLTYPES)
            self.cur = self.conn.cursor()
        else:
            self.conn = None
            self.cur = None
        # Create adapter from python boolean to sqlite integer.
        sqlite3.register_adapter(bool, int)
        sqlite3.register_converter("bool", lambda x: bool(int(x)))

    def create(self) -> None:
        """Create a new empty database.

        Database Columns:
            path:       The relative path to the file.
            lastsync:   The date and time (UTC) that the file was last updated
                        by a sync in seconds since the epoch.
            trash:      A boolean representing whether the file is considered
                        to be in the trash.

        Raises:
            FileExistsError:    The database file already exists.
        """
        if os.path.isfile(self.path):
            raise FileExistsError

        self.conn = sqlite3.connect(
            self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.cur = self.conn.cursor()

        with self.conn:
            self.cur.execute("""\
                CREATE TABLE files (
                    path text,
                    lastsync real,
                    deleted bool
                );
                """)

    def add_files(self, paths: Iterable[str], deleted=False) -> None:
        """Add new file paths to the database.

        Args:
            paths:  The file paths to add.
        """
        with self.conn:
            for path in paths:
                self.cur.execute("""\
                    INSERT INTO files (path, deleted)
                    SELECT ?, ?
                    WHERE NOT EXISTS (SELECT 1 FROM files WHERE path=?);
                    """, (path, deleted, path))

    def rm_files(self, paths: Iterable[str]) -> None:
        """Remove file paths from the database.

        Args:
            paths:  The file paths to remove.
        """
        with self.conn:
            for path in paths:
                self.cur.execute("""\
                    DELETE FROM files
                    WHERE path=?;
                    """, (path,))

    def update_synctime(self, paths: Iterable[str]) -> None:
        """Update the time of the last sync for some files.

        Args:
            paths:  The file paths to set.
        """
        time = datetime.datetime.utcnow().replace(
            tzinfo=datetime.timezone.utc).timestamp()
        with self.conn:
            for path in paths:
                self.cur.execute("""\
                    UPDATE files
                    SET lastsync=?
                    WHERE path=?;
                    """, (time, path))

    def list_files(self, deleted=None, min_lastsync=None) -> Set[str]:
        """Get a list of file paths that match certain constraints.

        Args:
            deleted:        Select files marked as deleted.
            min_lastsync:   Select files that were last synced more recently
                            than this time.
        """
        sql_command = """\
            SELECT path
            FROM files
            WHERE path IS NOT NULL
            """
        sql_args = []
        if deleted is not None:
            sql_command += "AND deleted=?\n"
            sql_args.append(deleted)
        if min_lastsync is not None:
            sql_command += "AND lastsync>?\n"
            sql_args.append(min_lastsync)
        sql_command += ";"

        with self.conn:
            self.cur.execute(sql_command, sql_args)
        return {path for path, in self.cur.fetchall()}
