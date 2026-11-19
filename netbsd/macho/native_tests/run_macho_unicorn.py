#!/usr/bin/env python3
"""Emulate a TEST-ONLY Mach-O entry and embedded 11.1 kernel, not firmware."""
import argparse
import hashlib
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_CR0
from run_unicorn import Elf32, MEMORY_END, u32


def load_macho(machine, path):
    data = Path(path).read_bytes()
    magic, cpu, _, kind, ncmds, size, _ = struct.unpack_from('<7I', data)
    if (magic, cpu, kind) != (0xfeedface, 7, 2) or 28 + size > len(data):
        raise ValueError('not a complete i386 Mach-O executable')
    offset, entry, loaded = 28, None, False
    for _ in range(ncmds):
        command, length = struct.unpack_from('<II', data, offset)
        if length < 8 or offset + length > 28 + size:
            raise ValueError('invalid Mach-O load command')
        if command == 1 and data[offset+8:offset+24].rstrip(b'\0') == b'__TEXT':
            _, vm, vmsize, fileoff, filesize = struct.unpack_from('<16s4I', data, offset+8)
            if vm + vmsize > MEMORY_END or fileoff + filesize > len(data) or filesize > vmsize:
                raise ValueError('Mach-O segment outside fixture memory')
            machine.mem_write(vm, data[fileoff:fileoff+filesize])
            machine.mem_write(vm+filesize, bytes(vmsize-filesize))
            loaded = True
        if command == 5:
            entry = struct.unpack_from('<I', data, offset + 16 + 10*4)[0]
        offset += length
    if offset != 28 + size or not loaded or entry is None:
        raise ValueError('missing segment or thread entry')
    return entry


def descriptor(kind, base, pages, attrs):
    return struct.pack('<IIQQQQ', kind, 0, base, 0, pages, attrs) + bytes(8)


def exercise(native, kernel, macho, malformed=False):
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0, MEMORY_END)
    entry = load_macho(machine, macho)
    if entry != native.entry:
        raise AssertionError('Mach-O thread entry does not match linked entry')
    source = native.symbol('kernel_start')
    end = native.symbol('kernel_end')
    embedded = bytes(machine.mem_read(source, end-source))
    if hashlib.sha256(embedded).digest() != hashlib.sha256(kernel.data).digest():
        raise AssertionError('packaged kernel differs from the supplied ELF')
    bss_start, bss_end = native.symbol('__bss_start'), native.symbol('__bss_end')
    machine.mem_write(bss_start, b'\xa5' * (bss_end-bss_start))
    runtime = (1 << 63) | 0xf
    memory_map = b''.join((descriptor(7, 0xc0000, 0x1f40, 0xf),
                           descriptor(2, 0x2000000, 0xb07, 0xf),
                           descriptor(7, 0x2b07000, 0xb33c, 0xf),
                           descriptor(5, 0x2b07000, 0x25, runtime),
                           descriptor(6, 0x2b2c000, 0x2b, runtime),
                           descriptor(6, 0x2b57000, 1, runtime)))
    map_pa, apple_pa, info_pa = 0x03020000, 0x03022000, 0x03010000
    machine.mem_write(map_pa, memory_map)
    apple = bytearray(0x44c)
    struct.pack_into('<IIII', apple, 0x404, map_pa, len(memory_map), 48, 2 if malformed else 1)
    struct.pack_into('<I', apple, 0x444, 0x02b57f10)
    apple[0x448] = 32
    machine.mem_write(apple_pa, bytes(apple))
    segments = [p for p in kernel.programs if p[0] == 1]
    if malformed:
        for _, _, _, pa, _, memsz, _, _ in segments:
            machine.mem_write(pa, b'\x5a' * memsz)
        machine.mem_write(info_pa, b'\x9b' * 16384)
    machine.reg_write(UC_X86_REG_CR0, 0x13)
    machine.reg_write(UC_X86_REG_EAX, apple_pa)
    machine.reg_write(UC_X86_REG_ESP, 0x03030000)
    kernel_entry = kernel.symbol('start', physical=True)
    loader = kernel.symbol('native_loader', physical=True)
    # Find the call's return site from the unmodified kernel bytes.
    segment = next(p for p in kernel.programs if p[0] == 1 and p[3] <= kernel_entry < p[3]+p[4])
    code = kernel.data[segment[1]+kernel_entry-segment[3]:][:512]
    returns = [kernel_entry+i+5 for i in range(len(code)-5)
               if code[i] == 0xe8 and
               (kernel_entry+i+5+struct.unpack_from('<i', code, i+1)[0]) & 0xffffffff == loader]
    if len(returns) != 1:
        raise AssertionError('cannot find unique native_loader call')
    seen = []
    def observe(uc, address, size, _):
        if address == native.symbol('fixture_start'):
            if any(uc.mem_read(bss_start, bss_end-bss_start)):
                raise AssertionError('Mach-O entry failed to clear BSS')
            if not 0x03004000 <= uc.reg_read(UC_X86_REG_ESP) < 0x03008000:
                raise AssertionError('Mach-O entry did not install its synthetic stack')
        elif address == native.symbol('fixture_failed'):
            seen.append('rejected')
            uc.emu_stop()
        elif address == kernel_entry:
            seen.append('kernel')
        elif address == loader:
            seen.append('native_loader')
        elif address == returns[0]:
            seen.append('returned')
            uc.emu_stop()
    for address in (native.symbol('fixture_start'), native.symbol('fixture_failed'), kernel_entry, loader, returns[0]):
        machine.hook_add(UC_HOOK_CODE, observe, begin=address, end=address)
    machine.emu_start(entry, MEMORY_END, count=500000000)
    if malformed:
        if seen != ['rejected'] or u32(machine, native.symbol('fixture_status')) != 0xbad:
            raise AssertionError(f'malformed map not rejected: {seen!r}')
        for _, _, _, pa, _, memsz, _, _ in segments:
            if bytes(machine.mem_read(pa, memsz)) != b'\x5a' * memsz:
                raise AssertionError('rejected entry modified kernel destination')
        if bytes(machine.mem_read(info_pa, 16384)) != b'\x9b' * 16384:
            raise AssertionError('rejected entry modified bootinfo destination')
        return
    if seen != ['kernel', 'native_loader', 'returned']:
        raise AssertionError(f'unexpected Mach-O entry control flow: {seen!r}')
    if u32(machine, native.symbol('fixture_status')) != 0x600d:
        raise AssertionError('fixture did not complete native preparation')
    bootinfo = kernel.symbol('bootinfo', physical=True)
    if u32(machine, bootinfo) != 2 or u32(machine, bootinfo+8) != 14:
        raise AssertionError('real kernel did not copy expected EFI bootinfo')
    efi_length = u32(machine, bootinfo+4)
    if u32(machine, bootinfo+4+efi_length+4) != 9:
        raise AssertionError('real kernel did not copy normalized memory map')
    efi_ptr, map_ptr = u32(machine, info_pa+4), u32(machine, info_pa+8)
    map_len = u32(machine, map_ptr)
    expected = bytes(machine.mem_read(efi_ptr, efi_length)) + bytes(machine.mem_read(map_ptr, map_len))
    if bytes(machine.mem_read(bootinfo+4, len(expected))) != expected:
        raise AssertionError('real kernel copied different bootinfo bytes')
    count = u32(machine, map_ptr+8)
    regions = [struct.unpack('<QQI', machine.mem_read(map_ptr+12+20*i, 20)) for i in range(count)]
    if not any(kind == 2 and start <= 0x02b07000 and start+length >= 0x02b58000
               for start, length, kind in regions):
        raise AssertionError('overlapping runtime region is not reserved')
    for name in ('biosextmem', 'biosbasemem'):
        if u32(machine, kernel.symbol(name, physical=True)):
            raise AssertionError('nonzero legacy memory fallback')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True)
    parser.add_argument('--kernel', required=True)
    parser.add_argument('--macho', required=True)
    args = parser.parse_args()
    native, kernel = Elf32(args.native), Elf32(args.kernel)
    exercise(native, kernel, args.macho, malformed=True)
    exercise(native, kernel, args.macho)
    print('PASS: packaged Mach-O entry rejected malformed map and entered real NetBSD 11.1 native_loader')
    print('LIMIT: synthetic firmware/map and fixed test addresses; not Apple firmware or a complete boot')


if __name__ == '__main__':
    main()
