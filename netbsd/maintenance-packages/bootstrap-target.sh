#!/bin/sh
# Install the basic binary package tools into a mounted NetBSD target.
set -eu
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
[ "$#" -eq 1 ] || { echo 'usage: bootstrap-target.sh TARGET-ROOT' >&2; exit 2; }
root=${1%/}
[ -n "$root" ] && [ "$root" != / ] && [ -x "$root/usr/sbin/pkg_add" ] && [ -d "$root/etc" ] || {
    echo 'expected a mounted NetBSD target root' >&2; exit 1;
}
[ -s /etc/resolv.conf ] || { echo 'installer has no DNS configuration' >&2; exit 1; }
resolver=$(mktemp "$root/etc/.atv-resolv.XXXXXXXX")
trap 'rm -f "$resolver"' EXIT HUP INT TERM
cat /etc/resolv.conf > "$resolver"
chmod 644 "$resolver"
mv -f "$resolver" "$root/etc/resolv.conf"

repo=https://cdn.netbsd.org/pub/pkgsrc/packages/NetBSD/i386/11.1/All
echo 'Initializing target HTTPS certificates.'
chroot "$root" /usr/sbin/certctl rehash
echo 'Installing pkgin, pkg_chk and git in the target system.'
PKG_PATH="$repo" chroot "$root" /usr/sbin/pkg_add pkgin pkg_chk git
chroot "$root" /usr/sbin/pkg_info -e 'pkgin-[0-9]*'
chroot "$root" /usr/sbin/pkg_info -e 'pkg_chk-[0-9]*'
chroot "$root" /usr/sbin/pkg_info -e 'git-base-[0-9]*'
mkdir -p "$root/usr/pkg/etc/pkgin"
printf '%s\n' "$repo" > "$root/usr/pkg/etc/pkgin/repositories.conf"
echo 'pkgin and pkg_chk installed and registered in the target.'

# Clone into a temporary directory so failed downloads can be retried.
if [ ! -e "$root/usr/pkgsrc/wip" ]; then
    [ -d "$root/usr/pkgsrc" ] || { echo 'missing pkgsrc tree' >&2; exit 1; }
    [ ! -e "$root/usr/pkgsrc/.wip-clone" ] || { echo 'remove incomplete .wip-clone before retrying' >&2; exit 1; }
    if ! chroot "$root" /usr/pkg/bin/git clone --depth 1 https://github.com/NetBSD/pkgsrc-wip.git /usr/pkgsrc/.wip-clone; then
        rm -rf "$root/usr/pkgsrc/.wip-clone"
        exit 1
    fi
    mv "$root/usr/pkgsrc/.wip-clone" "$root/usr/pkgsrc/wip"
fi
[ -d "$root/usr/pkgsrc/wip/.git" ] || { echo 'existing wip is not a Git checkout; preserve it and clone manually' >&2; exit 1; }
