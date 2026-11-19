#!/usr/bin/env python3
"""Test hardware entry rejects missing owned-page EFI allocation coverage.

Requires a compiled candidate and the uncompressed 11.1 kernel. This executes
the actual Mach-O in synthetic memory, never physical hardware.
"""
import argparse
import pathlib
import struct
import sys

TARGET = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TARGET))
import run_emulated
from run_unicorn import Elf32, u32
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_CR0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'macho', 'kernel'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    native, kernel = Elf32(args.native), Elf32(args.kernel)
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0, 0x10000000)
    entry = run_emulated.load_macho(machine, args.macho)
    owned = native.symbol('projected_pages')
    apple = run_emulated.fixture(machine, None, owned)
    # Last synthetic entry normally marks the projection pages LoaderData.
    # Keep their conventional overlap, but remove allocation-type coverage.
    machine.mem_write(0x03020000 + 6 * 48, struct.pack('<I', 7))
    segments = [p for p in kernel.programs if p[0] == 1]
    writes = []
    for _, _, _, pa, _, size, _, _ in segments:
        machine.hook_add(UC_HOOK_MEM_WRITE,
                         lambda uc, access, address, length, value, data: writes.append((address, length)),
                         begin=pa, end=pa + size - 1)
    seen = []
    def code(uc, address, size, data):
        if address == native.symbol('target_emulated_failed'):
            seen.append('rejected')
            uc.emu_stop()
        elif address == kernel.symbol('start', physical=True):
            seen.append('kernel')
            uc.emu_stop()
    for addr in (native.symbol('target_emulated_failed'), kernel.symbol('start', physical=True)):
        machine.hook_add(UC_HOOK_CODE, code, begin=addr, end=addr)
    machine.reg_write(UC_X86_REG_CR0, 0x13)
    machine.reg_write(UC_X86_REG_EAX, apple)
    machine.emu_start(entry, 0x10000000, count=500000000)
    if seen != ['rejected'] or u32(machine, native.symbol('target_emulated_status')) != 0xbad or writes:
        raise AssertionError(f'expected fail-closed rejection, got {seen}, writes={writes[:3]}')
    print('PASS: missing projection-page LoaderData coverage rejects before kernel writes')


if __name__ == '__main__':
    main()
