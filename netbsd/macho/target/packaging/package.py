#!/usr/bin/env python3
"""Package an experimental embedded-kernel Mach-O in a new USB image.

This validates the container and disk metadata, not firmware safety or boot.
The source Mach-O must already contain the complete uncompressed NetBSD ELF.
"""
import argparse
import hashlib
import mmap
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import uuid
import zlib

SECTOR = 512
RECOVERY_GUID = uuid.UUID('5265636f-7665-11aa-aa11-00306543ecac').bytes_le
MACH = struct.Struct('<7I')
ELF = struct.Struct('<16sHHIIIIIHHHHHH')
UINT32_MAX = (1 << 32) - 1
ROOT = Path(__file__).resolve().parents[2]
BUILDER = ROOT / 'build-image.sh'
sys.path.insert(0, str(ROOT))
from netbsd_elf import plan_elf  # noqa: E402; shared offline ELF validation


def regular(path):
    path = Path(path)
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or not st.st_size:
        raise ValueError(f'expected nonempty regular file: {path}')
    return path


def file_sha256(path):
    digest = hashlib.sha256()
    with regular(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_payload(macho_path, kernel_path):
    """Validate ELF identity and one executable Mach-O mapping containing it."""
    kernel = regular(kernel_path).read_bytes()
    if len(kernel) < ELF.size:
        raise ValueError('truncated kernel')
    h = ELF.unpack_from(kernel)
    if h[0][:7] != b'\x7fELF\x01\x01\x01' or h[1:4] != (2, 3, 1):
        raise ValueError('kernel must be an uncompressed i386 ELF executable')
    plan_elf(kernel)
    path = regular(macho_path)
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if len(data) < MACH.size:
            raise ValueError('truncated Mach-O header')
        magic, cpu, _, kind, ncmds, cmdsize, _ = MACH.unpack_from(data)
        if (magic, cpu, kind) != (0xfeedface, 7, 2) or not ncmds or ncmds > 256:
            raise ValueError('expected IA-32 executable Mach-O')
        command_end = MACH.size + cmdsize
        if command_end > len(data):
            raise ValueError('truncated load commands')
        offset, mapped, entry = MACH.size, [], None
        for _ in range(ncmds):
            if offset + 8 > command_end:
                raise ValueError('truncated load command')
            command, size = struct.unpack_from('<II', data, offset)
            if size < 8 or size % 4 or offset + size > command_end:
                raise ValueError('invalid load command size')
            if command == 1:
                if size < 56:
                    raise ValueError('truncated LC_SEGMENT')
                _, _, _, vmaddr, vmsize, fileoff, filesize, _, initprot, _, _ = struct.unpack_from('<II16s8I', data, offset)
                if fileoff + filesize > len(data) or filesize > vmsize or vmaddr + vmsize > 1 << 32:
                    raise ValueError('invalid Mach-O segment range')
                if initprot & 4 and filesize:
                    mapped.append((fileoff, fileoff + filesize, vmaddr, vmaddr + filesize))
            elif command == 5:
                if size != 80 or entry is not None:
                    raise ValueError('invalid or duplicate IA-32 LC_UNIXTHREAD')
                flavor, count = struct.unpack_from('<II', data, offset + 8)
                if flavor != UINT32_MAX or count != 16:
                    raise ValueError('unsupported IA-32 thread state')
                entry = struct.unpack_from('<I', data, offset + 56)[0]
            offset += size
        if offset != command_end:
            raise ValueError('load command count mismatch')
        if entry is None or not any(start <= entry < end for _, _, start, end in mapped):
            raise ValueError('Mach-O thread entry is not executable and file backed')
        position = data.find(kernel)
        if position < 0 or data.find(kernel, position + 1) >= 0:
            raise ValueError('Mach-O must contain one exact copy of supplied kernel')
        if not any(start <= position and position + len(kernel) <= end for start, end, _, _ in mapped):
            raise ValueError('embedded kernel is not entirely inside an executable mapped segment')
    return hashlib.sha256(kernel).hexdigest()


def validate_reference(reference):
    if len(reference) != SECTOR or reference[510:] != b'\x55\xaa':
        raise ValueError('invalid reference MBR')
    if mbr_entry(reference, 0) != (0xee, 1, 39) or mbr_entry(reference, 1) != (0xda, 40, 62461) or any(reference[478:510]):
        raise ValueError('unexpected reference hybrid MBR layout')
    if reference[467:470] != b'\xfe\xff\xff':
        raise ValueError('reference recovery entry lacks the verified saturated CHS end')


def mbr_entry(mbr, index):
    pos = 446 + index * 16
    return mbr[pos + 4], *struct.unpack_from('<II', mbr, pos + 8)


def hybrid_mbr(reference, image):
    """Adopt known hybrid entry format, deriving the recovery span from GPT."""
    validate_reference(reference)
    image.seek(0, os.SEEK_END)
    image_size = image.tell()
    if image_size % SECTOR or image_size < 4 * 1024 * 1024:
        raise ValueError('invalid image size')
    image.seek(0)
    mbr = image.read(SECTOR)
    header = image.read(SECTOR)
    if len(mbr) != SECTOR or mbr[510:] != b'\x55\xaa' or len(header) != SECTOR or header[:8] != b'EFI PART':
        raise ValueError('invalid destination GPT or MBR')
    header_size, stored_crc = struct.unpack_from('<II', header, 12)
    if not 92 <= header_size <= SECTOR:
        raise ValueError('invalid GPT header size')
    check = bytearray(header[:header_size]); check[16:20] = bytes(4)
    if zlib.crc32(check) & UINT32_MAX != stored_crc:
        raise ValueError('invalid GPT header CRC')
    current, alternate, first_usable, last_usable = struct.unpack_from('<QQQQ', header, 24)
    entries_lba, count, size, entries_crc = struct.unpack_from('<QIII', header, 72)
    if (current != 1 or alternate != image_size // SECTOR - 1 or first_usable > last_usable or
            last_usable >= alternate or entries_lba < 2 or not 1 <= count <= 1024 or
            not 128 <= size <= 1024 or size % 8 or
            entries_lba * SECTOR + count * size > first_usable * SECTOR):
        raise ValueError('unsupported GPT geometry')
    image.seek(entries_lba * SECTOR)
    entries = image.read(count * size)
    if len(entries) != count * size or zlib.crc32(entries) & UINT32_MAX != entries_crc:
        raise ValueError('invalid GPT entry array CRC')
    image.seek(alternate * SECTOR)
    backup = image.read(SECTOR)
    if len(backup) != SECTOR or backup[:8] != b'EFI PART':
        raise ValueError('invalid backup GPT header')
    backup_size, backup_crc = struct.unpack_from('<II', backup, 12)
    if backup_size != header_size:
        raise ValueError('mismatched GPT header sizes')
    backup_check = bytearray(backup[:backup_size]); backup_check[16:20] = bytes(4)
    if zlib.crc32(backup_check) & UINT32_MAX != backup_crc:
        raise ValueError('invalid backup GPT header CRC')
    backup_current, backup_alternate, backup_first, backup_last = struct.unpack_from('<QQQQ', backup, 24)
    backup_entries_lba, backup_count, backup_entry_size, backup_entries_crc = struct.unpack_from('<QIII', backup, 72)
    if ((backup_current, backup_alternate, backup_first, backup_last) != (alternate, current, first_usable, last_usable) or
            backup[56:72] != header[56:72] or
            (backup_count, backup_entry_size, backup_entries_crc) != (count, size, entries_crc) or
            backup_entries_lba <= last_usable or backup_entries_lba * SECTOR + count * size > alternate * SECTOR):
        raise ValueError('mismatched backup GPT geometry')
    image.seek(backup_entries_lba * SECTOR)
    if image.read(count * size) != entries:
        raise ValueError('mismatched backup GPT entries')
    used = [entries[i:i + size] for i in range(0, len(entries), size) if any(entries[i:i + 16])]
    if len(used) != 1 or used[0][:16] != RECOVERY_GUID:
        raise ValueError('expected one Apple TV recovery partition')
    first, last = struct.unpack_from('<QQ', used[0], 32)
    if first != 40 or first < first_usable or not first <= last <= last_usable:
        raise ValueError('unexpected recovery partition bounds')
    length = last - first + 1
    if length > UINT32_MAX:
        raise ValueError('recovery partition exceeds MBR address limit')
    # A builder may have written either a protective or hybrid MBR. Never
    # accept other layouts or overwrite unrelated entries.
    first_entry, second_entry = mbr_entry(mbr, 0), mbr_entry(mbr, 1)
    if first_entry[0:2] != (0xee, 1) or any(mbr[478:510]):
        raise ValueError('unexpected destination MBR')
    if any(mbr[462:478]) and not (first_entry == (0xee, 1, 39) and second_entry == (0xda, 40, length)):
        raise ValueError('destination has incompatible hybrid entries')
    result = bytearray(mbr)
    result[446:478] = reference[446:478]
    struct.pack_into('<II', result, 470, first, length)
    return bytes(result)


def package(macho, kernel, reference, output, recovery, image_mib, recovery_mib, check):
    original_macho_digest = file_sha256(macho)
    digest = validate_payload(macho, kernel)
    reference = regular(reference)
    with reference.open('rb') as source:
        source_mbr = source.read(SECTOR)
    validate_reference(source_mbr)
    output = Path(output)
    if output.exists() or output.is_symlink() or not output.name or output.name in ('.', '..'):
        raise ValueError('output must be a new regular file')
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir() or str(parent).startswith(('/dev/', '/proc/', '/sys/')) or str(parent) in ('/dev', '/proc', '/sys'):
        raise ValueError('invalid output directory')
    # Leave room for HFS+ metadata and the existing boot assets. This is a
    # preflight lower bound, not a substitute for the filesystem copy check.
    if recovery_mib < 16 or image_mib < recovery_mib + 2 or recovery_mib > 9999 or image_mib > 9999:
        raise ValueError('invalid image or recovery size')
    if Path(macho).stat().st_size + 8 * 1024 * 1024 > recovery_mib * 1024 * 1024 - 40 * SECTOR:
        raise ValueError('recovery partition too small for payload plus metadata margin')
    output = parent / output.name
    with tempfile.TemporaryDirectory(prefix='.atv1-target-', dir=parent) as work:
        staging = Path(work) / 'image.img'
        cmd = ['bash', str(BUILDER), '--kernel', str(macho), '--recovery', str(recovery),
               '--output', str(staging), '--image-mib', str(image_mib), '--recovery-mib', str(recovery_mib)]
        if check:
            subprocess.run(cmd + ['--check'], check=True)
            return digest
        # The builder must consume exactly the bytes that were validated,
        # even if another process changes either input during packaging.
        staged_macho = Path(work) / 'payload.macho'
        staged_kernel = Path(work) / 'payload.elf'
        shutil.copyfile(macho, staged_macho)
        shutil.copyfile(kernel, staged_kernel)
        if file_sha256(staged_macho) != original_macho_digest or validate_payload(staged_macho, staged_kernel) != digest:
            raise ValueError('Mach-O or kernel input changed during packaging')
        cmd[cmd.index('--kernel') + 1] = str(staged_macho)
        subprocess.run(cmd, check=True)
        with staging.open('r+b') as image:
            result = hybrid_mbr(source_mbr, image)
            image.seek(0); image.write(result); image.flush(); os.fsync(image.fileno())
        os.link(staging, output)  # Never replace a destination created concurrently.
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--macho', required=True)
    parser.add_argument('--kernel', required=True, help='exact uncompressed kernel ELF embedded in Mach-O')
    parser.add_argument('--reference-image', required=True, help='previously working hybrid-MBR image')
    parser.add_argument('--output', required=True, help='new regular image file')
    parser.add_argument('--recovery', default=str(ROOT.parent.parent / 'image' / 'recovery'))
    parser.add_argument('--image-mib', type=int, default=128)
    parser.add_argument('--recovery-mib', type=int, default=96)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        digest = package(args.macho, args.kernel, args.reference_image, args.output, args.recovery,
                         args.image_mib, args.recovery_mib, args.check)
        print(f'Embedded kernel SHA-256: {digest}')
        print('Preflight only; no image created.' if args.check else
              f'Created {args.output}. Experimental packaging; hardware boot is unverified.')
    except (ValueError, OSError, subprocess.CalledProcessError, struct.error) as error:
        parser.exit(1, f'error: {error}\n')


if __name__ == '__main__':
    main()
