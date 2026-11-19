#!/usr/bin/env python3
"""Prepare a NetBSD 11.1/i386 installer kernel for kexec-tools 2.0.1."""
import argparse
import hashlib
from pathlib import Path
import struct

from netbsd_elf import plan_elf


def physical_entry_image(data):
    plan = plan_elf(data)
    if (plan['virtual_entry'], plan['physical_entry']) != (0xC0100000, 0x00100000):
        raise ValueError('unexpected NetBSD installer entry mapping')
    # NetBSD 11.1 INSTALL has its Multiboot 1 header at .text + 12.
    # The ELF loading rules apply because flag bit 16 is clear.
    if data[0x100C:0x1018] != struct.pack('<III', 0x1BADB002, 2, 0xE4524FFC):
        raise ValueError('unexpected NetBSD installer Multiboot header')
    result = bytearray(data)
    # This kexec release jumps to e_entry with paging off while placing
    # each segment at p_paddr. Change only e_entry in the diagnostic copy.
    struct.pack_into('<I', result, 24, plan['physical_entry'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--sha256', required=True, help='expected input SHA-256')
    args = parser.parse_args()
    try:
        data = args.kernel.read_bytes()
        if hashlib.sha256(data).hexdigest() != args.sha256.lower():
            raise ValueError('kernel SHA-256 mismatch')
        result = physical_entry_image(data)
        with args.output.open('xb') as stream:
            stream.write(result)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f'Unable to prepare kernel: {error}\n')
    print(hashlib.sha256(result).hexdigest())


if __name__ == '__main__':
    main()
