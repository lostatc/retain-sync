"""Test io.py.

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

import pytest

from zielen.io import is_unsafe_symlink, scan_tree, symlink_tree


@pytest.fixture
def files(fs):
    fs.CreateFile("/docs/report.odt", contents="apple")
    fs.CreateFile("/docs/scans/receipt.pdf", contents="banana")


def test_symlink_tree(files, fs):
    """A tree of symlinks can be created."""
    fs.CreateFile("/dest/report.odt")
    symlink_tree(
        "/docs", "/dest", {"report.odt", "scans/receipt.pdf"}, {"scans"})
    assert os.path.isdir("/dest/scans")
    assert os.path.isfile("/dest/report.odt")
    assert os.path.islink("/dest/scans/receipt.pdf")


def test_symlink_tree_with_exclude(files, fs):
    """Files can be excluded when creating a tree of symlinks."""
    fs.CreateFile("/dest/report.odt")
    symlink_tree(
        "/docs", "/dest", {"report.odt", "scans/receipt.pdf"}, {"scans"},
        exclude={"scans/receipt.pdf"})
    assert os.path.isdir("/dest/scans")
    assert os.path.isfile("/dest/report.odt")


def test_symlink_tree_with_overwrite(files, fs):
    """Files can be overwritten when creating a tree of symlinks."""
    fs.CreateFile("/dest/report.odt")
    symlink_tree(
        "/docs", "/dest", {"report.odt", "scans/receipt.pdf"}, {"scans"},
        overwrite=True)
    assert os.path.isdir("/dest/scans")
    assert os.path.islink("/dest/report.odt")
    assert os.path.islink("/dest/scans/receipt.pdf")


def test_rec_scan(files):
    """A directory can be recursively scanned for files."""
    expected_output = {
        "/docs/report.odt", "/docs/scans", "/docs/scans/receipt.pdf"}
    assert {entry.path for entry in scan_tree("docs")} == expected_output


def test_is_unsafe_symlink(fs):
    """Relative symlinks are considered not unsafe."""
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
