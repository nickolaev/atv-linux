"""Hardware-only policy accepts bounded unknown SDTs, never bad checksums."""
import ctypes
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

TARGET = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TARGET))
from test_firmware import FirmwareTests, Range, READ, Result, checksum


class HardwarePolicyTests(unittest.TestCase):
    def test_unknown_sdt_requires_valid_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            libpath = pathlib.Path(tmp) / 'hardware-fw.so'
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-shared', '-fPIC', '-I', str(TARGET),
                            str(TARGET / 'hardware/firmware.c'), '-o', str(libpath)], check=True)
            lib = ctypes.CDLL(str(libpath))
            fn = lib.target_validate_firmware
            fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(Range),
                           ctypes.c_uint32, READ, ctypes.c_void_p, ctypes.POINTER(Result)]
            fn.restype = ctypes.c_int
            fixture = FirmwareTests('test_valid_acpi_and_runtime_overlap')
            fixture.fn = fn
            fixture.setUp()
            root = bytearray(44)
            root[:4] = b'RSDT'
            struct.pack_into('<III', root, 4, 44, 0, 0)
            struct.pack_into('<II', root, 36, 0x6000, 0x8000)
            checksum(root, 9)
            fixture.mem[0x4000:0x4000 + len(root)] = root
            sdt = bytearray(36)
            sdt[:4] = b'HPET'
            struct.pack_into('<I', sdt, 4, len(sdt))
            checksum(sdt, 9)
            fixture.mem[0x8000:0x8000 + len(sdt)] = sdt
            self.assertEqual(fixture.run_guard()[0], 0)
            fixture.mem[0x8009] ^= 1
            self.assertNotEqual(fixture.run_guard()[0], 0)


if __name__ == '__main__':
    unittest.main()
