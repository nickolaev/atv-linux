"""Optional whole-Mach-O returning actual-copy test with synthetic firmware.

Set RETURNING_COMBINED_MACHO, ATV_DIAG_ELF and ATV_DIAG_KERNEL, and install
Unicorn. This does not establish Apple firmware ownership or stack bounds.
"""
import os
import struct
import sys
import unittest
import zlib
from pathlib import Path

RETURNING = Path(__file__).resolve().parent.parent / 'returning'
sys.path.insert(0, str(RETURNING))
import test_shim_unicorn as base
if base.Uc is not None:
    from unicorn.x86_const import (UC_X86_REG_CR3, UC_X86_REG_CR4, UC_X86_REG_EIP,
                                  UC_X86_REG_FS, UC_X86_REG_GS)

CHECKPOINT = os.environ.get('ATV_CHECKPOINT_TEST') == '1'


@unittest.skipUnless(base.Uc is not None and base.COMBINED and base.HIGH_ELF and base.KERNEL,
                     'requires actual-copy fixture and Unicorn')
class ActualCopyTests(base.CombinedReturningTests):
    def test_combined_hook_returns_for_valid_and_rejected_firmware(self):
        cases = ('valid', 'valid_apple_envelope', 'valid_with_sources', 'valid_near_boundary', 'valid_above_cap', 'missing_return_state', 'stack_restricted', 'kernel_collision', 'bad_acpi',
                     'config_unbacked', 'config_overlap', 'devtree_unbacked',
                     'devtree_overlap', 'devtree_bad_pair', 'framebuffer_overlap',
                     'framebuffer_overflow', 'kernel_span_overflow', 'kernel_span_overlap', 'kernel_span_bad_pair',
                     'runtime_overflow', 'efi_pointer_unbacked', 'kernel_above_cap')
        if CHECKPOINT:
            cases += ('bda_unbacked', 'bda_conflicting', 'checkpoint_bad_hash', 'checkpoint_bad_bootinfo')
        for case in cases:
            with self.subTest(case=case):
                u = base.Uc(base.UC_ARCH_X86, base.UC_MODE_32)
                u.mem_map(0, 0x10000000)
                status, high = self.load_all_segments(u)
                apple = self.make_firmware(u, 'acpi' if case == 'bad_acpi' else None,
                                           self.high.symbol('projected_pages'))
                map_pa, map_len = struct.unpack('<II', u.mem_read(apple + 0x404, 8))
                extra = base.descriptor(2, high[0], (high[1] - high[0]) // 4096, 15)
                if CHECKPOINT and case != 'bda_unbacked':
                    extra += base.descriptor(7, 0, 0x8f, 15)
                if case == 'bda_conflicting':
                    extra += base.descriptor(4, 0, 1, 15)
                if case != 'missing_return_state':
                    extra += base.descriptor(4, 0x0f000000, 0x1000, 15)
                if case == 'stack_restricted':
                    extra += base.descriptor(11, 0x0f007000, 2, 0)
                if case == 'kernel_collision':
                    extra += base.descriptor(4, 0x00100000, 1, 15)
                if case == 'kernel_above_cap':
                    extra += base.descriptor(7, 0x10000000, 0x2000, 15)
                u.mem_write(map_pa + map_len, extra)
                u.mem_write(apple + 0x408, struct.pack('<I', map_len + len(extra)))
                # The integration fixture normally uses deliberately unmapped
                # dropped pointers. The real-copy mode must reserve even those
                # references, so supply distinct descriptor-backed objects.
                config_pa = 0x02b56d90
                for index in range(6):
                    u.mem_write(config_pa + index * 20 + 16,
                                struct.pack('<I', 0x0f010000 + index * 0x1000))
                if case == 'config_unbacked':
                    u.mem_write(config_pa + 16, struct.pack('<I', 0x0ef00000))
                elif case == 'config_overlap':
                    u.mem_write(config_pa + 16, struct.pack('<I', 0x00100000))
                elif case == 'valid_near_boundary':
                    # Unknown object starts just before its backing descriptor
                    # ends; its unknown length could extend into later memory.
                    u.mem_write(config_pa + 16, struct.pack('<I', 0x02b56ff0))
                elif case == 'valid_above_cap':
                    # All actual-copy destinations are below this bound.
                    u.mem_write(config_pa + 16, struct.pack('<I', 0xf0000000))
                elif case == 'devtree_unbacked':
                    u.mem_write(apple + 0x42c, struct.pack('<II', 0x0ef00000, 4096))
                elif case == 'devtree_overlap':
                    u.mem_write(apple + 0x42c, struct.pack('<II', 0x00110000, 4096))
                elif case == 'devtree_bad_pair':
                    u.mem_write(apple + 0x42c, struct.pack('<II', 0x0f010000, 0))
                elif case == 'framebuffer_overlap':
                    u.mem_write(apple + 0x414, struct.pack('<I', 0x00100000))
                    u.mem_write(apple + 0x41c, struct.pack('<I', 4096))
                    u.mem_write(apple + 0x424, struct.pack('<I', 1))
                elif case == 'framebuffer_overflow':
                    u.mem_write(apple + 0x414, struct.pack('<I', 0xfffff000))
                    u.mem_write(apple + 0x41c, struct.pack('<I', 4096))
                    u.mem_write(apple + 0x424, struct.pack('<I', 2))
                elif case == 'kernel_span_overflow':
                    u.mem_write(apple + 0x434, struct.pack('<II', 0xfffff000, 0x2000))
                elif case == 'kernel_span_overlap':
                    u.mem_write(apple + 0x434, struct.pack('<II', 0x00110000, 4096))
                elif case == 'kernel_span_bad_pair':
                    u.mem_write(apple + 0x434, struct.pack('<II', 0x02000000, 0))
                elif case == 'runtime_overflow':
                    u.mem_write(apple + 0x43c, struct.pack('<II', 0xfffffffe, 0x100))
                elif case == 'efi_pointer_unbacked':
                    systable = bytearray(u.mem_read(0x02b57f10, 72))
                    struct.pack_into('<I', systable, 24, 0x0ef00000)
                    struct.pack_into('<I', systable, 16, 0)
                    struct.pack_into('<I', systable, 16, zlib.crc32(systable))
                    u.mem_write(0x02b57f10, bytes(systable))
                elif case == 'valid_apple_envelope':
                    # Photo: Apple's envelope crosses distinct mapped segments
                    # and the unmapped gap; the whole span must be reserved.
                    u.mem_write(apple + 0x434, struct.pack('<II', 0x02000000, 0x0371b000))
                elif case == 'valid_with_sources':
                    u.mem_write(apple + 0x42c, struct.pack('<II', 0x0f020000, 1024))
                    u.mem_write(apple + 0x434, struct.pack('<II', 0x0f030000, 4096))
                    u.mem_write(apple + 0x43c, struct.pack('<II', 0x0f040, 1))
                    u.mem_write(apple + 0x414, struct.pack('<I', 0x10018000))
                    u.mem_write(apple + 0x41c, struct.pack('<I', 0xc00))
                    u.mem_write(apple + 0x424, struct.pack('<I', 480))
                    systable = bytearray(u.mem_read(0x02b57f10, 72))
                    struct.pack_into('<I', systable, 24, 0x0f050000)
                    struct.pack_into('<I', systable, 16, 0)
                    struct.pack_into('<I', systable, 16, zlib.crc32(systable))
                    u.mem_write(0x02b57f10, bytes(systable))
                elif case == 'kernel_above_cap':
                    # Move the second PT_LOAD above the 256 MiB boundary in
                    # the embedded test ELF while leaving its entry intact.
                    phoff = struct.unpack_from('<I', self.kernel.data, 28)[0]
                    phentsize, phnum = struct.unpack_from('<HH', self.kernel.data, 42)
                    indices = [i for i in range(phnum)
                               if struct.unpack_from('<I', self.kernel.data,
                                                     phoff + i * phentsize)[0] == 1]
                    self.assertGreaterEqual(len(indices), 2)
                    field = self.high.symbol('kernel_start') + phoff + indices[1] * phentsize + 12
                    u.mem_write(field, struct.pack('<I', 0x10000000))
                gdt_pa, idt_pa, stack = 0x0f002000, 0x0f004000, 0x0f008000
                gdt = bytes(16) + bytes.fromhex('ffff0000009acf00ffff00000092cf00')
                u.mem_write(gdt_pa, gdt)
                u.reg_write(base.UC_X86_REG_GDTR, (0, gdt_pa, len(gdt) - 1, 0))
                u.reg_write(base.UC_X86_REG_IDTR, (0, idt_pa, 0x7ff, 0))
                u.reg_write(base.UC_X86_REG_CR0, 0x13)
                for reg, value in ((base.UC_X86_REG_CS, 0x10), (base.UC_X86_REG_DS, 0x18),
                                   (base.UC_X86_REG_ES, 0x18), (base.UC_X86_REG_SS, 0x18),
                                   (UC_X86_REG_FS, 0x18), (UC_X86_REG_GS, 0x18)):
                    u.reg_write(reg, value)
                regs = (base.UC_X86_REG_EAX, base.UC_X86_REG_EBX, base.UC_X86_REG_ECX,
                        base.UC_X86_REG_EDX, base.UC_X86_REG_ESI, base.UC_X86_REG_EDI,
                        base.UC_X86_REG_EBP, base.UC_X86_REG_ESP, base.UC_X86_REG_EFLAGS)
                for reg, value in zip(regs, (apple, 0x12340018, 0x33, 0x44, 0x55,
                                             0x66, apple, stack, 0x402)):
                    u.reg_write(reg, value)
                initial = [u.reg_read(reg) for reg in regs]
                machine_registers = (base.UC_X86_REG_GDTR, base.UC_X86_REG_IDTR,
                                     base.UC_X86_REG_CS, base.UC_X86_REG_DS,
                                     base.UC_X86_REG_ES, base.UC_X86_REG_SS,
                                     UC_X86_REG_FS, UC_X86_REG_GS,
                                     base.UC_X86_REG_CR0, UC_X86_REG_CR3, UC_X86_REG_CR4)
                machine_before = [u.reg_read(reg) for reg in machine_registers]
                if CHECKPOINT:
                    u.mem_write(0x472, b'\xa5\x5a')
                protected = [(0x02b50000, 0x02b58000), (map_pa, map_pa + map_len + len(extra)),
                             (apple, apple + 0x44c), (gdt_pa, gdt_pa + 32),
                             (idt_pa, idt_pa + 0x800)]
                before = [bytes(u.mem_read(a, b - a)) for a, b in protected]
                linux_ranges = [(0x02000000, status), (status + 48, 0x02afd000)]
                linux_before = [bytes(u.mem_read(a, b - a)) for a, b in linux_ranges]
                writes = []
                def check_write(_u, _access, address, size, _value, _data):
                    if any(p[0] == 1 and address < p[3] + p[5] and p[3] < address + size
                           for p in self.kernel.programs):
                        writes.append((address, size))
                # Bytewise physical copying produces millions of writes; the
                # successful case is verified by full destination comparison.
                if not case.startswith('valid') and not case.startswith('checkpoint_bad'):
                    u.hook_add(base.UC_HOOK_MEM_WRITE, check_write)
                entered = []
                if CHECKPOINT:
                    native_loader = self.kernel.symbol('native_loader', physical=True)
                    checkpoint_return = self.high.symbol('checkpoint_return')
                    for name, address in (('native_loader', native_loader),
                                          ('checkpoint_return', checkpoint_return)):
                        u.hook_add(base.UC_HOOK_CODE,
                                   lambda _u, _a, _s, _d, label=name: entered.append(label),
                                   begin=address, end=address)
                    if case.startswith('checkpoint_bad'):
                        def mutate(uc, _address, _size, _data):
                            if case == 'checkpoint_bad_hash':
                                addr = self.high.symbol('kernel_start') + 100
                            else:
                                esp = uc.reg_read(base.UC_X86_REG_ESP)
                                addr = struct.unpack('<I', uc.mem_read(esp + 12, 4))[0] + 20
                            uc.mem_write(addr, bytes((uc.mem_read(addr, 1)[0] ^ 1,)))
                        addr = self.high.symbol('checkpoint_run')
                        u.hook_add(base.UC_HOOK_CODE, mutate, begin=addr, end=addr)
                # The checkpoint hashes the entire real 23 MiB kernel in
                # emulation.  The copy-only limit expires before this returns.
                budget = 3000000000 if CHECKPOINT else 500000000
                u.emu_start(0x02001008, 0x02001010, count=budget)
                self.assertEqual(u.reg_read(UC_X86_REG_EIP), 0x02001010,
                                 f'{case} did not return before the instruction limit')
                self.assertEqual([u.reg_read(reg) for reg in regs], initial)
                self.assertEqual([u.reg_read(reg) for reg in machine_registers], machine_before)
                if CHECKPOINT:
                    self.assertEqual(bytes(u.mem_read(0x472, 2)), b'\xa5\x5a')
                self.assertEqual([bytes(u.mem_read(a, b - a)) for a, b in protected], before)
                self.assertEqual([bytes(u.mem_read(a, b - a)) for a, b in linux_ranges], linux_before,
                                 'original Linux loader or initrd changed outside status record')
                words = struct.unpack('<12I', u.mem_read(status, 48))
                self.assertEqual(words[:2], (0x47414944, 1))
                # Stage-6 protection failures reuse four status words as
                # kind, start, length and reason/index/type. A missing
                # descriptor is encoded as index 0xffff and type 0xff.
                failure_details = {
                    # Hook stack points 40 bytes below initial ESP after the
                    # saved frame and the low-to-high call return address.
                    'missing_return_state': (1, 0x0f006fd8, 8192, 0x05ffffff),
                    'config_unbacked': (0x0700, 0x0ef00000, 1, 0x05ffffff),
                    'devtree_unbacked': (4, 0x0ef00000, 4096, 0x05ffffff),
                    'devtree_bad_pair': (4, 0x0f010000, 0, 0x07ffffff),
                    'efi_pointer_unbacked': (0x0818, 0x0ef00000, 1, 0x05ffffff),
                    'framebuffer_overflow': (10, 0xfffff000, 8192, 0x01ffffff),
                }
                if case in failure_details:
                    self.assertEqual(words[2:4], (6, 10), case)
                    self.assertEqual(words[8:12], failure_details[case], case)
                if case == 'stack_restricted':
                    self.assertEqual(words[2:4], (6, 10), case)
                    self.assertEqual(words[8:11], (1, 0x0f006fd8, 8192), case)
                    self.assertEqual(words[11] >> 24, 3, case)
                    self.assertEqual((words[11] >> 8) & 0xffff,
                                     (map_len + len(extra)) // 48 - 1, case)
                    self.assertEqual(words[11] & 0xff, 11, case)
                if case.startswith('valid'):
                    self.assertEqual(words[2:4], (11 if CHECKPOINT else 10, 0))
                    copied = zeroed = 0
                    for kind, off, _, pa, filesz, memsz, _, _ in self.kernel.programs:
                        if kind != 1: continue
                        if not CHECKPOINT:
                            self.assertEqual(bytes(u.mem_read(pa, filesz)), self.kernel.data[off:off + filesz])
                            self.assertFalse(any(u.mem_read(pa + filesz, memsz - filesz)))
                        copied += filesz
                        zeroed += memsz - filesz
                    self.assertEqual(words[8:10], (copied, zeroed))
                    self.assertNotEqual(words[11], 0)
                    if case == 'valid_apple_envelope':
                        self.assertTrue(words[11] + 16384 <= 0x02000000 or words[11] >= 0x0571b000)
                    count, efi, memmap = struct.unpack('<III', u.mem_read(words[11], 12))
                    self.assertEqual(count, 2)
                    self.assertEqual(struct.unpack('<I', u.mem_read(efi + 4, 4))[0], 14)
                    self.assertEqual(struct.unpack('<I', u.mem_read(memmap + 4, 4))[0], 9)
                    if CHECKPOINT:
                        self.assertEqual(entered, ['native_loader', 'checkpoint_return'])
                    if case == 'valid_near_boundary':
                        self.assertLessEqual(words[11] + 16384, 0x02b56ff0)
                        for kind, _, _, pa, _, memsz, _, _ in self.kernel.programs:
                            if kind == 1:
                                self.assertLessEqual(pa + memsz, 0x02b56ff0)
                else:
                    if not case.startswith('checkpoint_bad'):
                        self.assertFalse(writes, f'{case} wrote a kernel destination')
                    self.assertNotEqual(words[3], 0)
                    if CHECKPOINT:
                        self.assertFalse(entered, f'{case} entered native_loader')


if __name__ == '__main__':
    unittest.main()
