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
import sqlite3
import threading
import subprocess

import pyinotify

from zielen.basecommand import Command


class Daemon(Command):
    """Watch for file access in the local directory and adjust priorities.

    Every time a file or symlink is opened in the local directory, increment
    its priority value by a constant. There is a "cooldown" period that
    coalesces quick successive openings of the same file. At regular
    intervals, multiply the priority values of each file by a constant. Run
    the 'sync' command at a regular user-defined interval.

    Attributes:
        ADJUST_INTERVAL: This is the interval of time (in seconds) to wait
            between making priority adjustments. Two files accessed within this
            interval of time will be weighted the same.
        INCREMENT_AMOUNT: A constant value to add to the priority value every
            time a file is accessed.
        COOLDOWN_PERIOD: The number of seconds that must pass after a file has
            had its priority incremented before its priority can be incremented
            again.
        profile: The currently selected profile.
        _files_queue: A queue of filesystem events that are waiting to be
            processed.
        _cooldown_files: A dict of file paths that have been opened within the
            past COOLDOWN_PERIOD seconds and their timestamps.
    """
    ADJUST_INTERVAL = 10*60
    INCREMENT_AMOUNT = 1
    COOLDOWN_PERIOD = 1

    def __init__(self, profile_input: str) -> None:
        super().__init__()
        self.profile_input = profile_input
        self.profile = self.select_profile(profile_input)
        self._files_queue = queue.Queue()
        self._cooldown_files = {}

    def main(self) -> None:
        """Start the daemon."""
        self.profile.read()

        sync_thread = threading.Thread(target=self._sync, daemon=True)
        sync_thread.start()

        local_dir = self.profile.local_path
        if self.profile.remote_host:
            dest_dir = self.profile.mnt_dir
        else:
            dest_dir = self.profile.remote_path

        wm = pyinotify.WatchManager()
        notifier = pyinotify.ThreadedNotifier(
            wm, lambda x: self._files_queue.put((x, time.time())))
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
        deduplicated_paths = []
        while True:
            accessed_paths = []
            while not self._files_queue.empty():
                event, timestamp = self._files_queue.get()
                for watch_path in watch_paths:
                    if os.path.commonpath([
                            event.pathname, watch_path]) == watch_path:
                        rel_path = os.path.relpath(event.pathname, watch_path)
                        break

                if not event.dir and self.profile.get_path_info(rel_path):
                    # The file is in the local database and is not a directory.
                    # New files do not have a priority value until the first
                    # sync after they are added.
                    accessed_paths.append((rel_path, timestamp))

            for path, timestamp in accessed_paths:
                past_timestamp = self._cooldown_files.get(path)

                if ((past_timestamp
                        and timestamp > past_timestamp + self.COOLDOWN_PERIOD)
                        or not past_timestamp):
                    # The time at which the current file was opened is not
                    # within self.COOLDOWN_PERIOD seconds of the time it
                    # was last opened.
                    deduplicated_paths.append(path)

                    # Update the timestamp for accessed file paths. Putting
                    # this inside the conditional statement prevents the
                    # cooldown period from lasting more than
                    # self.COOLDOWN_PERIOD seconds.
                    self._cooldown_files[path] = timestamp

            # Remove any file paths that were modified more than
            # self.COOLDOWN_PERIOD seconds in the past.
            current_time = time.time()
            self._cooldown_files = {
                path: timestamp
                for path, timestamp in self._cooldown_files.items()
                if timestamp > current_time - self.COOLDOWN_PERIOD}

            # If the database is locked due to a long-running sync, try again.
            try:
                self._adjust()
                self.profile.increment(
                    deduplicated_paths, self.INCREMENT_AMOUNT)
                self.profile.read()
                self.profile.write()
            except sqlite3.OperationalError:
                continue
            else:
                deduplicated_paths = []
            finally:
                time.sleep(3)

    def _adjust(self) -> None:
        """Adjust the priority values in the database at regular intervals."""
        if time.time() >= self.profile.last_adjust + self.ADJUST_INTERVAL:
            # This is necessary because a sync may have occurred since
            # the last adjustment, which updates a value in the info
            # file. If we don't read the info file before writing to it,
            # that value will get reset.
            self.profile.read()

            # Use the formula for half-life to calculate the constant to
            # multiply each priority value by.
            half_life = self.profile.priority_half_life
            adjust_constant = 0.5 ** (self.ADJUST_INTERVAL / half_life)

            self.profile.adjust_all(adjust_constant)
            self.profile.last_adjust = time.time()
            self.profile.write()

    def _sync(self) -> None:
        """Initiate a sync in a subprocess at a regular interval."""
        last_attempt = self.profile.last_sync
        while True:
            if time.time() >= last_attempt + self.profile.sync_interval:
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
            time.sleep(3)
