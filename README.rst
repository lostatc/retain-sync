======
zielen
======
This program is still in active development, and is not yet ready for general
use.

**zielen** is a program that tries to conserve disk space by redistributing
your files based on their size and how frequently you access them. Your most
frequently-used files stay local for quick access, while files used less
frequently are pushed to a remote destination to conserve disk space. This can
be a slower, higher-capacity hard drive or another computer via NFS or SMB.
Symbolic links are used to allow you to access those remote files as if they
were still where you left them.

You can specify how much data you want the program to keep in the local
directory vs the remote one. Since different machines can share a remote
directory, **zielen** allows you to store your files centrally and sync them
across multiple clients as storage space permits.

`Documentation <https://zielen.readthedocs.io/en/latest/index.html>`_

Features
========
* Allows syncing across filesystem boundaries, including network filesystems
* Does not require root privileges
* Gives the user the ability to exclude files from syncing
* Handles interruptions and dropped connections
* Provides options for configuring syncing behavior
* Supports templates for quickly setting up new directories

Installation
============
Dependencies
------------
* `Python <https://www.python.org/>`_ >= 3.5
* `pyinotify <https://github.com/seb-m/pyinotify>`_
* `Sphinx <http://www.sphinx-doc.org/en/stable/>`_

Installing from source
----------------------
Run the following commands in the downloaded source directory::

    make
    sudo make install
