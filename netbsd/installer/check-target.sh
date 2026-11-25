#!/bin/sh
# Read-only inventory for the Apple TV disk identified in the hardware report.
set -eu
[ "$#" -eq 1 ] || { echo 'usage: check-target.sh wdN' >&2; exit 2; }
disk=$1
case "$disk" in wd[0-9]*) ;; *) echo 'expected an ATA disk name' >&2; exit 1 ;; esac
case "${disk#wd}" in *[!0-9]*|'') echo 'invalid disk name' >&2; exit 1 ;; esac
identify=$(atactl "$disk" identify) || { echo 'ATA identify failed' >&2; exit 1; }
printf '%s\n' "$identify" | grep -Eq '^Model: FUJITSU MHW2040AT, Rev:' || {
    echo 'unexpected disk model' >&2; exit 1;
}
printf '%s\n' "$identify" | grep -Eq '^Device type: ATA([,[:space:]]|$)' || {
    echo 'target is not an ATA device' >&2; exit 1;
}
printf '%s\n' "$identify" | grep -Eq '^Capacity .*78140160 sectors, 512 bytes/sector' || {
    echo 'unexpected disk geometry' >&2; exit 1;
}
printf 'Matched %s against observed model and geometry.\n' "$disk"
printf 'This inventory does not establish mount state, boot disk or exclusive access.\n'
