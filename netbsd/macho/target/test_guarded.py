"""Synthetic integration only; no physical firmware access or handoff."""
import ctypes
import pathlib
import struct
import subprocess
import tempfile
import unittest

import test_firmware
from test_firmware import READ
from test_scratch import Range, TargetPlan, desc

HERE = pathlib.Path(__file__).parent


class GuardedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        lib = pathlib.Path(cls.tmp.name) / 'guarded.so'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-fPIC', '-DTARGET_EMULATION_ONLY', str(HERE / 'guarded.c'),
                        str(HERE / 'firmware.c'), str(HERE / 'plan.c'),
                        str(HERE / 'scratch.c'), str(HERE.parent / 'native/handoff.c'),
                        '-o', str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.fn = cls.lib.target_guarded_plan_emulation
        cls.fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.POINTER(Range), ctypes.c_uint32, READ, ctypes.c_void_p,
                           ctypes.c_uint64, ctypes.POINTER(TargetPlan)]
        cls.fn.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_guard_precedes_map_planning(self):
        source = test_firmware.FirmwareTests('test_valid_acpi_and_runtime_overlap')
        source.setUp()
        raw_map = bytes(source.map) + desc(7, 0x100000, 0x1000)
        map_data = ctypes.create_string_buffer(raw_map)
        ident = b'\x7fELF\x01\x01\x01' + bytes(9)
        header = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, 0xc0100000,
                             52, 0, 0, 52, 32, 1, 0, 0, 0)
        ph = struct.pack('<8I', 1, 0x1000, 0xc0100000, 0x100000,
                         0x1000, 0x2000, 5, 0x1000)
        kernel = ctypes.create_string_buffer((header + ph).ljust(0x2000, b'\0'))
        protected = (Range * 1)(Range(0x2100000, 0x2200000))

        @READ
        def read(_, address, dest, size):
            if address + size > len(source.mem):
                return -1
            ctypes.memmove(dest, bytes(source.mem[address:address + size]), size)
            return 0

        def run():
            result = TargetPlan()
            result.kernel.entry = 0xdeadbeef
            rc = self.fn(kernel, len(kernel) - 1, 0x3000000, map_data, 0x2000000,
                         len(raw_map), 48, 1, 0x1100, protected, 1, read, None,
                         0x10000000, ctypes.byref(result))
            return rc, result

        rc, result = run()
        self.assertEqual(rc, 0)
        self.assertEqual(result.kernel.entry, 0x100000)
        self.assertGreaterEqual(result.scratch.stack.start, 0x102000)
        source.mem[0x2000] ^= 1  # unsupported configuration GUID
        rc, result = run()
        self.assertEqual(rc, -1)
        self.assertEqual(result.kernel.entry, 0xdeadbeef)

    def test_source_snapshot_and_selected_acpi_fail_closed(self):
        class Sources(ctypes.Structure):
            _fields_ = [('system', ctypes.c_ubyte * 72), ('config', ctypes.c_ubyte * 1280),
                        ('config_pa', ctypes.c_uint32), ('config_length', ctypes.c_uint32),
                        ('firmware', test_firmware.Result)]
        source = test_firmware.FirmwareTests('test_valid_acpi_and_runtime_overlap')
        source.setUp()
        mapping = ctypes.create_string_buffer(bytes(source.map))
        protected = (Range * 1)(Range(0x10000, 0x11000))

        @READ
        def read(_, address, dest, size):
            if address + size > len(source.mem):
                return -1
            ctypes.memmove(dest, bytes(source.mem[address:address + size]), size)
            return 0

        snapshot = self.lib.target_read_efi_sources
        snapshot.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                             ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(Range),
                             ctypes.c_uint32, READ, ctypes.c_void_p, ctypes.POINTER(Sources)]
        acpi = self.lib.target_validate_acpi
        acpi.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                         ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(Range),
                         ctypes.c_uint32, READ, ctypes.c_void_p,
                         ctypes.POINTER(test_firmware.Result)]
        result = Sources()
        self.assertEqual(snapshot(mapping, len(source.map), 48, 1, 0x1100,
                                  protected, 1, read, None, ctypes.byref(result)), 0)
        self.assertEqual((result.config_pa, result.config_length), (0x2000, 20))
        fw = test_firmware.Result()
        self.assertEqual(acpi(mapping, len(source.map), 48, 1, 0x3000,
                              protected, 1, read, None, ctypes.byref(fw)), 0)
        before = bytes(result)
        source.mem[0x1110] ^= 1
        self.assertNotEqual(snapshot(mapping, len(source.map), 48, 1, 0x1100,
                                     protected, 1, read, None, ctypes.byref(result)), 0)
        self.assertEqual(bytes(result), before)
        ctypes.memset(ctypes.byref(fw), 0xa5, ctypes.sizeof(fw))
        before_fw = bytes(fw)
        source.mem[0x7009] ^= 1
        self.assertNotEqual(acpi(mapping, len(source.map), 48, 1, 0x3000,
                                 protected, 1, read, None, ctypes.byref(fw)), 0)
        self.assertEqual(bytes(fw), before_fw)


if __name__ == '__main__':
    unittest.main()
