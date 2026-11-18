#!/bin/sh
# Returning diagnostic only: the snapshot is copied before Linux starts.
exec </dev/console >/dev/console 2>&1

show_status() {
    printf '\n--- NetBSD returning loader diagnostic ---\n'
    if [ ! -r /atv-loader-diag.bin ]; then
        printf 'Status file missing. No loader result is available.\n'
        return
    fi
    set -- $(hexdump -v -n 48 -e '12/4 "%08x " "\n"' /atv-loader-diag.bin)
    if [ "$#" -eq 12 ] && [ "$1" = 31574f4c ]; then
        printf 'Low hook reached the high call, but no completed high status.\n'
        return
    fi
    if [ "$#" -ne 12 ] || [ "$1" != 47414944 ] || [ "$2" != 00000001 ]; then
        printf 'No completed loader status. The high payload may not have run,\n'
        printf 'or the hook may have rejected the entry state.\n'
        return
    fi
    stage=$3 error=$4
    printf 'Stage=%s error=%s (hexadecimal)\n' "$stage" "$error"
    case "$error" in
        00000000) printf 'No reported validation error.\n' ;;
        00000001) printf 'Boot arguments rejected.\n' ;;
        00000002) printf 'EFI map shape rejected.\n' ;;
        00000003) printf 'Initial reservation rejected.\n' ;;
        00000004) printf 'EFI system/configuration read rejected.\n' ;;
        00000005) printf 'Selected EFI, ACPI, or SMBIOS validation rejected.\n' ;;
        00000006) printf 'Firmware reservation limit reached.\n' ;;
        00000007) printf 'Kernel or scratch memory planning rejected.\n' ;;
        00000008) printf 'Native boot-information preparation rejected.\n' ;;
        00000009) printf 'Original Linux loader bounds rejected.\n' ;;
        0000000a) printf 'Live return-state memory could not be protected.\n' ;;
        0000000b) printf 'Kernel copy verification failed.\n' ;;
        0000000c) printf 'BIOS data area protection rejected.\n' ;;
        0000000d) printf 'Early NetBSD entry checkpoint rejected or failed.\n' ;;
        0000000e) printf 'NetBSD boot-information verification failed.\n' ;;
        *) printf 'Unknown error code.\n' ;;
    esac
    printf 'Apple arguments=%s map=%s bytes=%s system=%s\n' "$5" "$6" "$7" "$8"
    if [ "$stage" = 00000006 ] && [ "$error" = 0000000a ]; then
        site=$9
        detail=${12}
        reason=$(( (0x$detail >> 24) & 255 ))
        desc=$(( (0x$detail >> 8) & 65535 ))
        dtype=$(( 0x$detail & 255 ))
        printf 'Protection check=%s address=%s length=%s\n' "$site" "${10}" "${11}"
        case "$site" in
            00000001) printf 'Object: hook stack guard\n' ;;
            00000002) printf 'Object: GDT\n' ;;
            00000003) printf 'Object: IDT\n' ;;
            00000004) printf 'Object: Apple device tree\n' ;;
            00000005) printf 'Object: Apple kernel range\n' ;;
            00000006) printf 'Object: EFI runtime pages\n' ;;
            000007??) printf 'Object: EFI configuration entry (low byte is index)\n' ;;
            000008??) printf 'Object: EFI system-table pointer (low byte is offset)\n' ;;
            00000009) printf 'Object: unknown-pointer suffix reservation\n' ;;
            0000000a) printf 'Object: framebuffer\n' ;;
            *) printf 'Object: unknown\n' ;;
        esac
        case "$reason" in
            1) why='invalid range or outside supported memory' ;;
            2) why='malformed EFI descriptor' ;;
            3) why='unsupported intersecting EFI type' ;;
            4) why='descriptor exceeds 4 GiB' ;;
            5) why='no single descriptor covers the range' ;;
            6) why='reservation capacity exceeded' ;;
            7) why='inconsistent or malformed fields' ;;
            *) why='unknown reason' ;;
        esac
        printf 'Reason=%s (%s), descriptor=%s type=%s\n' "$reason" "$why" "$desc" "$dtype"
        return
    fi
    if { [ "$stage" = 0000000a ] || [ "$stage" = 0000000b ]; } && [ "$error" = 00000000 ]; then
        printf 'Copied bytes=%s zeroed bytes=%s (hexadecimal)\n' "$9" "${10}"
    else
        printf 'Selected kind=%s pointer=%s\n' "$9" "${10}"
    fi
    printf 'Projected EFI=%s planned bootinfo=%s\n' "${11}" "${12}"
    if [ "$stage" = 00000009 ] && [ "$error" = 00000000 ]; then
        printf 'Dry-run preparation completed. No NetBSD kernel was started.\n'
    fi
    if [ "$stage" = 0000000a ] && [ "$error" = 00000000 ]; then
        printf 'Kernel and boot information copied and verified in RAM.\n'
        printf 'NetBSD was not started; Linux will resume.\n'
    fi
    if [ "$stage" = 0000000b ] && [ "$error" = 00000000 ]; then
        printf 'NetBSD native loader returned; CPU state was restored.\n'
        printf 'This does not establish a full kernel boot.\n'
    fi
}

export_seq=0
export_ready=0
export_status() {
    if [ "$export_ready" -eq 1 ]; then
        printf 'HTTP status remains available to the local network on port 8080.\n'
        ifconfig eth0
        return
    fi
    [ -r /atv-loader-diag.bin ] || { printf 'Status file unavailable.\n'; return; }
    export_seq=$((export_seq + 1))
    export_dir=/tmp/atv-loader-export-$$-$export_seq
    mkdir "$export_dir" || { printf 'Cannot create export directory.\n'; return; }
    cp /atv-loader-diag.bin "$export_dir/atv-loader-diag.bin" || return
    show_status > "$export_dir/status.txt" || return
    printf '\nConfiguring wired Ethernet with DHCP.\n'
    ifconfig eth0 up || return
    if ! udhcpc -n -q -t 3 -T 3 -i eth0; then
        printf 'DHCP failed. Status remains available on screen.\n'; return
    fi
    if ! httpd -p 8080 -h "$export_dir"; then
        printf 'Could not start HTTP server; it may already be running.\n'; return
    fi
    export_ready=1
    printf 'HTTP files are available to the local network.\n'
    printf 'Status: http://<eth0 IPv4 address>:8080/status.txt\n'
    printf 'Raw record: http://<eth0 IPv4 address>:8080/atv-loader-diag.bin\n'
    ifconfig eth0
}

show_status
while :; do
    printf '\n1: Loader status  2: Export over Ethernet    Power off to exit\nSelect a page: '
    if ! IFS= read -r choice; then
        while :; do sleep 3600; done
    fi
    case "$choice" in
        1) show_status ;;
        2) export_status ;;
        *) printf 'Select 1 or 2.\n' ;;
    esac
done
