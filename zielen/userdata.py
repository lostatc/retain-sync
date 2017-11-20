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
import shutil
import sqlite3
import time
import hashlib
from typing import (
    Tuple, Iterable, List, Dict, NamedTuple, Generator, Union, Set)

from zielen.exceptions import RemoteError
from zielen.containerbase import SyncDBFile
from zielen.io import scan_tree, checksum, total_size
from zielen.profile import ProfileExcludeFile
from zielen.utils import FactoryDict, secure_string

PathData = NamedTuple("PathData", [("directory", bool), ("lastsync", float)])


class TrashDir:
    """Get information about the user's local trash directory.

    Attributes:
        paths: The path or paths of the trash directories.
        _stored_sizes: A list of tuples containing the paths and sizes of every file
            in the trash.
    """
    def __init__(self, paths: Union[Iterable[str], str]) -> None:
        if isinstance(paths, str):
            self.paths = [paths]
        else:
            self.paths = paths
        self._stored_sizes = []

    @property
    def _sizes(self) -> List[Tuple[str, int]]:
        """Get the sizes of every top-level file in the trash directory.

        Top-level directories are collectively treated as a single file.

        Returns:
            A list of file paths and sizes in bytes.
        """
        if not self._stored_sizes:
            output = []
            for path in self.paths:
                if os.path.isdir(path):
                    for entry in os.scandir(path):
                        if not entry.is_dir():
                            output.append((
                                entry.path,
                                entry.stat(follow_symlinks=False).st_size))
                        else:
                            output.append((entry.path, total_size(entry.path)))

            self._stored_sizes = output
        return self._stored_sizes

    def check_file(self, path: str) -> bool:
        """Check if a file is in the trash by comparing sizes and checksums.

        The checksum is only computed for files which are the same size as
        the file being checked against.

        Args:
            path: The path of the file to check the trash directory for.

        Returns:
            True if the file is in the trash directory and False otherwise.
        """
        # The blake2b hash function is faster than sha256, but only available
        # as of Python 3.6.
        if "blake2b" in hashlib.algorithms_available:
            hash_func = "blake2b"
        else:
            hash_func = "sha256"

        file_size = total_size(path)
        overlap_files = {
            filepath for filepath, size in self._sizes if file_size == size}

        if overlap_files:
            overlap_sums = {
                checksum(filepath, hash_func=hash_func)
                for filepath in overlap_files if os.path.lexists(filepath)}
            if checksum(path, hash_func=hash_func) in overlap_sums:
                return True
        return False


class SyncDir:
    """Perform operations on a sync directory.

    Attributes:
        path: The directory path without a trailing slash.
    """

    def __init__(self, path: str) -> None:
        self.path = path.rstrip(os.sep)
        self._sub_entries = []

    def scan_paths(
            self, rel=True, files=True, symlinks=True, dirs=True, exclude=None,
            memoize=True, lookup=True) -> Dict[str, os.stat_result]:
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
            def lookup_stat(path: str) -> os.stat_result:
                full_path = os.path.join(self.path, path)
                for entry, rel_path in self._sub_entries:
                    if entry.path == full_path:
                        return entry.stat()
                return os.stat(full_path, follow_symlinks=False)

            output = FactoryDict(lookup_stat)
        else:
            output = {}

        if not memoize or not self._sub_entries:
            self._sub_entries = []
            for entry in scan_tree(self.path):
                # Computing the relative path is expensive to do each time.
                rel_path = os.path.relpath(entry.path, self.path)
                self._sub_entries.append((entry, rel_path))

        for entry, rel_path in self._sub_entries:
            if entry.is_file(follow_symlinks=False) and not files:
                continue
            elif entry.is_dir(follow_symlinks=False) and not dirs:
                continue
            elif entry.is_symlink() and not symlinks:
                continue
            elif rel_path in exclude:
                continue
            else:
                if rel:
                    output[rel_path] = entry.stat(follow_symlinks=False)
                else:
                    output[entry.path] = entry.stat(follow_symlinks=False)

        return output

    def disk_usage(self, memoize=True) -> int:
        """Get the total disk usage of the directory and all of its contents.

        Args:
            memoize: Use cached data if available.

        Returns:
            The total disk usage of the directory in bytes.
        """
        paths = self.scan_paths(memoize=memoize)

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


class RemoteSyncDir(SyncDir):
    """Perform operations on a remote sync directory.

    Attributes:
        util_dir: Contains special program files.
        safe_path: Defined relative to util_dir in order to prevent access when
            util_dir is missing. The keeps files from being moved into an empty
            mountpoint.
        trash_dir: The path of the remote trash directory.
        _exclude_dir: The path of the directory containing copies of each client's
            exclude pattern file.
        _db_file: The remote database object.
    """
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.util_dir = os.path.join(self.path, ".zielen")
        self.safe_path = os.path.normpath(os.path.join(self.util_dir, ".."))
        self.trash_dir = os.path.join(self.util_dir, "Trash")
        self._exclude_dir = os.path.join(self.util_dir, "exclude")
        self._db_file = RemoteDBFile(os.path.join(self.util_dir, "remote.db"))

        # Import methods from content classes.
        self.add_paths = self._db_file.add_paths
        self.rm_paths = self._db_file.rm_paths
        self.get_path_info = self._db_file.get_path_info
        self.get_paths = self._db_file.get_paths

    def generate(self) -> None:
        """Generate files for storing persistent data."""
        os.makedirs(self._exclude_dir, exist_ok=True)
        os.makedirs(self.trash_dir, exist_ok=True)

        try:
            self._db_file.create()
        except FileExistsError:
            pass

    def write(self) -> None:
        """Write data to persistent storage."""
        self._db_file.commit()

    def close(self) -> None:
        """Close all database connections."""
        self._db_file.close()

    def add_exclude_file(self, filepath: str, profile_id: str) -> None:
        """Add a profile exclude file to the remote.

        Args:
            filepath: The path of the profile exclude file.
            profile_id: A unique ID for the profile.
        """
        try:
            shutil.copy(filepath, os.path.join(self._exclude_dir, profile_id))
        except FileNotFoundError:
            if not os.path.isdir(self.util_dir):
                raise RemoteError("the remote directory could not be found")
            else:
                raise

    def rm_exclude_file(self, profile_id: str) -> None:
        """Remove a profile exclude file from the remote.

        Args:
            paaaaaaaaaaaaaaaarofile_id: The unique ID used when adding the exclude file.
        """
        try:
            os.remove(os.path.join(self._exclude_dir, profile_id))
        except FileNotFoundError:
            pass

    def check_excluded(
            self, paths: Iterable[str], start_path: str) -> Set[str]:
        """Get the paths that have been excluded by each client.

        Args:
            paths: The paths to check.
            start_path: The path of the directory to match globbing patterns
                against.

        Returns:
            The subset of input paths that have been excluded by each client.
        """
        pattern_files = []
        for entry in os.scandir(self._exclude_dir):
            pattern_files.append(ProfileExcludeFile(entry.path))

        rm_files = set()
        for path in paths:
            for pattern_file in pattern_files:
                if path not in pattern_file.all_matches(start_path):
                    break
            else:
                rm_files.add(path)

        return rm_files

    def scan_paths(
            self, rel=True, files=True, symlinks=True, dirs=True, exclude=None,
            memoize=True, lookup=True):
        """Extend parent method to automatically exclude the util directory."""
        rel_util_path = os.path.relpath(self.util_dir, self.path)
        output = super().scan_paths(
            rel=rel, files=files, symlinks=symlinks, dirs=dirs,
            exclude=exclude, memoize=memoize)
        output = {
            path: stats for path, stats in output.items()
            if os.path.commonpath((path, rel_util_path)) != rel_util_path}
        return output


class RemoteDBFile(SyncDBFile):
    """Manipulate the remote file database.

    This database uses a transitive closure table to represent the file
    hierarchy.

    Attributes:
        path: The path of the database file.
        _conn: The sqlite connection object for the database.
        _cur: The sqlite cursor object for the connection.
    """
    def create(self) -> None:
        """Create a new empty database.

        Raises:
            FileExistsError: The database file already exists.
        """
        if os.path.isfile(self.path):
            raise FileExistsError("the database file already exists")

        self._conn = sqlite3.connect(
            self.path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level="DEFERRED")
        self._conn.create_function("gen_salt", 0, lambda: secure_string(8))

        self._cur = self._conn.cursor()
        self._cur.arraysize = 20

        with self._transact():
            self._cur.executescript("""\
                PRAGMA foreign_keys = ON;

                CREATE TABLE nodes (
                    id          INTEGER NOT NULL,
                    path        TEXT    NOT NULL,
                    directory   BOOL    NOT NULL,
                    lastsync    REAL    NOT NULL,
                    PRIMARY KEY (id) ON CONFLICT IGNORE
                );

                CREATE TABLE closure (
                    ancestor    INT     NOT NULL,
                    descendant  INT     NOT NULL,
                    depth       INT     DEFAULT 0,
                    PRIMARY KEY (ancestor, descendant) ON CONFLICT IGNORE,
                    FOREIGN KEY (ancestor)
                        REFERENCES nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (descendant)
                        REFERENCES nodes(id) ON DELETE CASCADE
                ) WITHOUT ROWID;

                CREATE TABLE collisions (
                    path        TEXT    NOT NULL,
                    salt        TEXT    NOT NULL,
                    PRIMARY KEY (path) ON CONFLICT IGNORE
                );
                """)

    def add_paths(self, files: Iterable[str], dirs: Iterable[str],
                  replace=False) -> None:
        """Add new file paths to the database if not already there.

        A file path is automatically marked as a directory when sub-paths are
        added to the database. The purpose of the separate parameter for
        directory paths is to distinguish empty directories from files.

        Set the 'lastsync' value for these files to the current time.

        Args:
            files: The paths of regular files to add to the database.
            dirs: The paths of directories to add to the database.
            replace: Replace existing rows instead of ignoring them.
        """
        # Sort paths by depth. A file can't be added to the database until its
        # parent directory has been added.
        files = set(files)
        dirs = set(dirs)
        paths = list(files | dirs)
        paths.sort(key=lambda x: x.count(os.sep))
        timestamp = time.time()

        while True:
            parents = set()
            insert_nodes_vals = []
            insert_closure_vals = []
            rm_vals = []
            for path in paths:
                path_id = self._get_path_id(path)
                parent = os.path.dirname(path)
                if parent:
                    parents.add(parent)
                    parent_id = self._get_path_id(parent)
                else:
                    parent_id = path_id

                rm_vals.append({
                    "path_id": path_id})
                insert_nodes_vals.append({
                    "path": path,
                    "path_id": path_id,
                    "directory": bool(path in dirs),
                    "lastsync": timestamp})
                insert_closure_vals.append({
                    "path_id": path_id,
                    "parent_id": parent_id})

            # If there are any hash collisions with paths already in the
            # database, generate salt and continue the loop to regenerate
            # the path IDs.
            self._cur.executemany("""\
                INSERT INTO collisions (path, salt)
                SELECT :path, gen_salt()
                FROM nodes
                WHERE id = :path_id
                AND path != :path;
                """, insert_nodes_vals)
            if self._cur.rowcount <= 0:
                break

        if replace:
            # Remove paths from the database if they already exist.
            self._cur.executemany("""\
                DELETE FROM nodes
                WHERE id = :path_id
                """, rm_vals)

        # Insert new values into both tables.
        self._cur.executemany("""\
            INSERT INTO nodes (id, path, directory, lastsync)
            VALUES (:path_id, :path, :directory, :lastsync);
            """, insert_nodes_vals)
        self._cur.executemany("""\
            INSERT INTO closure (ancestor, descendant, depth)
            SELECT ancestor, :path_id, c.depth + 1
            FROM closure AS c
            WHERE descendant = :parent_id
            UNION ALL SELECT :path_id, :path_id, 0;
            """, insert_closure_vals)
        self._mark_directory(parents)

    def rm_paths(self, paths: Iterable[str]) -> None:
        """Remove file paths from the database.

        If the path is the path of a directory, then all paths under it are
        removed as well.

        Args:
            paths: The file paths to remove.
        """
        # A generator expression can't be used here because recursive use of
        # cursors is not allowed.
        rm_vals = [{
            "path_id": self._get_path_id(path)}
            for path in paths]

        self._cur.executemany("""\
            DELETE FROM nodes
            WHERE id IN (
                SELECT n.id
                FROM nodes AS n
                JOIN closure AS c
                ON (n.id = c.descendant)
                WHERE c.ancestor = :path_id);
            """, rm_vals)
        self._cur.execute("""
            DELETE FROM collisions
            WHERE path NOT IN (
                SELECT path
                FROM nodes);
            """)

    def get_path_info(self, path: str) -> PathData:
        """Get data associated with a file path.

        Args:
            path: The file path to search the database for.

        Returns:
            A named tuple containing a bool representing whether the file is
            a directory and the time that the file was last updated by a
            sync as a unix timestamp.
        """
        path_id = self._get_path_id(path)
        self._cur.execute("""\
            SELECT directory, lastsync
            FROM nodes
            WHERE id = :path_id;
            """, {"path_id": path_id})

        result = self._cur.fetchone()
        if result:
            return PathData(*result)

    def get_paths(
            self, root=None, directory=None, min_lastsync=None
            ) -> Dict[str, PathData]:
        """Get a dict of values for paths that match certain constraints.

        Args:
            root: A relative directory path. Results are restricted to just
                paths under this directory path.
            directory: Restrict results to just directory paths (True) or just
                file paths (False).
            min_lastsync: Restrict results to files that were last synced more
                recently than this time.

        Returns:
            A dict containing file paths as keys and named tuples as values.
            These named tuples contain a bool representing whether the file
            is a directory and the time that the file was last updated by a
            sync as a unix timestamp.
        """
        start_id = self._get_path_id(root) if root else None
        self._cur.execute("""\
            SELECT n.path, n.directory, n.lastsync
            FROM nodes AS n
            JOIN closure AS c
            ON (n.id = c.descendant)
            WHERE (:start_id IS NULL OR c.ancestor = :start_id)
            AND (:directory IS NULL OR n.directory = :directory)
            AND (:min_lastsync IS NULL OR n.lastsync > :min_lastsync);
            """, {"start_id": start_id, "directory": directory,
                  "min_lastsync": min_lastsync})

        # As long as self._cur.arraysize is greater than 1, fetchmany() should
        # be more efficient than fetchall().
        return {
            path: PathData(directory, lastsync)
            for array in iter(self._cur.fetchmany, [])
            for path, directory, lastsync in array}
