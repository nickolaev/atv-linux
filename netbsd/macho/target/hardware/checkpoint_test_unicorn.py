"""Exercise the isolated native checkpoint against the real 11.1 ELF.

Requires Unicorn and CHECKPOINT_ELF, CHECKPOINT_KERNEL, NATIVE_TESTS paths.
This is not a hardware safety test.
"""
import os
import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, os.environ.get('NATIVE_TESTS', ''))
try:
    from run_unicorn import Elf32
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.x86_const import (UC_X86_REG_EIP, UC_X86_REG_EAX, UC_X86_REG_EBX,
        UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
        UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS, UC_X86_REG_CR0,
        UC_X86_REG_CR3, UC_X86_REG_CR4, UC_X86_REG_CS, UC_X86_REG_DS,
        UC_X86_REG_ES, UC_X86_REG_SS, UC_X86_REG_FS, UC_X86_REG_GS,
        UC_X86_REG_GDTR, UC_X86_REG_IDTR)
except ImportError:
    Uc = None

ELF = os.environ.get('CHECKPOINT_ELF')
KERNEL = os.environ.get('CHECKPOINT_KERNEL')


@unittest.skipUnless(Uc and ELF and KERNEL, 'provide Unicorn and checkpoint/kernel paths')
class CheckpointTests(unittest.TestCase):
    def run_case(self, case):
        native, kernel = Elf32(ELF), Elf32(KERNEL)
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x08000000)
        native.load(u)
        kernel.load(u)
        source, gdt, idt, stack, transfer, info = (0x06000000, 0x03300000,
                                                  0x03301000, 0x0300f000,
                                                  0x03008000, 0x05000000)
        self.assertLess(source + len(kernel.data), 0x08000000)
        u.mem_write(source, kernel.data)
        if case == 'bad_hash':
            u.mem_write(source, bytes([kernel.data[0] ^ 1]))
        if case == 'bad_code':
            u.mem_write(0x1001d8, b'\x90')
        if case == 'bad_destination':
            b = u.mem_read(0x100300, 1)[0]
            u.mem_write(0x100300, bytes([b ^ 1]))
        if case == 'bad_bss':
            bss = next(p for p in kernel.programs if p[0] == 1 and p[5] > p[4])
            u.mem_write(bss[3] + bss[5] - 1, b'\xff')
        original_gdt = bytes(16) + bytes.fromhex('ffff0000009acf00ffff00000092cf00')
        u.mem_write(gdt, original_gdt)
        u.reg_write(UC_X86_REG_GDTR, (0, gdt, 31, 0))
        u.reg_write(UC_X86_REG_IDTR, (0, idt, 0x7ff, 0))
        u.reg_write(UC_X86_REG_CR0, 0x13)
        for reg, value in ((UC_X86_REG_CS, 0x10), (UC_X86_REG_DS, 0x18),
                           (UC_X86_REG_ES, 0x18), (UC_X86_REG_SS, 0x18),
                           (UC_X86_REG_FS, 0x18), (UC_X86_REG_GS, 0x18)):
            u.reg_write(reg, value)
        if case == 'bad_selector':
            u.reg_write(UC_X86_REG_FS, 0)
        u.reg_write(UC_X86_REG_EFLAGS, 0x402)
        u.mem_write(0x472, b'\x56\x78')
        efi = struct.pack('<IIQI', 32, 14, 0x02b57f10, 1) + bytes(12)
        mmap = struct.pack('<IIIQQI', 32, 9, 1, 0x100000, 0x1f00000, 1)
        blob = bytearray(struct.pack('<III', 2, info+12, info+44) + efi + mmap)
        if case == 'bad_info_pointer':
            struct.pack_into('<I', blob, 4, info + 0x4000)
        if case == 'bad_info_length':
            struct.pack_into('<I', blob, 44, 0xffffffff)
        expected = 0x05010000
        u.mem_write(info, bytes(blob))
        u.mem_write(expected, bytes(blob))
        if case == 'changed_info':
            u.mem_write(info + 20, b'\x11')
        u.mem_write(stack, struct.pack('<8I', 0x80000, source, len(kernel.data), info,
                                       transfer, 1, expected, len(blob)))
        u.reg_write(UC_X86_REG_ESP, stack)
        regs = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP,
                UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
                UC_X86_REG_FS, UC_X86_REG_GS, UC_X86_REG_EFLAGS,
                UC_X86_REG_CR0, UC_X86_REG_CR3, UC_X86_REG_CR4)
        for reg, value in ((UC_X86_REG_EBX, 0x11223344), (UC_X86_REG_ESI, 0x55667788),
                           (UC_X86_REG_EDI, 0x12345678), (UC_X86_REG_EBP, 0x87654321)):
            u.reg_write(reg, value)
        before = [u.reg_read(reg) for reg in regs]
        before_gdtr, before_idtr = u.reg_read(UC_X86_REG_GDTR), u.reg_read(UC_X86_REG_IDTR)
        before_gdt = bytes(u.mem_read(gdt, 32))
        before_patch = bytes(u.mem_read(0x1001d0, 13))
        seen, forbidden, sensitive_writes = [], [], []
        allowed = [(0x472, 0x474), (0x03000000, 0x03010000), (0x03fff000, 0x04010000)]
        allowed += [(p[3], p[3]+p[5]) for p in kernel.programs if p[0] == 1]
        # Track sensitive destinations from the start, including hash and
        # validation. Restrict hook ranges so SHA's stack writes stay fast.
        def sensitive(_u, _access, address, size, _value, _data):
            sensitive_writes.append((address, size))
        for start, end in [(0x472, 0x474), (info, info + len(blob))] + [
                (p[3], p[3]+p[5]) for p in kernel.programs if p[0] == 1]:
            u.hook_add(UC_HOOK_MEM_WRITE, sensitive, begin=start, end=end-1)
        def write_hook(_u, _access, addr, size, _value, _data):
            if not any(a <= addr and addr+size <= b for a, b in allowed):
                forbidden.append((addr, size))
        def start_tracking(uc, _address, _size, _data):
            # SHA-256 processes ~23 MiB. Start the expensive per-write hook
            # at the transfer boundary, not during the CPU-only hash loop.
            uc.hook_add(UC_HOOK_MEM_WRITE, write_hook)
        u.hook_add(UC_HOOK_CODE, start_tracking,
                   begin=native.symbol('checkpoint_enter'), end=native.symbol('checkpoint_enter'))
        for name, address in (('native_loader', kernel.symbol('native_loader', physical=True)),
                              ('checkpoint_return', native.symbol('checkpoint_return'))):
            u.hook_add(UC_HOOK_CODE, lambda _u, _a, _s, _d, label=name: seen.append(label),
                       begin=address, end=address)
        u.emu_start(native.symbol('checkpoint_test_outer'), 0x80000, timeout=240000000)
        self.assertEqual(u.reg_read(UC_X86_REG_EIP), 0x80000, 'checkpoint did not return')
        expected_status = 0 if case == 'valid' else 0xffffffff
        self.assertEqual(struct.unpack('<I', u.mem_read(native.symbol('checkpoint_outer_status'), 4))[0], expected_status)
        self.assertEqual(seen, ['native_loader', 'checkpoint_return'] if case == 'valid' else [])
        self.assertEqual([u.reg_read(reg) for reg in regs], before)
        self.assertEqual(u.reg_read(UC_X86_REG_GDTR), before_gdtr)
        self.assertEqual(u.reg_read(UC_X86_REG_IDTR), before_idtr)
        self.assertEqual(bytes(u.mem_read(gdt, 32)), before_gdt)
        self.assertEqual(bytes(u.mem_read(0x472, 2)), b'\x56\x78')
        self.assertEqual(bytes(u.mem_read(0x1001d0, 13)), before_patch)
        self.assertEqual(forbidden, [])
        if case not in ('valid', 'bad_selector'):
            self.assertEqual(sensitive_writes, [])
        dest = kernel.symbol('bootinfo', physical=True)
        if case == 'valid':
            self.assertEqual(struct.unpack('<I', u.mem_read(dest, 4))[0], 2)
            self.assertEqual(bytes(u.mem_read(dest+4, len(efi)+len(mmap))), efi+mmap)
            self.assertEqual(struct.unpack('<I', u.mem_read(kernel.symbol('boothowto', physical=True), 4))[0], 0x20002)
        else:
            self.assertEqual(struct.unpack('<I', u.mem_read(dest, 4))[0], 0)

    def test_native_return_preserves_context_and_bda(self):
        self.run_case('valid')

    def test_rejects_changed_kernel_hash(self):
        self.run_case('bad_hash')

    def test_rejects_changed_checkpoint_bytes(self):
        self.run_case('bad_code')

    def test_rejects_unexpected_selector_and_restores_patch(self):
        self.run_case('bad_selector')

    def test_rejects_corrupted_kernel_destination(self):
        self.run_case('bad_destination')

    def test_rejects_corrupted_kernel_bss(self):
        self.run_case('bad_bss')

    def test_rejects_malformed_bootinfo_pointer(self):
        self.run_case('bad_info_pointer')

    def test_rejects_malformed_bootinfo_length(self):
        self.run_case('bad_info_length')

    def test_rejects_changed_bootinfo(self):
        self.run_case('changed_info')


if __name__ == '__main__':
    unittest.main()
