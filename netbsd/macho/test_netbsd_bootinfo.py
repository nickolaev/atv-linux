import struct
import unittest

from netbsd_bootinfo import serialize_efi_bootinfo


class BootInfoTests(unittest.TestCase):
    def test_pointer_array_and_raw_efi_records(self):
        data = bytes(range(48)) + bytes(range(48, 96))
        result = serialize_efi_bootinfo(0x2000000, 0x2b57f10, data, 48, 1)
        self.assertEqual(struct.unpack_from('<III', result), (2, 0x200000c, 0x200002c))
        self.assertEqual(struct.unpack_from('<IIQI12s', result, 12),
                         (32, 14, 0x2b57f10, 1, bytes(12)))
        self.assertEqual(struct.unpack_from('<IIIII', result, 44),
                         (23 + 96, 15, 2, 1, 48))
        self.assertEqual(result[64:160], data)
        self.assertEqual(result[160:], bytes(3))
        self.assertEqual(len(result), 163)

    def test_40_descriptor_case(self):
        result = serialize_efi_bootinfo(0x1000000, 0x2b57f10, bytes(0x780), 48, 1)
        self.assertEqual(struct.unpack_from('<III', result, 52), (40, 1, 48))
        self.assertEqual(len(result), 12 + 32 + 23 + 0x780)

    def test_rejects_invalid_addresses(self):
        for base, table in ((0, 4), (2, 4), (1 << 32, 4), (4, 0), (4, 2), (4, 1 << 32)):
            with self.subTest(base=base, table=table), self.assertRaises(ValueError):
                serialize_efi_bootinfo(base, table, bytes(48), 48, 1)

    def test_rejects_wraparound_and_excessive_map(self):
        with self.assertRaises(ValueError):
            serialize_efi_bootinfo(0xfffffff0, 4, bytes(48), 48, 1)
        with self.assertRaises(ValueError):
            serialize_efi_bootinfo(0x1000, 4, bytes(48 * 341), 48, 1)

    def test_rejects_invalid_descriptor_inputs(self):
        for data, size, version in ((b'', 48, 1), (bytes(47), 48, 1),
                                    (bytes(36), 36, 1), (bytes(42), 42, 1),
                                    (bytes(48), 48, -1), (bytearray(48), 48, 1)):
            with self.subTest(size=size, version=version), self.assertRaises(ValueError):
                serialize_efi_bootinfo(0x1000, 4, data, size, version)


if __name__ == '__main__':
    unittest.main()
