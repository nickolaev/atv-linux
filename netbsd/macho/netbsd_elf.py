#!/usr/bin/env python3
"""Inspect an i386 ELF kernel without loading it or modifying any image.

Physical range arguments are half-open [start, end). A plan produced without
usable_ranges has *not* been checked against available machine memory.
"""
import argparse
import json
import struct
from pathlib import Path


LIMIT = 1 << 32
ELF_HEADER = struct.Struct('<16sHHIIIIIHHHHHH')
PROGRAM_HEADER = struct.Struct('<8I')


def _ranges(ranges, name):
    checked = []
    for start, end in ranges:
        if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= LIMIT):
            raise ValueError(f'invalid {name} range')
        checked.append((start, end))
    return checked


def plan_elf(data, usable_ranges=None, reserved_ranges=()):
    """Return load segments and translated entry; never read or write memory.

    If supplied, every physical segment must fit entirely in one usable range
    and must not intersect a reserved range. Ranges are caller-provided: this
    function does not discover or verify the hardware memory map.
    """
    usable = None if usable_ranges is None else _ranges(usable_ranges, 'usable')
    reserved = _ranges(reserved_ranges, 'reserved')
    if len(data) < ELF_HEADER.size:
        raise ValueError('truncated ELF header')
    (ident, typ, machine, version, entry, phoff, _, _, ehsize, phsize,
     phnum, _, _, _) = ELF_HEADER.unpack_from(data)
    if ident[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('expected little-endian ELF32 version 1')
    if typ != 2 or machine != 3 or version != 1:
        raise ValueError('expected an i386 ELF executable')
    if ehsize != ELF_HEADER.size or phsize != PROGRAM_HEADER.size or not phnum:
        raise ValueError('invalid ELF header or program header size')
    if phoff < ehsize or phoff + phnum * phsize > len(data) or phoff + phnum * phsize > LIMIT:
        raise ValueError('program header table outside file')

    segments = []
    entries = []
    for index in range(phnum):
        kind, offset, vaddr, paddr, filesz, memsz, flags, align = PROGRAM_HEADER.unpack_from(data, phoff + index * phsize)
        if kind != 1:
            continue
        if not memsz or filesz > memsz or offset + filesz > len(data) or offset + filesz > LIMIT:
            raise ValueError('invalid load segment file or memory size')
        if paddr + memsz > LIMIT or vaddr + memsz > LIMIT:
            raise ValueError('load segment address overflows 32 bits')
        if align not in (0, 1) and (align & (align - 1) or (vaddr - offset) % align):
            raise ValueError('invalid load segment alignment')
        end = paddr + memsz
        if usable is not None and not any(start <= paddr and end <= stop for start, stop in usable):
            raise ValueError('load segment outside caller-provided usable memory')
        if any(paddr < stop and start < end for start, stop in reserved):
            raise ValueError('load segment overlaps reserved memory')
        if any(paddr < prior['physical_address'] + prior['memory_size'] and
               prior['physical_address'] < end for prior in segments):
            raise ValueError('overlapping physical load segments')
        segment = {'file_offset': offset, 'virtual_address': vaddr,
                   'physical_address': paddr, 'file_size': filesz,
                   'memory_size': memsz, 'flags': flags, 'alignment': align}
        segments.append(segment)
        if vaddr <= entry < vaddr + memsz:
            entries.append(segment)
    if not segments:
        raise ValueError('no load segments')
    if len(entries) != 1:
        raise ValueError('entry must map to exactly one load segment')
    segment = entries[0]
    delta = entry - segment['virtual_address']
    if not segment['flags'] & 1 or delta >= segment['file_size']:
        raise ValueError('entry must be in executable file-backed bytes')
    return {'virtual_entry': entry, 'physical_entry': segment['physical_address'] + delta,
            'memory_checked': usable is not None, 'segments': segments}


def parse_range(value):
    try:
        start, end = value.split(':', 1)
        return int(start, 0), int(end, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError('range must be START:END with exclusive END') from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path, help='uncompressed ELF32 kernel')
    parser.add_argument('--usable', type=parse_range, action='append', help='usable physical range START:END (exclusive)')
    parser.add_argument('--reserve', type=parse_range, action='append', default=[], help='reserved physical range START:END (exclusive)')
    args = parser.parse_args()
    try:
        print(json.dumps(plan_elf(args.kernel.read_bytes(), args.usable, args.reserve), indent=2))
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f'cannot plan kernel: {error}\n')


if __name__ == '__main__':
    main()
