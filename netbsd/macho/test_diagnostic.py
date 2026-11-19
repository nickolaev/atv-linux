#!/usr/bin/env python3
"""Run bounded rendering checks on a native host, without invoking firmware."""
import pathlib
import subprocess
import struct
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
from elf_to_macho import convert
from patch_known_loader import patch
HARNESS = r'''
#include <stdint.h>
#include <string.h>
#include "diagnostic.c"
int main(void) {
    uint32_t fb[66 * 66];
    memset(fb, 0xaa, sizeof(fb));
    if (!draw_pattern(fb + 1, 66 * 4, 64, 64, 32)) return 1;
    if (fb[0] != 0xaaaaaaaa || fb[66 * 66 - 1] != 0xaaaaaaaa) return 2;
    if (fb[1] != 0x00102050 || fb[1 + 20 * 66 + 20] != 0x00ffffff ||
        fb[1 + 40 * 66 + 20] != 0x0000ff00) return 3;
    if (draw_pattern(fb, 256, 64, 64, 16)) return 4;
    if (draw_pattern(fb, 252, 64, 64, 32)) return 5;
    if (draw_pattern(fb, 256, 64, 4097, 32)) return 6;
    if (draw_pattern((uint32_t *)(uintptr_t)-4, 256, 64, 64, 32)) return 7;
    return 0;
}
'''

class PatternTest(unittest.TestCase):
    def test_patch_known_wrapper_preserves_other_bytes(self):
        original = (ROOT / '../../image/recovery/mach_kernel').read_bytes()
        ident = b'\x7fELF\x01\x01\x01' + bytes(9)
        hdr = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, 0x2001000,
                          52, 0, 0, 52, 32, 1, 0, 0, 0)
        ph = struct.pack('<8I', 1, 0x100, 0x2001000, 0x2001000, 4, 4, 5, 0x1000)
        diagnostic = (hdr + ph).ljust(0x100, b'\0') + b'test'
        result = patch(original, diagnostic)
        self.assertEqual(result[:4096], original[:4096])
        self.assertEqual(result[4096:4100], b'test')
        self.assertEqual(result[4100:], original[4100:])
        with self.assertRaises(ValueError):
            patch(original, diagnostic[:24])

    def test_elf_wrapper(self):
        ident = b'\x7fELF\x01\x01\x01' + bytes(9)
        hdr = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, 0x2001000,
                          52, 0, 0, 52, 32, 1, 0, 0, 0)
        ph = struct.pack('<8I', 1, 0x100, 0x2001000, 0x2001000, 4, 4, 5, 0x1000)
        result = convert((hdr + ph).ljust(0x100, b'\0') + b'test')
        self.assertEqual(struct.unpack_from('<7I', result)[:5],
                         (0xfeedface, 7, 3, 2, 3))
        self.assertEqual(struct.unpack_from('<I', result, 28 + 56 + 32)[0], 0)
        self.assertEqual(struct.unpack_from('<I', result, 28 + 56 + 124 + 16 + 40)[0], 0x2001000)
        self.assertEqual(result[4096:], b'test')
        with self.assertRaises(ValueError):
            convert(b'bad')

    def test_pattern_and_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / "test.c"
            binary = pathlib.Path(tmp) / "test"
            source.write_text(HARNESS)
            subprocess.run(["clang", "-DHOST_TEST", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT),
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

if __name__ == "__main__":
    unittest.main()
