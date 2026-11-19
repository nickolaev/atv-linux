#!/usr/bin/env python3
"""Build key-bearing returning diagnostics in private, exclusive staging."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import inject


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def copy_input(source, destination, private=False):
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as src:
        info = os.fstat(src.fileno())
        if not stat.S_ISREG(info.st_mode) or not info.st_size or (private and stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('expected nonempty regular input and mode-0600 key')
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)


def check_parent_chain(parent):
    """Reject ancestors where an unrelated user can rename staging paths."""
    for path in (parent, *parent.parents):
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()):
            raise ValueError('output directory chain has an untrusted owner')
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) and not info.st_mode & stat.S_ISVTX:
            raise ValueError('output directory chain is shared-writable without sticky protection')


def build(args):
    output = Path(args.output)
    if output.exists() or output.is_symlink() or output.name in ('', '.', '..'):
        raise ValueError('output must be a new file')
    parent = output.parent.resolve(strict=True)
    if str(parent) in ('/dev', '/proc', '/sys') or str(parent).startswith(('/dev/', '/proc/', '/sys/')):
        raise ValueError('invalid output directory')
    check_parent_chain(parent)
    output = parent / output.name
    old_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix='.atv-private-', dir=parent) as tmp:
            work = Path(tmp)
            os.chmod(work, 0o700)
            staged = {}
            for name in ('original', 'menu', 'poll', 'auth', 'supervisor', 'key', 'shim', 'high', 'kernel', 'reference'):
                staged[name] = work / name
                copy_input(getattr(args, name), staged[name], private=name == 'key')
            prepared = inject.inject(*(staged[n].read_bytes() for n in ('original', 'menu', 'poll', 'auth', 'supervisor', 'key')))
            returning = module('atv_returning_package', ROOT / 'macho/target/returning/package.py')
            combined, _ = returning.package(prepared, staged['shim'].read_bytes(), staged['high'].read_bytes())
            macho = work / 'combined.macho'
            fd = os.open(macho, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream: stream.write(combined)
            target = module('atv_target_package', ROOT / 'macho/target/packaging/package.py')
            image = work / 'private.img'
            target.package(macho, staged['kernel'], staged['reference'], image,
                           Path(args.recovery), 128, 96, False)
            os.chmod(image, 0o600)
            os.link(image, output, follow_symlinks=False)
    finally:
        os.umask(old_umask)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'menu', 'poll', 'auth', 'supervisor', 'key', 'shim', 'high', 'kernel', 'reference', 'output', 'recovery'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        build(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'private build failed: {exc}\n')
    print(f'Created private image {args.output}; hardware use is unverified.')


if __name__ == '__main__':
    main()
