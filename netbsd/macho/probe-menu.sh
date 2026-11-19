#!/bin/sh
# Run inside the original bootloader's Linux initramfs, before any kexec.
exec </dev/console >/dev/console 2>&1
show_entry() {
    printf '\n--- Apple TV entry and boot arguments ---\n'
    probe=
    # Kernel command-line arguments are whitespace-separated words.
    # shellcheck disable=SC2013
    for arg in $(cat /proc/cmdline); do
        case "$arg" in atvprobe=*) probe=${arg#atvprobe=} ;; esac
    done
    if [ -n "$probe" ]; then
        old_ifs=$IFS
        IFS=,
        set -f
        # Split the comma-delimited probe, without pathname expansion.
        # shellcheck disable=SC2086
        set -- $probe
        set +f
        IFS=$old_ifs
        if [ "$#" -eq 16 ] && [ "$1" = entry ]; then
            shift
            printf 'Entry confirmed; numbers are hexadecimal.\n'
            printf 'Revision/version: %s\n' "$1"; shift
            printf 'Video base/mode:  %s %s\n' "$1" "$2"; shift 2
            printf 'Pitch/width/height/depth: %s %s %s %s\n' "$1" "$2" "$3" "$4"; shift 4
            printf 'Memory map/size:  %s %s\n' "$1" "$2"; shift 2
            printf 'Descriptor size/version: %s %s\n' "$1" "$2"; shift 2
            printf 'EFI table: %s\n' "$1"; shift
            printf 'CR0/CR3/EFLAGS: %s %s %s\n' "$1" "$2" "$3"
        else
            printf 'Incomplete or unexpected entry probe: %s\n' "$probe"
        fi
    else
        printf 'Entry probe marker not present.\n'
    fi
    printf '\nKernel: '
    uname -a
    printf '\nFramebuffer devices:\n'
    cat /proc/fb 2>/dev/null || :
    for f in /sys/class/graphics/fb0/name /sys/class/graphics/fb0/virtual_size /sys/class/graphics/fb0/bits_per_pixel /sys/class/graphics/fb0/stride; do
        if [ -r "$f" ]; then printf '%s: ' "${f##*/}"; cat "$f"; fi
    done
}

show_platform() {
    printf '\n--- Platform and devices ---\n'
    printf 'Initial Linux command line:\n'
    cat /proc/cmdline
    grep -E '^(model name|cpu family|model|stepping|flags)[[:space:]]*:' /proc/cpuinfo 2>/dev/null | head -n 5
    grep -E '^(MemTotal|MemFree):' /proc/meminfo 2>/dev/null
    printf '\nBlock devices:\n'
    cat /proc/partitions 2>/dev/null || :
    printf '\nUSB devices:\n'
    for f in /sys/bus/usb/devices/*/idVendor; do
        [ -r "$f" ] || continue
        printf '%s ' "${f%/idVendor}"
        cat "$f"
        [ ! -r "${f%/idVendor}/idProduct" ] || cat "${f%/idVendor}/idProduct"
    done
}

show_log() {
    printf '\n--- Recent kernel messages ---\n'
    dmesg | tail -n 25
}

show_video_log() {
    printf '\n--- Video and firmware messages ---\n'
    dmesg | grep -iE 'efi|framebuffer|vesa|nvidia|vga|fbcon' | tail -n 20
}

show_entry
while :; do
    printf '\n1: Entry/framebuffer  2: Platform/devices  3: Recent log  4: Video log\n'
    printf 'Select a page (power off to exit): '
    if ! IFS= read -r choice; then
        printf '\nNo console input; power off to exit.\n'
        while :; do sleep 3600; done
    fi
    case "$choice" in
        1) show_entry ;;
        2) show_platform ;;
        3) show_log ;;
        4) show_video_log ;;
        *) printf '\nChoose 1, 2, 3 or 4.\n' ;;
    esac
done
