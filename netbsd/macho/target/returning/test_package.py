import gzip
import importlib.util
import struct
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('returning_package', HERE / 'package.py')
pkg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pkg)
from embed_boot_menu import add_menu_to_rcs, find_initrd


def fixture_original():
    original = bytearray((HERE.parents[3] / 'image/recovery/mach_kernel').read_bytes())
    off, size = find_initrd(original)
    archive = gzip.decompress(original[off:off+size])
    archive = add_menu_to_rcs(archive, b'#!/bin/sh\nprintf "test"\n')
    compressed = gzip.compress(archive, compresslevel=9, mtime=0)
    if len(compressed) + 512 > size:
        raise RuntimeError('test menu did not free enough initrd space')
    original[off:off+size] = compressed + bytes(size-len(compressed))
    return bytes(original)


def fixture_shim():
    code = b'\x90' + b''.join(struct.pack('<I', n) for n in pkg.MARKERS) + b'\xc3'
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    h = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, pkg.BASE+pkg.HOOK,
                    52, 0, 0, 52, 32, 1, 0, 0, 0)
    p = struct.pack('<8I', 1, 84, pkg.BASE+pkg.HOOK, pkg.BASE+pkg.HOOK,
                    len(code), len(code), 5, 4096)
    return h+p+code


def fixture_high(vm=0x03fff000, valid=True):
    h = struct.pack('<7I', 0xfeedface, 7, 3, 2, 3, 192, 1)
    pz = struct.pack('<II16s8I', 1, 56, b'__PAGEZERO', 0, 4096, 0, 0, 0, 0, 0, 0)
    seg = struct.pack('<II16s8I', 1, 56, b'__TEXT', vm, 8192, 0, 8192, 7, 5, 0, 0)
    regs = [0]*16
    regs[10] = vm+4096
    thread = struct.pack('<4I16I', 5, 80, 0xffffffff, 16, *regs)
    result = bytearray((h+pz+seg+thread).ljust(8192, b'\0'))
    if valid:
        result[4096:4096+len(pkg.ABI)] = pkg.ABI
    return bytes(result)


class ReturningPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = fixture_original()
        cls.shim = fixture_shim()
        cls.high = fixture_high()

    def test_layout_and_byte_preservation(self):
        out, status = pkg.package(self.original, self.shim, self.high)
        count, length, end, segs, entry = pkg.macho(out)
        self.assertEqual((count, length, end, entry), (8, 1256, 0x504, 0x02001000))
        added = [x for x in segs if x[0] == b'__ATVDIAG'][0]
        self.assertEqual(added[1:3], (0x03fff000, 8192))
        self.assertEqual(out[added[3]:added[3]+added[4]], self.high)
        self.assertEqual(out[0x1008], 0xe9)
        self.assertEqual(status, pkg.BASE + out.index(pkg.NAME+b'\0') + len(pkg.NAME)+1 + (-len(pkg.NAME)-1-110)%4)
        self.assertEqual(out[status-pkg.BASE:status-pkg.BASE+48], bytes(48))
        self.assertEqual(out[0x1010:0x2000], self.original[0x1010:0x2000])
        self.assertEqual(out[28:0x4cc], self.original[28:0x4cc])
        self.assertEqual(out[0x100d:0x1010], self.original[0x100d:0x1010])

    def test_rejects_overlapping_high_and_nonreturning_payload(self):
        for high in (fixture_high(vm=0x02afc000), fixture_high(valid=False)):
            with self.assertRaises(ValueError):
                pkg.package(self.original, self.shim, high)

    def test_rejects_unbacked_high_workspace(self):
        high = bytearray(self.high)
        struct.pack_into('<I', high, 28+56+28, 8192+65536)
        with self.assertRaises(ValueError):
            pkg.package(self.original, self.shim, bytes(high))

    def test_rejects_modified_header_cave_and_hook(self):
        for offset in (0x4cc, 0x600, 0x1008):
            altered = bytearray(self.original)
            altered[offset] ^= 0x11
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                pkg.package(bytes(altered), self.shim, self.high)

    def test_rejects_nonunique_shim_sentinel(self):
        altered = self.shim + struct.pack('<I', pkg.MARKERS[0])
        # Additional unreferenced file data is not itself an executable marker.
        pkg.package(self.original, altered, self.high)
        altered = bytearray(self.shim)
        altered[89:93] = struct.pack('<I', pkg.MARKERS[0])
        with self.assertRaises(ValueError):
            pkg.package(self.original, bytes(altered), self.high)


if __name__ == '__main__':
    unittest.main()
