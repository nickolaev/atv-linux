"""Offline tests for captured EFI snapshot validation."""
import struct
import unittest
import zlib

from decode import CAPTURE_SIZE, decode


def capture(status=0):
    data = bytearray(CAPTURE_SIZE)
    fields = (0x50414345, status, 0x2b00000, 0x2b06000, 96, 48, 1,
              0x2b57f10, 0x13, 0, 0x12, 96, 72 if status == 0 else 0,
              32, 0x00010004)
    struct.pack_into('<15I', data, 0, *fields)
    struct.pack_into('<IIQQQQ', data, 192, 7, 0, 0x100000, 0, 0x100, 8)
    struct.pack_into('<IIQQQQ', data, 240, 6, 0, 0x300000, 0x500000, 2, 0x8000000000000008)
    if status == 0:
        table = bytearray(72)
        struct.pack_into('<QIIII', table, 0, 0x5453595320494249, 0x1000a, 72, 0, 0)
        struct.pack_into('<12I', table, 24, *range(12))
        struct.pack_into('<I', table, 16, zlib.crc32(table) & 0xffffffff)
        data[64:136] = table
    return data


class DecodeTests(unittest.TestCase):
    def test_complete_capture_and_table_crc(self):
        result = decode(capture())
        self.assertEqual(result['status'], 'complete')
        self.assertEqual((result['boot_args_revision'], result['boot_args_version']), (4, 1))
        self.assertEqual(result['memory_map']['descriptor_size'], 48)
        desc = result['memory_map']['descriptors'][1]
        self.assertEqual((desc['physical_start'], desc['virtual_start'], desc['page_count']),
                         (0x300000, 0x500000, 2))
        self.assertEqual(desc['attributes'], 0x8000000000000008)
        self.assertTrue(result['system_table']['crc_valid'])
        self.assertEqual(result['system_table']['fields']['runtime_services'], 8)
        self.assertEqual(result['system_table']['fields']['boot_services'], 9)
        self.assertEqual(result['system_table']['fields']['configuration_table'], 11)
        self.assertFalse(result['memory_map']['source_covered_by_data_descriptor'])
        self.assertFalse(result['system_table_128_bytes_covered_by_data_descriptor'])

    def test_entry_stack_pointer_and_older_capture(self):
        data = capture()
        self.assertIsNone(decode(data)['registers']['hook_esp'])
        struct.pack_into('<I', data, 60, 0x2b54000)
        self.assertEqual(decode(data)['registers']['hook_esp'], 0x2b54000)

    def test_extended_register_trailer(self):
        data = capture()
        self.assertIsNone(decode(data)['registers']['extended'])
        struct.pack_into('<II7I6HIHIHI', data, 8128, 0x47455258, 1,
                         *range(1, 8), *range(8, 14), 14, 15, 16, 17, 18)
        result = decode(data)['registers']['extended']
        self.assertEqual(result['gpr']['eax'], 1)
        self.assertEqual(result['selectors']['gs'], 13)
        self.assertEqual(result['cr4'], 14)
        self.assertEqual(result['gdtr'], {'limit': 15, 'base': 16})
        self.assertEqual(result['idtr'], {'limit': 17, 'base': 18})

    def test_reports_data_descriptor_coverage_without_claiming_safety(self):
        data = capture()
        struct.pack_into('<I', data, 192, 4)  # BootServicesData
        struct.pack_into('<Q', data, 192 + 8, 0x2b00000)
        result = decode(data)
        self.assertTrue(result['memory_map']['source_covered_by_data_descriptor'])
        self.assertTrue(result['system_table_128_bytes_covered_by_data_descriptor'])
        struct.pack_into('<I', data, 192, 5)  # RuntimeServicesCode, not data
        result = decode(data)
        self.assertFalse(result['memory_map']['source_covered_by_data_descriptor'])
        self.assertFalse(result['system_table_128_bytes_covered_by_data_descriptor'])

    def test_crc_failure_is_explicit_observation(self):
        data = capture()
        data[64 + 40] ^= 1
        table = decode(data)['system_table']
        self.assertFalse(table['crc_valid'])
        self.assertNotEqual(table['crc32'], table['calculated_crc32'])

    def test_partial_capture_retains_map_without_table(self):
        result = decode(capture(3))
        self.assertEqual(result['status'], 'map_only')
        self.assertIsNone(result['system_table'])
        self.assertEqual(len(result['memory_map']['descriptors']), 2)
        data = capture(3)
        struct.pack_into('<I', data, 48, 72)
        with self.assertRaises(ValueError):
            decode(data)

    def test_rejects_missing_invalid_or_incomplete_header(self):
        variants = [capture()[:-1], bytes(CAPTURE_SIZE)]
        for offset, value in ((4, 2), (12, 0), (16, 97), (20, 44),
                              (24, 2), (44, 48), (48, 71)):
            data = capture()
            struct.pack_into('<I', data, offset, value)
            variants.append(data)
        for data in variants:
            with self.subTest(length=len(data)):
                with self.assertRaises(ValueError):
                    decode(data)

    def test_rejects_bad_table_signature_and_size(self):
        for offset, value in ((64, 0), (64 + 12, 80)):
            data = capture()
            struct.pack_into('<I', data, offset, value)
            with self.assertRaises(ValueError):
                decode(data)

    def test_reports_overlapping_descriptors(self):
        data = capture()
        struct.pack_into('<Q', data, 240 + 8, 0x100000)
        result = decode(data)
        overlaps = result['memory_map']['physical_overlaps']
        self.assertEqual(overlaps, [{'first_index': 0, 'second_index': 1,
                                     'start': 0x100000, 'end': 0x102000}])

    def test_reports_each_nested_overlap(self):
        data = capture()
        struct.pack_into('<III', data, 16, 144, 48, 1)
        struct.pack_into('<I', data, 44, 144)
        struct.pack_into('<IIQQQQ', data, 240, 6, 0, 0x110000, 0, 1, 8)
        struct.pack_into('<IIQQQQ', data, 288, 6, 0, 0x120000, 0, 1, 8)
        overlaps = decode(data)['memory_map']['physical_overlaps']
        self.assertEqual([(item['first_index'], item['second_index']) for item in overlaps],
                         [(0, 1), (0, 2)])

    def test_rejects_unaligned_empty_and_overflowing_descriptors(self):
        variants = []
        for offset, value in ((240 + 8, 0x300001),
                              (240 + 24, 0), (240 + 16, 0x500001),
                              (240 + 8, 0xfffffffffffff000)):
            data = capture()
            struct.pack_into('<Q', data, offset, value)
            variants.append(data)
        for data in variants:
            with self.assertRaises(ValueError):
                decode(data)


if __name__ == '__main__':
    unittest.main()
