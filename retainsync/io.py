"""Perform filesystem operations."""

"""
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
import itertools
import subprocess

from retainsync.utility import err
import retainsync.config as c

class DirOps:
    """Perform operations on a directory."""

    def __init__(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError
        elif not os.access(path, os.W_OK):
            raise PermissionError
        elif not os.path.isdir(path):
            raise NotADirectoryError
        self.path = path

    def _scan(self, path):
        """Recursively scan a directory tree and yield a DirEntry object."""
        for entry in os.scandir(path):
            yield entry
            if entry.is_dir(follow_symlinks=False):
                yield from self._scan(entry.path)

    def list_files(self):
        """Yield the absolute paths of files in the directory."""
        for entry in self._scan(self.path):
            if not entry.is_dir():
                yield entry.path

    def list_mtimes():
        """Yield a tuple containing the absolute file path and mtime."""
        for entry in self._scan(self.path):
            if not entry.is_dir():
                yield entry.path, entry.stat().st_mtime

    def list_dirs(self):
        """Yield the absolute paths of directories in the directory."""
        for entry in self._scan(self.path):
            if entry.is_dir():
                yield entry.path

    def total_size(self):
        """Get the total size of the directory and all of its contents."""
        total_size = 0
        for entry in self._scan(self.path):
            total_size += entry.stat().st_size
        return total_size

    def symlink_tree(self, destdir, overwrite=False):
        """Recursively copy the directory as a tree of symlinks.

        destdir     Create symlinks in this directory.
        overwrite   Overwrite existing files in the destination directory with
                    symlinks.
        """
        os.makedirs(destdir, exist_ok=True)
        for entry in self._scan(self.path):
            destfile = os.path.join(
                destdir, os.path.relpath(entry.path, self.path))
            if entry.is_dir():
                os.makedirs(destfile, exist_ok=True)
            else:
                try:
                    os.symlink(entry.path, destfile)
                except FileExistsError:
                    if overwrite:
                        os.remove(destfile)
                        os.symlink(entry.path, destfile)

class LocalDirOps(DirOps):
    """Perform operations on a local sync directory."""

class DestDirOps(DirOps):
    """Perform operations on a remote sync directory."""

    def __init__(self, path):
        """
        prgm_dir    Contains special program files. When the remote directory
                    is on another machine, an empty, unreadable (000) copy of
                    this directory exists in the local mountpoint.
        path        Defined relative to prgm_dir in order to prevent access
                    when the remote directory is unmounted.
        exclude_dir Contains copies of each client's 'exclude' file.
        trash_file  Contains a list of deleted files in the remote.
        """
        self.prgm_dir = os.path.join(path, ".retain-sync")
        self.path = os.path.join(self.prgm_dir, "..")
        self.exclude_dir = os.path.join(self.prgm_dir, "exclude")
        self.trash_file = os.path.join(self.prgm_dir, "trash")

    def mount_sshfs(self):
        """Mount remote directory over ssh."""
        name = c.name
        host = c.main.cfg_file.vals["RemoteHost"]
        user = c.main.cfg_file.vals["RemoteUser"]
        port = c.main.cfg_file.vals["Port"]
        remote = c.main.cfg_file.vals["RemoteDir"]
        opts = c.main.cfg_file.vals["SshfsOptions"]

        if user:
            user = user + "@"
        if port:
            port = "port=" + port
        else:
            port = "port=22"
        opt_string = "-o " + ",".join([opts, port, "nonempty"])
        cmd_sting = user + host + ":" + remote

        sshfs_cmd = subprocess.Popen(["sshfs", opt_string, cmd_string, self.path])
        try:
            sshfs_cmd.wait(20)
        except TimeoutExpired:
            err("Error: ssh connection timed out")
            sys.exit(1)
        if sshfs_cmd.returncode != 0:
            err("Error: failed to mount remote directory over ssh")
            sys.exit(1)
