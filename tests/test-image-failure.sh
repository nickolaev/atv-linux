#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/image" "$tmp/filesystem" "$tmp/scripts" "$tmp/bin"
cp "$repo/image/build.sh" "$tmp/image/build.sh"
cat > "$tmp/scripts/common.sh" <<'STUB'
update_sources() { return 0; }
verify_action() { local status=$?; [ "$status" -eq 0 ] || exit "$status"; }
install_package() { return 0; }
STUB
cat > "$tmp/bin/make" <<'STUB'
#!/bin/sh
[ "${1:-}" = clean ] && exit 0
exit 42
STUB
cat > "$tmp/bin/dd" <<'STUB'
#!/bin/sh
touch "$TEST_MARKER"
exit 0
STUB
chmod +x "$tmp/bin/make" "$tmp/bin/dd"
cd "$tmp/image"
if PATH="$tmp/bin:$PATH" TEST_MARKER="$tmp/dd-ran" bash ./build.sh > "$tmp/log" 2>&1; then
    echo 'Expected filesystem build failure' >&2; exit 1
fi
[ ! -e "$tmp/dd-ran" ] || { echo 'Image creation ran after filesystem failure' >&2; exit 1; }
[ ! -e atv-linux.img ]
printf '%s\n' 'Image build stops after filesystem failure'
