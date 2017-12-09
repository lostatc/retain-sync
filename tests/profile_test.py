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
        test_dirs = ["empty"]
        test_files = [
            "documents", "documents/scans", "documents/report.odt"]
        special_test_files = ["documents/scans/receipt.pdf"]

        database = ProfileDBFile(":memory:")
        database.create()
        database.add_paths(test_files, test_dirs)
        database.add_paths(special_test_files, [], priority=10.0, local=False)
        return database

    def test_get_paths(self, db):
        """File paths and data can be retrieved."""
        expected_output = {
            "empty": PathData(True, 0.0, True),
            "documents": PathData(True, 10.0, False),
            "documents/scans": PathData(True, 10.0, False),
            "documents/report.odt": PathData(False, 0.0, True),
            "documents/scans/receipt.pdf": PathData(False, 10.0, False)}
        assert db.get_paths() == expected_output

    def test_get_file_paths(self, db):
        """Regular file paths and data can be retrieved."""
        expected_output = {
            "documents/report.odt": PathData(False, 0.0, True),
            "documents/scans/receipt.pdf": PathData(False, 10.0, False)}
        assert db.get_paths(directory=False) == expected_output

    def test_get_directory_paths(self, db):
        """Results can be limited to directories."""
        expected_output = {
            "empty": PathData(True, 0.0, True),
            "documents": PathData(True, 10.0, False),
            "documents/scans": PathData(True, 10.0, False)}
        assert db.get_paths(directory=True) == expected_output

    def test_get_paths_from_root(self, db):
        """Results can be limited to paths under a root directory."""
        expected_output = {
            "documents": PathData(True, 10.0, False),
            "documents/scans": PathData(True, 10.0, False),
            "documents/report.odt": PathData(False, 0.0, True),
            "documents/scans/receipt.pdf": PathData(False, 10.0, False)}
        assert db.get_paths(root="documents") == expected_output

    def test_get_paths_from_nonexistent_root(self, db):
        """Querying with nonexistent root directory returns an empty dict."""
        assert db.get_paths(root="foobar") == {}

    def test_get_path_info(self, db):
        """Data about a specific path can be retrieved."""
        assert db.get_path_info(
            "documents/report.odt") == PathData(False, 0.0, True)

    def test_get_nonexistent_path_info(self, db):
        """Querying for a nonexistent path returns None."""
        assert db.get_path_info("foobar") is None

    def test_add_inflated_paths(self, db):
        """Paths can be added to the database with an inflated priority."""
        db.add_inflated(["documents/essay.odt"], [])
        expected_output = {
            "empty": PathData(True, 0.0, True),
            "documents": PathData(True, 20.0, False),
            "documents/scans": PathData(True, 10.0, False),
            "documents/essay.odt": PathData(False, 10.0, True),
            "documents/report.odt": PathData(False, 0.0, True),
            "documents/scans/receipt.pdf": PathData(False, 10.0, False)}
        assert db.get_paths() == expected_output

    def test_update_paths(self, db):
        """Information associated with paths can be updated."""
        db.update_paths(
            ["documents/scans/receipt.pdf"], priority=5.0, local=True)

        expected_output = {
            "empty": PathData(True, 0.0, True),
            "documents": PathData(True, 5.0, True),
            "documents/scans": PathData(True, 5.0, True),
            "documents/report.odt": PathData(False, 0.0, True),
            "documents/scans/receipt.pdf": PathData(False, 5.0, True)}
        assert db.get_paths() == expected_output

    def test_rm_paths(self, db):
        """Paths can be removed from the database."""
        db.rm_paths(["documents/scans"])
        expected_output = {
            "empty": PathData(True, 0.0, True),
            "documents": PathData(True, 0.0, True),
            "documents/report.odt": PathData(False, 0.0, True)}
        assert db.get_paths() == expected_output

    def test_increment(self, db):
        """Path priorities can be incremented."""
        db.increment(["documents/scans/receipt.pdf"], 1)
        expected_output = {
            "empty": PathData(True, 0.0, True),
            "documents": PathData(True, 11.0, False),
            "documents/scans": PathData(True, 11.0, False),
            "documents/report.odt": PathData(False, 0.0, True),
            "documents/scans/receipt.pdf": PathData(False, 11.0, False)}
        assert db.get_paths() == expected_output

    def test_adjust_all(self, db):
        """The priorities of all paths can be adjusted."""
        db.adjust_all(0.5)
        expected_output = {
            "empty": PathData(True, 0.0, True),
            "documents": PathData(True, 5.0, False),
            "documents/scans": PathData(True, 5.0, False),
            "documents/report.odt": PathData(False, 0.0, True),
            "documents/scans/receipt.pdf": PathData(False, 5.0, False)}
        assert db.get_paths() == expected_output


class TestProfileConfigFile:
    @pytest.fixture
    def cfg_file(self, fs):
        os.makedirs(get_program_dir())

        cfg = ProfileConfigFile("/config")
        cfg.raw_vals = {
            "LocalDir": "",
            "RemoteDir": "",
            "StorageLimit": ""}

        return cfg

    @pytest.mark.parametrize(
        "key,values", [
            ("LocalDir", ["", "rel_path"]),
            ("RemoteDir", ["", "rel/path"]),
            ("StorageLimit", ["", "abc", "123", "3.14", "123QiB"]),
            ("SyncInterval", ["", "abc", "3.14"]),
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
