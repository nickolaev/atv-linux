#!/bin/sh
# Explicitly invoked installer for the observed ATV1 ATA disk.
set -eu
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
[ "$#" -eq 3 ] || [ "$#" -eq 4 ] || { echo 'usage: install.sh wdN ASSET-DIRECTORY STATE-DIRECTORY [ACCOUNT-FILE]' >&2; exit 2; }
disk=$1
assets=$2
state=$3
account_file=${4-}
[ -z "$account_file" ] || [ -s "$account_file" ] || { echo 'missing administrator account file' >&2; exit 1; }
if [ -n "$account_file" ]; then
    account_name=$(sed -n '1p' "$account_file")
    account_hash=$(sed -n '2p' "$account_file")
    root_hash=$(sed -n '3p' "$account_file")
    case "$account_name" in ''|root|*[!a-z0-9_-]*|[!a-z]*) echo 'invalid administrator name' >&2; exit 1 ;; esac
    [ "${#account_name}" -le 16 ] && [ -n "$account_hash" ] && [ -n "$root_hash" ] || { echo 'invalid administrator credentials' >&2; exit 1; }
    unset account_name account_hash root_hash
fi
bindir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
[ -r "$bindir/ready.sh" ] && [ -r "$bindir/provision.sh" ] && [ -x "$bindir/fetch-sources.sh" ] && [ -x "$bindir/bootstrap-target.sh" ] || { echo 'missing installed-system reporter or package provisioning scripts' >&2; exit 1; }
"$bindir/check-target.sh" "$disk"
[ -d "$assets/sets" ] && [ -d "$assets/boot" ] && [ -d "$state" ] || { echo 'missing assets or state directory' >&2; exit 1; }
[ ! -e "$state/install-started" ] || { echo 'installation already started; refusing to repeat' >&2; exit 1; }
for set in base etc kern-GENERIC modules comp man text; do
    f=$assets/sets/$set.tgz
    echo "Verifying $set.tgz"
    expected=$(awk -v file="$set.tgz" '$1 == "SHA512" && $2 == "(" file ")" && $3 == "=" {print $4}' "$assets/sets/SHA512")
    [ -f "$f" ] && [ -n "$expected" ] && [ "$(sha512 -q "$f")" = "$expected" ] || { echo "invalid set $set" >&2; exit 1; }
done
[ "$(wc -c < "$assets/boot/recovery.fat" | tr -d ' ')" = 41943040 ] || { echo 'invalid recovery payload' >&2; exit 1; }
[ "$(wc -c < "$assets/boot/efi.fat" | tr -d ' ')" = 90177536 ] || { echo 'invalid EFI payload' >&2; exit 1; }
for name in recovery.fat efi.fat; do
    echo "Verifying $name"
    expected=$(awk -v file="$name" '$2 == file {print $1}' "$assets/boot/SHA512")
    [ -n "$expected" ] && [ "$(sha512 -q "$assets/boot/$name")" = "$expected" ] || { echo "invalid boot asset $name" >&2; exit 1; }
done
wedges=$(dkctl "$disk" listwedges) || { echo 'cannot list target wedges' >&2; exit 1; }
mounts=$(mount) || exit 1
# Wedge and direct mounts must be absent. Fail if the boot source is the target.
printf '%s\n' "$mounts" | awk -v disk="$disk" '$1 ~ ("^/dev/(r)?" disk "([a-p])?$") {found=1} END {exit !found}' && { echo 'target disk is mounted' >&2; exit 1; }
rootdev=$(printf '%s\n' "$mounts" | awk '$2 == "on" && $3 == "/" && $4 == "type" {print $1}')
case "$rootdev" in /dev/dk[0-9]*) ;; *) echo 'cannot establish USB root wedge' >&2; exit 1 ;; esac
statefs=$(df -P "$state" | awk 'NR == 2 {print $1}')
[ "$statefs" = "$rootdev" ] || { echo 'state must be on the running root filesystem' >&2; exit 1; }
for wedge in $(printf '%s\n' "$wedges" | awk '/^[[:space:]]*dk[0-9]+:/ {gsub(":", "", $1); print $1}'); do
    printf '%s\n' "$mounts" | awk -v dev="/dev/$wedge" '$1 == dev {found=1} END {exit !found}' && { echo "target wedge $wedge is mounted" >&2; exit 1; }
done
for wedge in $(printf '%s\n' "$wedges" | awk '/^[[:space:]]*dk[0-9]+:/ {gsub(":", "", $1); print $1}'); do
    [ "/dev/$wedge" != "$rootdev" ] || { echo 'target contains the running root' >&2; exit 1; }
done
# Refuse all active swap rather than relying on ambiguous device aliases.
swapctl -lk 2>&1 | grep -q '^no swap devices configured' || { echo 'active or unknown swap state' >&2; exit 1; }
[ "$rootdev" != "/dev/$disk" ] || exit 1
# The persistent marker is written before the first destructive operation.
printf 'target=%s\nstate=started\n' "$disk" > "$state/install-started"
sync
for wedge in $(printf '%s\n' "$wedges" | awk '/^[[:space:]]*dk[0-9]+:/ {gsub(":", "", $1); print $1}'); do
    dkctl "$disk" delwedge "$wedge"
done
if gpt header "$disk" >/dev/null 2>&1; then gpt destroy "$disk"; fi
gpt create -f "$disk"
gpt add -i 1 -b 83968 -s 176128 -t efi -l atv-esp "$disk"
gpt add -i 2 -b 2048 -s 81920 -t 5265636f-7665-11aa-aa11-00306543ecac -l atv-recovery "$disk"
gpt add -i 3 -b 260096 -s 2097152 -t swap -l atv-swap "$disk"
gpt add -i 4 -b 2357248 -t ffs -l atv-root "$disk"
dd if="$assets/boot/recovery.fat" of="/dev/r${disk}d" bs=512 seek=2048 conv=notrunc
dd if="$assets/boot/efi.fat" of="/dev/r${disk}d" bs=512 seek=83968 conv=notrunc
sync
dkctl "$disk" makewedges
wedges=$(dkctl "$disk" listwedges)
rootdk=$(printf '%s\n' "$wedges" | awk '$2 == "atv-root," {gsub(":", "", $1); print $1}')
espdk=$(printf '%s\n' "$wedges" | awk '$2 == "atv-esp," {gsub(":", "", $1); print $1}')
swapdk=$(printf '%s\n' "$wedges" | awk '$2 == "atv-swap," && $3 == 2097152 && $NF == "swap" {gsub(":", "", $1); print $1}')
case "$rootdk:$espdk:$swapdk" in dk[0-9]*:dk[0-9]*:dk[0-9]*) ;; *) echo 'cannot resolve target wedges' >&2; exit 1 ;; esac
# Refuse ambiguous labels or unexpected swap geometry before activating swap.
[ "$(printf '%s\n' "$wedges" | awk '$2 == "atv-swap," {n++} END {print n+0}')" -eq 1 ] || { echo 'target swap wedge is ambiguous' >&2; exit 1; }
case "$swapdk" in *[!0-9dk]*|'') echo 'invalid swap wedge' >&2; exit 1 ;; esac
(cd /dev && sh MAKEDEV "$rootdk" "$espdk" "$swapdk")
echo "Activating 1 GiB installation swap on /dev/$swapdk."
swapctl -a "/dev/$swapdk" || { echo 'could not activate installation swap' >&2; exit 1; }
# Keep swap active until the installer system shuts down. Removing it here
# would have to page data back into the Apple TV's limited physical memory.
swapctl -lk
newfs -O 1 "/dev/r$rootdk"
mkdir -p /mnt/atv-root /mnt/atv-esp
mount -t ffs "/dev/$rootdk" /mnt/atv-root
"$bindir/populate-root.sh" /mnt/atv-root "$assets/sets" "$assets/authorized_keys" "$account_file"
mount -t msdos "/dev/$espdk" /mnt/atv-esp
cp /mnt/atv-root/netbsd /mnt/atv-esp/netbsd
cat > /mnt/atv-esp/EFI/NetBSD/boot.cfg <<'CONFIG'
timeout=5
default=1
menu=NetBSD 11.1:userconf disable nouveau;root NAME=atv-root;boot esp:/netbsd -v
CONFIG
sources_ok=yes
echo 'Preparing HTTPS certificates for source downloads.'
if certctl rehash && "$bindir/fetch-sources.sh" /mnt/atv-root; then
    echo 'Source archives installed.'
else
    sources_ok=no
    echo 'Source download failed; after boot, run /usr/local/sbin/atv-provision-packages to retry.' >&2
fi
packages_ok=yes
if "$bindir/bootstrap-target.sh" /mnt/atv-root; then
    echo 'Basic package tools installed.'
else
    packages_ok=no
    echo 'Package bootstrap failed; after boot, run /usr/local/sbin/atv-provision-packages to retry.' >&2
fi
sync
umount /mnt/atv-esp
umount /mnt/atv-root
sync
[ "$sources_ok" = yes ] && [ "$packages_ok" = yes ] || { echo 'NetBSD installed, but package or source setup is incomplete.' >&2; exit 1; }
printf 'target=%s\nstate=installed\n' "$disk" > "$state/install-complete"
sync
echo 'Installation files written; cold boot is not yet verified.'
