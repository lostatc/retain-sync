"""Program-wide constants.

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
import os


def get_home_dir():
    return os.path.expanduser("~/")


def get_xdg_config_home():
    return os.getenv(
        "XDG_CONFIG_HOME", os.path.join(get_home_dir(), ".config"))


def get_xdg_data_home():
    return os.getenv(
        "XDG_DATA_HOME", os.path.join(get_home_dir(), ".local/share"))


def get_xdg_runtime_dir():
    return os.getenv(
        "XDG_RUNTIME_DIR", os.path.join("/run/user", str(os.getuid())))


def get_program_dir():
    return os.path.join(get_xdg_config_home(), "zielen")


def get_profiles_dir():
    return os.path.join(get_program_dir(), "profiles")
