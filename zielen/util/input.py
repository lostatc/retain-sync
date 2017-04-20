"""Manage command-line input and the printing of usage messages.

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
import os
import argparse
import pkg_resources
from textwrap import dedent

from zielen.exceptions import InputError


def usage(command: str) -> None:
    """Print a usage message."""

    if sys.stdout.isatty():
        normal = chr(27) + "[0m"    # No formatting.
        strong = chr(27) + "[1m"    # Bold, used for commands/options.
        emphasis = chr(27) + "[4m"  # Underlined, used for arguments.
    else:
        # Don't use colors if stdout isn't a tty.
        normal = emphasis = strong = ""

    if not command:
        help_msg = dedent("""\
            Usage: {1}zielen{0} [{2}global_options{0}] {2}command{0} [{2}command_options{0}] [{2}command_args{0}]

            Global options:
                    {1}--help{0}          Print a usage message and exit.
                    {1}--version{0}       Print the version number and exit.
                {1}-q{0}, {1}--quiet{0}         Suppress all non-error output.

            Commands:
                {1}initialize{0} [{2}options{0}] {2}name{0}
                    Create a new profile, called {2}name{0}, representing a pair of directories to
                    sync.

                {1}sync{0} {2}name{0}|{2}path{0}
                    Bring the local and remote directories in sync and redistribute files based on
                    their priorities.

                {1}reset{0} [{2}options{0}] {2}name{0}|{2}path{0}
                    Retrieve all files from the remote directory and de-initialize the
                    local directory.

                {1}list{0}
                    Print a table of all initialized local directories and the names of
                    their profiles.

                {1}empty-trash{0} {2}name{0}|{2}path{0}
                    Permanently delete all files in the remote trash directory.""")

    elif command == "initialize":
        help_msg = dedent("""\
            {1}initialize{0} [{2}options{0}] {2}name{0}
                Create a new profile, called {2}name{0}, representing a pair of directories to
                sync. Move files from the local directory to the remote one.

                {1}-e{0}, {1}--exclude{0} {2}file{0}
                    Get patterns from {2}file{0} representing files and directories to exclude from
                    syncing.

                {1}-t{0}, {1}--template{0} {2}file{0}
                    Get settings for the profile from the template {2}file{0} instead
                    of prompting the user interactively.

                {1}-a{0}, {1}--add-remote{0}
                    Instead of moving local files to an empty remote directory, start with
                    an existing remote directory and an empty local directory.""")

    elif command == "sync":
        help_msg = dedent("""\
            {1}sync{0} {2}name{0}|{2}path{0}
                Bring the local and remote directories in sync and redistribute files based on
                their priorities.""")

    elif command == "reset":
        help_msg = dedent("""\
            {1}reset{0} [{2}options{0}] {2}name{0}|{2}path{0}
                Retrieve all files from the remote directory and de-initialize the local
                directory.

                {1}-k{0}, {1}--keep-remote{0}
                    Copy files from the remote directory to the local one instead of moving
                    them.

                {1}-n{0}, {1}--no-retrieve{0}
                    Don't retrieve files from the remote directory.""")

    elif command == "list":
        help_msg = dedent("""\
            {1}list{0}
                Print a table of all initialized directories and the names of their
                profiles.""")

    elif command == "empty-trash":
        help_msg = dedent("""\
            {1}empty-trash{0} {2}name{0}|{2}path{0}
                Permanently delete all files in the remote trash directory.""")

    help_msg = help_msg.format(normal, strong, emphasis)
    print(help_msg)


class CustomArgumentParser(argparse.ArgumentParser):
    """Set custom formatting of error messages for argparse."""
    def error(self, message) -> None:
        raise InputError(message)


class HelpAction(argparse.Action):
    """Handle the '--help' flag."""
    def __init__(self, nargs=0, **kwargs) -> None:
        super().__init__(nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        usage(namespace.command)
        parser.exit()


class VersionAction(argparse.Action):
    """Handle the '--version' flag."""
    def __init__(self, nargs=0, **kwargs) -> None:
        super().__init__(nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        print(
            "zielen",
            pkg_resources.get_distribution("zielen").version)
        parser.exit()


class QuietAction(argparse.Action):
    """Handle the '--quiet' flag."""
    def __init__(self, nargs=0, **kwargs) -> None:
        super().__init__(nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        sys.stdout = open(os.devnull, "a")


def parse_args() -> argparse.Namespace:
    """Create a dictionary of parsed command-line arguments.

    Returns:
        A namepsace of command-line argument names and their values.
    """
    parser = CustomArgumentParser(add_help=False)
    parser.add_argument("--help", action=HelpAction)
    parser.add_argument("--version", action=VersionAction)
    parser.add_argument("--quiet", "-q", action=QuietAction)

    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    parser_init = subparsers.add_parser("initialize", add_help=False)
    parser_init.add_argument("--help", action=HelpAction)
    parser_init.add_argument("--exclude", "-e")
    parser_init.add_argument("--template", "-t")
    parser_init.add_argument("--add-remote", "-a", action="store_true")
    parser_init.add_argument("profile", metavar="profile name")
    parser_init.set_defaults(command="initialize")

    parser_sync = subparsers.add_parser("sync", add_help=False)
    parser_sync.add_argument("--help", action=HelpAction)
    parser_sync.add_argument("profile", metavar="profile name or path")
    parser_sync.set_defaults(command="sync")

    parser_reset = subparsers.add_parser("reset", add_help=False)
    parser_reset.add_argument("--help", action=HelpAction)
    parser_reset.add_argument("--keep-remote", "-k", action="store_true")
    parser_reset.add_argument("--no-retrieve", "-n", action="store_true")
    parser_reset.add_argument("profile", metavar="profile name or path")
    parser_reset.set_defaults(command="reset")

    parser_listprofiles = subparsers.add_parser("list", add_help=False)
    parser_listprofiles.add_argument("--help", action=HelpAction)
    parser_listprofiles.set_defaults(command="list")

    parser_emptytrash = subparsers.add_parser("empty-trash", add_help=False)
    parser_emptytrash.add_argument("--help", action=HelpAction)
    parser_emptytrash.add_argument("profile", metavar="profile name or path")
    parser_emptytrash.set_defaults(command="empty-trash")

    return parser.parse_args()
