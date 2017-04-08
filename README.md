# zielen
This program is still in active development, and is not yet ready for general
use.

zielen is a program that tries to conserve disk space by redistributing your
files based on their size and how frequently you access them. Your most
frequently-used files stay local for quick access, while files used less
frequently are pushed to a remote destination to conserve disk space. This can
be a slower, higher-capacity hard drive or another computer (using ssh).
Symbolic links are used to allow you to access those remote files as if they
were still where you left them.

You can specify how much data you want the program to keep in the local
directory vs the remote one. Multiple concurrent pairs of directories can be
synced, and since they can overlap, zielen allows you to store your files
centrally and sync them across multiple clients as storage space permits.

[Documentation](https://zielen.readthedocs.io/en/latest/index.html)

## Features
* uses rsync's delta-transfer algorithm to only sync the differences between
  files
* uses ssh for syncing between computers, which is secure and easy to set up
* does not require root privileges
* gives the user the ability to exclude files from syncing
* handles interruptions and dropped connections
* provides options for configuring syncing behavior
* supports configuration file templates

## Installation
#### Dependencies
* [python](https://www.python.org/) >= 3.5
* [sshfs](https://github.com/libfuse/sshfs)
* [rsync](https://rsync.samba.org/)
* [inotify](https://github.com/dsoprea/PyInotify)
* [Sphinx](http://www.sphinx-doc.org/en/stable/)

#### Installing from source
Run the following commands in the downloaded source directory.
```
make
sudo make install
```

## Notes
If you're using an ssh agent, zielen needs the location of the
authenication socket in order to connect. The program will try to find this
automatically, but if that doesn't work, add the following command to the
bottom of your ~/.bashrc file.
```
systemctl --user import-environment SSH_AUTH_SOCK
```
