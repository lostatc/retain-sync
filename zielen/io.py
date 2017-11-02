"""Access or modify the filesystem.

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
import contextlib
import hashlib
import os
import sys
import tempfile
import textwrap
from typing import Iterable, Optional

from zielen.utils import shell_cmd, ProgressBar
from zielen.exceptions import FileTransferError


def _rsync_cmd(add_args: list, files=None, exclude=None, msg="") -> None:
    """Run an rsync command and print a status bar.

    Args:
        add_args: A list of arguments to pass to rsync.
        files: A list of relative paths of files to sync.
        exclude: A list of relative paths of files to exclude from syncing.
        msg: A message to display opposite the progress bar. If empty, the bar
            won't appear.

    Raises:
        FileTransferError:  Rsync returned a non-zero exit code.
    """
    cmd_args = ["rsync", "--info=progress2"]

    with contextlib.ExitStack() as stack:
        # If an empty list is passed in for the 'files' argument, that should
        # mean that rsync should not copy any files. That's why these are only
        # skipped if the argument is None.
        if exclude is not None:
            exclude_file = stack.enter_context(
                tempfile.NamedTemporaryFile(mode="w+"))
            # All file paths must include a leading slash.
            exclude_file.write(
                "\n".join(["/" + path.lstrip("/") for path in exclude]))
            exclude_file.flush()
            cmd_args.append("--exclude-from=" + exclude_file.name)
        if files is not None:
            paths_file = stack.enter_context(
                tempfile.NamedTemporaryFile(mode="w+"))
            # All file paths must include a leading slash.
            paths_file.write(
                "\n".join(["/" + path.lstrip("/") for path in files]))
            paths_file.flush()
            cmd_args.append("--files-from=" + paths_file.name)

        cmd = shell_cmd(cmd_args + add_args)

        if msg is not None and sys.stdout.isatty():
            # Print status bar.
            rsync_bar = ProgressBar(0.35, msg=msg)
            for line in cmd.stdout:
                if not line.strip():
                    continue
                percent = float(line.split()[1].rstrip("%"))/100
                rsync_bar.update(percent)
            cmd.wait()
            # Make sure that the progress bar is full once the transfer is
            # completed.
            rsync_bar.update(1.0)
            print()

        stdout, stderr = cmd.communicate()
        if cmd.returncode != 0:
            # Print the last five lines of rsync's stderr.
            raise FileTransferError(
                "the file transfer failed to complete\n"
                + textwrap.indent(
                    "\n".join(stderr.splitlines()[-5:]), "rsync: "))


def rec_clone(source: str, dest: str, files=None, exclude=None, msg="",
              rm_source=False) -> None:
    """Recursively copy files, preserving file metadata.

    Args:
        source: The file to copy or directory to copy the contents of.
        dest: The location to copy the files to.
        files: A list of relative paths of files to sync. Missing files are
            ignored.
        exclude: A list of relative paths of files to exclude from syncing.
        msg: A message to display opposite the progress bar. If None, the
            progress bar won't appear.
        rm_source: Remove source files once they are copied to the destination.

    Raises:
        FileNotFoundError: The source or destination files couldn't be found.
        FileTransferError: The file transfer failed.
    """
    if not os.path.exists(source) or not os.path.exists(os.path.dirname(dest)):
        raise FileNotFoundError

    # The rsync option '--archive' does not imply '--recursive' when
    # '--files-from' is specified, so we have to explicitly include it.
    rsync_args = [
        "-asrHAXS", "--ignore-missing-args", os.path.join(source, ""), dest]
    if rm_source:
        rsync_args.append("--remove-source-files")
    _rsync_cmd(rsync_args, files=files, exclude=exclude, msg=msg)


def symlink_tree(src_dir: str, dest_dir: str,
                 src_files: Iterable[str], src_dirs: Iterable[str],
                 exclude=None, overwrite=False) -> None:
    """Recursively copy a directory as a tree of symlinks.

    This function does not look in the source directory. Instead, the caller
    is expected to provide the paths of all files and directories in the
    source. Files and directories need to be passed in separately to
    distinguish files from empty directories.

    Args:
        src_dir: The absolute path of the directory to source files from.
        dest_dir: The absolute path of the directory to create symlinks in.
        src_dirs: The relative paths of the directories to copy to the
            destination.
        src_files: The relative paths of the files to symlink in the
            destination.
        exclude: The relative paths of files/directories to not symlink.
        overwrite: Overwrite existing files in the destination directory
            with symlinks.
    """
    exclude = set() if exclude is None else set(exclude)
    src_dirs = set(src_dirs)
    src_files = set(src_files)
    src_paths = list(src_dirs | src_files)

    # Sort paths by depth from trunk to leaf.
    src_paths.sort(key=lambda x: x.count(os.sep))

    os.makedirs(dest_dir, exist_ok=True)
    for src_path in src_paths:
        full_src_path = os.path.join(src_dir, src_path)
        full_dest_path = os.path.join(dest_dir, src_path)
        for exclude_path in exclude:
            if (src_path == exclude_path
                    or src_path.startswith(
                        exclude_path.rstrip(os.sep) + os.sep)):
                break
        else:
            if src_path in src_dirs:
                try:
                    os.mkdir(full_dest_path)
                except FileExistsError:
                    pass
            elif src_path in src_files:
                try:
                    os.symlink(full_src_path, full_dest_path)
                except FileExistsError:
                    if overwrite:
                        os.remove(full_dest_path)
                        os.symlink(full_src_path, full_dest_path)


def rec_scan(path: str):
    """Recursively scan a directory tree and yield an os.DirEntry object.

    Args:
        path: The path of the directory to scan.
    """
    for entry in os.scandir(path):
        yield entry
        if entry.is_dir(follow_symlinks=False):
            yield from rec_scan(entry.path)


def total_size(path: str) -> int:
    """Find the size of a file or a directory and all its contents.

    Args:
        path: The path of the file to find the size of.

    Returns:
        The size of the file in bytes.
    """
    if os.path.isfile(path):
        return os.stat(path).st_size
    else:
        dir_size = os.stat(path).st_size
        for entry in rec_scan(path):
            dir_size += entry.stat().st_size
        return dir_size


def checksum(path: str, hash_func="sha256") -> str:
    """Get the checksum of a file, reading one block at a time.

    Args:
        path: The path of the file to find the checksum of. If this value is
            the path of a directory, a checksum will be computed based on all
            the files in the directory.
        hash_func: The name of the hash function to use.

    Returns:
        The hexadecimal checksum of the file.
    """
    file_hash = hashlib.new(hash_func)
    checksum_paths = []
    try:
        for entry in rec_scan(path):
            if entry.is_file(follow_symlinks=False):
                checksum_paths.append(entry.path)
    except NotADirectoryError:
        checksum_paths.append(path)

    # This is necessary to ensure that the same checksum is returned each time.
    checksum_paths.sort()

    for checksum_path in checksum_paths:
        block_size = os.stat(checksum_path).st_blksize
        with open(checksum_path, "rb") as file:
            for block in iter(lambda: file.read(block_size), b""):
                file_hash.update(block)
    return file_hash.hexdigest()


def is_unsafe_symlink(link_path: str, parent_path: str) -> bool:
    """Check if file is a symlink that can't be safely transferred.

    A symlink is unsafe to transfer if it is an absolute symlink or points to a
    file outside parent_path.

    Args:
        link_path: The absolute path of the symlink to check.
        parent_path: The absolute path of the parent directory to check the
            symlink destination against.

    Returns:
        True if the symlink is safe and False if it is not.
    """
    try:
        link_dest = os.readlink(link_path)
    except OSError:
        # The file is not a symlink.
        return False
    if not os.path.isabs(link_dest):
        abs_link_dest = os.path.normpath(
            os.path.join(os.path.dirname(link_path), link_dest))
        if (abs_link_dest == parent_path
                or abs_link_dest.startswith(
                    parent_path.rstrip(os.sep) + os.sep)):
            return False
    return True


def check_dir(path: str, expect_empty: bool) -> Optional[str]:
    """Check if a given directory path is valid.

    Args:
        path: The directory path to check.
        expect_empty: The directory should either be empty or not exist.

    Returns:
        An error message if the directory is not valid, and None otherwise.
    """
    if os.path.exists(path):
        if os.path.isdir(path):
            if not os.access(path, os.W_OK):
                return "must be a directory with write access"
            elif expect_empty and list(os.scandir(path)):
                return "must be an empty directory"
        else:
            return "must be a directory"
    else:
        if expect_empty:
            try:
                os.makedirs(path)
            except PermissionError:
                return "must be in a directory with write access"
        else:
            return "must be an existing directory"
