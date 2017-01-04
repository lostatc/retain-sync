"""The main module for the client.

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
import signal
import time

from retainsync.util.input import parse_args
from retainsync.util.misc import err
from retainsync.io.program import NotMountedError
from retainsync.commands.initialize import InitializeCommand
from retainsync.commands.sync import SyncCommand


def main() -> None:
    """Main function."""
    # Exit properly on SIGTERM, SIGHUP or SIGINT
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Read command-line arguments.
    cmd_args = parse_args()

    # Implement the '--quiet' flag.
    if cmd_args["quiet"]:
        sys.stdout = open(os.devnull, "a")

    if cmd_args["command"] == "initialize":
        command = InitializeCommand(
            cmd_args["profile"], cmd_args["exclude"], cmd_args["template"],
            cmd_args["add_remote"])
    elif cmd_args["command"] == "sync":
        command = SyncCommand(cmd_args["profile"])
    elif cmd_args["command"] == "reset":
        pass
    elif cmd_args["command"] == "list":
        pass
    elif cmd_args["command"] == "empty-trash":
        pass

    try:
        command.main()
    except NotMountedError:
        err("Error: the connection to the remote directory was lost")
        sys.exit(1)


def signal_handler(signum: int, frame) -> None:
    """Print an appropriate error message for an interruption by signal."""
    err("Error: program received", signal.Signals(signum).name)
    sys.exit(1)

if __name__ == "__main__":
    main()
