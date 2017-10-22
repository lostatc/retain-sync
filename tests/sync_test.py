"""Tests for the "sync" command.

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
import time
import shutil
import tempfile
import textwrap

import pytest

from zielen.commands.sync import SyncCommand
from zielen.commands.init import InitCommand
from zielen.profile import PathData as LocalPathData
from zielen.userdata import PathData as RemotePathData

# zielen takes the disk usage of files into account as opposed to their
# apparent size when calculating which ones to keep in the local directory.
BLOCK_SIZE = os.stat(tempfile.gettempdir()).st_blksize

TEST_DIR_PATHS = {"empty", "letters", "letters/upper", "numbers"}
TEST_FILE_PATHS = {
    "letters/a.txt": "a"*BLOCK_SIZE*2,
    "letters/upper/A.txt": "A"*BLOCK_SIZE*3,
    "numbers/1.txt": "1"*BLOCK_SIZE*2}
TEST_PATHS = TEST_DIR_PATHS | TEST_FILE_PATHS.keys()


def init_profile(
        tmp_path: str, profile_name: str, local_basename: str,
        remote_basename: str, add_remote=False) -> SyncCommand:
    """Initialize a profile.

    Args:
        tmp_path: The path of the temporary directory.
        profile_name: The name of the profile.
        local_basename: The basename of the local directory.
        remote_basename: The basename of the remote directory.
        add_remote: Initialize the profile with the '--add-remote' option.

    Returns:
        A SyncCommand instance for an initialized profile.
    """
    local_path = os.path.join(tmp_path, local_basename)
    remote_path = os.path.join(tmp_path, remote_basename)
    trash_path = os.path.join(tmp_path, "trash")

    os.chdir(tmp_path)

    # Create testing files and write their contents.
    os.makedirs(remote_path, exist_ok=True)
    os.makedirs(trash_path, exist_ok=True)
    if not add_remote:
        for path in TEST_DIR_PATHS:
            os.makedirs(os.path.join(local_basename, path), exist_ok=True)
        for path, contents in TEST_FILE_PATHS.items():
            with open(os.path.join(local_basename, path), "w") as file:
                file.write(contents)

    # Create template file for initializing the test profile.
    with open("template", "w") as file:
        file.write(textwrap.dedent("""\
            LocalDir={0}
            RemoteDir={1}
            StorageLimit={2}KiB
            TrashDirs={3}
            """.format(
            local_path, remote_path, BLOCK_SIZE*10 // 1024, trash_path)))

    init_command = InitCommand(
        profile_name, template="template", add_remote=add_remote)
    init_command.main()

    sync_command = SyncCommand(profile_name)
    sync_command.profile.increment(TEST_FILE_PATHS.keys(), 1)
    sync_command.main()

    return sync_command


@pytest.fixture
def command(monkeypatch):
    """Return a SyncCommand instance."""
    # These tests must use a temporary directory instead of pyfakefs because
    # modules written in C (like sqlite3) can't access a fake filesystem.
    tmp_dir = tempfile.TemporaryDirectory(prefix="zielen-")
    monkeypatch.setenv(
        "XDG_CONFIG_HOME", os.path.join(tmp_dir.name, "home", ".config"))

    # This function must yield instead of returning so that the temporary
    # directory object isn't cleaned up before the test.
    yield init_profile(tmp_dir.name, "test", "local", "remote")

    tmp_dir.cleanup()


# Some of these tests use time.sleep() to ensure that there is a measurable
# difference between the time of the sync and the mtimes of any files 
# modified in the tests. 


def test_new_local_files_are_synced(command):
    """New local files are added to the remote directory."""
    with open("local/letters/upper/B.txt", "w") as file:
        file.write("B"*BLOCK_SIZE*2)
    command.main()

    remote_paths = set(command.remote_dir.scan_paths(memoize=False).keys())
    assert remote_paths == TEST_PATHS | {"letters/upper/B.txt"}


def test_new_remote_files_are_synced(command):
    """New remote files are added to the local directory."""
    with open("remote/letters/upper/B.txt", "w") as file:
        file.write("B"*BLOCK_SIZE*2)
    command.main()

    local_paths = set(command.local_dir.scan_paths(
        memoize=False, symlinks=False).keys())
    assert local_paths == TEST_PATHS | {"letters/upper/B.txt"}


def test_new_remote_files_are_symlinked(command):
    """New remote files are symlinked if there's not enough space."""
    with open("remote/letters/upper/B.txt", "w") as file:
        file.write("B"*BLOCK_SIZE*5)
    command.main()

    local_paths = set(command.local_dir.scan_paths(
        memoize=False, symlinks=False).keys())
    local_symlink_paths = set(command.local_dir.scan_paths(
        memoize=False, files=False, dirs=False).keys())
    assert local_paths == TEST_PATHS
    assert local_symlink_paths == {"letters/upper/B.txt"}


def test_local_deletion_is_synced(command):
    """A file deleted in the local directory is deleted in the remote."""
    os.remove("local/letters/a.txt")
    command.main()

    remote_paths = set(command.remote_dir.scan_paths(memoize=False).keys())
    assert remote_paths == TEST_PATHS - {"letters/a.txt"}


def test_remote_deletion_is_synced(command):
    """A file deleted in the remote directory is deleted in the local."""
    os.remove("remote/letters/a.txt")
    command.main()

    local_paths = set(command.local_dir.scan_paths(memoize=False).keys())
    assert local_paths == TEST_PATHS - {"letters/a.txt"}


def test_local_modification_is_synced(command):
    """A modification to a local file is synced to the remote copy."""
    time.sleep(0.1)
    with open("local/letters/a.txt", "w") as file:
        # Make the modified file a different size so that rsync knows that 
        # the file has changed. 
        file.write("z"*BLOCK_SIZE*1)
    command.main()

    with open("remote/letters/a.txt") as file:
        assert file.read() == "z"*BLOCK_SIZE*1


def test_remote_modification_is_synced(command):
    """A modification to a remote file is synced to the local copy."""
    time.sleep(0.1)
    with open("remote/letters/a.txt", "w") as file:
        # Make the modified file a different size so that rsync knows that 
        # the file has changed. 
        file.write("z"*BLOCK_SIZE*1)
    command.main()

    with open("local/letters/a.txt") as file:
        assert file.read() == "z"*BLOCK_SIZE*1


def test_conflict_file_is_created(command):
    """A conflict file is created if both files are modified."""
    time.sleep(0.1)
    with open("local/letters/a.txt", "w") as file:
        file.write("z"*BLOCK_SIZE*2)
    time.sleep(0.1)
    with open("remote/letters/a.txt", "w") as file:
        file.write("y"*BLOCK_SIZE*2)
    time.sleep(0.1)
    command.main()

    local_paths = command.local_dir.scan_paths(memoize=False).keys()
    remote_paths = command.remote_dir.scan_paths(memoize=False).keys()
    local_conflict_path = os.path.join(
        "local", list(local_paths - TEST_PATHS)[0])
    remote_conflict_path = os.path.join(
        "remote", list(remote_paths - TEST_PATHS)[0])
    with open(local_conflict_path) as file:
        assert file.read() == "z"*BLOCK_SIZE*2
    with open(remote_conflict_path) as file:
        assert file.read() == "z"*BLOCK_SIZE*2
    with open("local/letters/a.txt") as file:
        assert file.read() == "y"*BLOCK_SIZE*2
    with open("remote/letters/a.txt") as file:
        assert file.read() == "y"*BLOCK_SIZE*2


def test_files_are_prioritized(command):
    """Files and directories are prioritized based on their usage and size."""
    time.sleep(0.1)
    with open("local/letters/a.txt", "w") as file:
        file.write("a"*BLOCK_SIZE*3)
    with open("local/letters/upper/A.txt", "w") as file:
        file.write("A"*BLOCK_SIZE*4)
    with open("local/numbers/1.txt", "w") as file:
        file.write("1"*BLOCK_SIZE*7)
    with open("local/_.txt", "w") as file:
        file.write("_"*BLOCK_SIZE*1)
    command.main()

    local_paths = set(command.local_dir.scan_paths(
        memoize=False, symlinks=False, dirs=False).keys())
    local_symlink_paths = set(command.local_dir.scan_paths(
        memoize=False, files=False, dirs=False).keys())
    expected_paths = {
        "letters/a.txt",
        "letters/upper/A.txt",
        "_.txt"}
    expected_symlink_paths = {
        "numbers/1.txt"}
    assert local_paths == expected_paths
    assert local_symlink_paths == expected_symlink_paths


def test_remote_files_moved_to_trash(command):
    """Remote files are moved to the trash if not found in local trash."""
    os.remove("local/letters/a.txt")
    command.main()

    remote_trash_names = [
        entry.name for entry in os.scandir(command.remote_dir.trash_dir)]
    assert "a.txt" in remote_trash_names


def test_remote_files_not_moved_to_trash(command):
    """Remote files are not moved to the trash if found in local trash."""
    shutil.move("local/letters/a.txt", "trash/deleted.txt")
    command.main()

    assert not list(os.scandir(command.remote_dir.trash_dir))


def test_excluded_files_removed_from_remote_directory(command):
    """Excluded files are removed from the remote directory."""
    with open(command.profile.ex_path, "a") as file:
        file.write("/letters/a.txt")
    command.main()

    remote_paths = set(command.remote_dir.scan_paths(memoize=False).keys())
    assert remote_paths == TEST_PATHS - {"letters/a.txt"}


def test_excluded_files_moved_to_local_directory(command):
    """Excluded files are moved to the local directory."""
    with open("remote/letters/upper/B.txt", "w") as file:
        file.write("B"*BLOCK_SIZE*4)
    with open(command.profile.ex_path, "a") as file:
        file.write("/letters/upper/B.txt")
    command.main()

    local_paths = set(command.local_dir.scan_paths(memoize=False).keys())
    assert local_paths == TEST_PATHS | {"letters/upper/B.txt"}


def test_excluded_files_are_not_synced(command):
    """Excluded files aren't synced to the remote directory."""
    with open("local/letters/upper/B.txt", "w") as file:
        file.write("B"*BLOCK_SIZE*2)
    with open(command.profile.ex_path, "a") as file:
        file.write("/letters/upper/B.txt")
    command.main()

    remote_paths = set(command.remote_dir.scan_paths(memoize=False).keys())
    assert remote_paths == TEST_PATHS


def test_partially_excluded_files_stay_in_remote_directory(command):
    """Files stay in the remote until they are excluded by all clients."""
    command2 = init_profile(
        os.path.dirname(command.local_dir.path), "test2", "local2", "remote",
        add_remote=True)
    with open("local/letters/upper/B.txt", "w") as file:
        file.write("B"*BLOCK_SIZE*2)
    with open(command2.profile.ex_path, "a") as file:
        file.write("/letters/upper/B.txt")
    command.main()

    remote_paths = set(command.remote_dir.scan_paths(memoize=False).keys())
    assert remote_paths == TEST_PATHS | {"letters/upper/B.txt"}
    
    
def test_partially_excluded_files_stay_in_sync(command):
    """Files stay in sync until they are excluded by all clients."""
    command2 = init_profile(
        os.path.dirname(command.local_dir.path), "test2", "local2", "remote",
        add_remote=True)
    with open("local/letters/upper/B.txt", "w") as file:
        file.write("B"*BLOCK_SIZE*2)
    with open(command2.profile.ex_path, "a") as file:
        file.write("/letters/upper/B.txt")
    command.main()
    command2.main()

    local_paths = set(command2.local_dir.scan_paths(memoize=False).keys())
    assert local_paths == TEST_PATHS | {"letters/upper/B.txt"}
    
    
def test_priority_of_new_files_is_inflated(command):
    """The priority of new files is inflated."""
    command.profile.increment(["numbers/1.txt"], 2)
    with open("local/letters/upper/B.txt", "w") as file:
        file.write("B"*BLOCK_SIZE*2)
    command.main()
    
    assert command.profile.get_path_info("letters/upper/B.txt").priority == 3.0


def test_trash_directory_is_cleaned_up(command, monkeypatch):
    """Files in the remote trash directory are automatically cleaned up."""
    test_trash_file = os.path.join(command.remote_dir.trash_dir, "test.txt")
    with open(test_trash_file, "w") as file:
        file.write("a")
    current_time = time.time()
    monkeypatch.setattr("time.time", lambda: current_time + 60*60*24*30)
    command.main()

    remote_trash_names = [
        entry.name for entry in os.scandir(command.remote_dir.trash_dir)]
    assert "test.txt" not in remote_trash_names


def test_option_use_trash(command):
    """The config option 'UseTrash' works as expected."""
    os.remove("local/letters/a.txt")
    with open(command.profile.cfg_path, "a") as file:
        file.write("UseTrash=no\n")
    command.main()

    assert not list(os.scandir(command.remote_dir.trash_dir))


def test_option_trash_cleanup_period(command, monkeypatch):
    """The config option 'TrashCleanupPeriod' works as expected."""
    test_trash_file = os.path.join(command.remote_dir.trash_dir, "test.txt")
    with open(test_trash_file, "w") as file:
        file.write("a")
    with open(command.profile.cfg_path, "a") as file:
        file.write("TrashCleanupPeriod=-1\n")
    current_time = time.time()
    monkeypatch.setattr("time.time", lambda: current_time + 60*60*24*30)
    command.main()

    remote_trash_names = [
        entry.name for entry in os.scandir(command.remote_dir.trash_dir)]
    assert "test.txt" in remote_trash_names


def test_option_inflate_priority(command):
    """The config option 'InflatePriority' works as expected."""
    command.profile.increment(["numbers/1.txt"], 2)
    with open("local/letters/upper/B.txt", "w") as file:
        file.write("B"*BLOCK_SIZE*2)
    with open(command.profile.cfg_path, "a") as file:
        file.write("InflatePriority=no\n")
    command.main()

    assert command.profile.get_path_info("letters/upper/B.txt").priority == 0.0


def test_option_account_for_size(command):
    """The config option 'AccountForSize' works as expected."""
    time.sleep(0.1)
    with open("local/numbers/1.txt", "w") as file:
        file.write("1"*BLOCK_SIZE*8)
    with open(command.profile.cfg_path, "a") as file:
        file.write("AccountForSize=no\n")
    command.profile.increment(["numbers/1.txt"], 2)
    command.main()

    local_paths = set(command.local_dir.scan_paths(
        memoize=False, symlinks=False, dirs=False).keys())
    local_symlink_paths = set(command.local_dir.scan_paths(
        memoize=False, files=False, dirs=False).keys())
    expected_symlink_paths = {
        "letters/a.txt",
        "letters/upper/A.txt"}
    assert local_paths == {"numbers/1.txt"}
    assert local_symlink_paths == expected_symlink_paths


def test_deleted_files_are_removed_from_databases(command):
    """Files removed from both directories are removed from both databases."""
    os.remove("local/letters/a.txt")
    os.remove("remote/letters/a.txt")
    command.main()

    assert "letters/a.txt" not in command.profile.get_paths()
    assert "letters/a.txt" not in command.remote_dir.get_paths()


def test_excluded_files_are_removed_from_databases(command):
    """Excluded files are removed from both databases."""
    with open(command.profile.ex_path, "a") as file:
        file.write("/letters/a.txt")
    command.main()

    assert "letters/a.txt" not in command.profile.get_paths()
    assert "letters/a.txt" not in command.remote_dir.get_paths()
