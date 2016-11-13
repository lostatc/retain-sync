"""Manage command-line input and the printing of usage messages."""

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

import argparse
import textwrap
import re
import sys
import pkg_resources

from retainsync.utility import err

def usage(command):
    """Print a usage message."""

    # Define ANSI escape color codes.
    if sys.stdout.isatty():
        normal = "\033[0m"      # This is no formatting.
        color1 = "\033[1;31m"   # This is bold red, used for commands/options.
        color2 = "\033[1;32m"   # This is bold green, used for arguments.
    else:
        # Don't use colors if stdout is being redirected.
        normal = ""
        color1 = ""
        color2 = ""

    if not command:
        help_msg = textwrap.dedent("""\
            Usage: {1}retain-sync{0} [{2}global_options{0}] {2}command{0} [{2}command_options{0}] [{2}command_arg{0}]

            Global options:
                    {1}--help{0}      Print a usage message and exit.
                    {1}--version{0}   Print the version number and exit.
                {1}-q{0}, {1}--quiet{0}     Suppress all non-error output.

            Commands:
                {1}initialize{0} [{2}options{0}] {2}config{0}
                    Create a new configuration for a pair of directories to sync.

                {1}sync{0} {2}config{0}|{2}path{0}
                    Redistribute files between the local and remote directories.

                {1}reset{0} [{2}options{0}] {2}config{0}|{2}path{0}
                    Retrieve all files from the remote directory and de-initialize the
                    local directory.

                {1}list-configs{0}
                    Print a table of all initialized directories and the names of their
                    configurations.

                {1}empty-trash{0} {2}config{0}|{2}path{0}
                    Permanently delete all files in the remote directory that are marked
                    for deletion.""")

    elif command == "initialize":
        help_msg = textwrap.dedent("""\
            {1}initialize{0} [{2}options{0}] {2}config{0}
                Create a new configuration for a pair of directories to sync.  Move files
                from the local directory to the remote one.
                {1}-e{0}, {1}--exclude{0} {2}file{0}
                    Get a list of file/directory paths from {2}file{0} (one per line) that
                    will be excluded from syncing. If {2}file{0} is '-', then a
                    newline-separated list of file paths will be accepted from stdin.
                {1}-t{0}, {1}--template{0} {2}file{0}
                    Get settings for the configuration from the template {2}file{0} instead
                    of prompting the user interactively.
                {1}-a{0}, {1}--add-remote{0}
                    Instead of moving local files to an empty remote directory, start with
                    an existing remote directory and an empty local directory.""")

    elif command == "sync":
        help_msg = textwrap.dedent("""\
            {1}sync{0} {2}config{0}|{2}path{0}
                Redistribute files between the local and remote directories based on their
                priority and update the remote directory with any new or deleted files.""")

    elif command == "reset":
        help_msg = textwrap.dedent("""\
            {1}reset{0} [{2}options{0}] {2}config{0}|{2}path{0}
                Retrieve all files from the remote directory and de-initialize the local
                directory.
                {1}-k{0}, {1}--keep-remote{0}
                    Copy files from the remote directory to the local one instead of moving
                    them.
                {1}-n{0}, {1}--no-retrieve{0}
                    Don't retrieve files from the remote directory.""")

    elif command == "list-configs":
        help_msg = textwrap.dedent("""\
            {1}list-configs{0}
                Print a table of all initialized directories and the names of their
                configurations.""")

    elif command == "empty-trash":
        help_msg = textwrap.dedent("""\
            {1}empty-trash{0} {2}config{0}|{2}path{0}
                Permanently delete all files in the remote directory that are marked for
                deletion.""")

    help_msg = help_msg.format(normal, color1, color2)
    print(help_msg)

class CustomArgumentParser(argparse.ArgumentParser):
    """Set custom formatting of error messages for argparse."""
    def error(self, message):
        err("Error: {0}".format(message))
        sys.exit(2)

class HelpAction(argparse.Action):
    """Handle the '--help' flag."""
    def __init__(self, nargs=0, **kwargs):
        super(HelpAction, self).__init__(nargs=nargs, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        usage(namespace.command)
        parser.exit()

class VersionAction(argparse.Action):
    """Handle the '--version' flag."""
    def __init__(self, nargs=0, **kwargs):
        super(VersionAction, self).__init__(nargs=nargs, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        print("retain-sync",
            pkg_resources.get_distribution("retain-sync").version)
        parser.exit()

def parse_args():
    """Parse command-line arguments."""

    parser = CustomArgumentParser(add_help=False)
    parser.add_argument("--help", action=HelpAction)
    parser.add_argument("--version", action=VersionAction)
    parser.add_argument("--quiet", "-q", action="store_true")

    subparsers = parser.add_subparsers(dest="command")

    parser_init = subparsers.add_parser("initialize", add_help=False)
    parser_init.add_argument("--help", action=HelpAction)
    parser_init.add_argument("--exclude", "-e")
    parser_init.add_argument("--template", "-t")
    parser_init.add_argument("--add-remote", "-a", action="store_true")
    parser_init.add_argument("config", metavar="config or path")
    parser_init.set_defaults(command="initialize")

    parser_sync = subparsers.add_parser("sync", add_help=False)
    parser_sync.add_argument("--help", action=HelpAction)
    parser_sync.add_argument("config", metavar="config or path")
    parser_sync.set_defaults(command="sync")

    parser_reset = subparsers.add_parser("reset", add_help=False)
    parser_reset.add_argument("--help", action=HelpAction)
    parser_reset.add_argument("--keep-remote", "-k", action="store_true")
    parser_reset.add_argument("--no-retrieve", "-n", action="store_true")
    parser_reset.add_argument("config", metavar="config or path")
    parser_reset.set_defaults(command="reset")

    parser_listconfigs = subparsers.add_parser("list-configs", add_help=False)
    parser_listconfigs.add_argument("--help", action=HelpAction)
    parser_listconfigs.set_defaults(command="list-configs")

    parser_emptytrash = subparsers.add_parser("empty-trash", add_help=False)
    parser_emptytrash.add_argument("--help", action=HelpAction)
    parser_emptytrash.add_argument("config", metavar="config or path")
    parser_emptytrash.set_defaults(command="empty-trash")

    return vars(parser.parse_args())
