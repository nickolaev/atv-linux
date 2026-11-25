#!/bin/sh
# Provision the installed NetBSD system once networking is available.
set -eu
PATH=/usr/pkg/sbin:/usr/pkg/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
state=/var/db/atv-packages
log=/var/log/atv-packages.log
repo=https://cdn.netbsd.org/pub/pkgsrc/packages/NetBSD/i386/11.1/All
sets=https://cdn.netbsd.org/pub/NetBSD/NetBSD-11.1/i386/binary/sets
sources=https://cdn.netbsd.org/pub/pkgsrc/current
mkdir -p "$state"
# A manual retry resumes after failure; a successful run is left alone.
[ ! -f "$state/complete" ] || exit 0
lock=/var/run/atv-packages.lock
mkdir "$lock" 2>/dev/null || exit 0
status=failed
stage=initializing
report() {
    result=$?
    trap - EXIT HUP INT TERM
    {
        echo ATV-NETBSD-PACKAGES-1
        echo "result=$status"
        echo "stage=$stage"
        echo "exit_status=$result"
        tail -n 80 "$log" 2>/dev/null || :
        echo report=complete
    } > "$state/report.txt"
    rmdir "$lock" 2>/dev/null || :
    exit "$result"
}
trap report EXIT
trap 'exit 1' HUP INT TERM
exec >> "$log" 2>&1
printf '\nStarting package provisioning: '
date -u

# Fresh NetBSD installations ship CA certificates but need the hashed trust
# directory populated before HTTPS package downloads can be verified.
stage=certificates
certctl rehash

# pkg_add resolves the matching pkgin archive and its dependencies using the
# official release repository; its own package database tracks installed files.
stage=packages
export PKG_PATH="$repo"
if ! pkg_info -e 'pkgin-[0-9]*' >/dev/null 2>&1; then
    pkg_add pkgin
fi
mkdir -p /usr/pkg/etc/pkgin
printf '%s\n' "$repo" > /usr/pkg/etc/pkgin/repositories.conf
pkgin -y update
failed_packages=
for package in pkg_chk tmux micro vim mc git; do
    if ! pkgin -y install "$package"; then
        failed_packages="$failed_packages $package"
        echo "Package installation failed: $package"
    fi
done

# Install the matching compiler and headers if this installation lacks them.
stage=compiler
if [ ! -x /usr/bin/cc ]; then
    cd "$state"
    ftp -o SHA512 "$sets/SHA512"
    ftp -o comp.tgz "$sets/comp.tgz"
    expected=$(awk '$1 == "SHA512" && $2 == "(comp.tgz)" && $3 == "=" { print $4 }' SHA512)
    [ -n "$expected" ] && [ "$(sha512 -q comp.tgz)" = "$expected" ]
    tar -xzpf comp.tgz -C /
    rm -f comp.tgz SHA512
fi

# Avoid replacing a locally modified source tree on a later retry. The fresh
# system receives a checked snapshot; normal pkgsrc update tools apply later.
stage=pkgsrc
if [ ! -d /usr/pkgsrc ]; then
    cd "$state"
    ftp -o pkgsrc.tar.gz.SHA512 "$sources/pkgsrc.tar.gz.SHA512"
    ftp -o pkgsrc.tar.gz "$sources/pkgsrc.tar.gz"
    expected=$(awk '$1 == "SHA512" && $2 == "(pkgsrc.tar.gz)" && $3 == "=" { print $4 }' pkgsrc.tar.gz.SHA512)
    [ -n "$expected" ] && [ "$(sha512 -q pkgsrc.tar.gz)" = "$expected" ]
    rm -rf "$state/source"
    mkdir -p "$state/source"
    tar -xzpf pkgsrc.tar.gz -C "$state/source"
    [ -f "$state/source/pkgsrc/Makefile" ]
    mv "$state/source/pkgsrc" /usr/pkgsrc
    rmdir "$state/source"
    rm -f pkgsrc.tar.gz pkgsrc.tar.gz.SHA512
fi
stage=wip
if [ ! -e /usr/pkgsrc/wip ]; then
    command -v git >/dev/null || { echo 'git is required to clone pkgsrc-wip' >&2; exit 1; }
    [ ! -e /usr/pkgsrc/.wip-clone ] || { echo 'remove incomplete .wip-clone before retrying' >&2; exit 1; }
    if ! git clone --depth 1 https://github.com/NetBSD/pkgsrc-wip.git /usr/pkgsrc/.wip-clone; then
        rm -rf /usr/pkgsrc/.wip-clone
        exit 1
    fi
    mv /usr/pkgsrc/.wip-clone /usr/pkgsrc/wip
fi
[ -d /usr/pkgsrc/wip/.git ] || { echo 'existing wip is not a Git checkout; preserve it and clone manually' >&2; exit 1; }
[ -z "$failed_packages" ] || { echo "Missing packages:$failed_packages"; exit 1; }
stage=complete
status=complete
printf 'installed=1\n' > "$state/complete"
sync
printf 'Package provisioning complete: '
date -u
