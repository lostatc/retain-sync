"""Test fstools.py.

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
import time
import tempfile

import pytest

from zielen.fstools import (
    is_unsafe_symlink, scan_tree, symlink_tree, transfer_tree)

TEST_FILE_PATHS = {
    "src/report.odt": "apple",
    "src/scans/receipt.pdf": "orange"}


@pytest.fixture
def files():
    tmp_dir = tempfile.TemporaryDirectory(prefix="zielen-")
    os.chdir(tmp_dir.name)

    for path, contents in TEST_FILE_PATHS.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as file:
            file.write(contents)

    # This function must yield instead of returning so that the temporary
    # directory object isn't cleaned up before the test.
    yield

    tmp_dir.cleanup()


def test_transfer_tree(files):
    """Files are copied from the source to the destination."""
    transfer_tree("src", "dest")

    assert os.path.isfile("dest/report.odt")
    assert os.path.isfile("dest/scans/receipt.pdf")


def test_transfer_tree_with_files(files):
    """Only specified files are copied."""
    transfer_tree("src", "dest", files=["scans/receipt.pdf"])

    assert not os.path.isfile("dest/report.odt")
    assert os.path.isfile("dest/scans/receipt.pdf")


def test_transfer_tree_with_exclude(files):
    """Excluded files are not copied."""
    transfer_tree("src", "dest", exclude=["report.odt"])

    assert not os.path.isfile("dest/report.odt")
    assert os.path.isfile("dest/scans/receipt.pdf")


def test_transfer_tree_with_rm_source(files):
    """The source files are removed."""
    transfer_tree("src", "dest", rm_source=True)

    assert not os.path.exists("src/report.odt")
    assert not os.path.exists("src/scans")
    assert not os.path.exists("src/scans/receipt.pdf")


def test_transfer_tree_copies_stats(files):
    """File metadata is copied."""
    original_mtime = os.stat("src/report.odt").st_mtime
    time.sleep(0.1)
    transfer_tree("src", "dest")

    assert os.stat("dest/report.odt").st_mtime == original_mtime


def test_symlink_tree(files):
    """A tree of symlinks can be created."""
    os.makedirs("dest")
    open("dest/report.odt", "w").close()
    symlink_tree(
        "src", "dest", {"report.odt", "scans/receipt.pdf"}, {"scans"})

    assert os.path.isdir("dest/scans")
    assert os.path.isfile("dest/report.odt")
    assert os.path.islink("dest/scans/receipt.pdf")


def test_symlink_tree_with_overwrite(files):
    """Files can be overwritten when creating a tree of symlinks."""
    os.makedirs("dest")
    open("dest/report.odt", "w").close()
    symlink_tree(
        "src", "dest", {"report.odt", "scans/receipt.pdf"}, {"scans"},
        overwrite=True)

    assert os.path.isdir("dest/scans")
    assert os.path.islink("dest/report.odt")
    assert os.path.islink("dest/scans/receipt.pdf")


def test_rec_scan(files):
    """A directory can be recursively scanned for files."""
    expected_output = {
        "src/report.odt", "src/scans", "src/scans/receipt.pdf"}

    assert {entry.path for entry in scan_tree("src")} == expected_output


def test_is_unsafe_symlink(fs):
    """Relative symlinks are not considered unsafe."""
    fs.CreateFile("parent/target")
    os.symlink("parent/target", "parent/link")

    assert is_unsafe_symlink("parent/link", "parent") is False


def test_is_unsafe_symlink_with_absolute_link(fs):
    """Absolute symlinks are considered unsafe."""
    fs.CreateFile("/parent/target")
    os.symlink("/parent/target", "/parent/link")

    assert is_unsafe_symlink("/parent/link", "/parent") is True


def test_is_unsafe_symlink_with_external_link(fs):
    """Symlinks pointing outside the parent directory are considered unsafe."""
    os.mkdir("/parent")
    fs.CreateFile("/target")
    os.symlink("/target", "/parent/link")

    assert is_unsafe_symlink("/parent/link", "/parent") is True
