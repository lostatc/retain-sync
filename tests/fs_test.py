"""Test fs.py.

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
import pytest

from zielen.fs import PathsDiff


class TestPathsDiff:
    @pytest.fixture
    def diff(self):
        files = {"file_a", "file_b"}
        return PathsDiff(files)

    def test_properties(self, diff):
        """The properties for a new object return correct data."""
        assert diff.init_paths == {"file_a", "file_b"}
        assert diff.res_paths == {"file_a", "file_b"}
        assert diff.mod_paths == set()

    def test_add_paths(self, diff):
        """Paths can be added to the resultant set."""
        diff.add(["file_c"])
        assert diff.init_paths == {"file_a", "file_b"}
        assert diff.res_paths == {"file_a", "file_b", "file_c"}
        assert diff.mod_paths == set()

    def test_rm_paths(self, diff):
        """Paths can be retrieved from the resultant set."""
        diff.rm(["file_b"])
        assert diff.init_paths == {"file_a", "file_b"}
        assert diff.res_paths == {"file_a"}
        assert diff.mod_paths == set()

    def test_rename_paths(self, diff):
        """Paths can be given a new name."""
        diff.rename([("file_b", "file_d")])
        assert diff.init_paths == {"file_a", "file_b"}
        assert diff.res_paths == {"file_a", "file_d"}
        assert diff.mod_paths == {("file_b", "file_d")}
