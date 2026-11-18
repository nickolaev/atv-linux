#!/bin/sh
# Run inside the original bootloader's Linux initramfs, before any kexec.
exec </dev/console >/dev/console 2>&1

capture_file=/atv-probe.bin
capture_ok=0
capture_page=0
preflight_page=0
pci_page=0
devices_page=0
log_page=0
firmware_page=0
if [ -r "$capture_file" ]; then
    # hexdump is the BusyBox 1.18 implementation included in this initramfs.
    # shellcheck disable=SC2046
    set -- $(hexdump -v -n 64 -e '16/4 "%08x " "\n"' "$capture_file")
    if [ "$#" -eq 16 ] && [ "$1" = 50414345 ]; then
        capture_status=$2
        capture_map_pa=$4
        capture_map_size_hex=$5
        capture_stride_hex=$6
        capture_version=$7
        capture_table_pa=$8
        capture_map_copied_hex=${12}
        capture_table_size_hex=${13}
        capture_efi_mode=${14}
        capture_revision=${15}
        capture_esp=${16}
        capture_map_size=$((0x$capture_map_size_hex))
        capture_stride=$((0x$capture_stride_hex))
        capture_map_copied=$((0x$capture_map_copied_hex))
        capture_table_size=$((0x$capture_table_size_hex))
        if { [ "$capture_status" = 00000000 ] || [ "$capture_status" = 00000003 ]; } &&
           [ "$capture_stride" -ge 40 ] && [ "$capture_stride" -le 8000 ] &&
           [ "$capture_map_size" -le 8000 ] && [ "$capture_map_size" -gt 0 ] &&
           [ "$capture_map_size" -eq "$capture_map_copied" ] &&
           [ "$((capture_map_size % capture_stride))" -eq 0 ] &&
           [ "$capture_table_size" -le 128 ]; then
            capture_ok=1
            capture_count=$((capture_map_size / capture_stride))
        fi
    fi
fi

show_capture() {
    printf '\n--- Firmware snapshot ---\n'
    if [ "$capture_ok" -ne 1 ]; then
        printf 'No complete, valid memory-map capture.\n'
        return
    fi
    printf 'Map address=%s bytes=%s stride=%s version=%s descriptors=%s\n' \
        "$capture_map_pa" "$capture_map_size" "$capture_stride" "$capture_version" "$capture_count"
    printf 'EFI table address=%s copied bytes=%s status=%s\n' \
        "$capture_table_pa" "$capture_table_size" "$capture_status"
    printf 'Boot revision/version=%s EFI mode=%s\n' "$capture_revision" "$capture_efi_mode"
    if [ "$capture_esp" != 00000000 ]; then
        printf 'Hook ESP=%s (location only; stack bounds unknown)\n' "$capture_esp"
    fi
    if [ "$capture_status" != 00000000 ]; then
        printf 'EFI system table was not fully captured; memory map may still be available.\n'
    fi
}

show_map_page() {
    show_capture
    [ "$capture_ok" -eq 1 ] || return
    first=$((capture_page * 8))
    if [ "$first" -ge "$capture_count" ]; then capture_page=0; first=0; fi
    end=$((first + 8))
    [ "$end" -le "$capture_count" ] || end=$capture_count
    printf 'Map page %s: descriptor %s through %s (hex words)\n' "$capture_page" "$first" "$((end - 1))"
    printf 'Each line: type, padding, physical low/high, virtual low/high, pages low/high, attributes low/high.\n'
    i=$first
    while [ "$i" -lt "$end" ]; do
        printf '%02d: ' "$i"
        hexdump -v -s "$((192 + i * capture_stride))" -n 40 -e '10/4 "%08x " "\n"' "$capture_file"
        i=$((i + 1))
    done
    capture_page=$((capture_page + 1))
}

show_table() {
    show_capture
    [ "$capture_ok" -eq 1 ] && [ "$capture_table_size" -gt 0 ] || return
    printf 'EFI system table bytes (hex):\n'
    hexdump -v -s 64 -n "$capture_table_size" -C "$capture_file"
}

export_capture() {
    [ "$capture_ok" -eq 1 ] || { printf '\nNo complete map to export.\n'; return; }
    mkdir -p /tmp/atv-capture || return
    cp "$capture_file" /tmp/atv-capture/atv-probe.bin || return
    if [ -x /atv-preflight ]; then
        /atv-preflight > /tmp/atv-capture/preflight.txt 2>&1 || :
    fi
    if [ -f /tmp/atv-firmware-observation.txt ]; then
        cp /tmp/atv-firmware-observation.txt /tmp/atv-capture/firmware-observation.txt || return
    fi
    printf '\nConfiguring wired Ethernet with DHCP; this can take a few seconds.\n'
    ifconfig eth0 up || return
    if ! udhcpc -n -q -t 3 -T 3 -i eth0; then
        printf 'DHCP failed. Use the paged map display instead.\n'
        return
    fi
    if ! httpd -p 8080 -h /tmp/atv-capture; then
        printf 'Could not start capture server; it may already be running.\n'
    fi
    printf 'HTTP capture server: http://<eth0 IPv4 address>:8080/atv-probe.bin\n'
    [ ! -f /tmp/atv-capture/preflight.txt ] || printf 'Preflight: http://<eth0 IPv4 address>:8080/preflight.txt\n'
    [ ! -f /tmp/atv-capture/firmware-observation.txt ] || printf 'Firmware observation: http://<eth0 IPv4 address>:8080/firmware-observation.txt\n'
    ifconfig eth0
}
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
    elif [ "$capture_ok" -eq 1 ]; then
        printf 'Entry confirmed by the firmware snapshot.\n'
    else
        printf 'Entry marker not present and no complete firmware snapshot.\n'
    fi
    printf '\nKernel: '
    uname -a
    printf '\nFramebuffer devices:\n'
    cat /proc/fb 2>/dev/null || :
    for f in /sys/class/graphics/fb0/name /sys/class/graphics/fb0/virtual_size /sys/class/graphics/fb0/bits_per_pixel /sys/class/graphics/fb0/stride; do
        if [ -r "$f" ]; then printf '%s: ' "${f##*/}"; cat "$f"; fi
    done
    show_capture
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

# All reports are stored in the initramfs and never written to a disk. Keeping
# each report stable lets repeated selections page through it for photographs.
show_page() {
    file=$1
    page=$2
    title=$3
    if [ ! -r "$file" ]; then printf '\n%s unavailable.\n' "$title"; next_page=0; return; fi
    lines=$(wc -l < "$file")
    if [ "$lines" -eq 0 ]; then printf '\n%s is empty.\n' "$title"; next_page=0; return; fi
    pages=$(((lines + 17) / 18))
    if [ "$page" -ge "$pages" ]; then page=0; fi
    first=$((page * 18 + 1))
    last=$((first + 17))
    printf '\n--- %s (page %s/%s; select again for next) ---\n' "$title" "$((page + 1))" "$pages"
    sed -n "${first},${last}p" "$file"
    next_page=$(((page + 1) % pages))
}

show_preflight_page() {
    if [ ! -x /atv-preflight ]; then printf '\nPreflight is not included in this image.\n'; return; fi
    if [ ! -f /tmp/atv-preflight.txt ]; then
        /atv-preflight > /tmp/atv-preflight.txt 2>&1 || :
    fi
    show_page /tmp/atv-preflight.txt "$preflight_page" 'NetBSD snapshot preflight'
    preflight_page=$next_page
}

show_firmware_page() {
    if [ ! -x /atv-observe-firmware ]; then printf '\nFirmware observer is not included in this image.\n'; return; fi
    if [ ! -f /tmp/atv-firmware-observation.txt ]; then
        /atv-observe-firmware > /tmp/atv-firmware-observation.txt 2>&1 || :
    fi
    show_page /tmp/atv-firmware-observation.txt "$firmware_page" 'Linux-time firmware observation'
    firmware_page=$next_page
}

show_pci_page() {
    if [ ! -f /tmp/atv-pci.txt ]; then
        {
            printf 'PCI address vendor device class driver\n'
            found=0
            for d in /sys/bus/pci/devices/*; do
                [ -r "$d/vendor" ] && [ -r "$d/device" ] || continue
                found=1
                vendor=$(cat "$d/vendor"); device=$(cat "$d/device")
                class=$(cat "$d/class" 2>/dev/null); driver=$(readlink "$d/driver" 2>/dev/null)
                printf '%s %s %s %s %s\n' "${d##*/}" "$vendor" "$device" "$class" "${driver##*/}"
            done
            [ "$found" -eq 1 ] || printf 'No PCI devices found in sysfs.\n'
        } > /tmp/atv-pci.txt
    fi
    show_page /tmp/atv-pci.txt "$pci_page" 'PCI devices'
    pci_page=$next_page
}

show_devices_page() {
    if [ ! -f /tmp/atv-devices.txt ]; then
        {
            printf 'Block devices (/proc/partitions blocks are KiB):\n'
            cat /proc/partitions 2>/dev/null || :
            for d in /sys/block/*; do
                [ -d "$d" ] || continue
                printf '\n%s: ' "${d##*/}"
                [ ! -r "$d/device/model" ] || cat "$d/device/model"
                printf '  size is in 512-byte sectors\n'
                for field in size removable ro; do
                    if [ -r "$d/$field" ]; then printf '  %s=' "$field"; cat "$d/$field"; fi
                done
            done
            printf '\nNetwork interfaces:\n'
            for d in /sys/class/net/*; do
                [ -d "$d" ] || continue
                printf '%s' "${d##*/}"
                for field in address operstate carrier; do
                    if [ -r "$d/$field" ]; then printf ' %s=' "$field"; value=$(cat "$d/$field" 2>/dev/null) && printf '%s' "$value" || printf '?'; fi
                done
                printf '\n'
            done
            printf '\nUSB devices (bus path vendor product):\n'
            for d in /sys/bus/usb/devices/*; do
                [ -r "$d/idVendor" ] && [ -r "$d/idProduct" ] || continue
                vendor=$(cat "$d/idVendor"); product=$(cat "$d/idProduct")
                printf '%s %s %s' "${d##*/}" "$vendor" "$product"
                if [ -r "$d/product" ]; then printf ' '; cat "$d/product"; else printf '\n'; fi
            done
        } > /tmp/atv-devices.txt
    fi
    show_page /tmp/atv-devices.txt "$devices_page" 'Storage and network'
    devices_page=$next_page
}

show_full_log_page() {
    if [ ! -f /tmp/atv-dmesg.txt ]; then dmesg > /tmp/atv-dmesg.txt 2>&1 || :; fi
    show_page /tmp/atv-dmesg.txt "$log_page" 'Full Linux kernel log'
    log_page=$next_page
}

show_registers() {
    printf '\n--- Probe hook registers (hexadecimal) ---\n'
    if [ "$capture_ok" -ne 1 ] || [ "$capture_map_copied" -gt 7936 ]; then
        printf 'Extended register trailer unavailable.\n'; return
    fi
    set -- $(hexdump -v -s 8128 -n 52 -e '13/4 "%08x " "\n"' "$capture_file")
    if [ "$#" -ne 13 ] || [ "$1" != 47455258 ] || [ "$2" != 00000001 ]; then
        printf 'Extended register trailer unavailable.\n'; return
    fi
    shift 2
    printf 'EAX=%s EBX=%s ECX=%s EDX=%s\n' "$1" "$2" "$3" "$4"; shift 4
    printf 'ESI=%s EDI=%s EBP=%s ESP=%s\n' "$1" "$2" "$3" "$capture_esp"; shift 3
    printf 'Selector pairs DS:CS=%s ES:SS=%s GS:FS=%s\n' "$1" "$2" "$3"; shift 3
    printf 'CR4=%s\n' "$1"
    printf 'GDTR and IDTR: 6 bytes each, little endian (limit, base):\n'
    hexdump -v -s 8180 -n 12 -C "$capture_file"
}

show_entry
while :; do
    printf '\n1: Entry  2: Devices  3: Recent log  4: Video log\n'
    printf '5: Next map page  6: EFI table  7: Export over Ethernet  8: Next preflight page\n'
    printf '9: Hook registers  10: PCI  11: Storage/network  12: Full Linux log\n'
    printf '13: Linux-time firmware observation (select again for next page)\n'
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
        5) show_map_page ;;
        6) show_table ;;
        7) export_capture ;;
        8) show_preflight_page ;;
        9) show_registers ;;
        10) show_pci_page ;;
        11) show_devices_page ;;
        12) show_full_log_page ;;
        13) show_firmware_page ;;
        *) printf '\nChoose a listed page.\n' ;;
    esac
done
