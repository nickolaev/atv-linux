#!/usr/bin/env python3
"""Prepare a returning menu Mach-O with authenticated agent files; not an image."""
import gzip
import hashlib
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'image'))
sys.path.insert(0, str(ROOT / 'netbsd/macho/map_probe'))
from embed_boot_menu import EXPECTED_SHA256, add_menu_to_rcs, find_initrd
from package import newc_entry


def validate_executable(auth):
    if len(auth) < 52 or auth[:7] != b'\x7fELF\x01\x01\x01' or auth[18:20] != b'\x03\x00':
        raise ValueError('expected i386 static executable')
    import struct
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', auth)
    if h[1] != 2 or h[9] != 32 or not h[10] or h[5] + h[9]*h[10] > len(auth):
        raise ValueError('invalid executable ELF')
    if any(struct.unpack_from('<I', auth, h[5]+i*h[9])[0] in (2, 3) for i in range(h[10])):
        raise ValueError('executable must not need dynamic linker')


def inject(original, menu, poll, auth, supervisor, key):
    if hashlib.sha256(original).hexdigest() != EXPECTED_SHA256:
        raise ValueError('unexpected original loader')
    if len(key) != 32 or not poll.startswith(b'#!/bin/sh\n'):
        raise ValueError('invalid key or poller')
    validate_executable(auth)
    validate_executable(supervisor)
    anchor = b'        2) export_status ;;\n'
    if menu.count(anchor) != 1:
        raise ValueError('unexpected returning menu')
    menu = menu.replace(b'1: Loader status  2: Export over Ethernet', b'1: Loader status  2: Export status  3: Network agent')
    menu = menu.replace(b'Select 1 or 2.', b'Select 1, 2 or 3.')
    menu = menu.replace(anchor, anchor + b'''        3) stop_agent || continue
           printf 'Controller URL (http://host:port): '; IFS= read -r controller
           start_agent "$controller" ;;
''')
    startup = b'''# Per-image authenticated agent; set atvnet=off in kernel flags to disable.
agent_pid=
agent_alive() {
    [ -n "$agent_pid" ] && kill -0 "$agent_pid" 2>/dev/null &&
      tr '\\000' ' ' < "/proc/$agent_pid/cmdline" 2>/dev/null | grep -q '/atv-net-poll'
}
stop_agent() {
    if ! agent_alive; then agent_pid=; return 0; fi
    control=/tmp/atv-netdiag-control
    if ! mkdir "$control/lock" 2>/dev/null; then
        printf 'Agent is busy; retry shortly.\n'; return 1
    fi
    if [ -e "$control/busy" ]; then
        rmdir "$control/lock"; printf 'Diagnostic job is running; retry after it finishes.\n'; return 1
    fi
    if ! : > "$control/stop"; then rmdir "$control/lock"; return 1; fi
    rmdir "$control/lock"
    remaining=15
    while agent_alive && [ "$remaining" -gt 0 ]; do
        sleep 1; remaining=$((remaining - 1))
    done
    if agent_alive; then printf 'Agent is stopping; retry shortly.\n'; return 1; fi
    wait "$agent_pid" 2>/dev/null || :
    agent_pid=
}
start_agent() {
    if agent_alive; then
        printf 'Network agent already running.\n'; return
    fi
    [ -z "$agent_pid" ] || wait "$agent_pid" 2>/dev/null || :
    agent_pid=
    if [ ! -x /atv-auth ] || [ ! -x /atv-supervise ] || [ ! -r /atv-net-poll ] || [ ! -r /atv-net-key ]; then
        printf 'Network agent files unavailable.\n'; return 1
    fi
    if ! ifconfig eth0 up || ! udhcpc -n -q -t 3 -T 3 -i eth0; then
        printf 'Network setup failed; select 3 to retry.\n'; return
    fi
    sh /atv-net-poll "$1" /atv-net-key &
    agent_pid=$!
    printf 'Network agent started; errors appear on this console.\n'
}
if ! grep -qw 'atvnet=off' /proc/cmdline; then
    start_agent http://192.168.100.246:8082
fi

show_status
'''
    if menu.count(b'\nshow_status\nwhile :; do') != 1:
        raise ValueError('unexpected returning menu startup')
    menu = menu.replace(b'\nshow_status\nwhile :; do', b'\n' + startup + b'while :; do')
    offset, size = find_initrd(original)
    archive = add_menu_to_rcs(gzip.decompress(original[offset:offset+size]), menu)
    pos = 0
    existing = set()
    while True:
        if archive[pos:pos+6] != b'070701': raise ValueError('invalid initrd')
        length = int(archive[pos+54:pos+62], 16)
        namesize = int(archive[pos+94:pos+102], 16)
        name = archive[pos+110:pos+109+namesize]
        if name == b'TRAILER!!!': break
        existing.add(name.removeprefix(b'./'))
        start = (pos+110+namesize+3)&~3
        pos = (start+length+3)&~3
        if pos > len(archive): raise ValueError('truncated initrd')
    entries = ((b'atv-net-poll', poll, 0o100700), (b'atv-auth', auth, 0o100700),
               (b'atv-supervise', supervisor, 0o100700), (b'atv-net-key', key, 0o100600))
    if any(n in existing for n, _, _ in entries): raise ValueError('bootstrap file already exists')
    added = b''.join(newc_entry(n, d, 0x41545500+i, mode)[0] for i, (n, d, mode) in enumerate(entries))
    compressed = gzip.compress(archive[:pos] + added + archive[pos:], compresslevel=9, mtime=0)
    if len(compressed) > size: raise ValueError('bootstrap initrd does not fit')
    result = bytearray(original)
    result[offset:offset+size] = compressed + bytes(size-len(compressed))
    return bytes(result)


def read_regular(path, private=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or (private and stat.S_IMODE(st.st_mode) != 0o600):
            raise ValueError('input must be regular; key must have mode 0600')
        return stream.read()


def main():
    if len(sys.argv) != 8:
        raise ValueError('usage: inject.py ORIGINAL MENU POLL AUTH SUPERVISOR KEY NEW_MENU_MACHO')
    original, menu, poll, auth, supervisor, keypath, output = map(Path, sys.argv[1:])
    data = inject(*(read_regular(p) for p in (original, menu, poll, auth, supervisor)), read_regular(keypath, private=True))
    # The Mach-O embeds the authentication key; do not publish it with the
    # caller's possibly permissive umask. Never overwrite an existing path.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f: f.write(data)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, EOFError) as e: sys.exit(str(e))
