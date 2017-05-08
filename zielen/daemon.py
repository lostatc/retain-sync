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
import queue
import threading
import subprocess
from typing import Tuple

import pyinotify

from zielen.basecommand import Command


class Daemon(Command):
    """Watch for file access in the local directory and adjust priorities.

    Every time a file or symlink is opened in the local directory, increment
    its priority value by a constant. At regular intervals, multiply the
    priority values of each file by a constant. Run the 'sync' command at a
    regular user-defined interval.

    Attributes:
        ADJUST_INTERVAL: This is the interval of time (in seconds) to wait
            between making priority adjustments. Two files accessed within this
            interval of time will be weighted the same.
        INCREMENT_AMOUNT: A constant value to add to the priority value every
            time a file is accessed.
        profile: The currently selected profile.
    """
    ADJUST_INTERVAL = 10*60
    INCREMENT_AMOUNT = 1

    def __init__(self, profile_input) -> None:
        super().__init__()
        self.profile_input = profile_input
        self.profile = self.select_profile(profile_input)

    def main(self) -> None:
        """Start the daemon."""
        self.profile.info_file.read()
        self.profile.cfg_file.read()
        self.profile.cfg_file.check_all()

        sync_thread = threading.Thread(target=self._sync, daemon=True)
        sync_thread.start()

        local_dir = self.profile.cfg_file.vals["LocalDir"]
        if self.profile.cfg_file.vals["RemoteHost"]:
            dest_dir = self.profile.mnt_dir
        else:
            dest_dir = self.profile.cfg_file.vals["RemoteDir"]

        wm = pyinotify.WatchManager()
        files_queue = queue.Queue()
        notifier = pyinotify.ThreadedNotifier(
            wm, files_queue.put, read_freq=1)
        notifier.coalesce_events()
        notifier.daemon = True
        notifier.start()

        mask = pyinotify.IN_OPEN | pyinotify.IN_CREATE
        watch_paths = [local_dir, dest_dir]
        for watch_path in watch_paths:
            wm.add_watch(watch_path, mask, rec=True, auto_add=True)

        # Every few seconds, get a set of file paths from the queue and
        # increment their priority values in the database. This is done to
        # spread out the individual sqlite transactions over time so that
        # the database isn't a bottleneck.
        while True:
            accessed_paths = []
            while not files_queue.empty():
                event = files_queue.get()
                for watch_path in watch_paths:
                    if os.path.commonpath([
                            event.pathname, watch_path]) == watch_path:
                        rel_path = os.path.relpath(event.pathname, watch_path)
                        break

                if not event.dir and self.profile.db_file.get_path(rel_path):
                    # The file is in the local database and is not a directory.
                    # New files do not have a priority value until the first
                    # sync after they are added.
                    accessed_paths.append(rel_path)

            self.profile.db_file.increment(
                accessed_paths, self.INCREMENT_AMOUNT)
            self.profile.db_file.conn.commit()

            self._adjust()
            time.sleep(3)

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
            half_life = self.profile.cfg_file.vals["PriorityHalfLife"]
            adjust_constant = (0.5 ** (self.ADJUST_INTERVAL / half_life))

            self.profile.db_file.adjust_all(adjust_constant)
            self.profile.info_file.vals["LastAdjust"] = time.time()
            self.profile.info_file.write()

    def _sync(self) -> None:
        """Initiate a sync in a subprocess at a regular interval."""
        last_attempt = self.profile.info_file.vals["LastSync"]
        while True:
            if (time.time() >= last_attempt
                    + self.profile.cfg_file.vals["SyncInterval"]):
                # Use a subprocess so that an in-progress sync continues
                # after the daemon exits and so that functions registered
                # with atexit execute correctly.
                cmd = subprocess.Popen(
                    ["zielen", "--debug", "sync", self.profile_input],
                    bufsize=1, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, universal_newlines=True)

                # Print the subprocess's stderr to stderr so that it is
                # added to the journal.
                for line in cmd.stderr:
                    if line:
                        print(line, file=sys.stderr, end="")
                cmd.wait()
                sys.stderr.flush()

                # If a sync fails, wait the full interval before trying again.
                last_attempt = time.time()
            time.sleep(1)
