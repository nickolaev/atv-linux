"""Exercise returning preflight against synthetic captures on the host."""
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def snapshot(descriptors):
    data = bytearray(8192)
    struct.pack_into('<15I', data, 0, 0x50414345, 3, 0x3000000, 0x3100000,
                     len(descriptors) * 48, 48, 1, 0, 0x13, 0, 2,
                     len(descriptors) * 48, 0, 32, 0x10004)
    for i, (typ, base, pages, attr) in enumerate(descriptors):
        struct.pack_into('<IIQQQQ', data, 192 + i * 48, typ, 0, base, 0, pages, attr)
    return data


class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.temp.name) / 'preflight'
        subprocess.run(['cc', '-DPREFLIGHT_HOST', '-Wall', '-Wextra', '-Werror',
                        '-O2', str(HERE / 'preflight.c'), '-o', str(cls.exe)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_capture(self, data):
        path = Path(self.temp.name) / 'capture'
        path.write_bytes(data)
        return subprocess.run([str(self.exe), str(path)], capture_output=True, text=True)

    def test_photographed_shape_and_metadata_placement(self):
        data = snapshot([(7, 0xc0000, 0x1f40, 8),
                         (7, 0x2b07000, 0xb33c, 8),
                         (5, 0x2b07000, 0x25, 0x800000000000000f),
                         (6, 0x2b2c000, 0x2b, 0x800000000000000f),
                         (6, 0x2b57000, 1, 0x800000000000000f)])
        result = self.run_capture(data)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count('MAP-CANDIDATE'), 2)
        self.assertIn('0x0000000002b58000 - 0x000000000de43000', result.stdout)
        self.assertIn('no kernel file was read', result.stdout)
        self.assertNotIn('  0x0000000002b07000 -', result.stdout)
        self.assertIn('EFI overlap pairs: 0x0000000000000003', result.stdout)
        self.assertIn('Hook ESP: not captured', result.stdout)

    def test_entry_stack_and_system_table(self):
        data = snapshot([(7, 0x2000000, 0x2000, 8),
                         (6, 0x2b57000, 1, 0x800000000000000f)])
        struct.pack_into('<I', data, 60, 0x2b57f00)
        struct.pack_into('<I', data, 4, 0)
        struct.pack_into('<I', data, 48, 72)
        table = bytearray(72)
        struct.pack_into('<QIIII', table, 0, 0x5453595320494249, 0x1000a, 72, 0, 0)
        struct.pack_into('<IIII', table, 56, 0x2b57a90, 0, 9, 0x2b56d90)
        struct.pack_into('<I', table, 16, zlib.crc32(table))
        data[64:136] = table
        result = self.run_capture(data)
        self.assertEqual(result.returncode, 0)
        self.assertIn('EFI system table CRC: VALID', result.stdout)
        self.assertIn('Config count: 0x0000000000000009', result.stdout)
        self.assertIn('Hook ESP: 0x0000000002b57f00', result.stdout)
        self.assertIn('EFI type 0x0000000000000006', result.stdout)
        self.assertIn('stack bounds are unknown', result.stdout)
        data[64+24] ^= 1
        self.assertIn('EFI system table CRC: INVALID', self.run_capture(data).stdout)

    def test_restricted_overlap_and_gap_rejected_as_candidates(self):
        data = snapshot([(7, 0x100000, 0x2000, 8), (6, 0x200000, 1, 8)])
        result = self.run_capture(data)
        self.assertEqual(result.returncode, 0)
        self.assertIn('segment 1: NOT COVERED', result.stdout)
        data = snapshot([(7, 0x100000, 0x100, 8)])
        self.assertEqual(self.run_capture(data).stdout.count('NOT COVERED'), 2)

    def test_rejects_incomplete_and_overflow(self):
        data = snapshot([(7, 0xfffffffffffff000, 1, 8)])
        self.assertNotEqual(self.run_capture(data).returncode, 0)
        self.assertNotEqual(self.run_capture(bytes(8191)).returncode, 0)
        data = snapshot([(7, 0x1000, 1, 8)])
        data[0] = 0
        self.assertNotEqual(self.run_capture(data).returncode, 0)


if __name__ == '__main__': unittest.main()
