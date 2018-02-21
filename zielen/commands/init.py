"""A class for the 'init' command.

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
import os
import re
import time
import shutil
import atexit
import textwrap
from typing import Optional

from zielen.paths import get_program_dir
from zielen.exceptions import InputError
from zielen.fstools import check_dir
from zielen.filelogic import FilesManager
from zielen.userdata import LocalSyncDir, RemoteSyncDir
from zielen.profile import Profile
from zielen.commandbase import Command, unlock


class InitCommand(Command):
    """Run the "init" command.

    Attributes:
        profile_input: The "name" argument for the command.
        profile: The currently selected profile.
        exclude: The argument for the "--exclude" option.
        template: The argument for the "--template" option.
        add_remote: The "--add-remote" options was given.
    """
    def __init__(self, profile_input: str, exclude=None, template=None,
                 add_remote=False) -> None:
        super().__init__()
        self.profile_input = profile_input
        self.exclude = exclude
        self.template = template
        self.add_remote = add_remote

    @unlock
    def main(self) -> None:
        """Run the command.

        Raises:
            InputError: The command-line arguments were invalid.
        """
        # Define cleanup functions.
        def cleanup_profile() -> None:
            """Remove the profile directory if empty."""
            try:
                os.rmdir(self.profile.path)
            except OSError:
                pass

        def delete_profile() -> None:
            """Delete the profile directory."""
            try:
                shutil.rmtree(self.profile.path)
            except FileNotFoundError:
                pass

        # Check that value of profile name is valid.
        if re.search(r"\s+", self.profile_input):
            raise InputError("profile name must not contain spaces")
        elif not re.search(r"^[\w-]+$", self.profile_input):
            raise InputError(
                "profile name must not contain special symbols")

        # Check the arguments of command-line options.
        if self.exclude:
            if not os.path.isfile(self.exclude):
                raise InputError(
                    "argument for '--exclude' is not a valid file")
        if self.template:
            if not os.path.isfile(self.template):
                raise InputError(
                    "argument for '--template' is not a valid file")

        atexit.register(cleanup_profile)
        self.profile = Profile(self.profile_input)
        try:
            self.profile.read()
        except FileNotFoundError:
            pass

        # Check if the profile has already been initialized.
        if self.profile.status == "initialized":
            raise InputError("this profile already exists")

        # Lock profile if not already locked.
        self.lock()

        # Check whether an interrupted initialization is being resumed.
        if self.profile.status == "partial":
            # Resume an interrupted initialization.
            print("Resuming initialization...\n")
            atexit.register(self.print_interrupt_msg)

            # The user doesn't have to specify the same command-line arguments
            # when they're resuming and initialization.
            self.add_remote = self.profile.add_remote

            self.local_dir = LocalSyncDir(self.profile.local_path)
            self.remote_dir = RemoteSyncDir(self.profile.remote_path)
            fm = FilesManager(self.local_dir, self.remote_dir, self.profile)
        else:
            # Start a new initialization.
            atexit.register(delete_profile)

            # Generate all files in the profile directory.
            init_options = {
                "add_remote": self.add_remote}
            self.profile.generate(
                init_options=init_options, exclude_path=self.exclude,
                template_path=self.template)

            # Check validity of local and remote directories.
            error_message = check_dir(
                self.profile.local_path, self.add_remote)
            if error_message:
                raise InputError("local directory {}".format(error_message))
            error_message = self._verify_local_dir(self.profile.local_path)
            if error_message:
                raise InputError(error_message)
            error_message = check_dir(
                self.profile.remote_path, not self.add_remote)
            if error_message:
                raise InputError("remote directory {}".format(error_message))

            self.local_dir = LocalSyncDir(self.profile.local_path)
            self.remote_dir = RemoteSyncDir(self.profile.remote_path)
            fm = FilesManager(self.local_dir, self.remote_dir, self.profile)

            # The profile is now partially initialized. If the
            # initialization is interrupted from this point, it can be
            # resumed.
            atexit.register(self.print_interrupt_msg)
            atexit.unregister(delete_profile)

        self.remote_dir.generate()

        # Copy files and/or create symlinks.
        if self.add_remote:
            fm.setup_from_remote()
        else:
            fm.setup_from_local()

        # Copy exclude pattern file to remote directory for use when remote dir
        # is shared.
        self.remote_dir.add_exclude_file(self.profile.exclude_path, self.profile.id)

        # The profile is now fully initialized. Update the profile.
        self.remote_dir.write()
        self.profile.status = "initialized"
        self.profile.last_sync = time.time()
        self.profile.last_adjust = time.time()
        self.profile.write()
        atexit.unregister(self.print_interrupt_msg)

        print(textwrap.dedent("""
            Run the following commands to start the daemon:
            'systemctl --user start zielen@{0}.service'
            'systemctl --user enable zielen@{0}.service'""".format(
                self.profile.name)))

    def _verify_local_dir(self, dir_path: str) -> Optional[str]:
        """Verity that local directory path doesn't overlap other profiles.

        Also verify that the local directory path doesn't overlap with the
        program directory.

        Args:
            dir_path: The absolute path of the local directory.

        Returns:
            An error message if the local directory is invalid and None
            otherwise.
        """
        common_path = os.path.commonpath([dir_path, get_program_dir()])
        if common_path in [dir_path, get_program_dir()]:
            return "local directory must not contain zielen config files"

        overlap_profiles = []
        for name, profile in self.profiles.items():
            if profile is self.profile or not os.path.isfile(profile.cfg_path):
                continue

            profile.read()

            common_path = os.path.commonpath([profile.local_path, dir_path])
            if common_path in [profile.local_path, dir_path]:
                overlap_profiles.append(name)

        if overlap_profiles:
            # Print a comma-separated list of conflicting profile names
            # after the error message.
            suffix = "s" if len(overlap_profiles) > 1 else ""
            return "local directory overlaps with the profile{0} {1}".format(
                suffix, ", ".join("'{}'".format(x) for x in overlap_profiles))
