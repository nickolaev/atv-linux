"""SMBIOS2 validator uses synthetic immutable bytes, never hardware reads."""
import ctypes
import pathlib
import struct
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).parent


class Range(ctypes.Structure):
    _fields_ = [('start', ctypes.c_uint64), ('end', ctypes.c_uint64)]


class Result(ctypes.Structure):
    _fields_ = [('count', ctypes.c_uint32), ('reservations', Range * 32)]


READ = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                        ctypes.c_void_p, ctypes.c_uint32)


class SmbiosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        lib = pathlib.Path(cls.tmp.name) / 'smbios.so'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-fPIC', '-DTARGET_EMULATION_ONLY', str(HERE / 'smbios.c'),
                        '-o', str(lib)], check=True)
        cls.fn = ctypes.CDLL(str(lib)).target_validate_smbios2
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
        self.table = bytearray(b'\x01\x04\x00\x00board\x00\x00\x7f\x04\xff\xff\x00\x00')
        self.mem[0x3000:0x3000+len(self.table)] = self.table
        self.entry = bytearray(31)
        self.entry[:4] = b'_SM_'
        self.entry[5:8] = bytes((31, 2, 6))
        self.entry[16:21] = b'_DMI_'
        struct.pack_into('<HIHB', self.entry, 22, len(self.table), 0x3000, 2, 0x26)
        self.update_entry()
        self.protected = (Range * 1)(Range(0x10000, 0x11000))
        self.reads = []
        self.fail_address = None
        self.entry_pa = 0x2000

    def update_entry(self):
        self.entry[21] = 0
        self.entry[21] = (-sum(self.entry[16:31])) & 255
        self.entry[4] = 0
        self.entry[4] = (-sum(self.entry)) & 255
        self.mem[0x2000:0x2000+len(self.entry)] = self.entry

    def run_guard(self):
        @READ
        def read(_, address, dest, length):
            self.reads.append((address, length))
            if address == self.fail_address or address + length > len(self.mem):
                return -1
            ctypes.memmove(dest, bytes(self.mem[address:address+length]), length)
            return 0
        memory_map = ctypes.create_string_buffer(bytes(self.map))
        result = Result()
        ctypes.memset(ctypes.byref(result), 0xa5, ctypes.sizeof(result))
        before = bytes(result)
        code = self.fn(memory_map, len(self.map), 48, 1, self.entry_pa, self.protected,
                       len(self.protected), read, None, ctypes.byref(result))
        if code:
            self.assertEqual(bytes(result), before)
        return code, result

    def test_valid_and_full_backing_descriptor_reserved(self):
        code, result = self.run_guard()
        self.assertEqual(code, 0)
        self.assertEqual(result.count, 1)
        self.assertEqual((result.reservations[0].start, result.reservations[0].end),
                         (0x1000, 0x10000))

    def test_bad_primary_and_intermediate_checksums(self):
        self.mem[0x2004] ^= 1
        self.assertNotEqual(self.run_guard()[0], 0)
        self.mem[0x2004] ^= 1
        self.entry[21] ^= 1
        self.entry[4] = 0
        self.entry[4] = (-sum(self.entry)) & 255
        self.mem[0x2000:0x201f] = self.entry
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_missing_anchors_and_invalid_entry_length(self):
        for offset, value in ((0, 0), (5, 30), (16, 0)):
            with self.subTest(offset=offset):
                old = self.mem[0x2000+offset]
                self.mem[0x2000+offset] = value
                self.assertNotEqual(self.run_guard()[0], 0)
                self.mem[0x2000+offset] = old

    def test_unterminated_invalid_length_and_bad_count(self):
        for offset, value in ((1, 3), (len(self.table)-1, 1), (0, 127)):
            with self.subTest(offset=offset):
                old = self.mem[0x3000+offset]
                self.mem[0x3000+offset] = value
                self.assertNotEqual(self.run_guard()[0], 0)
                self.mem[0x3000+offset] = old
        struct.pack_into('<H', self.entry, 28, 1)
        self.update_entry()
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_outside_memory_wrap_conflict_and_protected(self):
        for addr in (0, 0xfffffff0, 0x20000):
            with self.subTest(addr=addr):
                struct.pack_into('<I', self.entry, 24, addr)
                self.update_entry()
                self.assertNotEqual(self.run_guard()[0], 0)
        struct.pack_into('<I', self.entry, 24, 0x3000)
        self.update_entry()
        self.map += struct.pack('<IIQQQQ', 5, 0, 0x3000, 0, 1, 0) + bytes(8)
        self.assertNotEqual(self.run_guard()[0], 0)
        self.map = self.map[:-48]
        self.protected = (Range * 1)(Range(0x9000, 0xa000))
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_callback_failure_and_bad_map(self):
        self.fail_address = 0x3000
        self.assertNotEqual(self.run_guard()[0], 0)
        self.fail_address = None
        struct.pack_into('<Q', self.map, 24, 0)
        self.assertNotEqual(self.run_guard()[0], 0)

    def test_terminator_crosses_read_chunk(self):
        self.table = bytearray(b'\x01\x04\x00\x00' + b'a'*255 + b'\x00\x00' +
                               b'\x7f\x04\xff\xff\x00\x00')
        self.mem[0x3000:0x3000+len(self.table)] = self.table
        struct.pack_into('<H', self.entry, 22, len(self.table))
        self.update_entry()
        self.assertEqual(self.run_guard()[0], 0)

    def test_unaligned_entry_requires_both_mapped_pages(self):
        self.entry_pa = 0x1f00
        self.mem[0x1f00:0x1f1f] = self.entry
        self.assertEqual(self.run_guard()[0], 0)
        # A conflicting descriptor in the second mapped page must fail before
        # any physical read, even though entry bytes lie in the first page.
        self.reads.clear()
        self.map += struct.pack('<IIQQQQ', 5, 0, 0x2000, 0, 1, 0) + bytes(8)
        self.assertNotEqual(self.run_guard()[0], 0)
        self.assertEqual(self.reads, [])
        self.map = self.map[:-48]
        struct.pack_into('<Q', self.map, 48+24, 1)  # data ends at 0x2000
        self.assertNotEqual(self.run_guard()[0], 0)
        self.assertEqual(self.reads, [])

    def test_rejects_mapping_crossing_4g_before_read(self):
        for address in (0xffffe001, 0xfffff000, 0xffffffff):
            with self.subTest(address=address):
                self.entry_pa = address
                self.reads.clear()
                self.assertNotEqual(self.run_guard()[0], 0)
                self.assertEqual(self.reads, [])


if __name__ == '__main__':
    unittest.main()
