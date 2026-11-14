#!/bin/sh
# Open the console explicitly for keyboard input and visible output.
exec </dev/console >/dev/console 2>&1

unmount_system() {
    if ! umount "$mountpoint"; then
        /sbin/kexec --unload || true
        printf 'Could not unmount the selected partition. Power off to exit.\n'
        while :; do sleep 3600; done
    fi
}

boot_system() {
    distribution=$1
    target_label=$2
    kernel=$3
    initrd=$4
    kernel_args=$5
    count=0
    device=
    sys_device=
    # Check SCSI-style disks and partitions, including the internal disk, so a
    # duplicate label cannot make the later root=LABEL lookup ambiguous.
    for path in /sys/class/block/sd*; do
        name=${path##*/}
        case "$name" in sd[a-z]|sd[a-z][0-9]*) ;; *) continue ;; esac
        candidate=/dev/$name
        [ -b "$candidate" ] || continue
        label=$(/sbin/blkid -c /dev/null -s LABEL -o value "$candidate" 2>/dev/null) || continue
        [ "$label" = "$target_label" ] || continue
        count=$((count + 1))
        device=$candidate
        sys_device=$path
    done
    if [ "$count" -ne 1 ]; then
        printf '%s boot requires exactly one %s partition (found %s).\n' "$distribution" "$target_label" "$count"
        return 1
    fi
    if [ ! -f "$sys_device/partition" ]; then
        printf 'The selected filesystem is not on a partition; refusing to boot it.\n'
        return 1
    fi
    resolved=$(readlink -f "$sys_device") || { printf 'Cannot identify the selected disk.\n'; return 1; }
    case "$resolved" in
        */usb[0-9]/*) ;;
        *) printf 'The selected partition is not on USB; refusing to boot it.\n'; return 1 ;;
    esac

    mountpoint=/mnt/atv-system
    mkdir -p "$mountpoint" || return 1
    if ! mount -t ext3 -o ro "$device" "$mountpoint"; then
        printf 'Could not mount the selected partition read-only.\n'
        return 1
    fi
    if [ ! -f "$mountpoint/$kernel" ] || [ ! -f "$mountpoint/$initrd" ]; then
        printf '%s kernel or initramfs is missing.\n' "$distribution"
        unmount_system
        return 1
    fi
    printf 'Loading %s from %s...\n' "$distribution" "$device"
    if ! /sbin/kexec --load "$mountpoint/$kernel" \
        --initrd="$mountpoint/$initrd" --command-line="$kernel_args"; then
        printf 'Could not load the %s kernel.\n' "$distribution"
        unmount_system
        return 1
    fi
    unmount_system
    printf 'Starting %s...\n' "$distribution"
    /sbin/kexec --exec
    /sbin/kexec --unload || true
    printf '%s boot failed; returning to the menu.\n' "$distribution"
    return 1
}

while :; do
    printf '\nChoose a distribution:\n'
    printf '  1) Debian 12\n'
    printf '  2) Alpine Linux 3.24\n'
    printf 'Choose 1 or 2: '
    if ! IFS= read -r choice; then
        printf '\nUnable to read from the console. Power off to exit.\n'
        while :; do sleep 3600; done
    fi
    case "$choice" in
        1) boot_system 'Debian 12' ATVTESTROOT vmlinuz initrd.img \
            'root=LABEL=ATVTESTROOT rw net.ifnames=0 vesa video=vesafb earlyprintk=efi intel_idle.max_cstate=1 processor.max_cstate=2 nohpet' ;;
        2) boot_system 'Alpine Linux 3.24' ATVALPINE boot/vmlinuz-lts boot/initramfs-lts \
            'root=LABEL=ATVALPINE rootfstype=ext4 rootflags=noload overlaytmpfs overlaytmpfsflags=size=64m modules=loop,squashfs,sd-mod,usb-storage,ext4,overlay modloop=boot/modloop-lts net.ifnames=0' ;;
        *) printf 'Invalid choice. Please enter 1 or 2.\n' ;;
    esac
done
