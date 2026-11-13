#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
cd "$repo/filesystem"
. ./funcs.sh
cd "$tmp"
mkdir -p root bin
printf 'payload\n' > root/file
cat > bin/xz <<'STUB'
#!/bin/sh
exit 42
STUB
chmod +x bin/xz
if PATH="$tmp/bin:$PATH" create_fs_tarball root artifact; then
    echo 'Expected compression failure' >&2; exit 1
fi
[ -f root/file ] && [ ! -e artifact.tar.xz ]
cat > bin/xz <<'STUB'
#!/bin/sh
cat
STUB
cat > bin/tar <<'STUB'
#!/bin/sh
exit 43
STUB
chmod +x bin/tar bin/xz
if PATH="$tmp/bin:$PATH" create_fs_tarball root artifact; then
    echo 'Expected archive failure' >&2; exit 1
fi
[ -f root/file ] && [ ! -e artifact.tar.xz ]
rm bin/tar
PATH="$tmp/bin:$PATH" create_fs_tarball root artifact
[ ! -e root ]
tar -tf artifact.tar.xz | grep -Fx './file' >/dev/null
md5sum -c artifact.md5
printf '%s\n' 'Filesystem archive tests passed'
