#!/usr/bin/env python3
"""Build makefs ownership and device specification from official sets."""
import os
import pathlib
import tarfile

base = pathlib.Path('/home/nickolaev/atv-netbsd-inputs/generic-work')
root = base / 'root'
sets = pathlib.Path('/home/nickolaev/atv-netbsd-11.1-sysroot/sets')
entries = {}
for name in ('base.tgz', 'etc.tgz', 'modules.tgz', 'kern-GENERIC.tgz', 'comp.tgz'):
    with tarfile.open(sets / name) as archive:
        for entry in archive:
            name = './' + entry.name.removeprefix('./').rstrip('/')
            if name == './':
                name = '.'
            if entry.isdir() or entry.isfile() or entry.issym():
                entries[name] = (entry.uid, entry.gid, entry.mode & 0o7777, 'dir' if entry.isdir() else 'link' if entry.issym() else 'file')
with (base / 'root.mtree').open('w') as output:
    output.write('. type=dir uid=0 gid=0 mode=0755\n')
    for name, (uid, gid, mode, kind) in entries.items():
        if not os.path.lexists(root / name):
            continue
        escaped = ''.join('\\%03o' % ord(c) if c.isspace() or c == '\\' else c for c in name)
        output.write(f'{escaped} type={kind} uid={uid} gid={gid} mode={mode:o}\n')
    for name, major, minor, mode in [('console', 0, 0, 0o600), ('tty', 1, 0, 0o666), ('null', 2, 2, 0o666), ('zero', 2, 12, 0o666), ('random', 46, 0, 0o444), ('urandom', 46, 1, 0o644), ('klog', 7, 0, 0o600), ('bpf', 23, 0, 0o600), ('ptmx', 165, 0, 0o666), ('ptm', 165, 1, 0o666)]:
        output.write(f'./dev/{name} type=char uid=0 gid=0 mode={mode:o} device=netbsd,{major},{minor}\n')
    for unit in range(32):
        for prefix, kind in (('', 'block'), ('r', 'char')):
            output.write(f'./dev/{prefix}dk{unit} type={kind} uid=0 gid=5 mode=0640 device=netbsd,168,{unit}\n')
    for name, major, minor, mode in [('constty', 0, 1, 0o600), ('mem', 2, 0, 0o640), ('kmem', 2, 1, 0o640), ('full', 2, 11, 0o666), ('stdin', 22, 0, 0o666), ('stdout', 22, 1, 0o666), ('stderr', 22, 2, 0o666), ('sysmon', 67, 0, 0o644), ('watchdog', 67, 1, 0o644), ('power', 67, 2, 0o640)]:
        output.write(f'./dev/{name} type=char uid=0 gid=0 mode={mode:o} device=netbsd,{major},{minor}\n')
