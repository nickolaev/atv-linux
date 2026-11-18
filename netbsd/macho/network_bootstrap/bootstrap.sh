#!/bin/sh
# Optional Linux-time diagnostic launcher. Source from the returning menu.
# It deliberately never launches NetBSD or reuses Apple-time firmware pointers.
network_bootstrap() {
    printf 'Configuring Ethernet with DHCP...\n'
    ifconfig eth0 up || return 1
    udhcpc -n -q -t 3 -T 3 -i eth0 || return 1
    ifconfig eth0
    printf 'Diagnostic HTTP URL: '
    IFS= read -r url || return 1
    case "$url" in http://*) ;; *) printf 'Only HTTP URLs are supported.\n'; return 1 ;; esac
    printf 'Expected SHA-256 (64 hexadecimal characters): '
    IFS= read -r expected || return 1
    case "$expected" in *[!0-9a-f]*|'') printf 'Expected lowercase hexadecimal SHA-256.\n'; return 1 ;; esac
    [ "${#expected}" -eq 64 ] || { printf 'Invalid SHA-256 length.\n'; return 1; }
    work=$(mktemp -d /tmp/atv-netdiag.XXXXXX) || return 1
    # BusyBox ash ulimit -f uses KiB; use a subshell so the limit cannot leak.
    if ! (ulimit -f 8192 && wget -q -O "$work/payload" "$url"); then
        printf 'Download failed or exceeded the size limit.\n'; return 1
    fi
    [ -s "$work/payload" ] || { printf 'Empty payload.\n'; return 1; }
    set -- $(sha256sum "$work/payload")
    [ "$1" = "$expected" ] || { printf 'SHA-256 mismatch; not running.\n'; return 1; }
    printf 'Digest verified. Run this diagnostic now? Type yes: '
    IFS= read -r answer || return 1
    [ "$answer" = yes ] || { printf 'Cancelled.\n'; return 1; }
    # Shell payload intentionally runs only after local operator confirmation.
    sh "$work/payload" > "$work/status.txt" 2>&1
    result=$?
    printf '\nExit status: %s\n' "$result" >> "$work/status.txt"
    cat "$work/status.txt"
    mkdir "$work/export" || return 1
    cp "$work/status.txt" "$work/export/status.txt" || return 1
    if httpd -p 8081 -h "$work/export"; then
        printf 'Report available on local network: http://<eth0 IPv4>:8081/status.txt\n'
    else
        printf 'HTTP export unavailable; report is shown above.\n'
    fi
    return "$result"
}
