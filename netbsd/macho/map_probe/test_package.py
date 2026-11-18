"""Test the mixed gzip/newc packaging and (optionally) the i386 shim."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parents[2] / 'image'))
from package import package, CAPTURE_NAME, CAPTURE_SIZE, OBSERVER_NAME, archive_has_capture, newc_entry
from embed_boot_menu import find_initrd, add_menu_to_rcs
import gzip


def fake_elf(code=b'\xb8\xde\xc0\xed\xfe\xc3'):
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    h = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, 0x2000500,
                    52, 0, 0, 52, 32, 1, 0, 0, 0)
    p = struct.pack('<8I', 1, 0x100, 0x2000500, 0x2000500,
                    len(code), len(code), 5, 0x1000)
    return (h+p).ljust(0x100, b'\0') + code


def baseline():
    original = bytearray((ROOT.parents[2] / 'image/recovery/mach_kernel').read_bytes())
    offset, length = find_initrd(original)
    initrd = gzip.decompress(original[offset:offset+length])
    menu = b'#!/bin/sh\nprintf snapshot-test\\n\n'
    compressed = gzip.compress(add_menu_to_rcs(initrd, menu), compresslevel=9, mtime=0)
    if len(compressed) + 9000 > length:
        raise AssertionError('baseline test fixture no longer has sufficient padding')
    original[offset:offset+length] = compressed + bytes(length-len(compressed))
    return bytes(original)


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = baseline()

    def test_archive_and_existing_gzip(self):
        output, address = package(self.original, fake_elf())
        off, length = find_initrd(output)
        z = zlib.decompressobj(31)
        z.decompress(output[off:off+length])
        self.assertTrue(z.eof)
        remaining = z.unused_data
        used = length - len(remaining)
        self.assertEqual(output[off:off+used], self.original[off:off+used])
        skip = len(remaining) - len(remaining.lstrip(b'\0'))
        start = off + length - len(remaining) + skip
        self.assertEqual((start-off) % 4, 0)
        self.assertEqual(output[start:start+6], b'070701')
        self.assertEqual(output[start+110:start+110+len(CAPTURE_NAME)], CAPTURE_NAME)
        self.assertEqual(output[address-0x02000000:address-0x02000000+CAPTURE_SIZE], bytes(CAPTURE_SIZE))
        self.assertEqual(output[:0x500], self.original[:0x500])
        self.assertEqual(output[0x100d:off], self.original[0x100d:off])

    def test_rejects_repackaging_and_bad_shim(self):
        output, _ = package(self.original, fake_elf())
        with self.assertRaises(ValueError): package(output, fake_elf())
        with self.assertRaises(ValueError): package(self.original, fake_elf(b'\xc3'))
        with self.assertRaises(ValueError):
            package(self.original, fake_elf(b'\xc3') + b'\xde\xc0\xed\xfe')

    def test_optional_static_preflight_packaging(self):
        preflight = fake_elf(b'\xc3')
        output, _ = package(self.original, fake_elf(), preflight)
        off, length = find_initrd(output)
        z = zlib.decompressobj(31)
        z.decompress(output[off:off+length])
        archive = z.unused_data.lstrip(b'\0')
        name = b'atv-preflight\0'
        p = archive.index(name) - 110
        self.assertEqual(int(archive[p+14:p+22], 16), 0o100755)
        self.assertEqual(int(archive[p+54:p+62], 16), len(preflight))
        bad = bytearray(preflight)
        struct.pack_into('<I', bad, 52, 3)  # PT_INTERP
        with self.assertRaises(ValueError): package(self.original, fake_elf(), bad)

    def test_optional_observer_packaging_and_validation(self):
        observer = fake_elf(b'\x90\xc3')
        output, _ = package(self.original, fake_elf(), fake_elf(b'\xc3'), observer)
        off, length = find_initrd(output)
        z = zlib.decompressobj(31)
        z.decompress(output[off:off + length])
        archive = z.unused_data.lstrip(b'\0')
        self.assertTrue(archive_has_capture(archive, OBSERVER_NAME))
        pos = archive.index(OBSERVER_NAME + b'\0') - 110
        self.assertEqual(int(archive[pos + 14:pos + 22], 16), 0o100755)
        self.assertEqual(int(archive[pos + 54:pos + 62], 16), len(observer))
        bad = bytearray(observer)
        struct.pack_into('<I', bad, 52, 3)  # PT_INTERP
        with self.assertRaises(ValueError):
            package(self.original, fake_elf(), fake_elf(b'\xc3'), bad)
        with self.assertRaises(ValueError):
            package(self.original, fake_elf(), None, observer + bytes(100000))

    def test_observer_collision_checks_entry_names(self):
        trailer, _ = newc_entry(b'TRAILER!!!', b'', 2)
        for name in (OBSERVER_NAME, b'./' + OBSERVER_NAME, b'/' + OBSERVER_NAME):
            entry, _ = newc_entry(name, b'', 1)
            self.assertTrue(archive_has_capture(entry + trailer, OBSERVER_NAME))

    def test_independent_cpio_extracts_modified_capture(self):
        cpio = shutil.which('cpio')
        if not cpio:
            self.skipTest('cpio is required for independent archive extraction')
        output, address = package(self.original, fake_elf())
        output = bytearray(output)
        capture_offset = address - 0x02000000
        expected = b'ECAP' + bytes((i % 251 for i in range(CAPTURE_SIZE - 4)))
        output[capture_offset:capture_offset + CAPTURE_SIZE] = expected
        off, length = find_initrd(output)
        z = zlib.decompressobj(31)
        z.decompress(output[off:off + length])
        self.assertTrue(z.eof)
        raw_archive = z.unused_data.lstrip(b'\0')
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([cpio, '-id'], input=raw_archive, cwd=tmp,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            self.assertEqual((Path(tmp) / 'atv-probe.bin').read_bytes(), expected)

    def test_collision_checks_entry_names_not_contents(self):
        trailer, _ = newc_entry(b'TRAILER!!!', b'', 2)
        menu, _ = newc_entry(b'menu.sh', b'cat /atv-probe.bin', 1)
        self.assertFalse(archive_has_capture(menu + trailer))
        for name in (b'atv-probe.bin', b'./atv-probe.bin', b'/atv-probe.bin'):
            entry, _ = newc_entry(name, b'', 1)
            self.assertTrue(archive_has_capture(entry + trailer))
        with self.assertRaises(ValueError): archive_has_capture(b'bad')

    def test_emulated_capture(self):
        path = os.environ.get('SNAPSHOT_ELF')
        if not path:
            self.skipTest('set SNAPSHOT_ELF to run the i386 probe with Unicorn')
        from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
        from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX,
            UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
            UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS, UC_X86_REG_CR0,
            UC_X86_REG_CR4, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_SS,
            UC_X86_REG_ES, UC_X86_REG_FS, UC_X86_REG_GS, UC_X86_REG_GDTR, UC_X86_REG_IDTR)
        output, capture = package(self.original, Path(path).read_bytes())
        regs = [UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX,
                UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
                UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EFLAGS]
        args, table, map_pa, stack = 0x03000100, 0x03200000, 0x03100000, 0x03300800
        descriptor = struct.pack('<IIQQQQ', 6, 0, table, 0, 1, 8) + bytes(8)
        for case in ('complete', 'large-map', 'stack-overlap', 'short-table', 'bad-signature', 'map-overlap', 'table-overlap',
                     'invalid-map', 'wrapping-map', 'null-args'):
            with self.subTest(case=case):
                u = Uc(UC_ARCH_X86, UC_MODE_32)
                u.mem_map(0x02000000, 0x02000000)
                u.mem_write(0x02000000, output)
                u.reg_write(UC_X86_REG_CR0, 0x13)
                u.reg_write(UC_X86_REG_GDTR, (0, 0x03102000, 0x345, 0))
                u.reg_write(UC_X86_REG_IDTR, (0, 0x03103000, 0x456, 0))
                cr4 = u.reg_read(UC_X86_REG_CR4)
                selectors = [u.reg_read(r) for r in (UC_X86_REG_CS, UC_X86_REG_DS,
                              UC_X86_REG_SS, UC_X86_REG_ES, UC_X86_REG_FS, UC_X86_REG_GS)]
                actual_stack = capture + 4096 if case == 'stack-overlap' else stack
                values = [0 if case == 'null-args' else args, 0x22, 0x33, 0x44,
                          0x55, 0x66, args, actual_stack, 0x646]
                for reg, value in zip(regs, values): u.reg_write(reg, value)
                testmap = (capture if case == 'map-overlap' else
                           0xfffffff0 if case == 'wrapping-map' else map_pa)
                size = 8001 if case == 'invalid-map' else 7968 if case == 'large-map' else 48
                boot = bytearray(0x44c)
                struct.pack_into('<IIII', boot, 0x404, testmap, size, 48, 1)
                struct.pack_into('<I', boot, 0x444, capture if case == 'table-overlap' else table)
                u.mem_write(args, bytes(boot))
                if case == 'map-overlap':
                    u.mem_write(capture, descriptor)
                elif case != 'wrapping-map':
                    u.mem_write(map_pa, descriptor + (b'\x5a' * (size - 48) if case == 'large-map' else b''))
                hdr = bytearray(128)
                struct.pack_into('<QIII', hdr, 0, 0x5453595320494249, 0x1000a, 24 if case == 'short-table' else 72, 0)
                if case == 'bad-signature': hdr[0] = 0
                u.mem_write(table, bytes(hdr))
                u.mem_write(capture + CAPTURE_SIZE, b'GUARD')
                before = bytes(u.mem_read(capture, CAPTURE_SIZE))
                u.emu_start(0x02001008, 0x02001010, count=100000)
                self.assertEqual([u.reg_read(r) for r in regs], values)
                self.assertEqual(bytes(u.mem_read(capture + CAPTURE_SIZE, 5)), b'GUARD')
                after = bytes(u.mem_read(capture, CAPTURE_SIZE))
                if case == 'stack-overlap':
                    # The hook already pushes flags/registers before it can
                    # detect the alias. No other snapshot bytes may change.
                    self.assertEqual(after[:4096 - 36], before[:4096 - 36])
                    self.assertEqual(after[4096:], before[4096:])
                elif case in ('map-overlap', 'table-overlap', 'invalid-map', 'wrapping-map', 'null-args'):
                    self.assertEqual(after, before)
                else:
                    self.assertEqual(after[:4], b'ECAP')
                    self.assertEqual(struct.unpack_from('<I', after, 4)[0],
                                     0 if case in ('complete', 'large-map') else 3)
                    self.assertEqual(after[192:240], descriptor)
                    self.assertEqual(struct.unpack_from('<I', after, 60)[0], stack)
                    if case == 'large-map':
                        self.assertEqual(after[8128:192 + size], b'\x5a' * (192 + size - 8128))
                        self.assertEqual(after[192 + size:], bytes(8192 - 192 - size))
                    else:
                        self.assertEqual(after[8128:8132], b'XREG')
                        self.assertEqual(struct.unpack_from('<I', after, 8132)[0], 1)
                        self.assertEqual(struct.unpack_from('<7I', after, 8136),
                                         (args, 0x22, 0x33, 0x44, 0x55, 0x66, args))
                        self.assertEqual(struct.unpack_from('<6H', after, 8164), tuple(selectors))
                        self.assertEqual(struct.unpack_from('<I', after, 8176)[0], cr4)
                        self.assertEqual(struct.unpack_from('<HI', after, 8180), (0x345, 0x03102000))
                        self.assertEqual(struct.unpack_from('<HI', after, 8186), (0x456, 0x03103000))
                    self.assertEqual(struct.unpack_from('<I', after, 48)[0],
                                     72 if case in ('complete', 'large-map') else 0)
                    if case == 'complete':
                        self.assertEqual(after[64:136], hdr[:72])
                        cpio = shutil.which('cpio')
                        if cpio:
                            # Extract the actual emulated shim output using an
                            # independent archive implementation.
                            captured = bytearray(output)
                            start = capture - 0x02000000
                            captured[start:start + CAPTURE_SIZE] = after
                            off, length = find_initrd(captured)
                            z = zlib.decompressobj(31)
                            z.decompress(captured[off:off + length])
                            self.assertTrue(z.eof)
                            with tempfile.TemporaryDirectory() as tmp:
                                subprocess.run([cpio, '-id'], input=z.unused_data.lstrip(b'\0'),
                                               cwd=tmp, stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE, check=True)
                                self.assertEqual((Path(tmp) / 'atv-probe.bin').read_bytes(), after)


if __name__ == '__main__': unittest.main()
