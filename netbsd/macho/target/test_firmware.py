"""Bounded firmware-validator tests; no physical firmware access."""
import ctypes
import pathlib
import struct
import subprocess
import tempfile
import unittest
import uuid
import zlib

HERE = pathlib.Path(__file__).parent


class Range(ctypes.Structure):
    _fields_ = [('start', ctypes.c_uint64), ('end', ctypes.c_uint64)]


class Result(ctypes.Structure):
    _fields_ = [('count', ctypes.c_uint32), ('reservations', Range * 32)]


READ = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                        ctypes.c_void_p, ctypes.c_uint32)


def checksum(data, offset):
    data[offset] = 0
    data[offset] = (-sum(data)) & 255


class FirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        lib = pathlib.Path(cls.tmp.name) / 'firmware.so'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-fPIC', str(HERE / 'firmware.c'), '-o', str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.fn = cls.lib.target_validate_firmware
        cls.fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(Range),
                           ctypes.c_uint32, READ, ctypes.c_void_p, ctypes.POINTER(Result)]
        cls.fn.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.mem = bytearray(0x10000)
        self.map = bytearray(struct.pack('<IIQQQQ', 7, 0, 0x1000, 0, 15, 15) + bytes(8))
        self.map += struct.pack('<IIQQQQ', 6, 0, 0x1000, 0x1000, 15,
                                (1 << 63) | 15) + bytes(8)
        root = bytearray(40)
        root[:4] = b'RSDT'
        struct.pack_into('<I', root, 4, len(root))
        struct.pack_into('<I', root, 36, 0x6000)
        checksum(root, 9)
        self.mem[0x4000:0x4000+len(root)] = root
        dsdt = bytearray(64)
        dsdt[:4] = b'DSDT'
        struct.pack_into('<I', dsdt, 4, len(dsdt))
        checksum(dsdt, 9)
        self.mem[0x7000:0x7000+len(dsdt)] = dsdt
        fadt = bytearray(116)
        fadt[:4] = b'FACP'
        struct.pack_into('<I', fadt, 4, len(fadt))
        struct.pack_into('<I', fadt, 40, 0x7000)
        checksum(fadt, 9)
        self.mem[0x6000:0x6000+len(fadt)] = fadt
        rsdp = bytearray(20)
        rsdp[:8] = b'RSD PTR '
        struct.pack_into('<I', rsdp, 16, 0x4000)
        checksum(rsdp, 8)
        self.mem[0x3000:0x3014] = rsdp
        self.mem[0x2000:0x2014] = uuid.UUID('eb9d2d30-2d88-11d3-9a16-0090273fc14d').bytes_le + struct.pack('<I', 0x3000)
        self.mem[0x1100:0x1108] = b'IBI SYST'
        struct.pack_into('<I', self.mem, 0x110c, 72)
        struct.pack_into('<II', self.mem, 0x1140, 1, 0x2000)
        self.update_crc()
        self.protected = (Range * 1)(Range(0x10000, 0x11000))
        self.fail_addr = None
        self.reads = []

    def update_crc(self):
        table = bytearray(self.mem[0x1100:0x1148])
        table[16:20] = bytes(4)
        struct.pack_into('<I', self.mem, 0x1110, zlib.crc32(table))

    def run_guard(self):
        @READ
        def read(_, address, dest, size):
            self.reads.append((address, size))
            if address == self.fail_addr or address + size > len(self.mem):
                return -1
            ctypes.memmove(dest, bytes(self.mem[address:address+size]), size)
            return 0
        map_data = ctypes.create_string_buffer(bytes(self.map))
        output = Result()
        ctypes.memset(ctypes.byref(output), 0xa5, ctypes.sizeof(output))
        before = bytes(output)
        code = self.fn(map_data, len(self.map), 48, 1, 0x1100, self.protected,
                       len(self.protected), read, None, ctypes.byref(output))
        if code:
            self.assertEqual(bytes(output), before, 'failed validation changed output')
        return code, output

    def test_valid_acpi_and_runtime_overlap(self):
        code, out = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(out.count, 1)
        self.assertEqual((out.reservations[0].start, out.reservations[0].end), (0x1000, 0x10000))
        self.assertIn((0x6000, 36), self.reads)
        self.assertIn((0x7000, 36), self.reads)

    def test_unknown_or_duplicate_configuration_fails(self):
        self.mem[0x2000] ^= 1
        self.assertNotEqual(self.run_guard()[0], 0)
        self.assertNotIn((0x3000, 20), self.reads)
        self.mem[0x2000] ^= 1
        self.mem[0x2014:0x2028] = self.mem[0x2000:0x2014]
        struct.pack_into('<I', self.mem, 0x1140, 2)
        self.update_crc()
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_acpi2_xsdt_and_extended_checksum(self):
        root = bytearray(44)
        root[:4] = b'XSDT'
        struct.pack_into('<I', root, 4, len(root))
        struct.pack_into('<Q', root, 36, 0x6000)
        checksum(root, 9)
        self.mem[0x5000:0x5000+len(root)] = root
        rsdp = bytearray(36)
        rsdp[:8] = b'RSD PTR '
        rsdp[15] = 2
        struct.pack_into('<I', rsdp, 16, 0x4000)
        struct.pack_into('<I', rsdp, 20, len(rsdp))
        struct.pack_into('<Q', rsdp, 24, 0x5000)
        rsdp[8] = (-sum(rsdp[:20])) & 255
        checksum(rsdp, 32)
        self.mem[0x3000:0x3024] = rsdp
        self.mem[0x2000:0x2010] = uuid.UUID('8868e871-e4f1-11d3-bc22-0080c73c8881').bytes_le
        self.assertEqual(self.run_guard()[0], 0)
        self.mem[0x5020] ^= 1
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_conflicting_data_type_rejected(self):
        self.map += struct.pack('<IIQQQQ', 4, 0, 0x2000, 0, 1, 0) + bytes(8)
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_nested_dsdt_bad_checksum_or_pointer_fails(self):
        self.mem[0x7009] ^= 1
        self.assertNotEqual(self.run_guard()[0], 0)
        self.mem[0x7009] ^= 1
        struct.pack_into('<I', self.mem, 0x6028, 0x20000)
        fadt = bytearray(self.mem[0x6000:0x6074])
        checksum(fadt, 9)
        self.mem[0x6000:0x6074] = fadt
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_unknown_child_and_missing_fadt_fail(self):
        self.mem[0x6000:0x6004] = b'TEST'
        fadt = bytearray(self.mem[0x6000:0x6074])
        checksum(fadt, 9)
        self.mem[0x6000:0x6074] = fadt
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_facs_is_reserved_and_validated(self):
        facs = bytearray(64)
        facs[:4] = b'FACS'
        struct.pack_into('<I', facs, 4, len(facs))
        self.mem[0x8000:0x8040] = facs
        fadt = bytearray(self.mem[0x6000:0x6074])
        struct.pack_into('<I', fadt, 36, 0x8000)
        checksum(fadt, 9)
        self.mem[0x6000:0x6074] = fadt
        self.assertEqual(self.run_guard()[0], 0)
        self.mem[0x8000] ^= 1
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_nested_protected_and_overflow_pointer_fail_before_reads(self):
        self.protected[0] = Range(0x7000, 0x8000)
        self.assertNotEqual(self.run_guard()[0], 0)
        self.assertNotIn((0x7000, 36), self.reads)
        self.protected[0] = Range(0x10000, 0x11000)
        fadt = bytearray(148)
        fadt[:4] = b'FACP'
        struct.pack_into('<I', fadt, 4, len(fadt))
        struct.pack_into('<I', fadt, 40, 0x7000)
        struct.pack_into('<Q', fadt, 140, 0x100000000)
        checksum(fadt, 9)
        self.mem[0x6000:0x6000+len(fadt)] = fadt
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_streamed_dsdt_larger_than_page(self):
        dsdt = bytearray(5000)
        dsdt[:4] = b'DSDT'
        struct.pack_into('<I', dsdt, 4, len(dsdt))
        checksum(dsdt, 9)
        self.mem[0x7000:0x7000+len(dsdt)] = dsdt
        self.assertEqual(self.run_guard()[0], 0)
        self.mem[0x7000+4999] ^= 1
        self.assertNotEqual(self.run_guard()[0], 0)

    def set_madt(self, payload):
        table = bytearray(payload)
        table[:4] = b'APIC'
        struct.pack_into('<I', table, 4, len(table))
        checksum(table, 9)
        self.mem[0x9000:0x9000+len(table)] = table
        root = bytearray(44)
        root[:4] = b'RSDT'
        struct.pack_into('<III', root, 4, len(root), 0, 0)
        struct.pack_into('<II', root, 36, 0x6000, 0x9000)
        checksum(root, 9)
        self.mem[0x4000:0x4000+len(root)] = root

    def test_madt_rejects_short_and_malformed_entries(self):
        self.set_madt(bytes(36))
        self.assertNotEqual(self.run_guard()[0], 0)
        self.set_madt(bytes(44))
        self.assertEqual(self.run_guard()[0], 0)
        for entry in (bytes([0, 0]), bytes([0, 7]) + bytes(5),
                      bytes([0, 8]) + bytes(3), bytes([255, 8]) + bytes(6),
                      bytes([1, 8]) + bytes(6)):
            with self.subTest(entry=entry):
                self.set_madt(bytes(44) + entry)
                self.assertNotEqual(self.run_guard()[0], 0)
        self.set_madt(bytes(44) + bytes([0, 8]) + bytes(6) + bytes([1, 12]) + bytes(10))
        self.assertEqual(self.run_guard()[0], 0)

    def test_checksums_lengths_and_missing_reads_fail(self):
        for address in (0x1108, 0x3008, 0x4009):
            with self.subTest(address=address):
                self.mem[address] ^= 1
                self.assertNotEqual(self.run_guard()[0], 0)
                self.mem[address] ^= 1
        self.fail_addr = 0x4000
        self.assertNotEqual(self.run_guard()[0], 0)
        self.fail_addr = None
        struct.pack_into('<I', self.mem, 0x4004, 4097)
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_protected_and_conflicting_descriptors_fail_before_following(self):
        self.protected[0] = Range(0x2000, 0x3000)
        self.assertNotEqual(self.run_guard()[0], 0)
        self.assertNotIn((0x2000, 20), self.reads)
        self.protected[0] = Range(0x10000, 0x11000)
        self.map += struct.pack('<IIQQQQ', 5, 0, 0x2000, 0, 1, 0) + bytes(8)
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_conventional_alone_is_not_coverage(self):
        self.map = self.map[:48]
        self.assertNotEqual(self.run_guard()[0], 0)
        self.assertEqual(self.reads, [])

    def test_invalid_map_rejected_without_reads(self):
        struct.pack_into('<Q', self.map, 24, 0)
        self.assertNotEqual(self.run_guard()[0], 0)
        self.assertEqual(self.reads, [])


if __name__ == '__main__':
    unittest.main()
