import ctypes
import pathlib
import struct
import subprocess
import tempfile
import unittest
import uuid
import zlib

HERE = pathlib.Path(__file__).resolve().parent
U8 = ctypes.c_uint8


class Range(ctypes.Structure):
    _fields_ = [('start', ctypes.c_uint64), ('end', ctypes.c_uint64)]


class Capture(ctypes.Structure):
    _fields_ = [('config_address', ctypes.c_uint32), ('config_length', ctypes.c_uint32),
                ('rsdp_address', ctypes.c_uint32), ('rsdp_length', ctypes.c_uint32),
                ('config', U8 * 1280), ('rsdp', U8 * 256)]


READ = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                        ctypes.c_void_p, ctypes.c_uint32)


def rsdp():
    data = bytearray(36)
    data[:8] = b'RSD PTR '
    data[15] = 2
    struct.pack_into('<I', data, 20, len(data))
    data[8] = -sum(data[:20]) % 256
    data[32] = -sum(data) % 256
    return bytes(data)


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        so = pathlib.Path(cls.tmp.name) / 'capture.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(HERE / 'table_capture.c'), '-o', str(so)], check=True)
        cls.lib = ctypes.CDLL(str(so))
        cls.fn = cls.lib.tc_capture_tables
        cls.fn.argtypes = [ctypes.POINTER(U8), ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.POINTER(U8), ctypes.c_uint32, ctypes.POINTER(Range),
                           ctypes.c_uint32, READ, ctypes.c_void_p, ctypes.POINTER(Capture)]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.map = bytearray(struct.pack('<IIQQQQ', 6, 0, 0x1000, 0, 16, 8))
        self.system = bytearray(72)
        self.system[:8] = b'IBI SYST'
        struct.pack_into('<I', self.system, 12, len(self.system))
        struct.pack_into('<II', self.system, 64, 1, 0x2000)
        struct.pack_into('<I', self.system, 16, zlib.crc32(self.system))
        self.config = uuid.UUID('8868e871-e4f1-11d3-bc22-0080c73c8881').bytes_le + struct.pack('<I', 0x3000)
        self.memory = {0x2000: self.config, 0x3000: rsdp()}
        self.reads = []
        self.read_overrides = {}
        self.protected = [Range(0x8000, 0x9000)]

    def run_capture(self):
        @READ
        def read(_ctx, address, output, size):
            self.reads.append((address, size))
            data = self.read_overrides.get((address, size, self.reads.count((address, size))),
                                           self.memory.get(address, b''))
            if len(data) < size:
                return -1
            ctypes.memmove(output, data, size)
            return 0
        out = Capture()
        ctypes.memset(ctypes.byref(out), 0xa5, ctypes.sizeof(out))
        before = bytes(out)
        buf = (U8 * len(self.map)).from_buffer_copy(self.map)
        sys = (U8 * len(self.system)).from_buffer_copy(self.system)
        ranges = (Range * len(self.protected))(*self.protected)
        result = self.fn(buf, len(buf), 40, sys, len(sys), ranges,
                         len(ranges), read, None, ctypes.byref(out))
        return result, out, before

    def test_valid_capture(self):
        result, out, _ = self.run_capture()
        self.assertEqual(result, 0)
        self.assertEqual(bytes(out.config[:out.config_length]), self.config)
        self.assertEqual(bytes(out.rsdp[:out.rsdp_length]), rsdp())

    def test_overlap_and_bad_memory_never_write_output(self):
        for protected, expected_reads in [([Range(0x2000, 0x3000)], []),
                                          ([Range(0x3000, 0x4000)], [(0x2000, 20)])]:
            with self.subTest(protected=protected[0].start):
                self.protected = protected
                self.reads = []
                result, out, before = self.run_capture()
                self.assertEqual(result, -1)
                self.assertEqual(bytes(out), before)
                self.assertEqual(self.reads, expected_reads)

    def test_rejects_uncovered_and_conflicting_descriptors(self):
        self.map += struct.pack('<IIQQQQ', 11, 0, 0x3000, 0, 1, 0)
        result, out, before = self.run_capture()
        self.assertEqual(result, -1)
        self.assertEqual(bytes(out), before)
        self.assertEqual(self.reads, [(0x2000, 20)])

    def test_rejects_bad_checksum_and_oversized_count(self):
        self.memory[0x3000] = b'RSD PTR ' + bytes(28)
        result, out, before = self.run_capture()
        self.assertEqual(result, -1)
        self.assertEqual(bytes(out), before)
        struct.pack_into('<I', self.system, 64, 0xffffffff)
        struct.pack_into('<I', self.system, 16, 0)
        struct.pack_into('<I', self.system, 16, zlib.crc32(self.system))
        self.reads = []
        result, out, before = self.run_capture()
        self.assertEqual(result, -1)
        self.assertEqual(bytes(out), before)
        self.assertEqual(self.reads, [])

    def test_bad_system_crc_does_not_read(self):
        self.system[20] ^= 1
        result, out, before = self.run_capture()
        self.assertEqual(result, -1)
        self.assertEqual(bytes(out), before)
        self.assertEqual(self.reads, [])

    def test_changed_final_rsdp_read_is_revalidated(self):
        for field in ('signature', 'legacy', 'revision', 'length'):
            with self.subTest(field=field):
                changed = bytearray(rsdp())
                if field == 'signature':
                    changed[0] ^= 1
                elif field == 'legacy':
                    changed[9] ^= 1
                elif field == 'revision':
                    changed[15] = 0
                else:
                    struct.pack_into('<I', changed, 20, 37)
                if field in ('signature', 'revision'):
                    changed[8] = 0
                    changed[8] = -sum(changed[:20]) % 256
                # Preserve the extended checksum so it cannot mask the check.
                changed[32] = 0
                changed[32] = -sum(changed) % 256
                self.reads = []
                self.read_overrides = {(0x3000, 36, 2): bytes(changed)}
                result, out, before = self.run_capture()
                self.assertEqual(result, -1)
                self.assertEqual(bytes(out), before)


if __name__ == '__main__':
    unittest.main()
