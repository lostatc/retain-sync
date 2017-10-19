"""Test profile.py.

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
import re

import pytest

from zielen.paths import get_program_dir
from zielen.exceptions import FileParseError
from zielen.profile import ProfileDBFile, PathData, ProfileConfigFile


class TestProfileDBFile:
    @pytest.fixture
    def db(self):
        test_dirs = [
            "empty"
        ]
        test_files = [
            "documents", "documents/scans", "documents/scans/receipt.png"
        ]
        priority_test_files = [
            "documents/report.odt"
        ]

        database = ProfileDBFile(":memory:")
        database.create()
        database.add_paths(test_files, test_dirs)
        database.add_paths(priority_test_files, [], priority=10.0)
        return database

    def test_get_paths(self, db):
        """File paths and data can be retrieved."""
        expected_output = {
            "empty": PathData(True, 0.0),
            "documents": PathData(True, 10.0),
            "documents/scans": PathData(True, 0.0),
            "documents/report.odt": PathData(False, 10.0),
            "documents/scans/receipt.png": PathData(False, 0.0)}
        assert db.get_paths() == expected_output

    def test_get_file_paths(self, db):
        """Regular file paths and data can be retrieved."""
        expected_output = {
            "documents/report.odt": PathData(False, 10.0),
            "documents/scans/receipt.png": PathData(False, 0.0)}
        assert db.get_paths(directory=False) == expected_output

    def test_get_directory_paths(self, db):
        """Results can be limited to directories."""
        expected_output = {
            "empty": PathData(True, 0.0),
            "documents": PathData(True, 10.0),
            "documents/scans": PathData(True, 0.0)}
        assert db.get_paths(directory=True) == expected_output

    def test_get_paths_from_root(self, db):
        """Results can be limited to paths under a root directory."""
        expected_output = {
            "documents": PathData(True, 10.0),
            "documents/scans": PathData(True, 0.0),
            "documents/report.odt": PathData(False, 10.0),
            "documents/scans/receipt.png": PathData(False, 0.0)}
        assert db.get_paths(root="documents") == expected_output

    def test_get_paths_from_nonexistent_root(self, db):
        """Querying with nonexistent root directory returns an empty dict."""
        assert db.get_paths(root="foobar") == {}

    def test_get_path_info(self, db):
        """Data about a specific path can be retrieved."""
        assert db.get_path_info(
            "documents/report.odt") == PathData(False, 10.0)

    def test_get_nonexistent_path_info(self, db):
        """Querying for a nonexistent path returns None."""
        assert db.get_path_info("foobar") is None

    def test_replace_paths(self, db):
        """Existing paths in the database can be replaced."""
        db.add_paths(
            ["documents/scans/receipt.png"], [], priority=5.0, replace=True)
        expected_output = {
            "empty": PathData(True, 0.0),
            "documents": PathData(True, 15.0),
            "documents/scans": PathData(True, 5.0),
            "documents/report.odt": PathData(False, 10.0),
            "documents/scans/receipt.png": PathData(False, 5.0)}
        assert db.get_paths() == expected_output

    def test_add_inflated_paths(self, db):
        """Paths can be added to the database with an inflated priority."""
        db.add_inflated(["documents/essay.odt"], [])
        expected_output = {
            "empty": PathData(True, 0.0),
            "documents": PathData(True, 20.0),
            "documents/scans": PathData(True, 0.0),
            "documents/essay.odt": PathData(False, 10.0),
            "documents/report.odt": PathData(False, 10.0),
            "documents/scans/receipt.png": PathData(False, 0.0)}
        assert db.get_paths() == expected_output

    def test_rm_paths(self, db):
        """Paths can be removed from the database."""
        db.rm_paths(["documents/scans"])
        expected_output = {
            "empty": PathData(True, 0.0),
            "documents": PathData(True, 10.0),
            "documents/report.odt": PathData(False, 10.0)}
        assert db.get_paths() == expected_output

    def test_increment(self, db):
        """Path priorities can be incremented."""
        db.increment(["documents/report.odt"], 1)
        expected_output = {
            "empty": PathData(True, 0.0),
            "documents": PathData(True, 11.0),
            "documents/scans": PathData(True, 0.0),
            "documents/report.odt": PathData(False, 11.0),
            "documents/scans/receipt.png": PathData(False, 0.0)}
        assert db.get_paths() == expected_output

    def test_adjust_all(self, db):
        """The priorities of all paths can be adjusted."""
        db.adjust_all(0.5)
        expected_output = {
            "empty": PathData(True, 0.0),
            "documents": PathData(True, 5.0),
            "documents/scans": PathData(True, 0.0),
            "documents/report.odt": PathData(False, 5.0),
            "documents/scans/receipt.png": PathData(False, 0.0)}
        assert db.get_paths() == expected_output


class TestProfileConfigFile:
    @pytest.fixture
    def cfg_file(self, fs):
        os.makedirs(get_program_dir())
        os.makedirs("/empty")
        os.makedirs("/not_empty")
        fs.CreateFile("/not_empty/file")
        os.makedirs("/root")
        os.chmod("/root", 000)

        cfg = ProfileConfigFile("/config")
        cfg.raw_vals = {
            "LocalDir": "",
            "RemoteDir": "",
            "StorageLimit": ""}
        return cfg

    @pytest.mark.parametrize(
        "key,values", [
            ("LocalDir", [
                "", "rel_path", get_program_dir(), "/nonexistent", "/root",
                "/not_empty/file"]),
            ("RemoteDir", [
                "", "rel/path", "/root", "/not_empty/file"]),
            ("StorageLimit", ["", "abc", "123", "3.14", "123QiB"]),
            ("SyncInterval", ["", "abc", "3.14"]),
            ("TrashDirs", ["rel/path", "/abs/path:rel/path"]),
            ("PriorityHalfLife", ["", "abc"])
            ])
    def test_incorrect_syntax(self, cfg_file, key, values):
        """Incorrect config values return an error string."""
        for value in values:
            assert isinstance(cfg_file.check_value(key, value), str)

    @pytest.mark.parametrize(
        "key,values", [
            ("LocalDir", ["/empty"]),
            ("RemoteDir", ["/empty"]),
            ("StorageLimit", ["50MiB", "20 GB"]),
            ("SyncInterval", ["20"]),
            ("TrashDirs", ["/abs/path:~/path"]),
            ("PriorityHalfLife", ["120"])
            ])
    def test_correct_syntax(self, cfg_file, key, values):
        """Correct config values return None."""
        for value in values:
            assert cfg_file.check_value(key, value) is None

    def test_all_keys_present(self, cfg_file):
        """Checking the file with all required keys present returns None."""
        assert cfg_file.check_all(check_empty=False) is None

    def test_missing_keys(self, cfg_file):
        """Checking the file with required keys missing raises an exception."""
        del cfg_file.raw_vals["LocalDir"]
        with pytest.raises(FileParseError):
            cfg_file.check_all(check_empty=False)

    def test_unrecognized_keys(self, cfg_file):
        """Checking the file with unrecognized keys raises an exception."""
        cfg_file.raw_vals.update({"Foobar": ""})
        with pytest.raises(FileParseError):
            cfg_file.check_all(check_empty=False)
