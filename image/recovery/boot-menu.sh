#!/bin/sh
# Open the console explicitly for keyboard input and visible output.
exec </dev/console >/dev/console 2>&1

unmount_debian() {
    if ! umount "$mountpoint"; then
        /sbin/kexec --unload || true
        printf "Could not unmount the Debian partition. Power off to exit.\n"
        while :; do sleep 3600; done
    fi
}

boot_debian() {
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
        [ "$label" = ATVTESTROOT ] || continue
        count=$((count + 1))
        device=$candidate
        sys_device=$path
    done

    if [ "$count" -ne 1 ]; then
        printf 'Debian boot requires exactly one ATVTESTROOT partition (found %s).\n' "$count"
        return 1
    fi
    if [ ! -f "$sys_device/partition" ]; then
        printf "The Debian filesystem is not on a partition; refusing to boot it.\n"
        return 1
    fi
    resolved=$(readlink -f "$sys_device") || {
        printf 'Cannot identify the Debian disk.\n'
        return 1
    }
    case "$resolved" in
        */usb[0-9]/*) ;;
        *) printf 'The Debian partition is not on USB; refusing to boot it.\n'; return 1 ;;
    esac

    mountpoint=/mnt/atv-debian
    mkdir -p "$mountpoint" || return 1
    if ! mount -t ext3 -o ro "$device" "$mountpoint"; then
        printf 'Could not mount the Debian partition read-only.\n'
        return 1
    fi
    if [ ! -f "$mountpoint/vmlinuz" ] || [ ! -f "$mountpoint/initrd.img" ]; then
        printf 'Debian kernel or initramfs is missing.\n'
        unmount_debian
        return 1
    fi

    printf 'Loading Debian 12 from %s...\n' "$device"
    if ! /sbin/kexec --load "$mountpoint/vmlinuz" \
        --initrd="$mountpoint/initrd.img" \
        --command-line='root=LABEL=ATVTESTROOT rw net.ifnames=0 vesa video=vesafb earlyprintk=efi intel_idle.max_cstate=1 processor.max_cstate=2 nohpet'; then
        printf 'Could not load the Debian kernel.\n'
        unmount_debian
        return 1
    fi
    unmount_debian
    printf 'Starting Debian 12...\n'
    /sbin/kexec --exec
    /sbin/kexec --unload || true
    printf 'Debian boot failed; returning to the menu.\n'
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
        1) boot_debian ;;
        2)
            printf '\nSelected: Alpine Linux 3.24\n'
            printf 'Alpine booting is not implemented yet. Power off to exit.\n'
            while :; do sleep 3600; done
            ;;
        *) printf 'Invalid choice. Please enter 1 or 2.\n' ;;
    esac
done
