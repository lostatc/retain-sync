"""Watch for file access in the local directory and adjust priorities.

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
import sys
import time
import multiprocessing
import subprocess

import inotify.adapters

from zielen.basecommand import Command
from zielen.util.misc import err


class Daemon(Command):
    """Watch for file access in the local directory and adjust priorities.

    Every time a file is opened in the local directory, increment its
    priority value by one. Every twenty minutes, multiply the priority
    values of each file by a constant. Run the 'sync' command at a regular
    user-defined interval.

    Attributes:
        ADJUST_INTERVAL: This is the interval of time (in seconds) to wait
            between making priority adjustments. Two files accessed within this
            interval of time will be weighted the same.
        profile: The currently selected profile.
        files_queue: A Queue for temporarily holding the paths of files that
            have been opened in the local or remote directories before they're
            updated in the database.
    """
    ADJUST_INTERVAL = 10*60

    def __init__(self, profile_input) -> None:
        super().__init__()
        self.profile_input = profile_input
        self.profile = self.select_profile(profile_input)
        self.files_queue = multiprocessing.Queue()

    def main(self) -> None:
        """Start the daemon."""
        self.profile.info_file.read()
        self.profile.cfg_file.read()
        self.profile.cfg_file.check_all()

        sync_proc = multiprocessing.Process(target=self._sync, daemon=True)
        sync_proc.start()

        local_dir = self.profile.cfg_file.vals["LocalDir"]
        if self.profile.cfg_file.vals["RemoteHost"]:
            dest_dir = self.profile.mnt_dir
        else:
            dest_dir = self.profile.cfg_file.vals["RemoteDir"]

        # The 'inotify' documentation strongly recommends that directory
        # watches be in their own process.
        local_watch_proc = multiprocessing.Process(
            target=self._watch, args=(local_dir,), daemon=True)
        local_watch_proc.start()
        remote_watch_proc = multiprocessing.Process(
            target=self._watch, args=(dest_dir,), daemon=True)
        remote_watch_proc.start()

        # Every second, get a set of file paths from the queue and increment
        # their priority values in the database. This is done to spread out
        # the individual sqlite transactions over time so that the database
        # isn't a bottleneck. A set is used to prevent any individual file
        # from being counted more than once per second. Only the priorities of
        # regular files are incremented (not directories).
        while True:
            accessed_paths = set()
            while self.files_queue.qsize() != 0:
                path = self.files_queue.get()
                path_data = self.profile.db_file.get_path(path)
                if path_data and not path_data.directory:
                    accessed_paths.add(path)
            self.profile.db_file.increment(accessed_paths, 1)
            self.profile.db_file.conn.commit()

            self._adjust()
            time.sleep(1)

    def _adjust(self) -> None:
        """Adjust the priority values in the database every twenty minutes."""
        if (time.time() >= self.profile.info_file.vals["LastAdjust"]
                + self.ADJUST_INTERVAL):
            # This is necessary because a sync may have occurred since
            # the last adjustment, which updates a value in the info
            # file. If we don't read the info file before writing to it,
            # that value will get reset.
            self.profile.info_file.read()

            # Use the formula for half-life to calculate the constant to
            # multiply each priority value by.
            adjust_constant = (0.5 ** (
                    self.ADJUST_INTERVAL
                    / self.profile.cfg_file.vals["PriorityHalfLife"]))

            self.profile.db_file.adjust_all(adjust_constant)
            self.profile.info_file.update_adjusttime()
            self.profile.info_file.write()

    def _sync(self) -> None:
        """Initiate a sync at a regular interval."""
        last_attempt = self.profile.info_file.vals["LastSync"]
        while True:
            if (time.time() >= last_attempt
                    + self.profile.cfg_file.vals["SyncInterval"]):
                # Use a subprocess so that an in-progress sync continues
                # after the daemon exits and so that functions registered
                # with atexit execute correctly.
                cmd = subprocess.Popen(
                    ["zielen", "sync", self.profile_input], bufsize=1,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, universal_newlines=True)

                # Print the subprocess's stderr to stderr so that it is
                # added to the journal.
                for line in cmd.stderr:
                    if line.strip():
                        err(line)
                cmd.wait()
                sys.stderr.flush()

                # If a sync fails, wait the full interval before trying again.
                last_attempt = time.time()
            time.sleep(1)

    def _watch(self, start_path: str) -> None:
        """Get paths of files that have been opened and add them to a queue.

        Args:
            start_path: The absolute path of the directory to watch for file
                access.
        """
        # This class constructor only accepts file paths in bytes form.
        adapter = inotify.adapters.InotifyTree(start_path.encode())
        for event in adapter.event_gen():
            if event is not None:
                header, type_names, watch_path, filename = event
                accessed_path = os.path.relpath(
                    os.path.join(watch_path.decode(), filename.decode()),
                    start_path)
                if "IN_OPEN" in type_names:
                    self.files_queue.put(accessed_path)
