#!/usr/bin/env bash

scriptDir="$(dirname "${BASH_SOURCE[0]}")"

case "$1" in
	'') ;;
	--prefix)
		prefix="${2%/}" ; shift 2 ;;
	*)
		echo "help" ; exit 1 ;;
esac

# set default prefix
prefix="${prefix:-/usr/local}"

# check dependencies
[[ ! -x "$(which rsync 2> /dev/null)" ]] && \
	printf "Error: missing dependency \'rsync\'\n" && exit 1
[[ ! -x "$(which sshfs 2> /dev/null)" ]] && \
	printf "Error: missing dependency \'sshfs\'\n" && exit 1
[[ ! -x "$(which inotifywait 2> /dev/null)" ]] && \
	printf "Error: missing dependency \'inotify-tools\'\n" && exit 1
[[ ! -x "$(which systemctl 2> /dev/null)" ]] && \
	printf "Error: missing dependency \'systemd\'\n" && exit 1
[[ ! -x "$(which bc 2> /dev/null)" ]] && \
	printf "Error: missing dependency \'bc\'\n" && exit 1

# install scripts
[[ -d "$prefix/bin" ]] || mkdir "$prefix/bin"
cp "$scriptDir/retain-sync" "$prefix/bin/"
cp "$scriptDir/retain-syncd" "$prefix/bin/"

# install systemd unit files
[[ -d "$prefix/lib/systemd/user" ]] || mkdir -p "$prefix/lib/systemd/user"
cp "$scriptDir/init"/* "$prefix/lib/systemd/user/"
