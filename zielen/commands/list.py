"""A class for the 'list' command.

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
from zielen.utils import BoxTable
from zielen.commandbase import Command


class ListCommand(Command):
    """Run the "list" command."""
    def __init__(self) -> None:
        super().__init__()

    def main(self) -> None:
        if not self.profiles:
            print("\n-- No profiles --\n")
            return

        for name, profile in self.profiles.items():
            profile.read()

        table_data = [
            (name, profile.local_path)
            for name, profile in self.profiles.items()]
        table_data.insert(0, ("Profile", "Local Directory"))
        table = BoxTable(table_data)
        print(table.format())
