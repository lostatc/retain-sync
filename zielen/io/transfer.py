"""Run file transfer operations.

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
import sys
import tempfile
import contextlib
from textwrap import indent
from typing import Iterable

from zielen.exceptions import FileTransferError
from zielen.util.misc import ProgressBar, shell_cmd


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
            ex_file = stack.enter_context(
                tempfile.NamedTemporaryFile(mode="w+"))
            # All file paths must include a leading slash.
            ex_file.write(
                "\n".join(["/" + path.lstrip("/") for path in exclude]))
            ex_file.flush()
            cmd_args.append("--exclude-from=" + ex_file.name)
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
                + indent("\n".join(stderr.splitlines()[-5:]), "    "))


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
                continue
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