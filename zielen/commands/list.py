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

from zielen.basecommand import Command
from zielen.util.misc import print_table


class ListCommand(Command):
    """Print a table of all initialized profiles."""
    def __init__(self) -> None:
        super().__init__()

    def main(self) -> None:
        # TODO: figure out if this can be optimized
        for name, profile in self.profiles.items():
            profile.cfg_file.read()

        table_headers = ["Profile", "Local Directory"]
        table_data = [
            (name, profile.cfg_file.vals["LocalDir"])
            for name, profile in self.profiles.items()]
        print_table(table_data, table_headers)
