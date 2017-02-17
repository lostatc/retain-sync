"""The main module for the client.

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
import sys
import signal

from zielen.exceptions import ProgramError
from zielen.basecommand import Command
from zielen.daemon import Daemon
from zielen.commands.initialize import InitializeCommand
from zielen.commands.sync import SyncCommand
from zielen.util.input import parse_args
from zielen.util.misc import err


def main() -> int:
    """Start the program."""
    try:
        # Exit properly on SIGTERM, SIGHUP or SIGINT.
        signal.signal(signal.SIGTERM, signal_exception_handler)
        signal.signal(signal.SIGHUP, signal_exception_handler)
        signal.signal(signal.SIGINT, signal_exception_handler)

        cmd_args = parse_args()
        command = def_command(cmd_args)
        command.main()
    except ProgramError as e:
        for message in e.args:
            err("Error: {}".format(message))
        return 1
    return 0


def daemon(profile_name) -> int:
    """Start the daemon."""
    try:
        # Exit properly on SIGTERM, SIGHUP or SIGINT. SIGTERM is the method
        # by which the daemon will normally exit, and should not raise an
        # exception.
        signal.signal(signal.SIGTERM, signal_exit_handler)
        signal.signal(signal.SIGHUP, signal_exception_handler)
        signal.signal(signal.SIGINT, signal_exception_handler)

        ghost = Daemon(profile_name)
        ghost.main()
    except ProgramError as e:
        for message in e.args:
            err("Error: {}".format(message))
        return 1
    return 0


def def_command(cmd_args: dict) -> Command:
    """Get an Command subclass instance from the command-line input."""
    if cmd_args["command"] == "initialize":
        return InitializeCommand(
            cmd_args["profile"], cmd_args["exclude"], cmd_args["template"],
            cmd_args["add_remote"])
    elif cmd_args["command"] == "sync":
        return SyncCommand(cmd_args["profile"])
    elif cmd_args["command"] == "reset":
        pass
    elif cmd_args["command"] == "list":
        pass
    elif cmd_args["command"] == "empty-trash":
        pass


def signal_exception_handler(signum: int, frame) -> None:
    """Raise an exception with error message for an interruption by signal."""
    raise ProgramError("program received " + signal.Signals(signum).name)


def signal_exit_handler(signum: int, frame) -> None:
    """Exit the program normally in response to an interruption by signal."""
    sys.exit(0)
