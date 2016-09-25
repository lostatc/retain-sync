# retain-sync
retain-sync is a program that helps you conserve disk space by automatically
offloading the files you don't use as often to a remote server over ssh. It
uses sshfs and symbolic links to allow local and remote files to be accessible
from the same directory tree.  Files are prioritized based on how frequently
and recently they've been accessed as well as their size, and they're shuffled
back and forth between the local and remote machines so that the
highest-priority files are kept local for quick access and the lower-priority
files are stored remotely to conserve disk space. The amount of data that's
kept on the local machine is configurable by the user.

Since this software is still in an immature state, it is suggested that you
back up your data before testing it.

## Features
* uses rsync for file transfers
* doesn't require root privileges
* gives the user the ability to exclude files from syncing
* handles interruptions and dropped connections
* implements locking to prevent multiple operations from taking place on the
  same directory tree
* searches for deleted files in the user's local trash before deleting them on
  the server

## Installation
#### Dependencies
* bash >=4.0
* bc
* inotify-tools
* rsync
* sshfs
* systemd

#### Installing from source
```
git clone https://github.com/lostatc/retain-sync
cd retain-sync
sudo make install
```
