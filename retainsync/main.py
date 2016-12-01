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
import signal
import tempfile
from textwrap import dedent, indent

import retainsync.config as c
# from retainsync.commands import initialize
from retainsync.io.program import ProgramDir, SSHConnection
from retainsync.io.profile import ProfileDir, ProfileConfigFile
from retainsync.io.sync import LocalSyncDir, DestSyncDir
from retainsync.util.input import parse_args
from retainsync.util.misc import err, shell_cmd, progress_bar
from retainsync.io.transfer import rsync_cmd


def main():
    """Start user program."""

    # Exit properly on SIGTERM, SIGHUP or SIGINT
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Read command-line arguments.
    c.cmd_args = parse_args()

    # Implement '--quiet' flag.
    if c.cmd_args["quiet"]:
        sys.stdout = open(os.devnull, "a")

    if c.cmd_args["command"] == "initialize":
        initialize()
    # elif c.cmd_args["command"] == "sync":
    #     select_profile()
    #     commands.sync()
    # elif c.cmd_args["command"] == "reset":
	# 	select_profile()
    #     commands.reset()
    # elif c.cmd_args["command"] == "list-profiles":
    #     commands.list_profiles()
    # elif c.cmd_args["command"] == "empty-trash":
	# 	select_profile()
    #     commands.empty_trash()


def signal_handler(signum, frame):
    """Print an appropriate error message for an interruption by signal."""
    err("Error: program received", signal.Signals(signum).name)
    sys.exit(1)

def select_profile():
    """Get profile name from user input."""
    # Read the config files of each existing profile.
    c.profiles = {name: ProfileDir(name) for name in
                  ProgramDir.list_profiles()}
    for name, profile in c.profiles.items():
        profile.cfg_file.read()

    if c.cmd_args["profile"] in list(ProgramDir.list_profiles()):
        c.main = ProfileDir(c.cmd_args["profile"])
    else:
        input_path = os.path.abspath(c.cmd_args["profile"])
        if os.path.exists(input_path):
            for name, profile in c.profiles.items():
                if os.path.samefile(
                        input_path, profile.cfg_file.vals["LocalDir"]):
                    c.main = profile

    if not c.main:
        err("Error: parameter is not a profile name or initialized directory")
        sys.exit(1)

def initialize():
    """Run the 'initialize' command."""

    # Define cleanup functions.
    def unlock():
        """Release lock on the profile."""
        c.main.info_file.vals["Locked"] = False
        if os.path.isfile(c.main.info_file.path):
            c.main.info_file.write()

    def cleanup_profile():
        """Remove the profile directory if empty."""
        try:
            os.rmdir(c.main.path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def delete_profile():
        """Delete the profile directory."""
        try:
            shutil.rmtree(c.main.path)
        except FileNotFoundError:
            pass

    def interrupt_msg():
        """Warn user that initialization was interrupted."""
        print(dedent("""\
            Initialization was interrupted.
            Please run 'retain-sync initialize' to complete it or 'retain-sync reset' to
            cancel it."""))

    # Check that value of profile name is valid.
    if re.search(r"\s+", c.cmd_args["profile"]):
        err("Error: profile name may not contain spaces")
        sys.exit(1)
    elif not re.search(r"^[a-zA-Z0-9_-]+$", c.cmd_args["profile"]):
        err("Error: profile name may not contain special symbols")
        sys.exit(1)

    # Check the arguments of command-line options.
    if c.cmd_args["exclude"]:
        if c.cmd_args["exclude"] != "-" \
                and not os.path.isfile(c.cmd_args["exclude"]):
            err("Error: argument for '--exclude' is not a valid file")
            sys.exit(1)
    if c.cmd_args["template"]:
        if not os.path.isfile(c.cmd_args["template"]):
            err("Error: argument for '--template' is not a valid file")
            sys.exit(1)

    c.main = ProfileDir(c.cmd_args["profile"])
    atexit.register(cleanup_profile)

    # Read the config files of each existing profile.
    c.profiles = {name: ProfileDir(name) for name in ProgramDir.list_profiles()
                  if name != c.main.name}
    for name, profile in c.profiles.items():
        profile.cfg_file.read()

    c.main.info_file.read()

    # Check if the profile has already been initialized.
    if c.main.info_file.vals["Status"] == "init":
        err("Error: this profile already exists")
        sys.exit(1)

    # Check if the profile is locked.
    if c.main.info_file.vals["Locked"] is True:
        err("Error: another operation on this profile is already taking place")
        sys.exit(1)

    # Lock the profile.
    c.main.info_file.vals["Locked"] = True
    c.main.info_file.write()
    atexit.register(unlock)

    # Check whether an interrupted initialization is being resumed.
    if c.main.info_file.vals["Status"] == "part":
        # Resume an interrupted initialization.
        print("Resuming initialization...\n")

        c.main.cfg_file.read()
        c.main.cfg_file.check_all()

        local_dir = LocalSyncDir(c.main.cfg_file.vals["LocalDir"])
        if c.main.cfg_file.vals["RemoteHost"]:
            dest_dir = DestSyncDir(c.main.mnt_dir)
            c.ssh = SSHConnection()
            c.ssh.connect()
            atexit.register(c.ssh.disconnect)
        else:
            dest_dir = DestSyncDir(c.main.cfg_file.vals["RemoteDir"])
        dest_dir.check()
        atexit.register(interrupt_msg)
    else:
        # Start a new initialization.
        atexit.register(delete_profile)

        # Parse template file if one was given.
        if c.cmd_args["template"]:
            template_file = ProfileConfigFile(c.cmd_args["template"])
            template_file.read()
            template_file.check_all(check_empty=False, context="template file")
            c.main.cfg_file.raw_vals = template_file.raw_vals

        # Prompt user interactively for unset config values.
        c.main.cfg_file.prompt()

        # Write config values to file.
        # TODO: Get the path to the master config template from setup.py
        # instead of hardcoding it.
        c.main.cfg_file.write(os.path.join(
            sys.prefix, "share/retain-sync/config-template"))

        local_dir = LocalSyncDir(c.main.cfg_file.vals["LocalDir"])
        if c.main.cfg_file.vals["RemoteHost"]:
            dest_dir = DestSyncDir(c.main.mnt_dir)
            c.ssh = SSHConnection()
            c.ssh.connect()
            atexit.register(c.ssh.disconnect)
        else:
            dest_dir = DestSyncDir(c.main.cfg_file.vals["RemoteDir"])
        dest_dir.check()

        # Generate the exclude pattern file.
        c.main.ex_file.generate(c.cmd_args["exclude"])

        # The profile is now partially initialized. If the initilization is
        # interrupted from this point, it can be resumed.
        c.main.info_file.generate()
        atexit.register(interrupt_msg)
        atexit.unregister(delete_profile)

    atexit.register(dest_dir.unmount_ssh)
    dest_dir.mount_ssh()
    os.makedirs(dest_dir.ex_dir, exist_ok=True)

    if c.cmd_args["add_remote"]:
        # Expand exclude globbing patterns.
        c.main.ex_file.glob(dest_dir.path)

        # Check that there is enough local space to accomodate remote files.
        if dest_dir.total_size() > local_dir.space_avail():
            err("Error: not enough local space to accomodate remote files")
            sys.exit(1)
    else:
        # Expand exclude globbing patterns.
        c.main.ex_file.glob(local_dir.path)

        # Check that there is enough remote space to accomodate local files.
        if local_dir.total_size() > dest_dir.space_avail():
            err("Error: not enough space in remote to accomodate local files")
            sys.exit(1)

        # Copy local files to the server.
        rsync_cmd(
            ["-asHAXS", local_dir.tpath, dest_dir.safe_path],
            exclude=c.main.ex_file.rel_files,
            msg="Moving files to remote...")

    # Overwrite local files with symlinks to the corresponding files in the
    # remote dir.
    dest_dir.symlink_tree(local_dir.path, True)

    # Generate file priority database.
    if not os.path.isfile(c.main.db_file.path):
        c.main.db_file.create()
        for filepath in local_dir.list_files():
            c.main.db_file.add_file(filepath)

    # Copy exclude pattern file to remote directory for use when remote dir is
    # shared.
    shutil.copy(c.main.ex_file.path, os.path.join(
        dest_dir.ex_dir, c.main.info_file.vals["ID"]))

    # The profile is now fully initialized. Update the info file.
    c.main.info_file.vals["Status"] = "init"
    c.main.info_file.update_synctime()
    c.main.info_file.write()
    atexit.unregister(dest_dir.unmount_ssh)
    atexit.unregister(interrupt_msg)

    # Advise user to start/enable the daemon.
    print(dedent("""
        Run 'systemctl --user start retain-sync@{0}.service' to start the daemon.
        Run 'systemctl --user enable retain-sync@{0}.service' to start the daemon
        automatically on login""".format(c.main.name)))
