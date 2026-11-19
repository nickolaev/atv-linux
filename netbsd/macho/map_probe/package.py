#!/usr/bin/env python3
"""Add an EFI snapshot file to a known ATV1 Linux-initrd Mach-O copy.

This operates only on regular image files. The resulting snapshot is from the
boot in which the payload runs; it is not a memory map for a future boot.
"""
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / 'image'))
from patch_probe import patch as patch_entry
from embed_boot_menu import find_initrd

CAPTURE_SIZE = 8192
CAPTURE_NAME = b'atv-probe.bin'
PREFLIGHT_NAME = b'atv-preflight'
OBSERVER_NAME = b'atv-observe-firmware'
PLACEHOLDER = struct.pack('<I', 0xfeedc0de)


def newc_entry(name, data, inode, mode=0o100600):
    namesize = len(name) + 1
    fields = (inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, namesize, 0)
    header = b'070701' + b''.join(f'{f:08x}'.encode() for f in fields)
    prefix = header + name + b'\0'
    prefix += bytes((-len(prefix)) % 4)
    entry = prefix + data
    entry += bytes((-len(entry)) % 4)
    return entry, len(prefix)


def archive_has_capture(archive, name_to_find=CAPTURE_NAME):
    """Inspect newc entry names, not file contents that may mention the name."""
    pos = 0
    while True:
        if pos + 110 > len(archive) or archive[pos:pos+6] != b'070701':
            raise ValueError('invalid existing newc archive')
        try:
            size = int(archive[pos+54:pos+62], 16)
            namesize = int(archive[pos+94:pos+102], 16)
        except ValueError as error:
            raise ValueError('invalid existing newc header') from error
        name_start = pos + 110
        name_end = name_start + namesize
        if not namesize or name_end > len(archive) or archive[name_end-1] != 0:
            raise ValueError('invalid existing newc name')
        name = archive[name_start:name_end-1]
        data_start = (name_end + 3) & ~3
        if data_start + size > len(archive):
            raise ValueError('truncated existing newc entry')
        if name in (name_to_find, b'./' + name_to_find, b'/' + name_to_find):
            return True
        if name == b'TRAILER!!!':
            return False
        pos = (data_start + size + 3) & ~3


def text_segment(blob):
    h = struct.unpack_from('<7I', blob)
    pos, end = 28, 28 + h[5]
    for _ in range(h[4]):
        if pos + 56 > end:
            raise ValueError('invalid Mach-O command')
        cmd, size = struct.unpack_from('<II', blob, pos)
        if size < 8 or pos + size > end:
            raise ValueError('invalid Mach-O command size')
        if cmd == 1 and blob[pos+8:pos+24].rstrip(b'\0') == b'__TEXT':
            return struct.unpack_from('<4I', blob, pos+24)
        pos += size
    raise ValueError('missing __TEXT')


def check_preflight(blob, name='preflight'):
    """Require a static i386 executable, not a host or interpreter binary."""
    if len(blob) < 52 or blob[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError(f'{name} must be an ELF32 executable')
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', blob)
    if h[1:4] != (2, 3, 1) or h[9] != 32 or not h[10] or h[5] + h[9] * h[10] > len(blob):
        raise ValueError(f'invalid i386 {name} ELF')
    headers = [struct.unpack_from('<8I', blob, h[5] + i * h[9]) for i in range(h[10])]
    if any(p[0] in (2, 3) for p in headers) or not any(p[0] == 1 and p[6] & 1 and p[2] <= h[4] < p[2] + p[4] for p in headers):
        raise ValueError(f'{name} must be static with a file-backed executable entry')
    if any(p[0] == 1 and (p[1] + p[4] > len(blob) or p[4] > p[5]) for p in headers):
        raise ValueError(f'invalid {name} load segment')


def package(original, shim_elf, preflight=None, observer=None):
    offset, length = find_initrd(original)
    segment = original[offset:offset+length]
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        uncompressed = inflater.decompress(segment) + inflater.flush()
    except zlib.error as error:
        raise ValueError('invalid existing initramfs gzip stream') from error
    if not inflater.eof or not inflater.unused_data or any(inflater.unused_data):
        raise ValueError('initramfs must contain one gzip stream followed by zero padding')
    if archive_has_capture(uncompressed):
        raise ValueError('capture filename already exists in initramfs')
    if preflight is not None:
        check_preflight(preflight)
        if archive_has_capture(uncompressed, PREFLIGHT_NAME):
            raise ValueError('preflight filename already exists in initramfs')
    if observer is not None:
        check_preflight(observer, 'firmware observer')
        if archive_has_capture(uncompressed, OBSERVER_NAME):
            raise ValueError('firmware observer filename already exists in initramfs')
    used = len(segment) - len(inflater.unused_data)
    aligned = (used + 3) & ~3
    entry, data_offset = newc_entry(CAPTURE_NAME, bytes(CAPTURE_SIZE), 0x41545601)
    trailer, _ = newc_entry(b'TRAILER!!!', b'', 0x41545602)
    preflight_entry = newc_entry(PREFLIGHT_NAME, preflight, 0x41545603, 0o100755)[0] if preflight is not None else b''
    observer_entry = newc_entry(OBSERVER_NAME, observer, 0x41545604, 0o100755)[0] if observer is not None else b''
    archive = entry + preflight_entry + observer_entry + trailer
    if aligned + len(archive) > length:
        raise ValueError('snapshot archive does not fit in existing initrd padding')
    cap_file_offset = offset + aligned + data_offset
    vmaddr, vmsize, fileoff, filesize = text_segment(original)
    if (fileoff != 0 or cap_file_offset < fileoff or
            cap_file_offset + CAPTURE_SIZE > fileoff + filesize or
            cap_file_offset + CAPTURE_SIZE > fileoff + vmsize):
        raise ValueError('snapshot is not wholly mapped by __TEXT')
    cap_address = vmaddr + cap_file_offset - fileoff
    if cap_address + CAPTURE_SIZE > 0x100000000:
        raise ValueError('snapshot physical address wraps')
    if len(shim_elf) < 52 or shim_elf[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('expected little-endian ELF32 shim')
    elf_header = struct.unpack_from('<16sHHIIIIIHHHHHH', shim_elf)
    phoff, phsize, phnum = elf_header[5], elf_header[9], elf_header[10]
    if phsize != 32 or phoff + phsize * phnum > len(shim_elf):
        raise ValueError('invalid shim program header table')
    loads = [struct.unpack_from('<8I', shim_elf, phoff + phsize * i)
             for i in range(phnum)]
    loads = [segment for segment in loads if segment[0] == 1]
    if len(loads) != 1:
        raise ValueError('shim must contain exactly one load segment')
    load_offset, load_size = loads[0][1], loads[0][4]
    if (load_offset + load_size > len(shim_elf) or shim_elf.count(PLACEHOLDER) != 1 or
            shim_elf[load_offset:load_offset+load_size].count(PLACEHOLDER) != 1):
        raise ValueError('shim must contain exactly one destination placeholder in its load segment')
    patched_elf = shim_elf.replace(PLACEHOLDER, struct.pack('<I', cap_address), 1)
    blob = bytearray(original)
    blob[offset+aligned:offset+aligned+len(archive)] = archive
    out = patch_entry(bytes(blob), patched_elf)
    return out, cap_address


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5, 6):
        sys.exit('usage: package.py MENU_MACHO SHIM_ELF NEW_MACHO [PREFLIGHT_ELF [OBSERVER_ELF]]')
    try:
        preflight = Path(sys.argv[4]).read_bytes() if len(sys.argv) >= 5 else None
        observer = Path(sys.argv[5]).read_bytes() if len(sys.argv) == 6 else None
        result, address = package(Path(sys.argv[1]).read_bytes(), Path(sys.argv[2]).read_bytes(), preflight, observer)
        with Path(sys.argv[3]).open('xb') as output:
            output.write(result)
        print(f'EFI snapshot destination: 0x{address:08x}, {CAPTURE_SIZE} bytes')
    except (ValueError, OSError, struct.error) as error:
        sys.exit(str(error))
