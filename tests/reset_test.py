"""Tests for the "reset" command.

Copyright © 2016-2018 Garrett Powell <garrett@gpowell.net>

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
import textwrap
import tempfile

import pytest

from zielen.commands.init import InitCommand
from zielen.commands.reset import ResetCommand

TEST_DIR_PATHS = {"empty", "letters", "letters/upper", "numbers"}
TEST_FILE_PATHS = {"letters/a.txt", "letters/upper/A.txt", "numbers/1.txt"}
TEST_PATHS = TEST_DIR_PATHS | TEST_FILE_PATHS


@pytest.fixture
def command(monkeypatch):
    """Initialize a profile and return a ResetCommand object."""

    tmp_dir = tempfile.TemporaryDirectory(prefix="zielen-")
    monkeypatch.setenv(
        "XDG_CONFIG_HOME", os.path.join(tmp_dir.name, "home", ".config"))

    local_path = os.path.join(tmp_dir.name, "local")
    remote_path = os.path.join(tmp_dir.name, "remote")
    trash_path = os.path.join(tmp_dir.name, "trash")

    os.chdir(tmp_dir.name)

    # Create testing files.
    os.makedirs(remote_path, exist_ok=True)
    for path in TEST_DIR_PATHS:
        os.makedirs(os.path.join("local", path), exist_ok=True)
    for path in TEST_FILE_PATHS:
        with open(os.path.join("local", path), "w") as file:
            file.write("a")

    # Create template file for initializing the test profile.
    with open("template", "w") as file:
        file.write(textwrap.dedent("""\
            LocalDir={0}
            RemoteDir={1}
            StorageLimit=0KiB
            """.format(local_path, remote_path)))

    init_command = InitCommand("test", template="template")
    init_command.main()

    # This function must yield instead of returning so that the temporary
    # directory object isn't cleaned up before the test.
    yield ResetCommand("test")

    tmp_dir.cleanup()


def test_files_moved_to_local_directory(command):
    """Remote files are moved to the local directory."""
    command.main()

    local_paths = set(command.local_dir.scan_paths(
        memoize=False, symlinks=False))
    assert local_paths == TEST_PATHS


def test_files_deleted_from_remote_directory(command):
    """Files are removed from the remote directory."""
    command.main()

    remote_paths = set(command.remote_dir.scan_paths(memoize=False))
    assert not remote_paths


def test_profile_is_deleted(command):
    """The profile is deleted."""
    command.main()

    assert not os.path.isdir(command.profile.path)


def test_option_keep_remote(command):
    """Files stay in the remote directory."""
    command.keep_remote = True
    command.main()

    remote_paths = set(command.remote_dir.scan_paths(memoize=False))
    assert remote_paths == TEST_PATHS


def test_option_no_retrieve(command):
    """Files are not retrieved from the remote directory."""
    command.no_retrieve = True
    command.main()

    local_symlink_paths = set(command.local_dir.scan_paths(memoize=False))
    assert local_symlink_paths == TEST_DIR_PATHS
