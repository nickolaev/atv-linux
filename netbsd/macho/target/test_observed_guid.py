"""Partial transcription of a Linux-time ATV1 observation, not a raw dump.

The source is the user's page-13 photograph on this boot. EFI addresses and
the configuration entries are observations, not evidence that those objects
are still valid, readable, identity-mapped, or reusable in a later boot. The
root-table children were not captured. The bytes used below for the EFI
header, map padding and contents are synthetic and must never be used to boot.
"""
import ctypes
import pathlib
import struct
import subprocess
import tempfile
import unittest
import uuid
import zlib

from test_firmware import READ, Range, Result

HERE = pathlib.Path(__file__).parent

# Config GUIDs and values printed by the Linux-time observer. GUIDs use their
# conventional textual form; the configuration record uses UUID bytes_le.
OBSERVED_ENTRIES = (
    ('05ad34ba-6f02-4214-952e-4da0398e2bb9', 0x0de4bb68),
    ('7739f24c-93d7-11d4-9a3a-0090273fc14d', 0x0fd04010),
    ('4c19049f-4137-4dd3-9c10-8b97a83ffdfa', 0x0de4c230),
    ('49152e77-1ada-4764-b7a2-7afefed95e8b', 0x0de4c9c4),
    ('5751da6e-1376-4e02-ba92-d294fdd30901', 0x0fe402d0),
    ('f76761dc-ff89-44e4-9c0c-cd0ada4ef983', 0x02b2fea4),
    ('eb9d2d30-2d88-11d3-9a16-0090273fc14d', 0x0fefd000),
    ('8868e871-e4f1-11d3-bc22-0080c73c8881', 0x0fefd014),
    ('eb9d2d31-2d88-11d3-9a16-0090273fc14d', 0x0fcbe000),
)

# Values printed by the observer; no root-table bytes or child entries were
# captured. Lengths are bytes. The observer reported each checksum as valid.
OBSERVED_ROOTS = (
    ('RSDT', 0x0fefd038, 0x44, True),
    ('RSDT', 0x0fefd0fc, 0x44, True),
    ('XSDT', 0x0fefd1c0, 0x64, True),
)


class ObservedGuidTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        lib = pathlib.Path(cls.tmp.name) / 'firmware.so'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                        '-shared', '-fPIC', str(HERE / 'firmware.c'),
                        '-o', str(lib)], check=True)
        cls.library = ctypes.CDLL(str(lib))
        cls.validate = cls.library.target_validate_firmware
        cls.validate.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.POINTER(Range), ctypes.c_uint32, READ,
                                 ctypes.c_void_p, ctypes.POINTER(Result)]
        cls.validate.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_photo_values_are_partial_observations(self):
        self.assertEqual(len(OBSERVED_ENTRIES), 9)
        self.assertEqual(len({uuid.UUID(guid) for guid, _ in OBSERVED_ENTRIES}), 9)
        self.assertEqual([root[2] for root in OBSERVED_ROOTS], [68, 68, 100])
        self.assertTrue(all(root[3] for root in OBSERVED_ROOTS))

    def test_guard_rejects_observed_first_non_acpi_guid_before_following_it(self):
        # The map below models only the descriptor shapes required to read
        # these two objects; it is not the 40-entry firmware map from the TV.
        def descriptor(kind, base, pages, attrs):
            return struct.pack('<IIQQQQ', kind, 0, base, 0, pages, attrs) + bytes(8)

        raw_map = (descriptor(7, 0x02b07000, 0xb33c, 15) +
                   descriptor(6, 0x02b2c000, 0x2b, (1 << 63) | 15) +
                   descriptor(6, 0x02b57000, 1, (1 << 63) | 15))
        config = b''.join(uuid.UUID(guid).bytes_le + struct.pack('<I', address)
                          for guid, address in OBSERVED_ENTRIES)
        table = bytearray(72)
        table[:8] = b'IBI SYST'
        struct.pack_into('<I', table, 12, len(table))
        struct.pack_into('<II', table, 64, len(OBSERVED_ENTRIES), 0x02b56d90)
        struct.pack_into('<I', table, 16, zlib.crc32(table))
        objects = {0x02b57f10: bytes(table), 0x02b56d90: config}
        reads = []

        @READ
        def read(_, address, dest, length):
            reads.append((address, length))
            data = objects.get(address)
            if data is None or len(data) < length:
                return -1
            ctypes.memmove(dest, data[:length], length)
            return 0

        map_buffer = ctypes.create_string_buffer(raw_map)
        result = Result()
        ctypes.memset(ctypes.byref(result), 0xa5, ctypes.sizeof(result))
        before = bytes(result)
        code = self.validate(map_buffer, len(raw_map), 48, 1, 0x02b57f10,
                             None, 0, read, None, ctypes.byref(result))
        self.assertNotEqual(code, 0)
        self.assertEqual(bytes(result), before)
        self.assertIn((0x02b56d90, 180), reads)
        self.assertNotIn(OBSERVED_ENTRIES[0][1], [address for address, _ in reads])


if __name__ == '__main__':
    unittest.main()
