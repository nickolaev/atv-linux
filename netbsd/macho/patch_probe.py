#!/usr/bin/env python3
"""Add a bounded entry marker to the known Apple TV Mach-O loader copy."""
import struct
import sys
from pathlib import Path

SHIM_OFFSET = 0x500
SHIM_ADDRESS = 0x02000500
ENTRY_OFFSET = 0x1000
ENTRY_ADDRESS = 0x02001000
EXPECTED_ENTRY = bytes.fromhex('668cdb668ec389c59090909090909090')


def patch(original, elf):
    if len(original) < 0x1010 or original[:4] != b'\xce\xfa\xed\xfe':
        raise ValueError('expected 32-bit Mach-O')
    header = struct.unpack_from('<7I', original)
    if header[1:4] != (7, 3, 2) or 28 + header[5] > SHIM_OFFSET:
        raise ValueError('unexpected Mach-O header or load-command size')
    pos, end = 28, 28 + header[5]
    text = entry = None
    for _ in range(header[4]):
        if pos + 8 > end:
            raise ValueError('truncated Mach-O commands')
        cmd, size = struct.unpack_from('<II', original, pos)
        if size < 8 or pos + size > end:
            raise ValueError('invalid Mach-O command')
        if cmd == 1:
            if size < 56:
                raise ValueError('truncated segment command')
            count = struct.unpack_from('<I', original, pos+48)[0]
            if 56 + count * 68 > size:
                raise ValueError('truncated segment section table')
            for index in range(count):
                section = pos + 56 + index * 68
                section_size, section_offset = struct.unpack_from('<II', original, section+36)
                if section_size and section_offset and section_offset < ENTRY_OFFSET and section_offset + section_size > SHIM_OFFSET:
                    raise ValueError('section overlaps proposed shim location')
            if original[pos+8:pos+24].rstrip(b'\0') == b'__TEXT':
                text = struct.unpack_from('<4I', original, pos+24)
        if cmd == 5 and size >= 80:
            entry = struct.unpack_from('<I', original, pos + 16 + 10 * 4)[0]
        pos += size
    if pos != end or text is None or entry != ENTRY_ADDRESS:
        raise ValueError('unexpected Mach-O text or entry')
    vmaddr, vmsize, fileoff, filesize = text
    if (vmaddr != 0x02000000 or fileoff != 0 or vmsize < ENTRY_OFFSET + 16 or
            filesize < ENTRY_OFFSET + 16 or original[ENTRY_OFFSET:ENTRY_OFFSET+16] != EXPECTED_ENTRY):
        raise ValueError('known bootloader mapping or entry does not match')
    if len(elf) < 52 or elf[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('expected ELF32 little-endian shim')
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', elf)
    if h[1:3] != (2, 3) or h[4] != SHIM_ADDRESS or h[9] != 32 or h[5] + h[10] * 32 > len(elf):
        raise ValueError('unexpected ELF header or entry')
    loads = [struct.unpack_from('<8I', elf, h[5] + i*32) for i in range(h[10])]
    loads = [p for p in loads if p[0] == 1]
    if len(loads) != 1:
        raise ValueError('expected one ELF load segment')
    _, src, address, _, filesz, memsz, flags, _ = loads[0]
    if (address != SHIM_ADDRESS or filesz != memsz or not flags & 1 or not filesz or
            filesz > ENTRY_OFFSET - SHIM_OFFSET or src + filesz > len(elf)):
        raise ValueError('shim does not fit unused header padding')
    if any(original[SHIM_OFFSET:SHIM_OFFSET+filesz]):
        raise ValueError('shim location is not zero padding')
    out = bytearray(original)
    out[SHIM_OFFSET:SHIM_OFFSET+filesz] = elf[src:src+filesz]
    jump_from = ENTRY_ADDRESS + 8
    out[ENTRY_OFFSET+8:ENTRY_OFFSET+13] = b'\xe9' + struct.pack('<i', SHIM_ADDRESS - (jump_from + 5))
    return bytes(out)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit('usage: patch_probe.py ORIGINAL_MACHO SHIM_ELF NEW_MACHO')
    try:
        result = patch(Path(sys.argv[1]).read_bytes(), Path(sys.argv[2]).read_bytes())
        with Path(sys.argv[3]).open('xb') as output:
            output.write(result)
    except (ValueError, OSError, struct.error) as error:
        sys.exit(str(error))
