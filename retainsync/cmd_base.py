"""Define base class for program commands.

Copyright © 2016 Garrett Powell <garrett@gpowell.net>

This file is part of retain-sync.

retain-sync is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

retain-sync is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with retain-sync.  If not, see <http://www.gnu.org/licenses/>.
"""

import os
import sys
from typing import Dict

from retainsync.io.program import ProgramDir
from retainsync.io.profile import Profile
from retainsync.util.misc import err


class Command:
    """Base class for program commands.

    Attributes:
        profiles:   A dictionary of Profile instances.
    """
    def __init__(self) -> None:
        self._profiles = {}

    @property
    def profiles(self) -> Dict[str, Profile]:
        if not self._profiles:
            self._profiles = {name: Profile(name) for name in
                              ProgramDir.list_profiles()}
        return self._profiles

    def select_profile(self, input_str: str) -> Profile:
        # Check if input is the name of an existing profile.
        if input_str in self.profiles:
            return self.profiles[input_str]
        # Check if input is the path of an initialized directory.
        input_path = os.path.abspath(input_str)
        if os.path.exists(input_path):
            for name, profile in self.profiles.items():
                if not profile.cfg_file.vals:
                    profile.cfg_file.read()
                if os.path.samefile(
                        input_path, profile.cfg_file.vals["LocalDir"]):
                    return profile
        err("Error: argument is not a profile name or initialized directory")
        sys.exit(1)
