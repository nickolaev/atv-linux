#!/usr/bin/env python3
"""Wrap one fixed-address ELF32 load segment as an i386 Mach-O executable."""
import struct
import sys
from pathlib import Path

def convert(data):
    if len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('expected little-endian ELF32')
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
    _, typ, machine, _, entry, phoff, _, _, _, phsize, phnum, *_ = header
    if typ != 2 or machine != 3 or phsize != 32 or phoff + phnum * phsize > len(data):
        raise ValueError('expected i386 ELF executable with valid program headers')
    loads = [struct.unpack_from('<8I', data, phoff + i * phsize)
             for i in range(phnum)]
    loads = [p for p in loads if p[0] == 1]
    if len(loads) != 1:
        raise ValueError('expected exactly one ELF load segment')
    _, offset, address, _, size, memsize, flags, _ = loads[0]
    if (size > memsize or offset + size > len(data) or address < 4096 or
            not address <= entry < address + size or not flags & 1 or
            address + memsize > 0xffffffff):
        raise ValueError('invalid ELF load segment or entry')
    fileoff = 4096
    # Map the Mach-O header as part of __TEXT, like the existing ATV1 loader.
    # The ELF payload starts one page into that segment.
    header = struct.pack('<7I', 0xfeedface, 7, 3, 2, 3, 260, 1)
    pagezero = struct.pack('<II16s8I', 1, 56, b'__PAGEZERO', 0, 4096,
                           0, 0, 0, 0, 0, 4)
    segment = struct.pack('<II16s8I', 1, 124, b'__TEXT', address - fileoff,
                          (memsize + fileoff + 4095) & ~4095, 0,
                          fileoff + size, 7, 5, 1, 0)
    section = struct.pack('<16s16s9I', b'__text', b'__TEXT', address, size,
                          fileoff, 12, 0, 0, 0, 0, 0)
    regs = [0] * 16
    regs[10] = entry
    regs[8], regs[11], regs[12], regs[13] = 0x1f, 0x17, 0x1f, 0x1f
    thread = struct.pack('<4I16I', 5, 80, 0xffffffff, 16, *regs)
    return (header + pagezero + segment + section + thread).ljust(fileoff, b'\0') + data[offset:offset + size]

if __name__ == '__main__':
    try:
        Path(sys.argv[2]).write_bytes(convert(Path(sys.argv[1]).read_bytes()))
    except (ValueError, IndexError, OSError) as error:
        sys.exit(str(error))
