#!/usr/bin/env python3
"""Replace the entry code in a copy of the known ATV1 Mach-O wrapper.

The input and output must be separate files. This is a diagnostic experiment,
not a NetBSD loader. The ELF must have one fully file-backed load segment.
"""
import struct
import sys
from pathlib import Path


def patch(original, elf):
    if len(original) < 4096 or original[:4] != b'\xce\xfa\xed\xfe':
        raise ValueError('expected a 32-bit little-endian Mach-O')
    hdr = struct.unpack_from('<7I', original)
    if hdr[1:4] != (7, 3, 2) or 28 + hdr[5] > len(original):
        raise ValueError('unexpected Mach-O header')
    pos, end = 28, 28 + hdr[5]
    text = None
    entry = None
    for _ in range(hdr[4]):
        if pos + 8 > end:
            raise ValueError('truncated load commands')
        cmd, size = struct.unpack_from('<II', original, pos)
        if size < 8 or pos + size > end:
            raise ValueError('invalid load command')
        if cmd == 1 and size >= 56 and original[pos+8:pos+24].rstrip(b'\0') == b'__TEXT':
            if size < 124 or struct.unpack_from('<I', original, pos+48)[0] < 1:
                raise ValueError('missing __TEXT section')
            sect = pos + 56
            if original[sect:sect+16].rstrip(b'\0') != b'__text':
                raise ValueError('first __TEXT section is not __text')
            text = struct.unpack_from('<III', original, sect + 32)
        if cmd == 5 and size >= 80:
            entry = struct.unpack_from('<I', original, pos + 16 + 10 * 4)[0]
        pos += size
    if pos != end or text is None or entry is None:
        raise ValueError('missing Mach-O entry or text section')
    address, capacity, offset = text
    if entry != address or offset + capacity > len(original):
        raise ValueError('unexpected Mach-O entry location')
    if len(elf) < 52 or elf[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('expected ELF32 little-endian diagnostic')
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', elf)
    if h[1:3] != (2, 3) or h[4] != entry or h[9] != 32 or h[5] + h[10] * 32 > len(elf):
        raise ValueError('unexpected ELF header or entry')
    loads = [struct.unpack_from('<8I', elf, h[5] + i * 32) for i in range(h[10])]
    loads = [p for p in loads if p[0] == 1]
    if len(loads) != 1:
        raise ValueError('expected one ELF load segment')
    _, src, vaddr, _, filesz, memsz, flags, _ = loads[0]
    if vaddr != entry or filesz != memsz or not flags & 1 or not filesz or filesz > capacity or src + filesz > len(elf):
        raise ValueError('diagnostic does not fit the existing text section')
    return original[:offset] + elf[src:src+filesz] + original[offset+filesz:]


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit('usage: patch_known_loader.py ORIGINAL_MACHO DIAGNOSTIC_ELF NEW_MACHO')
    try:
        result = patch(Path(sys.argv[1]).read_bytes(), Path(sys.argv[2]).read_bytes())
        with Path(sys.argv[3]).open('xb') as output:
            output.write(result)
    except (ValueError, OSError, struct.error) as error:
        sys.exit(str(error))
