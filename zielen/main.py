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
        handle_signals()
        cmd_args = parse_args()
        command = def_command(cmd_args)
        command.main()
    except ProgramError as e:
        for message in e.args:
            err("Error: {}".format(message))
        return 1
    return 0


def daemon(profile_name) -> None:
    """Start the daemon."""
    try:
        handle_signals()
        ghost = Daemon(profile_name)
        ghost.main()
    except ProgramError as e:
        for message in e.args:
            err("Error: {}".format(message))


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


def handle_signals() -> None:
    """Exit properly on SIGTERM, SIGHUP or SIGINT."""
    def handler(signum: int, frame) -> None:
        """Print an appropriate error message for an interruption by signal."""
        raise ProgramError("program received" + signal.Signals(signum).name)

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGHUP, handler)
    signal.signal(signal.SIGINT, handler)
