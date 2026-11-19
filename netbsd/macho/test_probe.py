#!/usr/bin/env python3
import os
from pathlib import Path
import struct
import unittest

from patch_probe import patch

ROOT = Path(__file__).resolve().parent


def fake_elf(code=b'\xc3'):
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    hdr = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, 0x2000500,
                      52, 0, 0, 52, 32, 1, 0, 0, 0)
    ph = struct.pack('<8I', 1, 0x100, 0x2000500, 0x2000500,
                     len(code), len(code), 5, 0x1000)
    return (hdr + ph).ljust(0x100, b'\0') + code


class ProbeTest(unittest.TestCase):
    def test_patch_is_bounded_and_checks_cave(self):
        source = (ROOT / '../../image/recovery/mach_kernel').read_bytes()
        result = patch(source, fake_elf())
        self.assertEqual(result[:0x500], source[:0x500])
        self.assertEqual(result[0x500], 0xc3)
        self.assertEqual(result[0x501:0x1008], source[0x501:0x1008])
        self.assertEqual(result[0x1008], 0xe9)
        self.assertEqual(result[0x100d:], source[0x100d:])
        broken = bytearray(source)
        broken[0x500] = 1
        with self.assertRaises(ValueError):
            patch(broken, fake_elf())
        with self.assertRaises(ValueError):
            patch(source, b'bad')

    def test_emulated_entry(self):
        path = os.environ.get('PROBE_ELF')
        if not path:
            self.skipTest('set PROBE_ELF to the linked shim for Unicorn test')
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX,
            UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
            UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS,
            UC_X86_REG_CR0, UC_X86_REG_CR3)
        source = (ROOT / '../../image/recovery/mach_kernel').read_bytes()
        modified = patch(source, Path(path).read_bytes())
        regs = [UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
                UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
                UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS]
        for length in (0, 104, 105, None):
            with self.subTest(length=length):
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(0x02000000, 0x2000)
                u.mem_write(0x02000000, modified[:0x2000])
                u.mem_map(0x00100000, 0x1000)
                u.mem_map(0x00300000, 0x1000)
                values = [0 if length is None else 0x100100, 0x22, 0x33,
                          0x44, 0x55, 0x66, 0x77, 0x300800, 0x646]
                for reg, value in zip(regs, values):
                    u.reg_write(reg, value)
                if length is not None:
                    u.mem_write(0x100104, b'a' * length + b'\0' + b'Z' * (1024-length))
                    offsets = [0, 0x414, 0x418, 0x41c, 0x420, 0x424,
                               0x428, 0x404, 0x408, 0x40c, 0x410, 0x444]
                    fields = [0x12340001 + i for i in range(len(offsets))]
                    for offset, value in zip(offsets, fields):
                        u.mem_write(0x100100 + offset, struct.pack('<I', value))
                    fields += [u.reg_read(UC_X86_REG_CR0), u.reg_read(UC_X86_REG_CR3), 0x646]
                u.emu_start(0x02001008, 0x02001010, count=10000)
                self.assertEqual([u.reg_read(r) for r in regs], values)
                if length is not None:
                    cmdline = bytes(u.mem_read(0x100104, 1024))
                    encoded = ','.join(f'{v:08x}' for v in fields).encode()
                    expected = b'a' * length + (b' atvprobe=entry,' + encoded + b'\0' if length <= 104 else b'\0')
                    self.assertTrue(cmdline.startswith(expected))
                    self.assertEqual(bytes(u.mem_read(0x100104 + 255, 1)), b'Z')


if __name__ == '__main__':
    unittest.main()
