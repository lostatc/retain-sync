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

from zielen.exceptions import FileTransferError
from zielen.util.misc import progress_bar, shell_cmd


def _rsync_cmd(add_args: list, files=None, exclude=None, msg="") -> None:
    """Run an rsync command and print a status bar.

    Args:
        add_args:   A list of arguments to pass to rsync.
        files:      A list of relative file paths to sync.
        exclude:    A list of relative file paths to exclude from syncing.
        msg:        A message to display opposite the progress bar. If empty,
                    the bar won't appear.

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

        if msg and sys.stdout.isatty():
            # Print status bar.
            rsync_bar = progress_bar(0.35, msg)
            for line in cmd.stdout:
                if not line.strip():
                    continue
                percent = float(line.split()[1].rstrip("%"))/100
                rsync_bar(percent)
            cmd.wait()
            # Make sure that the progress bar is full once the transfer is
            # completed.
            rsync_bar(1.0)
            print()

        stdout, stderr = cmd.communicate()
        if cmd.returncode != 0:
            # Print the last five lines of rsync's stderr.
            raise FileTransferError(
                "the file transfer failed to complete\n"
                + indent("\n".join(stderr.splitlines()[-5:]), "    "))


def rclone(src: str, dest: str, files=None, exclude=None, msg="") -> None:
    """Recursively copy files, preserving file metadata.

    Args:
        src:        The file to copy or directory to copy the contents of.
        dest:       The location to copy the files to.
        files:      A list of relative file paths to sync.
        exclude:    A list of relative file paths to exclude from syncing.
        msg:        A message to display opposite the progress bar. If empty,
                    the bar won't appear.

    Raises:
        FileNotFoundError:  The source or destination files couldn't be found.
        FileTransferError:  The file transfer failed.
    """
    if not os.path.exists(src) or not os.path.exists(os.path.dirname(dest)):
        raise FileNotFoundError

    # The rsync option '--archive' does not imply '--recursive' when
    # '--files-from' is specified, so we have to explicitly include it.
    _rsync_cmd(
        ["-asrHAXS", os.path.join(src, ""), dest],
        files=files, exclude=exclude, msg=msg)
