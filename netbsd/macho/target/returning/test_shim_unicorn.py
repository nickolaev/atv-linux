#!/usr/bin/env python3
"""Instruction-level tests for the returning low hook (optional Unicorn)."""
import os
import struct
import sys
import unittest
from pathlib import Path

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
        UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP,
        UC_X86_REG_ESP, UC_X86_REG_EFLAGS, UC_X86_REG_CR0, UC_X86_REG_CS,
        UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS, UC_X86_REG_GDTR,
        UC_X86_REG_IDTR)
except ImportError:
    Uc = None

SHIM = os.environ.get('RETURNING_SHIM_ELF')
COMBINED = os.environ.get('RETURNING_COMBINED_MACHO')
HIGH_ELF = os.environ.get('ATV_DIAG_ELF')
KERNEL = os.environ.get('ATV_DIAG_KERNEL')
BASE, HIGH, HIGH_END = 0x02000600, 0x04000000, 0x04020000
STATUS, ARGS, MAP, SYSTEM, CONFIG = 0x02200000, 0x03000000, 0x03100000, 0x03200000, 0x03201000
GDT, IDT, STACK = 0x03300000, 0x03301000, 0x03310800


def segment(elf):
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', elf)
    if h[0][:7] != b'\x7fELF\x01\x01\x01' or h[4] != BASE or h[9] != 32:
        raise ValueError('unexpected linked low-shim ELF')
    loads = [struct.unpack_from('<8I', elf, h[5] + i * h[9]) for i in range(h[10])]
    loads = [p for p in loads if p[0] == 1]
    if len(loads) != 1 or loads[0][2] != BASE:
        raise ValueError('expected one load segment at hook address')
    _, off, _, _, filesz, memsz, _, _ = loads[0]
    if filesz != memsz or off + filesz > len(elf):
        raise ValueError('invalid shim segment')
    code = bytearray(elf[off:off + filesz])
    for marker, value in ((0xfeedc0de, STATUS), (0xfeedface, HIGH),
                          (0xfeedbeef, HIGH_END), (0xfeedbabe, HIGH)):
        raw = struct.pack('<I', marker)
        if code.count(raw) != 1:
            raise ValueError('missing or ambiguous patch sentinel')
        code[code.index(raw):code.index(raw) + 4] = struct.pack('<I', value)
    return bytes(code)


def descriptor(kind, base, pages, attrs=0):
    return struct.pack('<IIQQQQ', kind, 0, base, 0, pages, attrs) + bytes(8)


@unittest.skipUnless(Uc is not None and SHIM, 'set RETURNING_SHIM_ELF and install Unicorn')
class ReturningShimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = segment(Path(SHIM).read_bytes())

    def run_case(self, case):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x08000000)
        u.mem_write(BASE, self.code)
        # Tiny synthetic returning high bridge marks that it was reached.
        u.mem_write(HIGH, bytes.fromhex('c7420478563412c3'))
        u.mem_write(STATUS, b'\xa5' * 48)
        table = bytearray(128)
        table[:8] = b'IBI SYST'
        struct.pack_into('<II', table, 64, 1, HIGH + 0x1800 if case == 'config_array_alias' else CONFIG)
        u.mem_write(SYSTEM, bytes(table))
        entry = bytearray(20)
        struct.pack_into('<I', entry, 16, HIGH + 0x1000 if case == 'config_pointer_alias' else 0x03202000)
        u.mem_write(CONFIG, bytes(entry))
        high_type = 6 if case == 'unsafe_high_type' else 2
        high_attrs = (1 << 63) if case == 'runtime_high' else 0
        desc = descriptor(high_type, HIGH, 0x20, high_attrs) + descriptor(6, SYSTEM, 0x10)
        u.mem_write(MAP, desc)
        boot = bytearray(0x44c)
        map_pa = STATUS if case == 'map_alias' else MAP
        system_pa = STATUS if case == 'system_alias' else SYSTEM
        struct.pack_into('<IIII', boot, 0x404, map_pa, len(desc), 48, 1)
        struct.pack_into('<I', boot, 0x444, system_pa)
        args_pa = HIGH + 0x2000 if case == 'args_alias' else ARGS
        u.mem_write(args_pa, bytes(boot))
        if case == 'map_alias':
            u.mem_write(STATUS, desc[:48])
        # Guest descriptor caches are loaded before a rejected GDT is mutated.
        gdt = bytes(16) + bytes.fromhex('ffff0000009acf00ffff00000092cf00')
        gdt_pa = HIGH + 0x3000 if case == 'gdt_alias' else GDT
        idt_pa = HIGH + 0x4000 if case == 'idt_alias' else IDT
        u.mem_write(gdt_pa, gdt)
        u.reg_write(UC_X86_REG_GDTR, (0, gdt_pa, len(gdt) - 1, 0))
        u.reg_write(UC_X86_REG_IDTR, (0, idt_pa, 0x7ff, 0))
        u.reg_write(UC_X86_REG_CR0, 0x13)
        for reg, value in ((UC_X86_REG_CS, 0x10), (UC_X86_REG_DS, 0x18),
                           (UC_X86_REG_ES, 0x18), (UC_X86_REG_SS, 0x18)):
            u.reg_write(reg, value)
        if case == 'nonflat_code':
            u.mem_write(GDT + 0x12, b'\x01\x00')
        elif case == 'nonflat_data':
            u.mem_write(GDT + 0x1a, b'\x01\x00')
        regs = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
                UC_X86_REG_EFLAGS)
        values = (args_pa, 0x22334455, 0x33445566, 0x44556677, 0x55667788,
                  0x66778899, 0x778899aa, HIGH + 0x100 if case == 'stack_alias' else STACK, 0x402)
        for reg, value in zip(regs, values):
            u.reg_write(reg, value)
        before_regs = [u.reg_read(reg) for reg in regs]
        before_status = bytes(u.mem_read(STATUS, 48))
        called, bad_writes = [], []
        u.hook_add(UC_HOOK_CODE, lambda _u, address, _size, _data: called.append(address) if address == HIGH else None)
        def check_write(_u, _access, address, size, _value, _data):
            if address < 0x01600000 and address + size > 0x00100000:
                bad_writes.append((address, size))
        u.hook_add(UC_HOOK_MEM_WRITE, check_write)
        u.emu_start(BASE, 0x02001010, count=200000)
        self.assertEqual([u.reg_read(reg) for reg in regs], before_regs)
        self.assertEqual(bad_writes, [], 'dry-run hook wrote a kernel destination')
        after = bytes(u.mem_read(STATUS, 48))
        if case == 'valid':
            self.assertEqual(called, [HIGH])
            self.assertEqual(after[:8], b'LOW1\x78\x56\x34\x12')
        else:
            self.assertEqual(called, [], f'{case} reached the high bridge')
            self.assertEqual(after, before_status, f'{case} modified status before it was safe')

    def test_valid_entry_returns_with_cpu_state_restored(self):
        self.run_case('valid')

    def test_nonflat_code_and_data_descriptors_are_rejected(self):
        for case in ('nonflat_code', 'nonflat_data'):
            with self.subTest(case=case): self.run_case(case)

    def test_unowned_or_runtime_high_segment_is_rejected(self):
        for case in ('unsafe_high_type', 'runtime_high'):
            with self.subTest(case=case): self.run_case(case)

    def test_source_and_stack_aliases_are_rejected(self):
        for case in ('args_alias', 'map_alias', 'system_alias', 'config_array_alias',
                     'config_pointer_alias', 'stack_alias', 'gdt_alias', 'idt_alias'):
            with self.subTest(case=case): self.run_case(case)


@unittest.skipUnless(Uc is not None and COMBINED and HIGH_ELF and KERNEL,
                     'set RETURNING_COMBINED_MACHO, ATV_DIAG_ELF and ATV_DIAG_KERNEL')
class CombinedReturningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(target))
        sys.path.insert(0, str(target.parent / 'native_tests'))
        import run_emulated
        from run_unicorn import Elf32
        cls.make_firmware = staticmethod(run_emulated.fixture)
        cls.high = Elf32(HIGH_ELF)
        cls.kernel = Elf32(KERNEL)
        cls.blob = Path(COMBINED).read_bytes()

    def load_all_segments(self, u):
        blob = self.blob
        magic, cpu, _, typ, count, cmdbytes, _ = struct.unpack_from('<7I', blob)
        self.assertEqual((magic, cpu, typ), (0xfeedface, 7, 2))
        pos, end, ranges, names = 28, 28 + cmdbytes, [], []
        for _ in range(count):
            cmd, size = struct.unpack_from('<II', blob, pos)
            self.assertGreaterEqual(size, 8)
            self.assertLessEqual(pos + size, end)
            if cmd == 1:
                name = blob[pos + 8:pos + 24].split(b'\0', 1)[0]
                va, memsz, off, filesz = struct.unpack_from('<4I', blob, pos + 24)
                if memsz and name != b'__PAGEZERO':
                    self.assertLessEqual(filesz, memsz)
                    self.assertLessEqual(off + filesz, len(blob))
                    self.assertLessEqual(va + memsz, 0x10000000)
                    self.assertFalse(any(va < b and a < va + memsz for a, b in ranges))
                    ranges.append((va, va + memsz))
                    names.append(name)
                    u.mem_write(va, blob[off:off + filesz])
                    if memsz > filesz:
                        u.mem_write(va + filesz, bytes(memsz - filesz))
            pos += size
        self.assertEqual(pos, end)
        self.assertIn(b'__ATVDIAG', names)
        # Locate the appended newc status file and verify its actual bounds.
        name = b'atv-loader-diag.bin\0'
        nameoff = blob.index(name)
        self.assertEqual(blob[nameoff - 110:nameoff - 104], b'070701')
        record_size = int(blob[nameoff - 110 + 54:nameoff - 110 + 62], 16)
        self.assertEqual(record_size, 48)
        data_off = (nameoff + len(name) + 3) & ~3
        self.assertEqual(blob[data_off:data_off + 48], bytes(48))
        high = next((a, b) for (a, b), n in zip(ranges, names) if n == b'__ATVDIAG')
        return 0x02000000 + data_off, high

    def test_combined_hook_returns_for_valid_and_rejected_firmware(self):
        for case, stage, error in ((None, 9, 0), ('acpi', 5, 5), ('smbios', 5, 5),
                                   ('low_no_allocation', None, None),
                                   ('low_config_alias', None, None)):
            with self.subTest(case=case):
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(0, 0x10000000)
                status, high = self.load_all_segments(u)
                apple = self.make_firmware(u, case, self.high.symbol('projected_pages'))
                # Model a current-boot type-2 allocation for the entire
                # high segment. This is synthetic, not an ATV1 observation.
                map_pa, map_len = struct.unpack('<II', u.mem_read(apple + 0x404, 8))
                extra = descriptor(2, high[0], (high[1] - high[0]) // 4096, 15)
                if case != 'low_no_allocation':
                    u.mem_write(map_pa + map_len, extra)
                    u.mem_write(apple + 0x408, struct.pack('<I', map_len + len(extra)))
                if case == 'low_config_alias':
                    u.mem_write(0x2b56d90 + 16, struct.pack('<I', high[0] + 0x1000))
                gdt_pa, idt_pa, stack = 0x03103000, 0x03104000, 0x0300f000
                gdt = bytes(16) + bytes.fromhex('ffff0000009acf00ffff00000092cf00')
                u.mem_write(gdt_pa, gdt)
                u.reg_write(UC_X86_REG_GDTR, (0, gdt_pa, len(gdt) - 1, 0))
                u.reg_write(UC_X86_REG_IDTR, (0, idt_pa, 0x7ff, 0))
                u.reg_write(UC_X86_REG_CR0, 0x13)
                for reg, value in ((UC_X86_REG_CS, 0x10), (UC_X86_REG_DS, 0x18),
                                   (UC_X86_REG_ES, 0x18), (UC_X86_REG_SS, 0x18)):
                    u.reg_write(reg, value)
                regs = (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
                        UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP,
                        UC_X86_REG_ESP, UC_X86_REG_EFLAGS)
                for reg, value in zip(regs, (apple, 0x12340018, 0x33, 0x44, 0x55,
                                             0x66, apple, stack, 0x402)):
                    u.reg_write(reg, value)
                initial = [u.reg_read(reg) for reg in regs]
                writes = []
                def check_write(_u, _access, address, size, _value, _data):
                    if any(p[0] == 1 and address < p[3] + p[5] and p[3] < address + size
                           for p in self.kernel.programs):
                        writes.append((address, size))
                u.hook_add(UC_HOOK_MEM_WRITE, check_write)
                u.emu_start(0x02001008, 0x02001010, count=500000000)
                self.assertEqual([u.reg_read(reg) for reg in regs], initial)
                self.assertEqual(writes, [], 'combined dry-run wrote a kernel destination')
                words = struct.unpack('<12I', u.mem_read(status, 48))
                if stage is None:
                    self.assertEqual(words, (0,) * 12, 'low-guard failure unexpectedly wrote status')
                else:
                    self.assertEqual(words[:4], (0x47414944, 1, stage, error))


if __name__ == '__main__':
    unittest.main()
