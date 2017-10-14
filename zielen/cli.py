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
import signal
import sys
import os
import argparse
import pkg_resources
from textwrap import dedent

from linotype import Item, DefinitionStyle

from zielen.commandbase import Command
from zielen.daemon import Daemon
from zielen.exceptions import ProgramError, InputError
from zielen.commands.emptytrash import EmptyTrashCommand
from zielen.commands.init import InitCommand
from zielen.commands.list import ListCommand
from zielen.commands.reset import ResetCommand
from zielen.commands.sync import SyncCommand


def main_help_item() -> Item:
    """Structure the main help message.

    Returns:
        An Item object with the message.
    """
    root_item = Item()

    usage = root_item.add_text("Usage:")
    usage.add_definition(
        "zielen", "[global_options] command [command_args]", "")
    root_item.add_text("\n")

    global_opts = root_item.add_text("Global Options:", item_id="global_opts")
    global_opts.formatter.definition_style = DefinitionStyle.ALIGNED
    global_opts.add_definition(
        "    --help", "",
        "Print a usage message and exit.")
    global_opts.add_definition(
        "    --version", "",
        "Print the version number and exit.")
    global_opts.add_definition(
        "    --debug", "",
        "Print a full stack trace instead of an error message if an error "
        "occurs.")
    global_opts.add_definition(
        "-q, --quiet", "",
        "Suppress all non-error output.")
    root_item.add_text("\n")

    commands = root_item.add_text("Commands:", item_id="commands")
    commands.add_definition(
        "init", "[options] name",
        "Create a new profile, called name, representing a pair of "
        "directories to sync.")
    commands.add_text("\n")
    commands.add_definition(
        "sync", "name|path",
        "Bring the local and remote directories in sync and redistribute "
        "files based on their priorities.")
    commands.add_text("\n")
    commands.add_definition(
        "reset", "[options] name|path",
        "Retrieve all files from the remote directory and de-initialize the "
        "local directory.")
    commands.add_text("\n")
    commands.add_definition(
        "list", "",
        "Print a table of all profiles names and the paths of their local "
        "directories.")
    commands.add_text("\n")
    commands.add_definition(
        "empty-trash", "name|path",
        "Permanently delete all files in the remote trash directory.")

    return root_item


def command_help_item() -> Item:
    """Structure the help message for each command.

    Returns:
        An Item object with the message.
    """
    root_item = Item()

    init_item = root_item.add_definition(
        "init", "[options] name",
        "Create a new profile, called name, representing a pair of "
        "directories to sync. Move files from the local directory to the "
        "remote one.", item_id="init")
    init_item.add_text("\n")
    init_item.add_definition(
        "-e, --exclude", "file",
        "Get patterns from file representing files and directories to "
        "exclude from syncing.", item_id="exclude")
    init_item.add_text("\n")
    init_item.add_definition(
        "-t, --template", "file",
        "Get settings for the profile from the template file instead of "
        "prompting the user interactively. The user will still be prompted "
        "for any mandatory information that is missing from the template. A "
        "blank template can usually be found at "
        "/usr/share/zielen/config-template.", item_id="template")
    init_item.add_text("\n")
    init_item.add_definition(
        "-a, --add-remote", "",
        "Instead of moving local files to an empty remote directory, "
        "start with an existing remote directory and an empty local "
        "directory. Using this option, it is possible for two or more "
        "profiles to share a remote directory.", item_id="add-remote")
    root_item.add_text("\n")

    sync_item = root_item.add_definition(
        "sync", "name|path",
        "Bring the local and remote directories in sync and redistribute "
        "files based on their priorities. This command is run automatically "
        "at regular intervals by the daemon. This command accepts the name "
        "of a profile or the absolute path of its local directory.",
        item_id="sync")
    root_item.add_text("\n")

    reset_item = root_item.add_definition(
        "reset", "[options] name|path",
        "Retrieve all files from the remote directory and de-initialize the "
        "local directory. This command accepts the name of a profile or the "
        "absolute path of its local directory.", item_id="reset")
    reset_item.add_text("\n")
    reset_item.add_definition(
        "-k, --keep-remote", "",
        "Copy files from the remote directory to the local one instead of "
        "moving them. This leaves a copy of the files in the remote "
        "directory, which is useful when that remote directory is shared "
        "with other profiles that may also want to retrieve the files.",
        item_id="keep-remote")
    reset_item.add_text("\n")
    reset_item.add_definition(
        "-n, --no-retrieve", "",
        "Don't retrieve files from the remote directory. Remote files stay "
        "in the remote directory, and symbolic links to remote files are "
        "removed from the local directory. This option supersedes "
        "**--keep-remote**.", item_id="no-retrieve")
    root_item.add_text("\n")

    list_item = root_item.add_definition(
        "list", "",
        "Print a table of all profiles names and the paths of their local "
        "directories.", item_id="list")
    root_item.add_text("\n")

    empty_trash_item = root_item.add_definition(
        "empty-trash", "name|path",
        "Permanently delete all files in the remote trash directory. This "
        "command accepts the name of a profile or the absolute path of its "
        "local directory.", item_id="empty-trash")

    return root_item


class CustomArgumentParser(argparse.ArgumentParser):
    """Set custom formatting of error messages for argparse."""
    def error(self, message) -> None:
        raise InputError(message)


class HelpAction(argparse.Action):
    """Handle the '--help' flag."""
    def __init__(self, nargs=0, **kwargs) -> None:
        super().__init__(nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        if namespace.command:
            print(command_help_item().format(item_id=namespace.command))
        else:
            print(main_help_item().format())
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
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--quiet", "-q", action=QuietAction)

    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    parser_init = subparsers.add_parser("init", add_help=False)
    parser_init.add_argument("--help", action=HelpAction)
    parser_init.add_argument("--exclude", "-e")
    parser_init.add_argument("--template", "-t")
    parser_init.add_argument("--add-remote", "-a", action="store_true")
    parser_init.add_argument("profile", metavar="profile name")
    parser_init.set_defaults(command="init")

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
    except ProgramError as error:
        try:
            if cmd_args.debug:
                raise
        except NameError:
            pass
        for message in error.args:
            print("Error: {}".format(message), file=sys.stderr)
        return 1
    return 0


def daemon(profile_name) -> int:
    """Start the daemon.

    Always print a full stack trace instead of an error message.
    """
    # Exit properly on SIGTERM, SIGHUP or SIGINT. SIGTERM is the method
    # by which the daemon will normally exit, and should not raise an
    # exception.
    signal.signal(signal.SIGTERM, signal_exit_handler)
    signal.signal(signal.SIGHUP, signal_exception_handler)
    signal.signal(signal.SIGINT, signal_exception_handler)

    ghost = Daemon(profile_name)
    ghost.main()
    return 0


def def_command(cmd_args) -> Command:
    """Get an Command subclass instance from the command-line input."""
    if cmd_args.command == "init":
        return InitCommand(
            cmd_args.profile, cmd_args.exclude, cmd_args.template,
            cmd_args.add_remote)
    elif cmd_args.command == "sync":
        return SyncCommand(cmd_args.profile)
    elif cmd_args.command == "reset":
        return ResetCommand(
            cmd_args.profile, cmd_args.keep_remote,
            cmd_args.no_retrieve)
    elif cmd_args.command == "list":
        return ListCommand()
    elif cmd_args.command == "empty-trash":
        return EmptyTrashCommand(cmd_args.profile)


def signal_exception_handler(signum: int, frame) -> None:
    """Raise an exception with error message for an interruption by signal."""
    raise ProgramError("program received " + signal.Signals(signum).name)


def signal_exit_handler(signum: int, frame) -> None:
    """Exit the program normally in response to an interruption by signal."""
    sys.exit(0)
