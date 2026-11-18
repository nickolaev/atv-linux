"""Exercise offline conservative EFI memory-map normalization."""
import struct
import unittest

from efi_memmap import (BIM_ACPI, BIM_MEMORY, BIM_NVS, BIM_RESERVED,
                        BTINFO_MEMMAP, Descriptor, EFI_MEMORY_RUNTIME,
                        EFI_MEMORY_WB, Region, normalize_descriptors,
                        normalize_efi_map, parse_descriptors, serialize_memmap)


def raw_descriptor(typ, start, pages, attrs, stride=48):
    raw = struct.pack('<IIQQQQ', typ, 0xdeadbeef, start, 0x12345000, pages, attrs)
    return raw + bytes(stride - len(raw))


class EfiMemmapTests(unittest.TestCase):
    def test_observed_apple_overlap_reserves_runtime(self):
        conventional = Descriptor(7, 0x02b07000, 0xb33c, 0xf)
        runtime = [Descriptor(5, 0x02b07000, 0x25, EFI_MEMORY_RUNTIME | 0xf),
                   Descriptor(6, 0x02b2c000, 0x2b, EFI_MEMORY_RUNTIME | 0xf),
                   Descriptor(6, 0x02b57000, 1, EFI_MEMORY_RUNTIME | 0xf)]
        expected = [Region(0x02b07000, 0x02b58000, BIM_RESERVED),
                    Region(0x02b58000, 0x0de43000, BIM_MEMORY)]
        self.assertEqual(normalize_descriptors([conventional] + runtime), expected)
        self.assertEqual(normalize_descriptors(list(reversed(runtime)) + [conventional]), expected)

    def test_observed_low_range_contains_netbsd_11_installer_segments(self):
        # This photo-derived fixture is specific to one boot, not a reusable map.
        regions = normalize_descriptors([
            Descriptor(7, 0x000c0000, 0x1f40, 0xf),
            Descriptor(2, 0x02000000, 0xb07, 0xf),
        ])
        self.assertEqual(regions, [Region(0x000c0000, 0x02000000, BIM_MEMORY),
                                   Region(0x02000000, 0x02b07000, BIM_RESERVED)])
        for start, end in ((0x00100000, 0x00fa14d8), (0x00fa2000, 0x015a6000)):
            self.assertTrue(any(r.type == BIM_MEMORY and r.start <= start < end <= r.end for r in regions))

    def test_wb_and_restricted_class_precedence(self):
        spans = [Descriptor(7, 0x1000, 8, EFI_MEMORY_WB),
                 Descriptor(9, 0x2000, 2, 0),
                 Descriptor(10, 0x3000, 2, 0),
                 Descriptor(7, 0x5000, 1, EFI_MEMORY_RUNTIME | EFI_MEMORY_WB),
                 Descriptor(7, 0x6000, 1, 0),
                 Descriptor(0xff, 0x7000, 1, EFI_MEMORY_WB)]
        self.assertEqual(normalize_descriptors(spans), [
            Region(0x1000, 0x2000, BIM_MEMORY),
            Region(0x2000, 0x3000, BIM_ACPI),
            Region(0x3000, 0x4000, BIM_RESERVED),
            Region(0x4000, 0x5000, BIM_NVS),
            Region(0x5000, 0x8000, BIM_RESERVED),
            Region(0x8000, 0x9000, BIM_MEMORY),
        ])

    def test_only_conventional_writeback_is_usable(self):
        self.assertEqual(normalize_descriptors([Descriptor(7, 0x1000, 1, EFI_MEMORY_WB)])[0].type, BIM_MEMORY)
        self.assertEqual(normalize_descriptors([Descriptor(7, 0x1000, 1, 0)])[0].type, BIM_RESERVED)
        for typ in (0, 1, 2, 3, 4, 5, 6, 8, 11, 12, 13, 14, 0xffffffff):
            self.assertEqual(normalize_descriptors([Descriptor(typ, 0x1000, 1, EFI_MEMORY_WB)])[0].type, BIM_RESERVED)

    def test_reservations_round_outwards_and_do_not_create_ram(self):
        ds = [Descriptor(7, 0x1000, 4, EFI_MEMORY_WB), Descriptor(7, 0x8000, 1, EFI_MEMORY_WB)]
        self.assertEqual(normalize_descriptors(ds, [(0x1fff, 0x2001), (0x6000, 0x7000)]), [
            Region(0x1000, 0x3000, BIM_RESERVED), Region(0x3000, 0x5000, BIM_MEMORY),
            Region(0x8000, 0x9000, BIM_MEMORY)])

    def test_parse_stride_and_roundtrip(self):
        raw = raw_descriptor(7, 0x1000, 2, 0xf) + raw_descriptor(6, 0x2000, 1, EFI_MEMORY_RUNTIME | 0xf)
        self.assertEqual(parse_descriptors(raw, 48), [Descriptor(7, 0x1000, 2, 0xf),
            Descriptor(6, 0x2000, 1, EFI_MEMORY_RUNTIME | 0xf)])
        self.assertEqual(normalize_efi_map(raw, 48), [Region(0x1000, 0x2000, BIM_MEMORY),
                                                      Region(0x2000, 0x3000, BIM_RESERVED)])
        for data, stride, version in ((raw[:-1], 48, 1), (raw, 39, 1), (raw, 42, 1),
                                      (raw, 48, 2), (b'', 48, 1)):
            with self.subTest(stride=stride, version=version), self.assertRaises(ValueError):
                parse_descriptors(data, stride, version)

    def test_invalid_ranges_and_overflow(self):
        for item in (Descriptor(7, 1, 1, 8), Descriptor(7, 0x1000, 0, 8),
                     Descriptor(7, 0xfffffffffffff000, 1, 8), Descriptor(-1, 0, 1, 8),
                     Descriptor(7, 0, 1, 1 << 64)):
            with self.subTest(item=item), self.assertRaises(ValueError):
                normalize_descriptors([item])
        for r in ((4, 4), (-1, 4), (0xfffffffffffff000, 0xffffffffffffffff)):
            with self.subTest(r=r), self.assertRaises(ValueError):
                normalize_descriptors([Descriptor(7, 0, 1, 8)], [r])

    def test_btinfo_record_wire_format_and_validation(self):
        regions = [Region(0x1000, 0x3000, BIM_MEMORY), Region(0x3000, 0x4000, BIM_RESERVED)]
        record = serialize_memmap(regions)
        self.assertEqual(struct.unpack_from('<III', record), (52, BTINFO_MEMMAP, 2))
        self.assertEqual(struct.unpack_from('<QQI', record, 12), (0x1000, 0x2000, BIM_MEMORY))
        self.assertEqual(struct.unpack_from('<QQI', record, 32), (0x3000, 0x1000, BIM_RESERVED))
        for invalid in ([], [Region(0x1001, 0x3000, BIM_MEMORY)],
                        [regions[1], regions[0]], [Region(0, 0x1000, 0)],
                        [Region(0, 0x3000, BIM_MEMORY), Region(0x2000, 0x4000, BIM_NVS)]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                serialize_memmap(invalid)


if __name__ == '__main__':
    unittest.main()
