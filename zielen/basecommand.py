"""Define base class for program commands.

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
import atexit
from typing import Dict
from textwrap import dedent

from zielen.exceptions import UserInputError, LockError
from zielen.io.program import ProgramDir
from zielen.io.profile import Profile
from zielen.util.misc import err


class Command:
    """Base class for program commands.

    Attributes:
        profiles: A dictionary of Profile instances.
        profile: The currently selected profile.
    """
    def __init__(self) -> None:
        self.profiles = {
            name: Profile(name) for name in ProgramDir.list_profiles()}
        self.profile = None

    def select_profile(self, input_str: str) -> Profile:
        """Select the proper profile based on a name or local dir path.

        Returns:
            A Profile object for the selected profile.

        Raises:
            UserInputError: The input doesn't refer to any profile.
        """
        # Check if input is the name of an existing profile.
        if input_str in self.profiles:
            return self.profiles[input_str]
        # Check if input is the path of an initialized directory.
        input_path = os.path.abspath(input_str)
        if os.path.exists(input_path):
            for name, profile in self.profiles.items():
                if not profile.cfg_file.raw_vals:
                    profile.cfg_file.read()
                if os.path.samefile(
                        input_path, profile.cfg_file.vals["LocalDir"]):
                    return profile
        raise UserInputError(
            "argument is not a profile name or local directory path")

    def lock(self) -> None:
        """Lock the profile if not already locked."""
        def unlock() -> None:
            """Release the lock on the profile.

            Raises:
                LockError: The selected profile is already locked.
            """
            self.profile.info_file.raw_vals["Locked"] = False
            if os.path.isfile(self.profile.info_file.path):
                self.profile.info_file.write()

        if self.profile:
            if os.path.isfile(self.profile.info_file.path):
                self.profile.info_file.read()
            if self.profile.info_file.vals["Locked"]:
                raise LockError(
                    "another operation on this profile is already taking "
                    "place")
            self.profile.info_file.raw_vals["Locked"] = True
            atexit.register(unlock)
            self.profile.info_file.write()

    @staticmethod
    def print_interrupt_msg() -> None:
        """Warn the user that the profile is only partially initialized."""
        err(dedent("""
            Initialization was interrupted.
            Please run 'zielen initialize' to complete it or 'zielen reset' to cancel it."""))
