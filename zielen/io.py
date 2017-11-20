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
import shutil
import os
import sys
import tempfile
import textwrap
from typing import Iterable, Optional

from zielen.utils import shell_cmd, ProgressBar

PROGRESS_BAR_LENGTH = 0.35


def transfer_tree(
        source: str, dest: str, files=None, exclude=None,
        message="", rm_source=False) -> None:
    """Recursively copy files, preserving file metadata.

    Existing files in the destination are overwritten. A progress bar is
    printed to the terminal displaying the progress of the transfer.

    Args:
        source: The path of the directory to copy the contents of.
        dest: The path of the directory to copy the files to.
        files: An iterable of relative paths of files and directories to copy.
            Missing files are ignored. If None, copy all files.
        exclude: An iterable of relative paths of files to exclude from
            copying. Excluding a directory path does not exclude its children.
            If None, exclude no files.
        message: A message to display opposite the progress bar. If None, the
            progress bar won't appear.
        rm_source: Remove source files once they are copied to the destination.

    Raises:
        FileNotFoundError: The source or destination files couldn't be found.
    """
    if not os.path.exists(source):
        raise FileNotFoundError("source not found")
    elif not os.path.exists(os.path.dirname(dest)):
        raise FileNotFoundError("dest not found")

    use_bar = message is not None and sys.stdout.isatty()

    # Get a set of all source paths that are to be transferred.
    if files is None:
        rel_paths = {
            os.path.relpath(entry.path, source) for entry in scan_tree(source)}
    else:
        rel_paths = set()
        for path in files:
            try:
                for entry in scan_tree(os.path.join(source, path)):
                    rel_paths.add(os.path.relpath(entry.path, source))
            except NotADirectoryError:
                rel_paths.add(path)

    if exclude is not None:
        rel_paths -= set(exclude)

    # Sort the paths so that the path of a directory comes after the paths
    # of its files. This allows directories to be removed only after their
    # files have been removed.
    rel_paths = list(rel_paths)
    rel_paths.sort(reverse=True)

    source_paths = [os.path.join(source, path) for path in rel_paths]
    dest_paths = [os.path.join(dest, path) for path in rel_paths]

    if use_bar:
        source_sizes = {path: os.stat(path).st_size for path in source_paths}
        total_source_size = sum(source_sizes.values())
        transferred_size = 0
        transfer_bar = ProgressBar(PROGRESS_BAR_LENGTH, message=message)

    for source_path, dest_path in zip(source_paths, dest_paths):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        try:
            shutil.copy2(source_path, dest_path, follow_symlinks=False)
        except (shutil.SameFileError, FileExistsError):
            # The destination file is a symlink.
            os.remove(dest_path)
            shutil.copy2(source_path, dest_path, follow_symlinks=False)
        except IsADirectoryError:
            os.makedirs(dest_path, exist_ok=True)

        if use_bar:
            transferred_size += source_sizes[source_path]
            transfer_bar.update(transferred_size / total_source_size)

        if rm_source:
            try:
                os.remove(source_path)
            except OSError:
                os.rmdir(source_path)

    if use_bar:
        print()


def symlink_tree(src_dir: str, dest_dir: str,
                 src_files: Iterable[str], src_dirs: Iterable[str],
                 exclude=None, overwrite=False) -> None:
    """Recursively copy a directory as a tree of symlinks.

    This function does not look in the source directory. Instead, the caller
    is expected to provide the paths of all files and directories in the
    source directory. This is to minimize the number of times that the
    filesystem is queried. Files and directories need to be passed in
    separately to distinguish files from empty directories.

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


def scan_tree(path: str):
    """Recursively scan a directory tree and yield an os.DirEntry object.

    Args:
        path: The path of the directory to scan.

    Yields:
        An os.DirEntry object for each file in the tree.
    """
    for entry in os.scandir(path):
        yield entry
        if entry.is_dir(follow_symlinks=False):
            yield from scan_tree(entry.path)


def total_size(path: str) -> int:
    """Find the size of a file or a directory and all its contents.

    Args:
        path: The path of the file to find the size of.

    Returns:
        The size of the file in bytes.
    """
    if os.path.isdir(path):
        dir_size = os.stat(path).st_size
        for entry in scan_tree(path):
            dir_size += entry.stat().st_size
        return dir_size
    else:
        return os.stat(path).st_size


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
        for entry in scan_tree(path):
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
