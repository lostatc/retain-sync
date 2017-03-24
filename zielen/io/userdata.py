"""Perform operations on the user's files and directories.

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
import sqlite3
import datetime
import shutil
import collections
import functools
from contextlib import contextmanager
from typing import Tuple, Iterable, List, Set, Generator, Dict, NamedTuple

from zielen.exceptions import ServerError
from zielen.util.misc import rec_scan, md5sum, FactoryDict


class TrashDir:
    """Get information about the user's local trash directory.

    Attributes:
        paths: The paths of the trash directories.
        sizes: A list of tuples containing the paths and sizes of every file
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
                        # Because this is being used to determine if files
                        # are identical, the apparent size should be used
                        # instead of the disk usage.
                        output.append((
                            entry.path,
                            entry.stat(follow_symlinks=False).st_size))
            self._sizes = output
        return self._sizes

    def check_file(self, path: str) -> bool:
        """Check if a file is in the trash by comparing sizes and checksums."""
        overlap_files = [filepath for filepath, size in self.sizes if
                         os.stat(path).st_size == size]
        if overlap_files:
            overlap_sums = [md5sum(filepath) for filepath in overlap_files]
            if md5sum(path) in overlap_sums:
                return True
        return False


class SyncDir:
    """Perform operations on a sync directory.

    Attributes:
        path: The directory path without a trailing slash.
    """

    def __init__(self, path: str) -> None:
        self.path = path.rstrip("/")
        self._sub_entries = []

    def get_paths(self, rel=True, files=True, symlinks=True, dirs=True,
                  exclude=None, memoize=True, lookup=True
                  ) -> Dict[str, os.stat_result]:
        """Get the paths and stats of files in the directory.

        Symlinks are not followed. Directory paths and their os.stat_result
        objects are cached so that the filesystem is not scanned each time the
        method is called.

        Args:
            rel: Return relative file paths.
            files: Include regular files.
            symlinks: Include symbolic links.
            dirs: Include directories.
            exclude: An iterable of relative paths of files to not include in
                the output.
            memoize: If true, use cached data. Otherwise, re-scan the
                filesystem.
            lookup: Return a defaultdict that looks up the stats of files not
                already in the dictionary.

        Returns:
            A dict with file paths as keys and stat objects as values.
        """
        exclude = set() if exclude is None else set(exclude)
        if lookup:
            def lookup_stat(path):
                full_path = os.path.join(self.path, path)
                for entry in self._sub_entries:
                    if entry.path == full_path:
                        return entry.stat()
                return os.stat(full_path, follow_symlinks=False)

            output = FactoryDict(lookup_stat)
        else:
            output = {}

        if not memoize or not self._sub_entries:
            for entry in rec_scan(self.path):
                self._sub_entries.append(entry)

        for entry in self._sub_entries:
            if entry.is_file(follow_symlinks=False) and not files:
                continue
            elif entry.is_dir(follow_symlinks=False) and not dirs:
                continue
            elif entry.is_symlink() and not symlinks:
                continue
            else:
                rel_path = os.path.relpath(entry.path, self.path)
                common = {
                    os.path.commonpath([path, rel_path]) for path in exclude}
                if common & exclude:
                    # File is excluded or is in an excluded directory.
                    continue
                elif rel:
                    output.update({
                        rel_path: entry.stat(follow_symlinks=False)})
                else:
                    output.update({
                        entry.path: entry.stat(follow_symlinks=False)})

        return output

    def disk_usage(self, memoize=True) -> int:
        """Get the total disk usage of the directory and all of its contents.

        Args:
            memoize: Use cached data if available.

        Returns:
            The total disk usage of the directory in bytes.
        """
        paths = self.get_paths(memoize=memoize)

        total_size = 0
        for path, stat in paths.items():
            total_size += stat.st_blocks * 512
        return total_size

    def space_avail(self) -> int:
        """Get the available space in the filesystem the directory is in.

        Returns:
            The amount of free space in bytes.
        """
        return shutil.disk_usage(self.path).free


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
        prgm_dir: Contains special program files.
        safe_path: Defined relative to prgm_dir in order to prevent access when
            prgm_dir is missing.
        ex_dir: Contains copies of each client's exclude pattern file.
        db_file: Contains information on files in the remote.
    """
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.prgm_dir = os.path.join(self.path, ".zielen")
        self.safe_path = os.path.join(self.prgm_dir, "..")
        self.ex_dir = os.path.join(self.prgm_dir, "exclude")
        self.db_file = DestDBFile(os.path.join(self.prgm_dir, "remote.db"))

    def get_paths(self, rel=True, files=True, symlinks=True, dirs=True,
                  exclude=None, memoize=True, lookup=True):
        """Extend parent method to automatically exclude program directory."""
        exclude = set() if exclude is None else set(exclude)
        exclude.add(os.path.relpath(self.prgm_dir, self.path))
        return super().get_paths(
            rel=rel, files=files, symlinks=symlinks, dirs=dirs,
            exclude=exclude, memoize=memoize)


class DestDBFile:
    """Manipulate the remote file database.

    Attributes:
        path: The path to the database file.
    """
    _PathData = NamedTuple(
        "_PathData",
        [("directory", bool), ("deleted", bool), ("lastsync", float)])

    def __init__(self, path: str) -> None:
        self.path = path
        if os.path.isfile(self.path):
            self.conn = sqlite3.connect(
                self.path, detect_types=sqlite3.PARSE_DECLTYPES)
            self.cur = self.conn.cursor()
            self.cur.execute("""\
                PRAGMA foreign_keys = ON;
                """)
        else:
            self.conn = None
            self.cur = None
        # Create adapter from python boolean to sqlite integer.
        sqlite3.register_adapter(bool, int)
        sqlite3.register_converter("BOOL", lambda x: bool(int(x)))

    @contextmanager
    def transact(self) -> Generator[None, None, None]:
        """Check if database file exists and commit the transaction on exit.

        Raises:
            ServerError: The database file wasn't found.
        """
        if not os.path.isfile(self.path):
            raise ServerError(
                "the connection to the remote directory was lost")
        with self.conn:
            yield

    def create(self) -> None:
        """Create a new empty database.

        Database Columns:
            path: The relative path of the file.
            directory: A boolean representing whether the path is a directory.
            deleted: A boolean representing whether the file is marked for
                deletion.
            lastsync: The date and time (UTC) that the file was last updated by
                a sync in seconds since the epoch.

        Raises:
            FileExistsError: The database file already exists.
        """
        if os.path.isfile(self.path):
            raise FileExistsError

        self.conn = sqlite3.connect(
            self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.cur = self.conn.cursor()

        with self.transact():
            self.cur.executescript("""\
                PRAGMA foreign_keys = ON;

                CREATE TABLE nodes (
                    path        TEXT    NOT NULL,
                    directory   BOOL    NOT NULL,
                    deleted     BOOL    NOT NULL,
                    lastsync    REAL,
                    PRIMARY KEY (path)
                );

                CREATE TABLE closure (
                    ancestor    TEXT    NOT NULL,
                    descendant  TEXT    NOT NULL,
                    depth       INT     DEFAULT 0,
                    PRIMARY KEY (ancestor, descendant),
                    FOREIGN KEY (ancestor)
                        REFERENCES nodes(path) ON DELETE CASCADE,
                    FOREIGN KEY (descendant)
                        REFERENCES nodes(path) ON DELETE CASCADE
                );
                """)

    def _update_deleted(self, paths: Iterable[str]) -> None:
        """Mark directories as deleted if all their immediate children are.

        Directories are checked in leaf-to-trunk order. If the 'deleted'
        status of a directory is changed, also check its parent directory.

        Args:
            paths: The relative paths of the directories to update the status
                of.
        """
        # Sort paths by depth.
        paths = list(paths)
        paths.sort(key=lambda x: x.count(os.sep))

        # A deque is used here because a list cannot be appended to while it is
        # being iterated over.
        path_queue = collections.deque(paths)
        while len(path_queue) > 0:
            # TODO: Prevent directories from being checked multiple times
            # while making sure that directories are checked after all their
            # children.
            path = path_queue.pop()
            parent = os.path.dirname(path)
            self.cur.execute("""\
                UPDATE nodes
                SET deleted = 0
                WHERE path = :path
                AND deleted = 1;
                """, {"path": path})
            set_false = True if self.cur.rowcount else False
            self.cur.execute("""\
                UPDATE nodes
                SET deleted = 1
                WHERE path = :path
                AND deleted = 0
                AND NOT EXISTS (
                    SELECT n.*
                    FROM nodes AS n
                    JOIN closure AS c
                    ON (n.path = c.descendant)
                    WHERE c.ancestor = :path
                    AND c.depth = 1
                    AND n.deleted = 0
                    LIMIT 1);
                """, {"path": path})
            set_true = True if self.cur.rowcount else False

            if set_false is not set_true and parent:
                # The 'deleted' status of the file changed. Check the parent
                # directory.
                path_queue.appendleft(parent)

    def _update_synctime(self, paths: Iterable[str]) -> None:
        """Update the time of the last sync for some files.

        Args:
            paths: The file paths to set.
        """
        time = datetime.datetime.utcnow().replace(
            tzinfo=datetime.timezone.utc).timestamp()
        for path in paths:
            self.cur.execute("""\
                UPDATE nodes
                SET lastsync = :time
                WHERE path = :path;
                """, {"time": time, "path": path})

    def _mark_directory(self, paths: Iterable[str]) -> None:
        """Mark paths as directories."""
        for path in paths:
            self.cur.execute("""\
                UPDATE nodes
                SET directory = 1
                WHERE directory = 0
                AND path = :path;
                """, {"path": path})

    def add_paths(self, files: Iterable[str], dirs: Iterable[str],
                  deleted=False) -> None:
        """Add new file/directory paths to the database if not already there.

        A file path is automatically marked as a directory when sub-paths are
        added to the database. The purpose of the separate parameter for
        directory paths is to distinguish empty directories from files.

        Set the 'lastsync' value for these files to the current time.

        Args:
            files: The file paths to add to the database.
            dirs: The directory paths to add to the database.
            deleted: Mark the paths as deleted.
        """
        # Sort paths by depth. A file can't be added to the database until its
        # parent directory has been added.
        files = set(files)
        dirs = set(dirs)
        paths = list(files | dirs)
        paths.sort(key=lambda x: x.count(os.sep))

        parents = set()
        with self.transact():
            for path in paths:
                parent = os.path.dirname(path)
                if parent:
                    parents.add(parent)
                if path in dirs:
                    directory = True
                else:
                    directory = False

                try:
                    self.cur.execute("""\
                        INSERT INTO nodes (path, directory, deleted)
                        VALUES (:path, :directory, :deleted);
                        """, {"path": path, "directory": directory,
                              "deleted": deleted})
                    self.cur.execute("""\
                        INSERT INTO closure (ancestor, descendant, depth)
                        SELECT ancestor, :path, c.depth + 1
                        FROM closure AS c
                        WHERE descendant = :parent
                        UNION ALL SELECT :path, :path, 0;
                        """, {"path": path, "parent": parent})
                except sqlite3.IntegrityError:
                    # If one of the paths was already in the database, silently
                    # skip it.
                    pass
            self._mark_directory(parents)
            self._update_deleted(parents)
            self._update_synctime(paths)

    def rm_paths(self, paths: Iterable[str]) -> None:
        """Remove file/directory paths from the database.

        Args:
            paths: The file/directory paths to remove.
        """
        parents = set()
        with self.transact():
            for path in paths:
                parent = os.path.dirname(path)
                if parent:
                    parents.add(parent)
                self.cur.execute("""\
                    DELETE FROM nodes
                    WHERE path IN (
                        SELECT n.path
                        FROM nodes AS n
                        JOIN closure AS c
                        ON (n.path = c.descendant)
                        WHERE c.ancestor = :path);
                    """, {"path": path})
            self._update_deleted(parents)

    def get_path(self, path: str) -> _PathData:
        """Get data associated with a file path.

        Args:
            path: The file path to search the database for.

        Returns:
            A named tuple containing the values from the other database
            columns (directory, deleted, lastsync).
        """
        # Clear the query result set.
        self.cur.fetchall()

        self.cur.execute("""\
            SELECT * FROM nodes
            WHERE path = :path;
            """, {"path": path})

        result = self.cur.fetchone()
        if result:
            return self._PathData(*result[1:])

    def get_tree(self, start=None, directory=None, deleted=None,
                 min_lastsync=None) -> Dict[str, _PathData]:
        """Get a dict of values for paths that match certain constraints.

        Args:
            start: A relative directory path. Results are restricted to just
                paths under this directory path.
            directory: Restrict results to just directory paths (True) or just
                file paths (False).
            deleted: Restrict results to just paths marked for deletion (True)
                or just paths not marked for deletion (False).
            min_lastsync: Restrict results to files that were last synced more
                recently than this time.

        Returns:
            A dict containing file paths as keys and named tuples as values.
            These named tuples contain the values from the other database
            columns.
        """
        # Clear the query result set.
        self.cur.fetchall()

        self.cur.execute("""\
            SELECT n.* FROM nodes AS n
            JOIN closure AS c
            ON (n.path = c.descendant)
            WHERE (:start IS NULL OR c.ancestor = :start)
            AND (:directory IS NULL OR n.directory = :directory)
            AND (:deleted IS NULL OR n.deleted = :deleted)
            AND (:min_lastsync IS NULL OR n.lastsync > :min_lastsync);
            """, {"start": start, "directory": directory,
                  "deleted": deleted, "min_lastsync": min_lastsync})

        return {path: self._PathData(directory, deleted, lastsync)
                for path, directory, deleted, lastsync in self.cur.fetchall()}
