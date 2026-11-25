"""Validation tests for an offline NetBSD/i386 ELF load plan."""
import struct
import unittest

from netbsd_elf import plan_elf


def kernel(segments=None, entry=0xc0100004):
    if segments is None:
        # type, file offset, virtual address, physical address, file bytes,
        # memory bytes, flags, alignment
        segments = [(1, 0x1000, 0xc0100000, 0x100000, 0x20, 0x40, 5, 0x1000),
                    (1, 0x2000, 0xc0200000, 0x200000, 0x10, 0x30, 6, 0x1000)]
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    header = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, entry,
                         52, 0, 0, 52, 32, len(segments), 0, 0, 0)
    ph = b''.join(struct.pack('<8I', *segment) for segment in segments)
    return (header + ph).ljust(0x2100, b'\x00')


class PlanElfTests(unittest.TestCase):
    def test_maps_virtual_entry_and_bss(self):
        result = plan_elf(kernel(), [(0x100000, 0x300000)], [(0, 0x100000)])
        self.assertEqual(result['physical_entry'], 0x100004)
        self.assertTrue(result['memory_checked'])
        self.assertEqual(result['segments'][1]['memory_size'], 0x30)
        self.assertEqual(result['segments'][1]['file_size'], 0x10)

    def test_omitted_map_does_not_claim_memory_verified(self):
        self.assertFalse(plan_elf(kernel())['memory_checked'])
        with self.assertRaisesRegex(ValueError, 'usable memory'):
            plan_elf(kernel(), [])

    def test_rejects_truncated_wrong_machine_or_endian(self):
        with self.assertRaises(ValueError):
            plan_elf(b'\x7fELF')
        for offset, value in ((5, 2), (18, 0x3e)):
            data = bytearray(kernel())
            data[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                plan_elf(data)

    def test_rejects_truncated_program_table(self):
        data = bytearray(kernel())
        struct.pack_into('<I', data, 28, 0x20f0)
        with self.assertRaisesRegex(ValueError, 'program header table'):
            plan_elf(data)

    def test_rejects_bad_sizes_or_file_bounds(self):
        for change in ((16, 0x41), (4, 0x20ff)):
            data = bytearray(kernel())
            struct.pack_into('<I', data, 52 + change[0], change[1])
            with self.subTest(change=change), self.assertRaises(ValueError):
                plan_elf(data)

    def test_rejects_overflow_and_alignment(self):
        for change in ((12, 0xfffffff0), (28, 3), (4, 0x1001), (8, 0xfffffff0)):
            data = bytearray(kernel())
            struct.pack_into('<I', data, 52 + change[0], change[1])
            with self.subTest(change=change), self.assertRaises(ValueError):
                plan_elf(data)

    def test_rejects_physical_overlap_and_reserved(self):
        data = bytearray(kernel())
        struct.pack_into('<I', data, 52 + 32 + 12, 0x100020)
        with self.assertRaisesRegex(ValueError, 'overlapping physical'):
            plan_elf(data)
        with self.assertRaisesRegex(ValueError, 'reserved'):
            plan_elf(kernel(), [(0x100000, 0x300000)], [(0x200020, 0x200040)])
        with self.assertRaisesRegex(ValueError, 'usable memory'):
            plan_elf(kernel(), [(0x100000, 0x200020)])

    def test_entry_must_be_unique_executable_and_file_backed(self):
        for entry in (0xc0100030, 0xc0200000, 0xc0300000):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                plan_elf(kernel(entry=entry))
        segments = [(1, 0x1000, 0xc0100000, 0x100000, 0x20, 0x40, 5, 0x1000),
                    (1, 0x2000, 0xc0100000, 0x200000, 0x20, 0x40, 5, 0x1000)]
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            plan_elf(kernel(segments))

    def test_rejects_invalid_range(self):
        for bounds in ([(-1, 2)], [(1, 1)], [(0, (1 << 32) + 1)]):
            with self.subTest(bounds=bounds), self.assertRaisesRegex(ValueError, 'range'):
                plan_elf(kernel(), bounds)


if __name__ == '__main__':
    unittest.main()
