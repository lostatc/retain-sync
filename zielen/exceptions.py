"""Program-wide exceptions.

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
# Some of these exceptions closely resemble builtins. The point of having them
# separate is to differentiate errors that should print a user-friendly error
# message as opposed to a stack trace. We don't inherit from both ProgramError
# and a related builtin exception because doing so truncates the argument list.


class ProgramError(Exception):
    """Base exception for errors anticipated during normal operation."""


class ServerError(ProgramError):
    """Raised whenever a connection to the server cannot be established."""


class AvailableSpaceError(ProgramError):
    """Raised whenever there is not enough space to accommodate files."""


class InputError(ProgramError):
    """Raised whenever user-provided input is invalid."""


class FileParseError(ProgramError):
    """Raised whenever there is an issue parsing a program file."""


class FileTransferError(ProgramError):
    """Raised whenever there is an issue with a file transfer."""


class StatusError(ProgramError):
    """Raised whenever there is an issue with the status of the program."""
