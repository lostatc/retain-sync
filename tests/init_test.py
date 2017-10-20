"""Tests for the "init" command.

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
import tempfile
import textwrap

import pytest

from zielen.paths import get_program_dir
from zielen.exceptions import InputError
from zielen.commands.init import InitCommand
from zielen.profile import PathData as LocalPathData
from zielen.userdata import PathData as RemotePathData

TEST_DIR_PATHS = {"empty", "letters", "letters/upper", "numbers"}
TEST_FILE_PATHS = {"letters/a.txt", "letters/upper/A.txt", "numbers/1.txt"}
TEST_PATHS = TEST_DIR_PATHS | TEST_FILE_PATHS


def create_files(
        tmp_dir: str, local_basename: str, remote_basename: str,
        files_basename: str) -> None:
    """Create test files.

    Args:
        tmp_dir: The path of the temporary directory in which to create all
            new files.
        local_basename: The basename of the local directory.
        remote_basename: The basename of the remote directory.
        files_basename: The basename of the directory in which to create the files.
    """
    local_path = os.path.join(tmp_dir, local_basename)
    remote_path = os.path.join(tmp_dir, remote_basename)

    with open("template", "w") as file:
        file.write(textwrap.dedent("""\
            LocalDir={0}
            RemoteDir={1}
            StorageLimit=1KiB
            """.format(local_path, remote_path)))

    try:
        os.makedirs(local_path, exist_ok=True)
        os.makedirs(remote_path, exist_ok=True)
    except OSError:
        pass
    for path in TEST_DIR_PATHS:
        os.makedirs(os.path.join(files_basename, path), exist_ok=True)
    for path in TEST_FILE_PATHS:
        with open(os.path.join(files_basename, path), "w") as file:
            file.write("a")


@pytest.fixture
def temp_dir(monkeypatch):
    tmp_dir = tempfile.TemporaryDirectory(prefix="zielen-")
    monkeypatch.setenv(
        "XDG_CONFIG_HOME", os.path.join(tmp_dir.name, "home", ".config"))
    os.chdir(tmp_dir.name)

    yield tmp_dir.name

    tmp_dir.cleanup()


def test_files_moved_to_remote(temp_dir):
    """Local files are moved to the remote directory."""
    create_files(temp_dir, "local", "remote", "local")
    command = InitCommand("test", template="template")
    command.main()

    remote_paths = set(command.remote_dir.scan_paths(memoize=False).keys())
    assert remote_paths == TEST_PATHS


def test_local_symlinks_created(temp_dir):
    """Local files are replaced with symlinks."""
    create_files(temp_dir, "local", "remote", "local")
    command = InitCommand("test", template="template")
    command.main()

    local_symlink_paths = set(command.local_dir.scan_paths(
        memoize=False, files=False).keys())
    assert local_symlink_paths == TEST_PATHS


def test_add_remote(temp_dir):
    """Local symlinks are created when starting with a remote directory."""
    create_files(temp_dir, "local", "remote", "remote")
    command = InitCommand("test", template="template", add_remote=True)
    command.main()

    local_symlink_paths = set(command.local_dir.scan_paths(
        memoize=False, files=False).keys())
    assert local_symlink_paths == TEST_PATHS


def test_create_exclude_file(temp_dir):
    """Exclude patterns passed in are added to the exclude file."""
    exclude_patterns = "*.\n/letters/a.txt\n"
    with open("exclude", "w") as file:
        file.write(exclude_patterns)
    create_files(temp_dir, "local", "remote", "local")
    command = InitCommand("test", template="template", exclude="exclude")
    command.main()

    with open(command.profile.ex_path) as file:
        uncommented_lines = "".join(file.readlines()[-2:])
    assert uncommented_lines == exclude_patterns


def test_if_local_dir_is_nonexistent(temp_dir):
    """A nonexistent local directory raises an exception."""
    create_files(temp_dir, "local", "remote", "local")
    shutil.rmtree("local")
    command = InitCommand("test", template="template")

    with pytest.raises(InputError):
        command.main()


def test_if_remote_dir_is_nonexistent(temp_dir):
    """A nonexistent remote directory raises an exception."""
    create_files(temp_dir, "local", "nonexistent", "local")
    command = InitCommand("test", template="template", add_remote=True)

    with pytest.raises(InputError):
        command.main()


def test_if_local_dir_is_unwritable(temp_dir):
    """An unwritable local directory raises an exception."""
    create_files(temp_dir, "/root", "remote", "local")
    command = InitCommand("test", template="template")

    with pytest.raises(InputError):
        command.main()


def test_if_remote_dir_is_unwritable(temp_dir):
    """An unwritable remote directory raises an exception."""
    create_files(temp_dir, "local", "/root", "local")
    command = InitCommand("test", template="template")

    with pytest.raises(InputError):
        command.main()


def test_if_local_dir_is_a_file(temp_dir):
    """A file as the local directory raises an exception."""
    open("file", "w").close()
    create_files(temp_dir, "file", "remote", "local")
    command = InitCommand("test", template="template")

    with pytest.raises(InputError):
        command.main()


def test_if_remote_dir_is_a_file(temp_dir):
    """A file as the remote directory raises an exception."""
    open("file", "w").close()
    create_files(temp_dir, "local", "file", "local")
    command = InitCommand("test", template="template")

    with pytest.raises(InputError):
        command.main()


def test_if_local_dir_is_not_empty(temp_dir):
    """An non-empty local directory raises an exception."""
    create_files(temp_dir, "local", "remote", "local")
    command = InitCommand("test", template="template", add_remote=True)

    with pytest.raises(InputError):
        command.main()


def test_if_remote_dir_is_not_empty(temp_dir):
    """An non-empty remote directory raises an exception."""
    create_files(temp_dir, "local", "remote", "remote")
    command = InitCommand("test", template="template")

    with pytest.raises(InputError):
        command.main()


def test_if_local_dir_overlaps_config_files(temp_dir):
    """A local directory overlapping config files raises an exception."""
    create_files(temp_dir, get_program_dir(), "remote", "local")
    command = InitCommand("test", template="template")

    with pytest.raises(InputError):
        command.main()


def test_if_local_dir_overlaps_another_profile(temp_dir):
    """A local directory overlapping another profile raises an exception."""
    create_files(temp_dir, "local", "remote", "local")
    command = InitCommand("test", template="template")
    command.main()
    create_files(temp_dir, "local", "remote2", "local2")
    command2 = InitCommand("test2", template="template")

    with pytest.raises(InputError):
        command2.main()


def test_files_added_to_local_database(temp_dir):
    create_files(temp_dir, "local", "remote", "local")
    command = InitCommand("test", template="template")
    command.main()

    expected = {
        "empty": LocalPathData(True, 0.0),
        "letters": LocalPathData(True, 0.0),
        "letters/a.txt": LocalPathData(False, 0.0),
        "letters/upper": LocalPathData(True, 0.0),
        "letters/upper/A.txt": LocalPathData(False, 0.0),
        "numbers": LocalPathData(True, 0.0),
        "numbers/1.txt": LocalPathData(False, 0.0)}
    assert command.profile.get_paths() == expected


def test_files_added_to_remote_database(temp_dir, monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1495316810)
    create_files(temp_dir, "local", "remote", "local")
    command = InitCommand("test", template="template")
    command.main()

    expected = {
        "empty": RemotePathData(True, 1495316810),
        "letters": RemotePathData(True, 1495316810),
        "letters/a.txt": RemotePathData(False, 1495316810),
        "letters/upper": RemotePathData(True, 1495316810),
        "letters/upper/A.txt": RemotePathData(False, 1495316810),
        "numbers": RemotePathData(True, 1495316810),
        "numbers/1.txt": RemotePathData(False, 1495316810)}
    assert command.remote_dir.get_paths() == expected
