"""Test userdata.py.

Copyright © 2017 Garrett Powell <garrett@gpowell.net>

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

from zielen.userdata import TrashDir, RemoteDBFile, PathData, SyncDir


class TestTrashDir:
    @pytest.fixture
    def trash(self, fs):
        os.mkdir("/trash")
        fs.CreateFile("/trash/file_a", contents="apple")
        fs.CreateFile("/trash/file_b", contents="banana")

        return TrashDir("/trash")

    def test_check_different_size_file(self, trash, fs, monkeypatch):
        """Checking a file of a different size doesn't require a checksum."""
        monkeypatch.delattr("zielen.userdata.checksum")
        fs.CreateFile("/file_c", contents="kiwi")
        assert trash.check_file("/file_c") is False


class TestSyncDir:
    @pytest.fixture
    def sync_dir(self, fs):
        base_dir = "/base"
        sync_dir_paths = [
            "documents",
            "documents/scans",
            "pictures"
            ]
        fake_file_paths = [
            "documents/report.odt",
            "documents/scans/receipt.pdf",
            "pictures/portrait.png",
            ]

        for path in sync_dir_paths:
            os.makedirs(os.path.join(base_dir, path))
        for path in fake_file_paths:
            fs.CreateFile(os.path.join(base_dir, path))

        return SyncDir(base_dir)

    def test_get_paths(self, sync_dir):
        """Relative file db and their stat objects can be retrieved."""
        expected_output = {
            "documents": os.stat("/base/documents"),
            "documents/report.odt": os.stat("/base/documents/report.odt"),
            "documents/scans": os.stat("/base/documents/scans"),
            "documents/scans/receipt.pdf": os.stat(
                "/base/documents/scans/receipt.pdf"),
            "pictures": os.stat("/base/pictures"),
            "pictures/portrait.png": os.stat("/base/pictures/portrait.png")}

        assert sync_dir.scan_paths() == expected_output

    def test_get_absolute_paths(self, sync_dir):
        """Absolute file db and their stat objects can be retrieved."""
        expected_output = {
            "/base/documents": os.stat("/base/documents"),
            "/base/documents/report.odt": os.stat(
                "/base/documents/report.odt"),
            "/base/documents/scans": os.stat("/base/documents/scans"),
            "/base/documents/scans/receipt.pdf": os.stat(
                "/base/documents/scans/receipt.pdf"),
            "/base/pictures": os.stat("/base/pictures"),
            "/base/pictures/portrait.png": os.stat(
                "/base/pictures/portrait.png")}

        assert sync_dir.scan_paths(rel=False) == expected_output

    def test_get_only_file_paths(self, sync_dir):
        """The db of only normal files can be retrieved."""
        expected_output = {
            "documents/report.odt": os.stat("/base/documents/report.odt"),
            "documents/scans/receipt.pdf": os.stat(
                "/base/documents/scans/receipt.pdf"),
            "pictures/portrait.png": os.stat("/base/pictures/portrait.png")}

        assert sync_dir.scan_paths(
            symlinks=False, dirs=False) == expected_output

    def test_get_paths_except_excluded(self, sync_dir):
        """The db of certain files can be excluded."""
        excluded_paths = ["documents"]
        expected_output = {
            "pictures": os.stat("/base/pictures"),
            "pictures/portrait.png": os.stat("/base/pictures/portrait.png")}

        assert sync_dir.scan_paths(exclude=excluded_paths) == expected_output

    def test_get_paths_with_lookup(self, fs, sync_dir):
        """A defaultdict that looks up the stats of files is returned."""
        files = sync_dir.scan_paths(lookup=True)
        fs.CreateFile("/base/pictures/landscape.png")

        assert files["pictures/landscape.png"] == os.stat(
            "/base/pictures/landscape.png")

    def test_get_paths_without_lookup(self, sync_dir):
        """A defaultdict that looks up the stats of files is not returned."""
        files = sync_dir.scan_paths(lookup=False)

        with pytest.raises(KeyError):
            files["pictures/landscape.png"]

    def test_get_memoized_paths(self, monkeypatch, sync_dir):
        """Cached db is used instead of re-scanning the filesystem."""
        initial_mtime = sync_dir.scan_paths(
            memoize=True)["documents/report.odt"].st_mtime
        os.utime("/base/documents/report.odt", times=(1495316810, 1495316810))
        subsequent_mtime = sync_dir.scan_paths(
            memoize=True)["documents/report.odt"].st_mtime

        assert initial_mtime == subsequent_mtime


class TestProfileDBFile:
    @pytest.fixture
    def db(self, monkeypatch):
        test_dirs = [
            "empty"
        ]
        test_files = [
            "documents", "documents/scans", "documents/scans/receipt.png",
            "documents/report.odt"
        ]

        database = RemoteDBFile(":memory:")
        database.create()
        monkeypatch.setattr("time.time", lambda: 1495316810)
        database.add_paths(test_files, test_dirs)
        monkeypatch.undo()
        return database

    def test_get_paths(self, db):
        """File paths and data can be retrieved."""
        expected_output = {
            "empty": PathData(True, 1495316810),
            "documents": PathData(True, 1495316810),
            "documents/scans": PathData(True, 1495316810),
            "documents/report.odt": PathData(False, 1495316810),
            "documents/scans/receipt.png": PathData(False, 1495316810)}
        assert db.get_paths() == expected_output

    def test_get_file_paths(self, db):
        """Regular file paths and data can be retrieved."""
        expected_output = {
            "documents/report.odt": PathData(False, 1495316810),
            "documents/scans/receipt.png": PathData(False, 1495316810)}
        assert db.get_paths(directory=False) == expected_output

    def test_get_directory_paths(self, db):
        """Results can be limited to directories."""
        expected_output = {
            "empty": PathData(True, 1495316810),
            "documents": PathData(True, 1495316810),
            "documents/scans": PathData(True, 1495316810)}
        assert db.get_paths(directory=True) == expected_output

    def test_get_paths_from_root(self, db):
        """Results can be limited to paths under a root directory."""
        expected_output = {
            "documents": PathData(True, 1495316810),
            "documents/scans": PathData(True, 1495316810),
            "documents/report.odt": PathData(False, 1495316810),
            "documents/scans/receipt.png": PathData(False, 1495316810)}
        assert db.get_paths(root="documents") == expected_output

    def test_get_paths_from_nonexistent_root(self, db):
        """Querying with nonexistent root directory returns an empty dict."""
        assert db.get_paths(root="foobar") == {}

    def test_get_path_info(self, db):
        """Data about a specific path can be retrieved."""
        assert db.get_path_info(
            "documents/report.odt") == PathData(False, 1495316810)

    def test_get_nonexistent_path_info(self, db):
        """Querying for a nonexistent path returns None."""
        assert db.get_path_info("foobar") is None

    def test_replace_paths(self, db, monkeypatch):
        """Existing paths in the database can be replaced."""
        monkeypatch.setattr("time.time", lambda: 1495317002)
        db.add_paths(
            ["documents/scans/receipt.png"], [], replace=True)
        expected_output = {
            "empty": PathData(True, 1495316810),
            "documents": PathData(True, 1495316810),
            "documents/scans": PathData(True, 1495316810),
            "documents/report.odt": PathData(False, 1495316810),
            "documents/scans/receipt.png": PathData(False, 1495317002)}
        assert db.get_paths() == expected_output

    def test_rm_paths(self, db):
        """Paths can be removed from the database."""
        db.rm_paths(["documents/scans"])
        expected_output = {
            "empty": PathData(True, 1495316810),
            "documents": PathData(True, 1495316810),
            "documents/report.odt": PathData(False, 1495316810)}
        assert db.get_paths() == expected_output
