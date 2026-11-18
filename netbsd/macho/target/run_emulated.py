#!/usr/bin/env python3
"""Execute the emulator-only target pipeline; never run on Apple hardware."""
import argparse
import hashlib
import pathlib
import struct
import sys
import uuid
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'native_tests'))
from run_macho_unicorn import load_macho, descriptor
from run_unicorn import Elf32, MEMORY_END, u32
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_CR0


def fixture(machine, bad, owned):
    runtime = (1 << 63) | 15
    raw = b''.join((descriptor(7, 0xc0000, 0x1f40, 15),
                    descriptor(2, 0x2000000, 0xb07, 15),
                    descriptor(7, 0x2b07000, 0xb33c, 15),
                    descriptor(5, 0x2b07000, 0x25, runtime),
                    descriptor(6, 0x2b2c000, 0x2b, runtime),
                    descriptor(6, 0x2b57000, 1, runtime),
                    descriptor(2, owned, 2, 15)))
    map_pa, apple_pa = 0x03020000, 0x03022000
    machine.mem_write(map_pa, raw)
    apple = bytearray(0x44c)
    struct.pack_into('<IIII', apple, 0x404, map_pa, len(raw), 48, 1)
    struct.pack_into('<I', apple, 0x444, 0x2b57f10)
    apple[0x448] = 32
    machine.mem_write(apple_pa, bytes(apple))
    table = bytearray(72)
    table[:8] = b'IBI SYST'
    struct.pack_into('<I', table, 12, 72)
    struct.pack_into('<II', table, 64, 9, 0x2b56d90)
    struct.pack_into('<I', table, 16, zlib.crc32(table))
    machine.mem_write(0x2b57f10, bytes(table))
    # Same nine GUIDs as the photographed Linux-time table. Pointers and all
    # pointed-to bytes are synthetic; dropped GUIDs use unmapped addresses
    # so an accidental dereference fails the test.
    entries = [
        ('05ad34ba-6f02-4214-952e-4da0398e2bb9', 0xf0000000),
        ('7739f24c-93d7-11d4-9a3a-0090273fc14d', 0xf0001000),
        ('4c19049f-4137-4dd3-9c10-8b97a83ffdfa', 0xf0002000),
        ('49152e77-1ada-4764-b7a2-7afefed95e8b', 0xf0003000),
        ('5751da6e-1376-4e02-ba92-d294fdd30901', 0xf0004000),
        ('f76761dc-ff89-44e4-9c0c-cd0ada4ef983', 0xf0005000),
        ('eb9d2d30-2d88-11d3-9a16-0090273fc14d', 0x2b50000),
        ('8868e871-e4f1-11d3-bc22-0080c73c8881', 0x2b50020),
        ('eb9d2d31-2d88-11d3-9a16-0090273fc14d', 0x2b54000),
    ]
    if bad == 'smbios3':
        entries[0] = ('f2fd1544-9794-4a2c-992e-e5bbcf20e394', 0xf0000000)
    config = b''.join(uuid.UUID(guid).bytes_le + struct.pack('<I', address)
                      for guid, address in entries)
    machine.mem_write(0x2b56d90, bytes(config))
    root = bytearray(40)
    root[:4] = b'RSDT'
    struct.pack_into('<I', root, 4, len(root))
    struct.pack_into('<I', root, 36, 0x2b52000)
    root[9] = -sum(root) & 255
    machine.mem_write(0x2b51000, bytes(root))
    xsdt = bytearray(44)
    xsdt[:4] = b'XSDT'
    struct.pack_into('<I', xsdt, 4, len(xsdt))
    struct.pack_into('<Q', xsdt, 36, 0x2b52000)
    xsdt[9] = -sum(xsdt) & 255
    machine.mem_write(0x2b51200, bytes(xsdt))
    fadt = bytearray(116)
    fadt[:4] = b'FACP'
    struct.pack_into('<I', fadt, 4, len(fadt))
    struct.pack_into('<I', fadt, 40, 0x2b53000)
    fadt[9] = -sum(fadt) & 255
    machine.mem_write(0x2b52000, bytes(fadt))
    dsdt = bytearray(36)
    dsdt[:4] = b'DSDT'
    struct.pack_into('<I', dsdt, 4, len(dsdt))
    dsdt[9] = -sum(dsdt) & 255
    if bad == 'acpi':
        dsdt[9] ^= 1
    machine.mem_write(0x2b53000, bytes(dsdt))
    rsdp = bytearray(20)
    rsdp[:8] = b'RSD PTR '
    struct.pack_into('<I', rsdp, 16, 0x2b51000)
    rsdp[8] = -sum(rsdp) & 255
    machine.mem_write(0x2b50000, bytes(rsdp))
    rsdp2 = bytearray(36)
    rsdp2[:8] = b'RSD PTR '
    rsdp2[15] = 2
    struct.pack_into('<I', rsdp2, 16, 0x2b51000)
    rsdp2[8] = -sum(rsdp2[:20]) & 255
    struct.pack_into('<IQ', rsdp2, 20, 36, 0x2b51200)
    rsdp2[32] = -sum(rsdp2) & 255
    machine.mem_write(0x2b50020, bytes(rsdp2))
    records = b'\x01\x04\x00\x00board\x00\x00\x7f\x04\xff\xff\x00\x00'
    machine.mem_write(0x2b55000, records)
    smbios = bytearray(31)
    smbios[:4] = b'_SM_'
    smbios[5:8] = bytes((31, 2, 6))
    smbios[16:21] = b'_DMI_'
    struct.pack_into('<HIHB', smbios, 22, len(records), 0x2b55000, 2, 0x26)
    smbios[21] = -sum(smbios[16:31]) & 255
    smbios[4] = -sum(smbios) & 255
    if bad == 'smbios':
        smbios[4] ^= 1
    machine.mem_write(0x2b54000, bytes(smbios))
    return apple_pa


def run(native, kernel, macho, bad):
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0, MEMORY_END)
    entry = load_macho(machine, macho)
    a, b = native.symbol('kernel_start'), native.symbol('kernel_end')
    if hashlib.sha256(bytes(machine.mem_read(a, b - a))).digest() != hashlib.sha256(kernel.data).digest():
        raise AssertionError('Mach-O payload differs from kernel')
    owned = native.symbol('projected_pages')
    if owned & 4095:
        raise AssertionError('owned EFI pages not aligned')
    apple = fixture(machine, bad, owned)
    segments = [p for p in kernel.programs if p[0] == 1]
    if bad:
        for _, _, _, pa, _, size, _, _ in segments:
            machine.mem_write(pa, b'\x5a' * size)
    machine.reg_write(UC_X86_REG_CR0, 0x13)
    machine.reg_write(UC_X86_REG_EAX, apple)
    kernel_entry = kernel.symbol('start', physical=True)
    native_loader = kernel.symbol('native_loader', physical=True)
    segment = next(p for p in kernel.programs if p[0] == 1 and p[3] <= kernel_entry < p[3] + p[4])
    code = kernel.data[segment[1] + kernel_entry - segment[3]:][:512]
    returns = [kernel_entry + i + 5 for i in range(len(code) - 5)
               if code[i] == 0xe8 and
               (kernel_entry + i + 5 + struct.unpack_from('<i', code, i + 1)[0]) & 0xffffffff == native_loader]
    if len(returns) != 1:
        raise AssertionError('cannot find unique native_loader return site')
    seen = []
    started = [False]
    owned_writes = []
    def observe(uc, address, size, data):
        if address == native.symbol('target_emulated_start'):
            started[0] = True
        elif address == native.symbol('target_emulated_failed'):
            seen.append('rejected'); uc.emu_stop()
        elif address == native.symbol('nb_prepare_native_emulation'):
            seen.append('prepare')
        elif address == kernel_entry:
            seen.append('kernel')
        elif address == native_loader:
            seen.append('native_loader')
        elif address == returns[0]:
            seen.append('returned'); uc.emu_stop()
    def memory_write(uc, access, address, size, value, data):
        if started[0] and address < owned + 8192 and owned < address + size:
            owned_writes.append((address, size))
    machine.hook_add(UC_HOOK_MEM_WRITE, memory_write, begin=owned, end=owned + 8191)
    for address in (native.symbol('target_emulated_start'), native.symbol('target_emulated_failed'),
                    native.symbol('nb_prepare_native_emulation'),
                    kernel_entry, native_loader, returns[0]):
        machine.hook_add(UC_HOOK_CODE, observe, begin=address, end=address)
    machine.emu_start(entry, MEMORY_END, count=500000000)
    if bad:
        if seen != ['rejected'] or u32(machine, native.symbol('target_emulated_status')) != 0xbad:
            raise AssertionError(f'invalid firmware not rejected: {seen}')
        if owned_writes:
            raise AssertionError('rejected projection modified owned EFI pages')
        for _, _, _, pa, _, size, _, _ in segments:
            if bytes(machine.mem_read(pa, size)) != b'\x5a' * size:
                raise AssertionError('rejection modified kernel destination')
    elif seen != ['prepare', 'kernel', 'native_loader', 'returned'] or u32(machine, native.symbol('target_emulated_status')) != 0x600d:
        raise AssertionError(f'failed to reach native_loader: {seen}')
    else:
        if not owned_writes:
            raise AssertionError('valid projection did not write owned EFI pages')
        projected = u32(machine, native.symbol('target_emulated_projected'))
        info = u32(machine, native.symbol('target_emulated_bootinfo'))
        if projected != owned or u32(machine, projected + 64) != 3 or u32(machine, projected + 68) != owned + 4096:
            raise AssertionError('incorrect projected table or configuration count')
        header = bytearray(machine.mem_read(owned, 72))
        crc = struct.unpack_from('<I', header, 16)[0]
        struct.pack_into('<I', header, 16, 0)
        if zlib.crc32(header) != crc:
            raise AssertionError('projected system table CRC is invalid')
        projected_config = bytes(machine.mem_read(owned + 4096, 60))
        guids = [str(uuid.UUID(bytes_le=projected_config[i:i+16])) for i in (0, 20, 40)]
        if guids != ['eb9d2d30-2d88-11d3-9a16-0090273fc14d',
                     '8868e871-e4f1-11d3-bc22-0080c73c8881',
                     'eb9d2d31-2d88-11d3-9a16-0090273fc14d']:
            raise AssertionError(f'unexpected projected configuration {guids}')
        if u32(machine, info) != 2:
            raise AssertionError('expected EFI and native memory-map bootinfo')
        efi, mmap = u32(machine, info + 4), u32(machine, info + 8)
        if u32(machine, efi + 4) != 14 or u32(machine, efi + 8) != owned:
            raise AssertionError('kernel bootinfo does not point to owned EFI table')
        if u32(machine, mmap + 4) != 9:
            raise AssertionError('native normalized map missing')
        kernel_bootinfo = kernel.symbol('bootinfo', physical=True)
        efi_len, map_len = u32(machine, efi), u32(machine, mmap)
        copied = bytes(machine.mem_read(kernel_bootinfo + 4, efi_len + map_len))
        expected = bytes(machine.mem_read(efi, efi_len)) + bytes(machine.mem_read(mmap, map_len))
        if u32(machine, kernel_bootinfo) != 2 or copied != expected:
            raise AssertionError('kernel native_loader copied different EFI/map records')
        regions = [struct.unpack('<QQI', machine.mem_read(mmap + 12 + 20*i, 20))
                   for i in range(u32(machine, mmap + 8))]
        protected = [(0x2b2c000, 0x2b58000), (owned, owned + 8192),
                     (0x03020000, 0x03020000 + 7*48), (apple, apple + 0x44c),
                     (native.symbol('__image_start'), native.symbol('__image_end'))]
        for base, length, kind in regions:
            if kind == 1 and any(base < end and start < base + length for start, end in protected):
                raise AssertionError('normalized map exposes protected object as RAM')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'kernel', 'macho'):
        p.add_argument('--' + name, required=True)
    args = p.parse_args()
    native, kernel = Elf32(args.native), Elf32(args.kernel)
    for bad in ('smbios', 'acpi', 'smbios3'):
        run(native, kernel, args.macho, bad)
    run(native, kernel, args.macho, None)
    print('PASS: emulated target entry projects nine GUIDs, rejects invalid targets and reaches NetBSD native_loader')
    print('LIMIT: synthetic tables, trusted-read callback and test-only physical layout; not hardware safe')


if __name__ == '__main__':
    main()
