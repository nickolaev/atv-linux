#!/usr/bin/env python3
"""Run a compiled ATV1 native handoff into a real NetBSD i386 kernel.

Requires Unicorn and two uncompressed ELF32 files. The test intentionally stops
when NetBSD's real native_loader returns; it does not claim a full OS boot.
"""
import argparse
import struct
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS,
                               UC_X86_REG_CR0, UC_X86_REG_CR3, UC_X86_REG_CS,
                               UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS)

EH = struct.Struct('<16sHHIIIIIHHHHHH')
PH = struct.Struct('<8I')
SH = struct.Struct('<10I')
SYM = struct.Struct('<IIIBBH')
MEMORY_END = 0x08000000
KERNBASE = 0xc0000000


class Elf32:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        if len(self.data) < EH.size:
            raise ValueError(f'{path}: truncated ELF')
        h = EH.unpack_from(self.data)
        if h[0][:7] != b'\x7fELF\x01\x01\x01' or h[1:3] != (2, 3):
            raise ValueError(f'{path}: expected i386 ELF32 executable')
        self.entry = h[4]
        self.programs = [PH.unpack_from(self.data, h[5]+i*h[9]) for i in range(h[10])]
        self.sections = [SH.unpack_from(self.data, h[6]+i*h[11]) for i in range(h[12])]
        self.symbols = {}
        for s in self.sections:
            if s[1] != 2 or s[9] != SYM.size:
                continue
            strings = self.sections[s[6]]
            names = self.data[strings[4]:strings[4]+strings[5]]
            for pos in range(s[4], s[4]+s[5], SYM.size):
                n, value, _, _, _, _ = SYM.unpack_from(self.data, pos)
                if n < len(names):
                    end = names.find(b'\0', n)
                    if end != -1:
                        self.symbols[names[n:end].decode('ascii', 'replace')] = value

    def load(self, machine):
        for kind, off, _, pa, size, memsz, _, _ in self.programs:
            if kind != 1:
                continue
            if size > memsz or off+size > len(self.data) or pa+memsz > MEMORY_END:
                raise ValueError('ELF segment outside emulated memory')
            machine.mem_write(pa, self.data[off:off+size])
            if memsz > size:
                machine.mem_write(pa+size, bytes(memsz-size))

    def symbol(self, name, physical=False):
        value = self.symbols[name]
        if physical:
            if value < KERNBASE:
                raise ValueError(f'{name} is not a high NetBSD kernel symbol')
            value -= KERNBASE
        return value


def u32(machine, address):
    return struct.unpack('<I', machine.mem_read(address, 4))[0]


def call(machine, address, args, return_to=0x00080000, require_return=True):
    stack = 0x0300f000
    frame = struct.pack('<' + 'I' * (len(args)+1), return_to, *args)
    machine.mem_write(stack, frame)
    machine.reg_write(UC_X86_REG_ESP, stack)
    machine.emu_start(address, return_to, count=500000000)
    if require_return and machine.reg_read(UC_X86_REG_EIP) != return_to:
        raise AssertionError('emulated call did not return before the instruction limit')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True, help='linked test-only native handoff ELF')
    parser.add_argument('--kernel', required=True, help='real, uncompressed NetBSD i386 INSTALL ELF')
    args = parser.parse_args()
    native, kernel = Elf32(args.native), Elf32(args.kernel)
    machine = Uc(UC_ARCH_X86, UC_MODE_32)
    machine.mem_map(0, MEMORY_END)
    native.load(machine)
    machine.reg_write(UC_X86_REG_CR0, 0x13)  # observed ATV1 state: PE on, paging off
    machine.reg_write(UC_X86_REG_CR3, 0)
    machine.reg_write(UC_X86_REG_EFLAGS, 0x602)  # DF and IF set; handoff must clear DF

    # The actual C planner and copier, not the Python loader, consume the
    # official ELF. Bounds are synthetic and establish no ATV1 memory safety.
    source_pa, plan_pa, usable_pa, reserved_pa = 0x05000000, 0x04020000, 0x04021000, 0x04022000
    if source_pa + len(kernel.data) > MEMORY_END:
        raise ValueError('kernel ELF too large for synthetic source region')
    machine.mem_write(source_pa, kernel.data)
    machine.mem_write(usable_pa, struct.pack('<QQ', 0x00100000, 0x02000000))
    machine.mem_write(reserved_pa, struct.pack('<QQ', 0x00100000, 0x00101000))
    machine.mem_write(0x00100000, b'\x5a' * 16)
    call(machine, native.symbol('nb_plan_elf'),
         [source_pa, len(kernel.data), source_pa, usable_pa, 1, reserved_pa, 1, plan_pa])
    if machine.reg_read(UC_X86_REG_EAX) != 0xffffffff or u32(machine, plan_pa+4) != 0:
        raise AssertionError('native planner did not reject a reserved-range collision')
    if bytes(machine.mem_read(0x00100000, 16)) != b'\x5a' * 16:
        raise AssertionError('rejected native plan modified kernel memory')
    # A partial semantic transcription of the photographed ATV1 map, not a
    # recovered raw snapshot. The large conventional descriptor overlaps the
    # three runtime descriptors; the physical addresses of test allocations
    # remain synthetic and do not establish their safety on real hardware.
    def descriptor(kind, base, pages, attributes):
        return struct.pack('<IIQQQQ', kind, 0, base, 0, pages, attributes) + bytes(8)
    runtime = (1 << 63) | 0xf
    raw_map = b''.join((
        descriptor(7, 0x000c0000, 0x1f40, 0xf),
        descriptor(2, 0x02000000, 0xb07, 0xf),
        descriptor(7, 0x02b07000, 0xb33c, 0xf),
        descriptor(5, 0x02b07000, 0x25, runtime),
        descriptor(6, 0x02b2c000, 0x2b, runtime),
        descriptor(6, 0x02b57000, 1, runtime),
    ))
    map_pa, info_pa, table_pa = 0x04011000, 0x04008000, 0x02b57f10
    apple_pa, input_pa, result_pa = 0x04026000, 0x04024000, 0x04025000
    machine.mem_write(map_pa, raw_map)
    apple = bytearray(0x44c)
    struct.pack_into('<IIII', apple, 0x404, map_pa, len(raw_map), 48, 1)
    struct.pack_into('<I', apple, 0x444, table_pa)
    apple[0x448] = 32
    machine.mem_write(apple_pa, bytes(apple))
    machine.mem_write(usable_pa, struct.pack('<QQQQ', 0x00100000, 0x02000000,
                                             0x02b58000, 0x08000000))
    machine.mem_write(reserved_pa, struct.pack('<QQ', 0x04050000, 0x04051000))
    # Every pointer in this i386 struct is deliberately an emulated physical
    # address. Ranges and objects are disjoint and fit inside the fake map.
    inputs = [apple_pa, len(apple), apple_pa, map_pa, len(raw_map), map_pa,
              source_pa, len(kernel.data), source_pa, info_pa, 16384, info_pa,
              0x02000000, 0, 0x02010000, 0,
              0x03004000, 0, 0x03008000, 0,
              usable_pa, 2, reserved_pa, 1,
              native.symbol('fixture_write'), native.symbol('fixture_zero'), 0]
    machine.mem_write(input_pa, struct.pack('<27I', *inputs))
    machine.mem_write(info_pa, b'\x9b' * 16)
    # A malformed EFI descriptor version must be rejected without writing
    # kernel/bootinfo memory before the successful integrated preparation.
    machine.mem_write(apple_pa + 0x410, struct.pack('<I', 2))
    call(machine, native.symbol('nb_prepare_native_emulation'), [input_pa, result_pa])
    if machine.reg_read(UC_X86_REG_EAX) != 0xffffffff:
        raise AssertionError('integrated preparation accepted unsupported EFI map version')
    if bytes(machine.mem_read(info_pa, 16)) != b'\x9b' * 16 or bytes(machine.mem_read(0x100000, 16)) != b'\x5a' * 16:
        raise AssertionError('rejected integrated preparation modified output memory')
    machine.mem_write(apple_pa + 0x410, struct.pack('<I', 1))
    segments = [p for p in kernel.programs if p[0] == 1]
    for _, off, _, pa, filesz, memsz, _, _ in segments:
        if memsz > filesz:
            machine.mem_write(pa + filesz, b'\xa5' * (memsz-filesz))
    call(machine, native.symbol('nb_prepare_native_emulation'), [input_pa, result_pa])
    if machine.reg_read(UC_X86_REG_EAX) != 0:
        raise AssertionError('integrated preparation rejected valid synthetic inputs')
    entry_plan, segment_count = struct.unpack('<II', machine.mem_read(result_pa, 8))
    result_info, result_size = struct.unpack('<II', machine.mem_read(result_pa + 264, 8))
    if (entry_plan, segment_count, result_info) != (
            kernel.symbol('start', physical=True), len(segments), info_pa):
        raise AssertionError('integrated preparation produced incorrect plan or bootinfo result')
    for _, off, _, pa, filesz, memsz, _, _ in segments:
        if bytes(machine.mem_read(pa, filesz)) != kernel.data[off:off+filesz]:
            raise AssertionError('native C copier produced incorrect segment bytes')
        if memsz > filesz and any(machine.mem_read(pa+filesz, memsz-filesz)):
            raise AssertionError('native C copier did not zero kernel BSS')

    count = u32(machine, info_pa)
    if count != 2:
        raise AssertionError(f'bootinfo pointer count is {count}, expected 2')
    efi_ptr, map_ptr = u32(machine, info_pa+4), u32(machine, info_pa+8)
    efi = bytes(machine.mem_read(efi_ptr, 32))
    info_map_len = u32(machine, map_ptr)
    info_map = bytes(machine.mem_read(map_ptr, info_map_len))
    if struct.unpack_from('<IIQI', efi) != (32, 14, table_pa, 1):
        raise AssertionError('serialized EFI identity mismatch')
    map_len, map_type, map_count = struct.unpack_from('<III', info_map)
    if map_type != 9 or map_len != 12 + 20 * map_count or result_size != 12 + len(efi) + map_len:
        raise AssertionError('normalized BTINFO_MEMMAP record has invalid layout')
    regions = [struct.unpack_from('<QQI', info_map, 12 + 20*i) for i in range(map_count)]
    previous_end = 0
    for base, size, kind in regions:
        if not size or base < previous_end or kind not in (1, 2, 3, 4):
            raise AssertionError(f'invalid normalized region {(base, size, kind)!r}')
        if kind == 1 and base < 0x02b58000 and base + size > 0x02b07000:
            raise AssertionError('runtime memory was exposed as usable RAM')
        previous_end = base + size
    if not any(kind == 2 and base <= 0x02b07000 and base + size >= 0x02b58000
               for base, size, kind in regions):
        raise AssertionError('photographed runtime span is not reserved')
    protected = ((0x02000000, 0x02010000), (0x03004000, 0x03008000),
                 (apple_pa, apple_pa + len(apple)), (map_pa, map_pa + len(raw_map)),
                 (source_pa, source_pa + len(kernel.data)), (info_pa, info_pa + 16384),
                 (table_pa & ~4095, (table_pa & ~4095) + 4096),
                 (0x04050000, 0x04051000))
    for base, size, kind in regions:
        if kind == 1 and any(base < end and start < base + size for start, end in protected):
            raise AssertionError('live allocation was exposed as usable RAM')
    for _, _, _, pa, _, memsz, _, _ in segments:
        if not any(kind == 1 and base <= pa and base + size >= pa + memsz
                   for base, size, kind in regions):
            raise AssertionError('kernel segment is not covered by normalized RAM')

    entry = kernel.symbol('start', physical=True)
    loader = kernel.symbol('native_loader', physical=True)
    start_code = bytes(machine.mem_read(entry, 512))
    call_returns = []
    for i in range(len(start_code)-5):
        if start_code[i] == 0xe8:
            rel = struct.unpack_from('<i', start_code, i+1)[0]
            if (entry+i+5+rel) & 0xffffffff == loader:
                call_returns.append(entry+i+5)
    if len(call_returns) != 1:
        raise AssertionError('could not uniquely locate kernel native_loader call')
    stop_at = call_returns[0]
    seen = []
    stack_top = 0x03008000
    stack_writes = []
    machine.mem_write(stack_top - 40, b'\xa5' * 4)
    def observe_write(uc, access, address, size, value, _):
        if stack_top - 128 <= address < stack_top:
            stack_writes.append((address, size))
    def observe(uc, address, size, _):
        if address == entry:
            if not stack_writes or min(addr for addr, _ in stack_writes) != stack_top - 36:
                raise AssertionError(f'expected 36-byte transient transfer stack, got {stack_writes!r}')
            if bytes(uc.mem_read(stack_top - 40, 4)) != b'\xa5' * 4:
                raise AssertionError('transfer wrote below the expected transient stack')
            esp = uc.reg_read(UC_X86_REG_ESP)
            words = struct.unpack('<7I', uc.mem_read(esp, 28))
            if words != (0, 0x42, 0, info_pa, 0, 0, 0):
                raise AssertionError(f'wrong native entry stack: {words!r}')
            if uc.reg_read(UC_X86_REG_EFLAGS) & 0x600:
                raise AssertionError('direction or interrupt flag remains set at kernel entry')
            if uc.reg_read(UC_X86_REG_CR0) & 0x80000000 or uc.reg_read(UC_X86_REG_EAX) in (0x2badb002, 0x36d76289):
                raise AssertionError('paging is enabled or kernel could select Multiboot')
            selectors = tuple(uc.reg_read(r) for r in (UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS))
            if selectors != (8, 16, 16, 16):
                raise AssertionError(f'wrong native entry segment selectors: {selectors!r}')
            seen.append('kernel entry')
        elif address == loader:
            seen.append('native_loader')
        elif address == stop_at:
            seen.append('native_loader return')
            uc.emu_stop()
    machine.hook_add(UC_HOOK_CODE, observe)
    machine.hook_add(UC_HOOK_MEM_WRITE, observe_write)
    # Nonzero legacy values must be suppressed by the assembly handoff so the
    # 11.1 kernel selects the supplied BTINFO_MEMMAP instead of the fallback.
    args_frame = [entry, stack_top, 0x42, info_pa, 0, 240000, 640]
    try:
        call(machine, native.symbol('nb_enter_native'), args_frame, require_return=False)
    except UcError as error:
        raise RuntimeError(f'Unicorn stopped before native_loader returned: {error}') from error
    if seen != ['kernel entry', 'native_loader', 'native_loader return']:
        raise AssertionError(f'unexpected kernel control flow: {seen!r}')
    if bytes(machine.mem_read(0x472, 2)) != b'\x34\x12':
        raise AssertionError('real kernel entry warm-boot marker not observed')
    bootinfo = kernel.symbol('bootinfo', physical=True)
    if u32(machine, bootinfo) != 2:
        raise AssertionError('real NetBSD native_loader did not retain two records')
    copied = bytes(machine.mem_read(bootinfo+4, len(efi)+len(info_map)))
    if copied != efi + info_map:
        raise AssertionError('real NetBSD native_loader copied different bootinfo records')
    for name, expected in (('boothowto', 0x42), ('biosextmem', 0), ('biosbasemem', 0)):
        actual = u32(machine, kernel.symbol(name, physical=True))
        if actual != expected:
            raise AssertionError(f'{name} is {actual:#x}, expected {expected:#x}')
    print('PASS: real NetBSD native_loader copied EFI identity and normalized overlapping memory map')
    print('LIMIT: semantic map fixture and synthetic allocations; not an ATV1 hardware boot')


if __name__ == '__main__':
    main()
