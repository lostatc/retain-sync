# retain-sync
retain-sync is a program that helps you conserve disk space by automatically
offloading the files you don't use as often to a local or remote destination.
This can be a slower, higher-capacity hard drive or a remote file server (using
sshfs). Files are prioritized based on how frequently and recently they've been
accessed as well as the file size. The highest-priority files are kept in the
local directory for quick access, while lower priority files are moved to the
remote directory to conserve disk space. The program uses symbolic links to
allow files in the remote directory to be accessible from the local one. The
user can specify how much data they want to remain in the local directory at
any given point in time. Multiple concurrent pairs of directories can be
synced, and since they can overlap, retain-sync allows you to store your files
centrally and sync them across multiple clients as storage space permits.

Since this software is still in an immature state, it is recommended that you
back up your data before testing it.

## Features
* uses rsync for file transfers
* doesn't require root privileges
* doesn't have a server-side component
* gives the user the ability to exclude files from syncing
* handles interruptions and dropped connections
* implements locking to prevent multiple operations from taking place on the
  same directory tree
* searches for deleted files in the user's local trash before deleting them on
  the server
* provides options for configuring syncing behavior
* supports configuration file templates

## Installation
#### Dependencies
* python >= 3.5
* rsync
* sshfs (optional)
* systemd

#### Installing from source
```
git clone https://github.com/lostatc/retain-sync
cd retain-sync
sudo make install
```

## Documentation
[retain-sync(1)](https://lostatc.github.io/retain-sync/retain-sync.1.html)
