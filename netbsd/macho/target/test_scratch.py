"""Target scratch range prototype: no firmware or physical memory access."""
import ctypes
import pathlib
import random
import struct
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).parent


class Range(ctypes.Structure):
    _fields_ = [('start', ctypes.c_uint64), ('end', ctypes.c_uint64)]


class Scratch(ctypes.Structure):
    _fields_ = [('usable', Range), ('stack', Range), ('bootinfo', Range)]


class Segment(ctypes.Structure):
    _fields_ = [(k, ctypes.c_uint32) for k in
                ('source_offset', 'physical_address', 'file_size', 'memory_size')]


class KernelPlan(ctypes.Structure):
    _fields_ = [('entry', ctypes.c_uint32), ('segment_count', ctypes.c_uint32),
                ('segments', Segment * 16)]


class TargetPlan(ctypes.Structure):
    _fields_ = [('kernel', KernelPlan), ('scratch', Scratch),
                ('usable', Range * 17), ('usable_count', ctypes.c_uint32),
                ('protected', Range * 32), ('protected_count', ctypes.c_uint32)]


def desc(kind, start, pages, attrs=8):
    return struct.pack('<IIQQQQ8x', kind, 0, start, 0, pages, attrs)


class ScratchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        lib = pathlib.Path(cls.tmp.name) / 'scratch.so'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-shared',
                        '-fPIC', str(HERE / 'scratch.c'), str(HERE / 'plan.c'),
                        str(HERE.parent / 'native/handoff.c'), '-o', str(lib)], check=True)
        cls.library = ctypes.CDLL(str(lib))
        cls.fn = cls.library.target_find_scratch
        cls.fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.c_uint32, ctypes.POINTER(Range), ctypes.c_uint32,
                           ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32,
                           ctypes.POINTER(Scratch)]
        cls.fn.restype = ctypes.c_int
        cls.plan_fn = cls.library.target_plan_memory
        cls.plan_fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.c_uint32, ctypes.POINTER(Range), ctypes.c_uint32,
                                ctypes.c_uint64, ctypes.POINTER(TargetPlan)]
        cls.plan_fn.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def plan(self, raw, reserved=(), limit=0x10000000, stride=48, version=1):
        data = ctypes.create_string_buffer(raw)
        alloc = (Range * len(reserved))(*(Range(*r) for r in reserved))
        result = Scratch(Range(7, 8), Range(9, 10), Range(11, 12))
        ret = self.fn(data, len(raw), stride, version, alloc, len(reserved), limit,
                      0x10000, 0x4000, ctypes.byref(result))
        return ret, result

    def test_photo_overlap_and_reservations(self):
        runtime = (1 << 63) | 15
        raw = (desc(7, 0x02b07000, 0xb33c, 15) +
               desc(5, 0x02b07000, 0x25, runtime) +
               desc(6, 0x02b2c000, 0x2c, runtime))
        ret, out = self.plan(raw, [(0x04000001, 0x06000001)])
        self.assertEqual(ret, 0)
        self.assertGreaterEqual(out.usable.start, 0x06001000)
        self.assertEqual(out.usable.end, 0x0de43000)
        self.assertEqual(out.stack.end, out.bootinfo.start)
        self.assertEqual(out.stack.end - out.stack.start, 0x10000)
        self.assertEqual(out.bootinfo.end - out.bootinfo.start, 0x4000)

    def test_order_and_restricted_overlap(self):
        a, b = desc(7, 0x100000, 0x100), desc(11, 0x180000, 0x80)
        for raw in (a + b, b + a):
            ret, out = self.plan(raw)
            self.assertEqual(ret, 0)
            self.assertEqual(out.usable.end, 0x180000)

    def test_no_usable_or_invalid_preserves_output(self):
        bad = [desc(2, 0x100000, 0x100), desc(7, 0x100001, 0x100),
               desc(7, 0x100000, 0), desc(7, 0xfffffffffffff000, 2)]
        for raw in bad:
            ret, out = self.plan(raw)
            self.assertEqual(ret, -1)
            self.assertEqual((out.usable.start, out.usable.end), (7, 8))
        ret, out = self.plan(desc(7, 0x100000, 0x100), [(0, 1 << 32)])
        self.assertEqual(ret, -1)
        self.assertEqual((out.stack.start, out.stack.end), (9, 10))

    def test_reject_version_and_no_write(self):
        ret, out = self.plan(desc(7, 0x100000, 0x100), version=2)
        self.assertEqual(ret, -1)
        self.assertEqual((out.bootinfo.start, out.bootinfo.end), (11, 12))

    def test_low_memory_excluded_and_4g_clipped(self):
        ret, _ = self.plan(desc(7, 0, 0x100))
        self.assertEqual(ret, -1)
        ret, out = self.plan(desc(7, 0xfff00000, 0x100), limit=1 << 32)
        self.assertEqual(ret, 0)
        self.assertEqual(out.usable.end, 0xfffff000)

    def test_output_never_intersects_random_restrictions(self):
        rng = random.Random(117)
        for _ in range(100):
            restrictions = []
            raw = desc(7, 0x100000, 0x1000)
            for _ in range(8):
                start = 0x100000 + rng.randrange(0x1000) * 4096
                end = min(start + rng.randrange(1, 40) * 4096, 0x1100000)
                raw += desc(6, start, (end - start) // 4096, 1 << 63)
                restrictions.append((start, end))
            reserved = [(0x100000 + rng.randrange(0x1000) * 4096,
                         0x1100000)]
            ret, out = self.plan(raw, reserved)
            if ret:
                continue
            for lo, hi in restrictions + reserved:
                self.assertFalse(out.usable.start < hi and lo < out.usable.end)
            self.assertLessEqual(out.usable.start, out.stack.start)
            self.assertLessEqual(out.bootinfo.end, out.usable.end)

    def test_kernel_plan_checks_map_and_reserves_destinations(self):
        ident = b'\x7fELF\x01\x01\x01' + bytes(9)
        header = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, 0xc0100000,
                             52, 0, 0, 52, 32, 1, 0, 0, 0)
        ph = struct.pack('<8I', 1, 0x1000, 0xc0100000, 0x100000,
                         0x1000, 0x2000, 5, 0x1000)
        kernel = ctypes.create_string_buffer((header + ph).ljust(0x2000, b'\0'))
        protected = (Range * 1)(Range(0x3000000, 0x3010000))

        def run(raw):
            data = ctypes.create_string_buffer(raw)
            result = TargetPlan()
            result.kernel.entry = 0xdeadbeef
            rc = self.plan_fn(kernel, len(kernel) - 1, 0x4000000, data, len(raw),
                              48, 1, protected, 1, 0x10000000, ctypes.byref(result))
            return rc, result

        raw = desc(7, 0x100000, 0x1000) + desc(7, 0x5000000, 0x1000)
        rc, result = run(raw)
        self.assertEqual(rc, 0)
        self.assertEqual((result.kernel.entry, result.kernel.segment_count), (0x100000, 1))
        self.assertEqual((result.usable[0].start, result.usable[0].end), (0x100000, 0x102000))
        self.assertGreaterEqual(result.scratch.stack.start, 0x5000000)
        rc, result = run(raw + desc(5, 0x100000, 1, 1 << 63))
        self.assertEqual(rc, -1)
        self.assertEqual(result.kernel.entry, 0xdeadbeef)


if __name__ == '__main__':
    unittest.main()
