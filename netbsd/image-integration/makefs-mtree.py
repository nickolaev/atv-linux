#!/usr/bin/env python3
"""Generate NetBSD root ownership and device metadata for host makefs."""
import os
from pathlib import Path
import stat
import sys
import tarfile

if len(sys.argv) != 4:
    raise SystemExit('usage: makefs-mtree.py ROOT RELEASE-SETS OUTPUT')
root, sets, output = map(Path, sys.argv[1:])
entries = {}
for archive_name in ('base.tgz', 'etc.tgz', 'kern-GENERIC.tgz', 'modules.tgz'):
    with tarfile.open(sets / archive_name) as archive:
        for entry in archive:
            path = './' + entry.name.removeprefix('./').rstrip('/')
            if path == './':
                continue
            if entry.isdir() or entry.isfile() or entry.issym() or entry.islnk():
                entries[path] = (entry.uid, entry.gid, entry.mode & 0o7777,
                                 'dir' if entry.isdir() else 'link' if entry.issym() else 'file')

# Files added by the image builder are owned by root. Extracted release
# members retain their archive metadata regardless of the host user's UID.
for current, dirs, files in os.walk(root, followlinks=False):
    for name in dirs + files:
        path = Path(current) / name
        relative = './' + path.relative_to(root).as_posix()
        if relative in entries:
            continue
        info = path.lstat()
        kind = 'link' if stat.S_ISLNK(info.st_mode) else 'dir' if stat.S_ISDIR(info.st_mode) else 'file'
        entries[relative] = (0, 0, info.st_mode & 0o7777, kind)

def escape(path):
    return ''.join('\\%03o' % ord(c) if c.isspace() or c == '\\' else c for c in path)

with output.open('w') as stream:
    stream.write('. type=dir uid=0 gid=0 mode=0755\n')
    for name, (uid, gid, mode, kind) in sorted(entries.items()):
        if os.path.lexists(root / name):
            stream.write(f'{escape(name)} type={kind} uid={uid} gid={gid} mode={mode:o}\n')
    devices = [
        ('console', 0, 0, 0o600), ('tty', 1, 0, 0o666),
        ('null', 2, 2, 0o666), ('zero', 2, 12, 0o666),
        ('random', 46, 0, 0o444), ('urandom', 46, 1, 0o644),
        ('klog', 7, 0, 0o600), ('bpf', 23, 0, 0o600),
        ('ptmx', 165, 0, 0o666), ('ptm', 165, 1, 0o666),
        ('constty', 0, 1, 0o600), ('mem', 2, 0, 0o640),
        ('kmem', 2, 1, 0o640), ('full', 2, 11, 0o666),
        ('stdin', 22, 0, 0o666), ('stdout', 22, 1, 0o666),
        ('stderr', 22, 2, 0o666), ('sysmon', 67, 0, 0o644),
        ('watchdog', 67, 1, 0o644), ('power', 67, 2, 0o640),
    ]
    for name, major, minor, mode in devices:
        stream.write(f'./dev/{name} type=char uid=0 gid=0 mode={mode:o} device=netbsd,{major},{minor}\n')
    for unit in range(32):
        for prefix, kind in (('', 'block'), ('r', 'char')):
            stream.write(f'./dev/{prefix}dk{unit} type={kind} uid=0 gid=5 mode=0640 device=netbsd,168,{unit}\n')
    for partition in range(8):
        suffix = chr(ord('a') + partition)
        for prefix, kind, major in (('', 'block', 0), ('r', 'char', 3)):
            stream.write(f'./dev/{prefix}wd0{suffix} type={kind} uid=0 gid=5 mode=0640 device=netbsd,{major},{partition}\n')
    for prefix, kind, major in (('', 'block', 0), ('r', 'char', 3)):
        stream.write(f'./dev/{prefix}wd0 type={kind} uid=0 gid=5 mode=0640 device=netbsd,{major},3\n')
