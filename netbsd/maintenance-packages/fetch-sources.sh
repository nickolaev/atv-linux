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

mv "$work/pkgsrc" "$destination/pkgsrc"
echo 'Installed pkgsrc archive in /usr/pkgsrc.'
