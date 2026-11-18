#!/bin/sh
# Fetch source archives into a mounted installed root or the running system.
set -eu
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
[ "$#" -eq 1 ] || { echo 'usage: fetch-sources.sh TARGET-ROOT' >&2; exit 2; }
root=${1%/}
[ -n "$root" ] || root=/
[ -d "$root/usr" ] || { echo 'missing target /usr' >&2; exit 1; }
destination=${root%/}/usr
[ ! -e "$destination/pkgsrc" ] || { echo 'pkgsrc already exists; refusing to replace it' >&2; exit 1; }
work=$(mktemp -d "$destination/.atv-pkgsrc.XXXXXXXX")
trap 'rm -rf "$work"' EXIT HUP INT TERM

echo 'Downloading current pkgsrc archive'
ftp -o "$work/pkgsrc.tar.gz.SHA512" https://cdn.netbsd.org/pub/pkgsrc/current/pkgsrc.tar.gz.SHA512
ftp -o "$work/pkgsrc.tar.gz" https://cdn.netbsd.org/pub/pkgsrc/current/pkgsrc.tar.gz
expected=$(awk '$1 == "SHA512" && $2 == "(pkgsrc.tar.gz)" && $3 == "=" {print $4}' "$work/pkgsrc.tar.gz.SHA512")
[ -n "$expected" ] && [ "$(sha512 -q "$work/pkgsrc.tar.gz")" = "$expected" ] || { echo 'pkgsrc checksum failed' >&2; exit 1; }
tar -xzpf "$work/pkgsrc.tar.gz" -C "$work"
[ -f "$work/pkgsrc/Makefile" ] || { echo 'invalid pkgsrc archive' >&2; exit 1; }

echo 'Downloading current pkgsrc-wip archive'
# GitHub's archive is an official read-only mirror of pkgsrc-wip. HTTPS
# authenticates the download; upstream publishes no detached checksum here.
ftp -o "$work/wip.tar.gz" https://github.com/NetBSD/pkgsrc-wip/archive/refs/heads/master.tar.gz
tar -xzpf "$work/wip.tar.gz" -C "$work"
[ -f "$work/pkgsrc-wip-master/Makefile" ] || { echo 'invalid pkgsrc-wip archive' >&2; exit 1; }
mv "$work/pkgsrc-wip-master" "$work/pkgsrc/wip"
mv "$work/pkgsrc" "$destination/pkgsrc"
echo 'Installed pkgsrc and pkgsrc-wip archives in /usr/pkgsrc.'
