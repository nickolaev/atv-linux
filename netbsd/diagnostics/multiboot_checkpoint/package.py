#!/usr/bin/env python3
"""Add a physically linked Multiboot entry checkpoint to a NetBSD 11.1 ELF."""
import argparse
import hashlib
from pathlib import Path
import struct
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'macho'))
from netbsd_elf import ELF_HEADER, LIMIT, PROGRAM_HEADER, plan_elf


PAGE_SIZE = 0x1000
CHECKPOINT_ADDRESS = 0x01C00000
CHECKPOINT_LIMIT = 0x10000
NETBSD_ENTRY = 0x00100000
NETBSD_FILE_START = 0x1000
ELF_ENTRY_OFFSET = 24
ELF_PHNUM_OFFSET = 44
MULTIBOOT_HEADER_OFFSET = NETBSD_FILE_START + 12
MULTIBOOT_HEADER = struct.pack('<III', 0x1BADB002, 2, 0xE4524FFC)


def package(kernel, checkpoint, address):
    if address != CHECKPOINT_ADDRESS:
        raise ValueError(f'checkpoint must be linked at {CHECKPOINT_ADDRESS:#010x}')
    if not 0 < len(checkpoint) <= CHECKPOINT_LIMIT:
        raise ValueError('checkpoint must contain between 1 and 65536 bytes')
    if checkpoint.startswith(b'\x7fELF'):
        raise ValueError('checkpoint must be a flat binary')

    original_plan = plan_elf(kernel)
    if (original_plan['virtual_entry'], original_plan['physical_entry']) != (0xC0100000, NETBSD_ENTRY):
        raise ValueError('unexpected NetBSD installer entry mapping')
    if (kernel[MULTIBOOT_HEADER_OFFSET:MULTIBOOT_HEADER_OFFSET + len(MULTIBOOT_HEADER)]
            != MULTIBOOT_HEADER):
        raise ValueError('unexpected NetBSD installer Multiboot header')

    header = ELF_HEADER.unpack_from(kernel)
    phoff, phsize, phnum = header[5], header[9], header[10]
    slot = phoff + phsize * phnum
    if phoff != ELF_HEADER.size or phnum != 3 or slot + phsize > NETBSD_FILE_START:
        raise ValueError('unexpected NetBSD installer program header table')
    if any(kernel[slot:slot + phsize]):
        raise ValueError('new program header slot is occupied')
    for index in range(phnum):
        _, offset, _, _, filesz, _, _, _ = PROGRAM_HEADER.unpack_from(kernel, phoff + index * phsize)
        if filesz and offset < slot + phsize and offset + filesz > slot:
            raise ValueError('new program header slot overlaps existing segment data')

    checkpoint_offset = (len(kernel) + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)
    if checkpoint_offset + len(checkpoint) > LIMIT:
        raise ValueError('output exceeds 32-bit ELF offsets')
    result = bytearray(kernel)
    result.extend(bytes(checkpoint_offset - len(kernel)))
    result.extend(checkpoint)
    struct.pack_into('<I', result, ELF_ENTRY_OFFSET, address)
    struct.pack_into('<H', result, ELF_PHNUM_OFFSET, phnum + 1)
    # PT_LOAD, with read/write/execute flags for code, stack and DMA buffers.
    PROGRAM_HEADER.pack_into(result, slot, 1, checkpoint_offset, address, address,
                             len(checkpoint), len(checkpoint), 7, PAGE_SIZE)
    # Reuse the ELF validator to enforce physical load-range disjointness and
    # to verify that the new entry maps to its executable, file-backed bytes.
    plan_elf(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path, help='unmodified-entry NetBSD 11.1/i386 INSTALL ELF')
    parser.add_argument('checkpoint', type=Path, help='flat checkpoint linked at --address')
    parser.add_argument('output', type=Path)
    parser.add_argument('--sha256', required=True, help='expected input kernel SHA-256')
    parser.add_argument('--address', required=True, type=lambda value: int(value, 0),
                        help=f'physical checkpoint entry point ({CHECKPOINT_ADDRESS:#010x})')
    args = parser.parse_args()
    try:
        kernel = args.kernel.read_bytes()
        if hashlib.sha256(kernel).hexdigest() != args.sha256.lower():
            raise ValueError('input kernel SHA-256 mismatch')
        result = package(kernel, args.checkpoint.read_bytes(), args.address)
        with args.output.open('xb') as stream:
            stream.write(result)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f'Unable to package checkpoint: {error}\n')
    print(hashlib.sha256(result).hexdigest())


if __name__ == '__main__':
    main()
