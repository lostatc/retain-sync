SYNOPSIS
========
**zielen** [*global_options*] *command* [*command_options*] [*command_args*]

DESCRIPTION
===========
**zielen** is a program that distributes files between a local and remote
directory based on how frequently they're accessed with the intent of
conserving disk space. This remote directory can be on a separate hard drive or
a seprate machine entirely (using ssh). Files are prioritized based on how
frequently and recently they've been accessed as well as the file size. The
highest-priority files are kept in the local directory for quick access, while
lower priority files are moved to the remote directory to conserve disk space.
It uses symbolic links to allow files in the remote directory to be accessible
from the local one. The user can specify how much data they want to remain in
the local directory at any given point in time Multiple local directories can
be synced concurrently with either different remote directories or the same
one. Since local directories on different machines can pair with the same
remote directory, **zielen** can be used to sync files between machines.

**zielen** is intended as a single-user solution only. It does not require root
access, and is meant to run as an unprivileged user. If the remote directory is
located on a separate machine, **zielen** does not need to be installed on that
machine to function, although you do need to have passwordless ssh access to it
(i.e. via public key authentication with an ssh agent).

Terminology
-----------
Local Directory
    A local directory is a directory on your local machine that you want to
    contain only the files that it has space for.

Remote Directory
    A remote directory is a directory, either on your local machine or
    elsewhere, that you want to contain a master copy of all of your files to
    be synced with one or more local directories.

Client
    A client is any computer containing a local directory that syncs with a
    remote directory on another computer.

Profile
    For every pair of directories you wish to sync, a profile must first be
    generated using the **initialize** command. Each profile has a config file
    that stores information about the two directories and settings that can be
    used to configure the syncing behavior (see FILES_).

Priority
    The priority is an internal value assigned to each file that is used to
    determine which should stay in the local directory. It is based on how
    frequently the file is accessed (weighted toward more recent access) and
    the size of the file (favoring smaller files).

Storage Limit
    The storage limit is the user-defined amount of data that will remain in
    the local directory. The program will fill the local directory until it
    reaches this size, starting with the highest priority files. Excluded files
    and symlinks pointing to files in the remote directory don't count toward
    the storage limit. Setting it to zero will prevent any files from remaining
    in the local directory.

GLOBAL OPTIONS
==============
**--help**
    Display a usage message and exit.

**--version**
    Print the version number and exit.

**-q**, **--quiet**
    Suppress all non-error output.

COMMANDS
========
**initialize** [*options*] *name*
    Create a new profile, called *name*, representing a pair of directories to
    sync. Move files from the local directory to the remote one.

    **-e**, **--exclude** *file*
        Get patterns from *file* representing files and directories to exclude
        from syncing (see EXCLUDING_).

    **-t**, **--template** *file*
        Get settings for the profile from the template *file* instead of
        prompting the user interactively. The user will still be prompted for
        any mandatory information that is missing from the template. A blank
        template can usually be found at /usr/share/zielen/config-template.

    **-a**, **--add-remote**
        Instead of moving local files to an empty remote directory, start with
        an existing remote directory and an empty local directory. Using this
        option, it is possible for two or more profiles to share a remote
        directory.

**sync** *name*\ \|\ *path*
    Bring the local and remote directories in sync and redistribute files based
    on their priorities. This command accepts the absolute *path* of a local
    initialized directory or the *name* of its profile. This command is run
    automatically at intervals while the daemon is running.

**reset** [*options*] *name*\ \|\ *path*
    Retrieve all files from the remote directory and de-initialize the local
    directory. This command accepts the absolute *path* of a local initialized
    directory or the *name* of its profile.

    **-k**, **--keep-remote**
        Copy files from the remote directory to the local one instead of moving
        them. This leaves a copy of the files in the remote directory, which is
        useful when that remote directory is shared with other profiles that
        may also want to retrieve the files.

    **-n**, **--no-retrieve**
        Don't retrieve files from the remote directory. This still
        de-initializes the local directory, but leaves it with whatever files
        are already in it. Remote files stay in the remote directory, and
        symlinks to remote files are removed from the local directory. This
        option supersedes **--keep-remote**.

**list**
    Print a table of all initialized directories and the names of their
    profiles.

**empty-trash**
    Permanently delete all files in the remote directory that are marked for
    deletion (see TRASH_). This command accepts the absolute path of a local
    initialized directory or the name of its profile.

SYNCING
=======
Whenever a profile is initialized, **zielen** will direct the user to start the
daemon for that profile. The daemon monitors file access in the local directory
and runs the **sync** command whenever a file is modified, with a cooldown
period that's configurable in the profile config file (see FILES_).

A sync conflict occurs when a file has been modified in both the local and
remote directories since the last sync. Such conflicts are handled by renaming
the file that was modified the least recently. The new file name contains the
word "conflict" and the date and time of the sync. This copy is treated as a
new, independent file that is synced like any other.

When calculating which files to store locally, **zielen** first considers whole
directories, and when a directory is selected, it includes all of its
subdirectories. Once no more whole directories can fit within the storage
limit, it fills the remaining space with the highest-priority individual files
that remain. This behavior can be overridden by setting **SyncExtraFiles** to
'no' in the profile config file.

During a sync, files that are new since the last sync have their priority
artifically inflated in order to keep them in the local directory longer. This
is to prevent files from being removed from the local directory as soon as
they're created, when they're likely still being used. This behavior can be
overridden by setting **InflatePriority** to 'no' in the profile config file.

**zielen** uses **rsync** for copying files between the local and remote
directories, and should preserve symbolic links, permissions, modification
times, ownership, hard links, ACLs, extended attributes and sparse files as
long as both filesystems support them. The program deliberately does not sync
user-created symlinks. The rationale behind this is that absolute links will be
broken when copied to another directory.

EXCLUDING
=========
Files and directories can be excluded from syncing using the exclude pattern
file (see FILES_). Each line in the file specifies a shell globbing pattern
that represents files to exclude. Excluded files stay in the local directory
and don't count toward the storage limit. If a file is not already in the local
directory, it is copied from the remote directory during the next sync. In
single-client configurations, the file is then removed from the remote
directory. In multi-client configurations, a file is removed from the remote
directory only when it has been excluded by each client that shares that remote
directory. Until then, a copy remains in the remote directory and all copies of
the file stay in sync.

Patterns have the following format:

* Lines starting with a pound sign '#' serve as comments.
* An asterisk '*' matches anything, but stops at slashes.
* A double asterisk '**' matches anything, including slashes.
* A question mark '?' matches any single character.
* A set of brackets '[]' matches any single character contained within the
  brackets.
* To match any of the above meta-characters literally, wrap them in brackets.
* Patterns starting with a slash match file paths relative to the root of the
  sync directory.
* Patterns not starting with a slash match the ends of file paths anywhere in
  the tree.

TRASH
=====
Before **zielen** deletes a file in the remote directory, it first searches for
the file in the user's local trash directory by comparing file sizes first and
then checksums. If it finds a copy of the file in the user's trash, it
permanently deletes the file in the remote directory. Otherwise, it only marks
the file for deletion. Files marked for deletion are kept in the remote
directory and renamed to include the word "deleted" and the time and date of
the sync. This behavior can be overridden by setting **DeleteAlways** to \'yes'
in the profile config file. The command **empty-trash** can be used to
permanently delete all files in the remote directory that are marked for
deletion. The list of directories that are searched for deleted files can be
altered in the profile config file.

FILES
=====
~/.config/zielen/
    This is the **zielen** config directory. The program will respect
    XDG_CONFIG_HOME and, if it is set, put the directory there instead.

    profiles/<name>/
        This directory exists for each profile that the user has created, where
        <name> is the name of the profile.

        mnt/
            This is the sshfs mountpoint for the remote directory. Symbolic
            links in the local directory point to files in this directory.

        config
            This is the configuration file for the profile. It contains
            required information that the user is prompted for when the
            **initialize** command is run as well as additional settings that can
            be configured.

        exclude
            This is the exclude pattern file for the profile. It contians a
            list of patterns representing files and directories to be excluded
            from syncing (see EXCLUDING_).
