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
import time
import multiprocessing

import inotify.adapters

from zielen.basecommand import Command


class Daemon(Command):
    """Watch for file access in the local directory and adjust priorities.

    Every time a file is opened in the local directory, increment its
    priority value by one. Every twenty minutes, multiply the priority
    values of each file by a constant. These priority values are stored in
    the local database.

    Attributes:
        adjust_interval:    The interval of time (in seconds) to wait between
                            making priority adjustments.
        adjust_constant:    The constant value used to adjust priorities for
                            time.
        profile:            The currently selected profile.
        files_queue:        A Queue for temporarily holding the paths of files
                            that have been opened in the local or remote
                            directories before they're updated in the database.
    """
    adjust_interval = 20*60
    adjust_constant = 0.99

    def __init__(self, profile_in):
        super().__init__()
        self.profile = self.select_profile(profile_in)
        self.files_queue = multiprocessing.Queue()

    def main(self):
        """Start the daemon."""
        self.profile.info_file.read()
        self.profile.cfg_file.read()
        self.profile.cfg_file.check_all()

        adjust_proc = multiprocessing.Process(target=self._adjust, daemon=True)
        adjust_proc.start()

        local_dir = self.profile.cfg_file.vals["LocalDir"]
        if self.profile.cfg_file.vals["RemoteHost"]:
            remote_dir = self.profile.mnt_dir
        else:
            remote_dir = self.profile.cfg_file.vals["RemoteDir"]

        local_watch_proc = multiprocessing.Process(
            target=self._watch, args=(local_dir,), daemon=True)
        local_watch_proc.start()
        remote_watch_proc = multiprocessing.Process(
            target=self._watch, args=(remote_dir,), daemon=True)
        remote_watch_proc.start()

        # Every second, get a set of file paths from the queue and increment
        # their priority values in the database. This is done to spread out
        # the individual sqlite transactions over time so that the database
        # isn't a bottleneck. A set is used to prevent any individual file
        # from being counted more than once per second.
        while True:
            accessed_files = set()
            while self.files_queue.qsize() != 0:
                accessed_files.add(self.files_queue.get())
            self.profile.db_file.increment(accessed_files)
            time.sleep(1)

    def _adjust(self):
        """Adjust the priority values in the database every twenty minutes."""
        while True:
            if (time.time() >= self.profile.info_file.vals["LastAdjust"]
                    + self.adjust_interval):
                # This is necessary because a sync may have occurred since
                # the last adjustment, which updates a value in the info file.
                self.profile.info_file.read()

                self.profile.db_file.adjust_all(self.adjust_constant)
                self.profile.info_file.update_adjusttime()
                self.profile.info_file.write()
            time.sleep(5)

    def _watch(self, start_path: str):
        """Get path of files that have been opened and add them to a queue."""
        # This class constructor only accepts file paths in bytes form.
        adapter = inotify.adapters.InotifyTree(start_path.encode())
        for event in adapter.event_gen():
            if event is not None:
                header, type_names, watch_path, filename = event
                if "IN_OPEN" in type_names:
                    accessed_file = os.path.relpath(
                        os.path.join(watch_path.decode(), filename.decode()),
                        start_path)
                    self.files_queue.put(accessed_file)
