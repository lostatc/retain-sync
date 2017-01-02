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
import tempfile
import re
import stat
import atexit
from typing import Dict
from textwrap import dedent

from retainsync.io.program import ProgramDir
from retainsync.io.profile import Profile
from retainsync.util.misc import err


class Command:
    """Base class for program commands.

    Attributes:
        profiles:   A dictionary of Profile instances.
        profile:    The currently selected profile.
    """
    def __init__(self) -> None:
        self._profiles = {}
        self.profile = None

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

    def lock(self) -> None:
        """Lock the profile if not already locked."""
        def unlock() -> None:
            """Release the lock on the profile."""
            self.profile.info_file.vals["Locked"] = False
            if os.path.isfile(self.profile.info_file.path):
                self.profile.info_file.write()

        if self.profile:
            self.profile.info_file.read()
            if self.profile.info_file.vals["Locked"] is True:
                err("Error: another operation on this profile is already "
                    "taking place")
                sys.exit(1)
            self.profile.info_file.vals["Locked"] = True
            self.profile.info_file.write()
            atexit.register(unlock)

    def ssh_env(self) -> bool:
        """Set environment variables for ssh-agent."""
        if not os.environ["SSH_AUTH_SOCK"]:
            for entry in os.scandir(tempfile.gettempdir()):
                if (re.search("^ssh-", entry.name)
                        and entry.is_dir
                        and entry.stat().st_uid == os.getuid()):
                    for subentry in os.scandir(entry.path):
                        if (re.search(r"^agent\.[0-9]+$", subentry.name)
                                and stat.S_ISSOCK(subentry.stat().st_mode)
                                and subentry.stat().st_uid == os.getuid()):
                            os.environ["SSH_AUTH_SOCK"] = subentry.path
                            return True
            return False
        else:
            return True

    def interrupt_msg(sefl) -> None:
        """Warn user that initialization was interrupted."""
        err(dedent("""
            Initialization was interrupted.
            Please run 'retain-sync initialize' to complete it or 'retain-sync reset' to
            cancel it."""))
