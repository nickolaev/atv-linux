"""Projection uses synthetic immutable data and an injected validator only."""
import ctypes
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest
import uuid
import zlib

from test_observed_guid import OBSERVED_ENTRIES

HERE = pathlib.Path(__file__).parent


class Range(ctypes.Structure):
    _fields_ = [('start', ctypes.c_uint64), ('end', ctypes.c_uint64)]


class Result(ctypes.Structure):
    _fields_ = [('count', ctypes.c_uint32), ('reservation_count', ctypes.c_uint32),
                ('reservations', Range * 32)]


VALIDATE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                            ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64,
                            ctypes.POINTER(Range), ctypes.POINTER(ctypes.c_uint32))


def guid(value, address):
    return uuid.UUID(value).bytes_le + struct.pack('<I', address)


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        path = pathlib.Path(cls.tmp.name) / 'projection.so'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-DTARGET_EMULATION_ONLY', '-shared',
                        '-fPIC', str(HERE / 'project_efi.c'), '-o', str(path)], check=True)
        cls.lib = ctypes.CDLL(str(path))
        cls.fn = cls.lib.target_project_efi
        cls.fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.c_uint32, VALIDATE, ctypes.c_void_p, ctypes.c_void_p,
                           ctypes.POINTER(Result)]
        cls.fn.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.entries = [guid('05ad34ba-6f02-4214-952e-4da0398e2bb9', 0xdead0000),
                        guid('8868e871-e4f1-11d3-bc22-0080c73c8881', 0x3000),
                        guid('eb9d2d31-2d88-11d3-9a16-0090273fc14d', 0x4000)]
        self.calls = []
        self.fail_kind = 0
        self.bad_range = False

    def run_projection(self, *, owned=0x8000, header_corrupt=False, count=None):
        configs = b''.join(self.entries)
        system = bytearray(72)
        system[:8] = b'IBI SYST'
        struct.pack_into('<II', system, 8, 0x1000a, 72)
        struct.pack_into('<II', system, 64, len(self.entries) if count is None else count, 0x2000)
        struct.pack_into('<I', system, 16, zlib.crc32(system))
        if header_corrupt:
            system[24] ^= 1
        sbuf, cbuf = ctypes.create_string_buffer(bytes(system)), ctypes.create_string_buffer(configs)
        result = Result()
        pages = (ctypes.c_ubyte * 8192)()
        ctypes.memset(ctypes.byref(result), 0xa5, ctypes.sizeof(result))
        ctypes.memset(ctypes.byref(pages), 0xa5, ctypes.sizeof(pages))
        before = (bytes(result), bytes(pages))

        @VALIDATE
        def validate(_, kind, address, start, end, ranges, count_ptr):
            self.calls.append((kind, address))
            if kind == self.fail_kind:
                return -1
            ranges[0] = Range(start if self.bad_range else address & ~0xfff,
                              end if self.bad_range else (address & ~0xfff) + 0x1000)
            count_ptr[0] = 1
            return 0

        rc = self.fn(sbuf, len(system), 0x1000, cbuf, len(configs), 0x2000,
                     owned, validate, None, ctypes.byref(pages), ctypes.byref(result))
        return rc, result, pages, before

    def test_selects_only_validated_entries_and_recomputes_crc(self):
        rc, result, pages, _ = self.run_projection()
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [(2, 0x3000), (3, 0x4000)])
        self.assertEqual(result.count, 2)
        self.assertEqual(bytes(pages)[4096:4136], b''.join(self.entries[1:]))
        system = bytearray(pages[:72])
        self.assertEqual(struct.unpack_from('<II', system, 64), (2, 0x9000))
        actual_crc = struct.unpack_from('<I', system, 16)[0]
        system[16:20] = bytes(4)
        self.assertEqual(actual_crc, zlib.crc32(system))
        self.assertEqual(result.reservation_count, 2)

    def test_missing_smbios_or_callback_failure_never_writes_output(self):
        for failure in ('missing', 'invalid', 'overlap', 'bad_crc', 'source_overlap'):
            with self.subTest(failure=failure):
                self.setUp()
                if failure == 'missing': self.entries.pop()
                if failure == 'invalid': self.fail_kind = 3
                if failure == 'overlap': self.bad_range = True
                rc, out, pages, before = self.run_projection(owned=0x2000 if failure == 'source_overlap' else 0x8000,
                                                       header_corrupt=failure == 'bad_crc')
                self.assertEqual(rc, -1)
                self.assertEqual((bytes(out), bytes(pages)), before)

    def test_rejects_duplicate_and_smbios3(self):
        for entry in (self.entries[-1], guid('f2fd1544-9794-4a2c-992e-e5bbcf20e394', 0x5000)):
            self.setUp()
            self.entries.append(entry)
            rc, out, pages, before = self.run_projection()
            self.assertEqual(rc, -1)
            self.assertEqual((bytes(out), bytes(pages)), before)

    def test_handoff_symbol_is_not_built_without_emulation_flag(self):
        path = pathlib.Path(self.tmp.name) / 'disabled.so'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-fPIC', str(HERE / 'project_efi.c'), '-o', str(path)], check=True)
        with self.assertRaises(AttributeError):
            getattr(ctypes.CDLL(str(path)), 'target_project_efi')

    def test_observed_nine_guid_sequence_drops_unselected_without_callback(self):
        # Addresses/GUIDs are partial Linux-time photo transcriptions; all
        # validation here is synthetic and does not establish firmware safety.
        self.entries = [guid(value, address) for value, address in OBSERVED_ENTRIES]
        rc, result, pages, _ = self.run_projection()
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [(1, 0x0fefd000), (2, 0x0fefd014),
                                      (3, 0x0fcbe000)])
        self.assertEqual(result.count, 3)
        self.assertEqual(bytes(pages)[4096:4156], b''.join(self.entries[6:]))

    def test_owned_pages_aligned_and_full_extent_reserved(self):
        rc, result, pages, _ = self.run_projection()
        self.assertEqual(rc, 0)
        self.assertEqual(struct.unpack_from('<I', bytes(pages), 68)[0], 0x9000)
        self.assertEqual(self.run_projection(owned=0xffffd000)[0], 0)
        for owned in (0x8004, 0xffffe000, 0xfffff000):
            with self.subTest(owned=owned):
                rc, out, pages, before = self.run_projection(owned=owned)
                self.assertEqual(rc, -1)
                self.assertEqual((bytes(out), bytes(pages)), before)

    def test_i386_freestanding_link_without_runtime(self):
        clang, linker = shutil.which('clang'), shutil.which('ld.lld')
        if not clang or not linker:
            self.skipTest('clang and ld.lld required for freestanding link')
        obj = pathlib.Path(self.tmp.name) / 'project.o'
        elf = pathlib.Path(self.tmp.name) / 'project.elf'
        subprocess.run([clang, '--target=i386-unknown-none-elf', '-march=pentium-m',
                        '-mno-sse', '-mno-sse2', '-mno-mmx', '-mno-80387',
                        '-ffreestanding', '-fno-stack-protector', '-fno-pic',
                        '-fno-builtin', '-O2', '-DTARGET_EMULATION_ONLY', '-c',
                        str(HERE / 'project_efi.c'), '-o', str(obj)], check=True)
        subprocess.run([linker, '-m', 'elf_i386', '-e', 'target_project_efi',
                        str(obj), '-o', str(elf)], check=True)


if __name__ == '__main__':
    unittest.main()
