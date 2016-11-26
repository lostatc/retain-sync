"""
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
import re
import atexit
import shutil
from textwrap import dedent

import retainsync.config as c
from retainsync.parse   import ProgramDir, ProfileDir
from retainsync.parse   import ProfConfigFile
from retainsync.input   import parse_args
from retainsync.io      import LocalDirOps, DestDirOps
from retainsync.utility import env, err

def main():
    """Start user program."""

    # Read command-line arguments.
    c.cmd_args.update(parse_args())

    # Implement '--quiet' flag.
    if c.cmd_args["quiet"]:
        sys.stdout = open(os.devnull, "a")

    if c.cmd_args["command"] == "initialize":
        initialize()
    elif c.cmd_args["command"] == "sync":
        sync()
    elif c.cmd_args["command"] == "reset":
        reset()
    elif c.cmd_args["command"] == "list-profiles":
        list_profiles()
    elif c.cmd_args["command"] == "empty-trash":
        empty_trash()

def initialize():
    """Run the 'initialize' command."""

    def cleanup():
        """Run cleanup operations before exit."""
        c.main.info_file.vals["Locked"] = False
        c.main.info_file.write()

        if c.main.info_file.vals["Status"] == "part":
            print(dedent("""\
                Initialization was interrupted.
                Please run 'retain-sync initialize' to complete it or 'retain-sync reset' to
                cancel it."""))
        elif not c.main.info_file.vals["Status"] == "init":
            shutil.rmtree(c.main.path)

    # Check that value of profile name is valid.
    if re.search(r"\s+", c.cmd_args["profile"]):
        err("Error: profile name may not contain spaces")
        sys.exit(1)
    elif not re.search(r"^[a-zA-Z0-9_-]+$", c.cmd_args["profile"]):
        err("Error: profile name may not contain special symbols")
        sys.exit(1)

    c.name = c.cmd_args["profile"]

    # Check the arguments of command-line options.
    if c.cmd_args["exclude"]:
        if c.cmd_args["exclude"] == "-":
            c.cmd_args["exclude"] = "/dev/stdin"
        elif not os.path.isfile(c.cmd_args["exclude"]):
            err("Error: argument for '--exclude' is not a valid file")
            sys.exit(1)
    if c.cmd_args["template"]:
        if not os.path.isfile(c.cmd_args["template"]):
            err("Error: argument for '--template' is not a valid file")
            sys.exit(1)

    # Run cleanup function on exit.
    atexit.register(cleanup)

    c.main = ProfileDir(c.cmd_args["profile"])
    os.makedirs(c.main.path, exist_ok=True)

    # Read info file.
    if os.path.isfile(c.main.info_file.path):
        c.main.info_file.read()

    # Check if the profile has already been initialized.
    if c.main.info_file.vals["Status"] == "init":
        err("Error: this profile already exists")
        sys.exit(1)

    # Check whether an interrupted initialization is being resumed.
    if c.main.info_file.vals["Status"] == "part":
        # Resume an interrupted initialization.
        pass
    else:
        # Start a new initialization.

        # Parse template file if one was given.
        if c.cmd_args["template"]:
            template_file = ProfileDir(c.cmd_args["template"])
            template_file.read()
            template_file.check_all()
            c.main.cfg_file.raw_vals = template_file.raw_vals

        # Prompt user interactively for unset config values.
        c.main.cfg_file.prompt()
        c.main.cfg_file.mutate()

        local_dir = LocalDirOps(c.main.cfg_file.vals["LocalDir"])
        c.profiles.update(ProgramDir.inst_profiles())

        # Write config vals to file.
        # TODO: Get the path to the master config template from setup.py
        # instead of hardcoding it.
        c.main.cfg_file.write(os.path.join(sys.prefix,
            "share/retain-sync/config-template"))

        # Create info file and lock this profile.
        c.main.info_file.create()
        c.main.info_file.write()
