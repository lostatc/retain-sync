"""A class for the 'list' command.

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
from zielen.profile import ProfileConfigFile
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

        config_files = []
        for name, profile in self.profiles.items():
            # New ProfileConfigFile objects are created so that they syntax
            # of the config files isn't checked.
            config_file = ProfileConfigFile(profile.cfg_path)
            config_file.read()
            config_files.append((name, config_file))

        table_data = [(
                name, config_file.vals["LocalDir"],
                config_file.vals["RemoteDir"],
                config_file.vals["StorageLimit"])
            for name, config_file in config_files]
        table_data.insert(0, (
            "Profile", "Local Directory", "Remote Directory", "Limit"))
        table = BoxTable(table_data)
        print(table.format())
