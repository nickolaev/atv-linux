"""Exercise freestanding native loader logic without accessing hardware."""
import ctypes
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from efi_memmap import normalize_efi_map, serialize_memmap

ROOT = Path(__file__).resolve().parent
U32 = ctypes.c_uint32
U64 = ctypes.c_uint64


class Range(ctypes.Structure):
    _fields_ = [('start', U64), ('end', U64)]


class Segment(ctypes.Structure):
    _fields_ = [(x, U32) for x in ('source_offset', 'physical_address', 'file_size', 'memory_size')]


class Plan(ctypes.Structure):
    _fields_ = [('entry', U32), ('segment_count', U32), ('segments', Segment * 16)]


WRITE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, U32, ctypes.c_void_p, U32)
ZERO = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, U32, U32)


class Inputs(ctypes.Structure):
    _fields_ = [('apple_args', ctypes.c_void_p), ('apple_args_length', U32), ('apple_args_pa', U32),
                ('efi_map', ctypes.c_void_p), ('efi_map_length', U32), ('efi_map_pa', U32),
                ('kernel', ctypes.c_void_p), ('kernel_length', U32), ('kernel_pa', U32),
                ('bootinfo', ctypes.c_void_p), ('bootinfo_capacity', U32), ('bootinfo_pa', U32),
                ('loader', Range), ('stack', Range), ('usable', ctypes.POINTER(Range)), ('usable_count', U32),
                ('reserved', ctypes.POINTER(Range)), ('reserved_count', U32),
                ('write_fn', WRITE), ('zero_fn', ZERO), ('context', ctypes.c_void_p)]


class Result(ctypes.Structure):
    _fields_ = [('plan', Plan), ('bootinfo_pa', U32), ('bootinfo_size', U32)]


def elf(segments=None, entry=0xc0100004):
    if segments is None:
        segments = [(1, 0x1000, 0xc0100000, 0x100000, 16, 32, 5, 0x1000),
                    (1, 0x2000, 0xc0200000, 0x200000, 8, 16, 6, 0x1000)]
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    header = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 3, 1, entry,
                         52, 0, 0, 52, 32, len(segments), 0, 0, 0)
    data = bytearray((header + b''.join(struct.pack('<8I', *p) for p in segments)).ljust(0x2010, b'\0'))
    data[0x1000:0x1010] = bytes(range(16))
    data[0x2000:0x2008] = b'NETBSD!!'
    return bytes(data)


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        lib = str(Path(cls.temp.name) / 'handoff.so')
        subprocess.run(['clang', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-DNB_ENABLE_EXPERIMENTAL_HANDOFF', str(ROOT / 'handoff.c'),
                        str(ROOT / 'loader.c'), '-o', lib], check=True)
        cls.lib = ctypes.CDLL(lib)
        cls.lib.nb_plan_elf.argtypes = [ctypes.c_void_p, U32, U32, ctypes.POINTER(Range), U32,
                                        ctypes.POINTER(Range), U32, ctypes.POINTER(Plan)]
        cls.lib.nb_copy_kernel.argtypes = [ctypes.POINTER(Plan), ctypes.c_void_p, U32, WRITE, ZERO, ctypes.c_void_p]
        cls.lib.nb_build_bootinfo.argtypes = [ctypes.c_void_p, U32, U32, U32, ctypes.c_void_p,
                                              U32, U32, U32, U32, ctypes.POINTER(U32)]
        cls.lib.nb_prepare_native_emulation.argtypes = [ctypes.POINTER(Inputs), ctypes.POINTER(Result)]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def plan(self, data, usable=None, reserved=None, source=0x3000000):
        if usable is None:
            usable = [Range(0x100000, 0x300000)]
        if reserved is None:
            reserved = [Range(0x4000000, 0x4100000)]
        u = (Range * len(usable))(*usable)
        r = (Range * len(reserved))(*reserved)
        buf = ctypes.create_string_buffer(data)
        plan = Plan()
        result = self.lib.nb_plan_elf(buf, len(data), source, u, len(u), r, len(r), ctypes.byref(plan))
        return result, plan, buf

    def test_plan_and_copy_two_segments_and_bss(self):
        result, plan, buf = self.plan(elf())
        self.assertEqual((result, plan.entry, plan.segment_count), (0, 0x100004, 2))
        calls = []
        @WRITE
        def write(_, address, data, size):
            calls.append(('write', address, ctypes.string_at(data, size)))
            return 0
        @ZERO
        def zero(_, address, size):
            calls.append(('zero', address, size))
            return 0
        self.assertEqual(self.lib.nb_copy_kernel(ctypes.byref(plan), buf, len(buf)-1, write, zero, None), 0)
        self.assertEqual(calls, [('write', 0x100000, bytes(range(16))), ('zero', 0x100010, 16),
                                 ('write', 0x200000, b'NETBSD!!'), ('zero', 0x200008, 8)])

    def test_fail_closed_on_invalid_elf_and_ranges(self):
        good = elf()
        variants = [b'bad', good[:60]]
        for offset, value in ((5, 2), (18, 0x3e)):
            changed = bytearray(good); changed[offset] = value; variants.append(bytes(changed))
        for data in variants:
            result, plan, _ = self.plan(data)
            self.assertEqual((result, plan.segment_count), (-1, 0))
        cases = [([Range(0x100000, 0x200008)], [Range(0x4000000, 0x4100000)], 0x3000000),
                 ([Range(0x100000, 0x300000)], [Range(0x200005, 0x200010)], 0x3000000),
                 ([Range(0x100000, 0x300000)], [Range(0x4000000, 0x4100000)], 0x100000),
                 ([Range(0x300000, 0x100000)], [Range(0x4000000, 0x4100000)], 0x3000000)]
        for usable, reserved, source in cases:
            result, plan, _ = self.plan(good, usable, reserved, source)
            self.assertEqual((result, plan.segment_count), (-1, 0))

    def test_rejects_overlap_overflow_and_nonexecutable_entry(self):
        for offset, value in ((52 + 32 + 12, 0x100010), (52 + 12, 0xfffffff0),
                              (52 + 28, 3), (52 + 24, 4), (52 + 16, 64)):
            data = bytearray(elf()); struct.pack_into('<I', data, offset, value)
            result, plan, _ = self.plan(bytes(data))
            self.assertEqual((result, plan.segment_count), (-1, 0))

    def test_copy_validates_all_before_writing_and_stops_on_failure(self):
        _, plan, buf = self.plan(elf())
        calls = []
        @WRITE
        def write(_, address, data, size):
            calls.append(address)
            return -1
        @ZERO
        def zero(_, address, size):
            calls.append(address)
            return 0
        plan.segments[1].source_offset = 0xffffffff
        self.assertEqual(self.lib.nb_copy_kernel(ctypes.byref(plan), buf, len(buf)-1, write, zero, None), -1)
        self.assertEqual(calls, [])
        _, plan, buf = self.plan(elf())
        self.assertEqual(self.lib.nb_copy_kernel(ctypes.byref(plan), buf, len(buf)-1, write, zero, None), -1)
        self.assertEqual(calls, [0x100000])

    def test_bootinfo_matches_netbsd_layout_and_preserves_map(self):
        desc = bytes((i % 251 for i in range(48 * 40)))
        src = ctypes.create_string_buffer(desc)
        dst = ctypes.create_string_buffer(4096)
        used = U32()
        result = self.lib.nb_build_bootinfo(dst, len(dst), 0x3000000, 0x2b57f10,
                                           src, len(desc), 0x2b06000, 48, 1, ctypes.byref(used))
        self.assertEqual(result, 0)
        self.assertEqual(used.value, 12 + 32 + 23 + len(desc))
        raw = dst.raw[:used.value]
        self.assertEqual(struct.unpack_from('<III', raw), (2, 0x300000c, 0x300002c))
        self.assertEqual(struct.unpack_from('<IIQI', raw, 12), (32, 14, 0x2b57f10, 1))
        self.assertEqual(struct.unpack_from('<IIIII', raw, 44), (23 + len(desc), 15, 40, 1, 48))
        self.assertEqual(raw[64:64+len(desc)], desc)
        self.assertEqual(raw[-3:], bytes(3))

    def test_bootinfo_rejects_overlap_and_bad_size_without_writes(self):
        src = ctypes.create_string_buffer(bytes(48))
        dst = ctypes.create_string_buffer(b'X' * 128)
        used = U32(123)
        for dst_pa, table, src_len, map_pa, stride in ((0x3000000, 0x2b57f10, 48, 0x3000020, 48),
                                                        (0x3000000, 0, 48, 0x2b06000, 48),
                                                        (0x3000000, 0x2b57f10, 47, 0x2b06000, 48),
                                                        (0xfffffff0, 0x2b57f10, 48, 0x2b06000, 48)):
            used.value = 123
            result = self.lib.nb_build_bootinfo(dst, 128, dst_pa, table, src, src_len, map_pa, stride, 1, ctypes.byref(used))
            self.assertEqual((result, used.value), (-1, 123))
            self.assertEqual(dst.raw[:128], b'X' * 128)

    def test_bootinfo_rejects_used_pointer_alias(self):
        src = ctypes.create_string_buffer(b'Y' * 48)
        dst = ctypes.create_string_buffer(b'X' * 128)
        alias = ctypes.cast(src, ctypes.POINTER(U32))
        result = self.lib.nb_build_bootinfo(dst, 128, 0x3000000, 0x2b57f10,
                                           src, 48, 0x2b06000, 48, 1, alias)
        self.assertEqual(result, -1)
        self.assertEqual(src.raw[:48], b'Y' * 48)
        self.assertEqual(dst.raw[:128], b'X' * 128)

    def test_planner_rejects_result_alias_without_mutation(self):
        data = ctypes.create_string_buffer(elf())
        before = data.raw
        usable = (Range * 1)(Range(0x100000, 0x300000))
        reserved = (Range * 1)(Range(0x4000000, 0x4100000))
        output = ctypes.cast(data, ctypes.POINTER(Plan))
        self.assertEqual(self.lib.nb_plan_elf(data, len(data)-1, 0x3000000,
                                             usable, 1, reserved, 1, output), -1)
        self.assertEqual(data.raw, before)

    def integration_fixture(self):
        args = ctypes.create_string_buffer(0x44c)
        struct.pack_into('<IIIII', args, 0x404, 0x2b06000, 48 * 40, 48, 1, 0)
        struct.pack_into('<I', args, 0x444, 0x2b57f10)
        args[0x448] = b'\x20'
        mmap = bytearray(48 * 40)
        struct.pack_into('<I4xQQQQ', mmap, 0, 7, 0x100000, 0, 0x200, 8)
        for i in range(1, 40):
            struct.pack_into('<I4xQQQQ', mmap, 48 * i, 0, 0x100000000 + i * 4096, 0, 1, 0)
        # This synthetic descriptor covers the table's entire bounded header.
        struct.pack_into('<I4xQQQQ', mmap, 48, 6, 0x2b57000, 0x2b57000, 1, (1 << 63) | 15)
        mmap = ctypes.create_string_buffer(bytes(mmap))
        kernel = ctypes.create_string_buffer(elf())
        bootinfo = ctypes.create_string_buffer(b'X' * 4096)
        usable = (Range * 1)(Range(0x100000, 0x300000))
        reserved = (Range * 1)(Range(0x4000000, 0x4100000))
        calls = []
        @WRITE
        def write(_, address, data, size):
            calls.append(('write', address, size)); return 0
        @ZERO
        def zero(_, address, size):
            calls.append(('zero', address, size)); return 0
        x = Inputs(ctypes.addressof(args), 0x44c, 0x2b00000,
                   ctypes.addressof(mmap), 48 * 40, 0x2b06000,
                   ctypes.addressof(kernel), len(kernel)-1, 0x3000000,
                   ctypes.addressof(bootinfo), 4096, 0x280000,
                   Range(0x2000000, 0x2100000), Range(0x290000, 0x294000),
                   usable, 1, reserved, 1, write, zero, None)
        return x, args, mmap, kernel, bootinfo, usable, reserved, write, zero, calls

    def test_integration_prepares_captured_shape(self):
        x, args, mmap, kernel, bootinfo, usable, reserved, write, zero, calls = self.integration_fixture()
        result = Result()
        self.assertEqual(self.lib.nb_prepare_native_emulation(ctypes.byref(x), ctypes.byref(result)), 0)
        self.assertEqual((result.plan.entry, result.plan.segment_count), (0x100004, 2))
        self.assertEqual(result.bootinfo_pa, 0x280000)
        reservations = [(0x2000000, 0x2100000), (0x290000, 0x294000),
                        (0x2b00000, 0x2b0044c), (0x2b06000, 0x2b06780),
                        (0x280000, 0x281000), (0x2b57000, 0x2b58000),
                        (0x3000000, 0x3000000 + len(kernel)-1), (0x4000000, 0x4100000)]
        expected = serialize_memmap(normalize_efi_map(mmap.raw[:1920], 48, reserved_ranges=reservations))
        self.assertEqual(result.bootinfo_size, 44 + len(expected))
        self.assertEqual(bootinfo.raw[44:result.bootinfo_size], expected)
        self.assertEqual(struct.unpack_from('<II', bootinfo.raw, 12), (32, 14))
        self.assertEqual(len(calls), 4)

    def test_integration_observed_runtime_overlap(self):
        x, args, mmap, kernel, bootinfo, usable, reserved, write, zero, calls = self.integration_fixture()
        struct.pack_into('<I4xQQQQ', mmap, 48, 7, 0x02b07000, 0, 0xb33c, 8)
        struct.pack_into('<I4xQQQQ', mmap, 96, 5, 0x02b07000, 0x02b07000, 0x25, (1 << 63) | 15)
        struct.pack_into('<I4xQQQQ', mmap, 144, 6, 0x02b2c000, 0x02b2c000, 0x2b, (1 << 63) | 15)
        struct.pack_into('<I4xQQQQ', mmap, 192, 6, 0x02b57000, 0x02b57000, 1, (1 << 63) | 15)
        result = Result()
        self.assertEqual(self.lib.nb_prepare_native_emulation(ctypes.byref(x), ctypes.byref(result)), 0)
        count = struct.unpack_from('<I', bootinfo.raw, 52)[0]
        regions = [struct.unpack_from('<QQI', bootinfo.raw, 56 + i * 20) for i in range(count)]
        self.assertTrue(any(start <= 0x02b07000 and start + size >= 0x02b58000 and typ == 2
                            for start, size, typ in regions))
        self.assertFalse(any(start < 0x02b58000 and start + size > 0x02b07000 and typ == 1
                             for start, size, typ in regions))

        # Firmware order must not affect overlap precedence or serialization.
        original = mmap.raw[:1920]
        descriptors = [original[i:i+48] for i in range(0, 1920, 48)]
        mmap.raw = b''.join(reversed(descriptors)) + b'\0'
        second_info = ctypes.create_string_buffer(b'X' * 4096)
        x.bootinfo = ctypes.addressof(second_info)
        second = Result()
        self.assertEqual(self.lib.nb_prepare_native_emulation(ctypes.byref(x), ctypes.byref(second)), 0)
        self.assertEqual(second_info.raw[:second.bootinfo_size], bootinfo.raw[:result.bootinfo_size])

    def test_integration_table_coverage_rejects_before_writes(self):
        for change in ('missing', 'partial', 'code-overlap', 'reserved-overlap',
                       'conflicting-data', 'overflowing-descriptor', 'table-wrap'):
            with self.subTest(change=change):
                x, args, mmap, kernel, bootinfo, usable, reserved, write, zero, calls = self.integration_fixture()
                if change == 'missing':
                    struct.pack_into('<I4xQQQQ', mmap, 48, 7, 0x2b57000, 0, 1, 8)
                elif change == 'partial':
                    # Only a single page covers the first byte; the bounded
                    # header would cross the page (and is rejected up front).
                    struct.pack_into('<I', args, 0x444, 0x2b57fc0)
                elif change in ('code-overlap', 'reserved-overlap', 'conflicting-data'):
                    typ = {'code-overlap': 5, 'reserved-overlap': 0, 'conflicting-data': 4}[change]
                    struct.pack_into('<I4xQQQQ', mmap, 96, typ, 0x2b57000, 0, 1, 0)
                elif change == 'overflowing-descriptor':
                    struct.pack_into('<I4xQQQQ', mmap, 96, 6, 0xfffffffffffff000, 0, 2, 0)
                else:
                    struct.pack_into('<I', args, 0x444, 0xffffffe0)
                result = Result()
                ctypes.memset(ctypes.byref(result), 0xa5, ctypes.sizeof(result))
                before = bytes(result)
                self.assertEqual(self.lib.nb_prepare_native_emulation(ctypes.byref(x), ctypes.byref(result)), -1)
                self.assertEqual(bytes(result), before)
                self.assertEqual(bootinfo.raw[:4096], b'X' * 4096)
                self.assertEqual(calls, [])

    def test_integration_table_coverage_accepts_data_types(self):
        for typ in (2, 4, 6):
            with self.subTest(typ=typ):
                x, args, mmap, kernel, bootinfo, usable, reserved, write, zero, calls = self.integration_fixture()
                struct.pack_into('<I', mmap, 48, typ)
                result = Result()
                self.assertEqual(self.lib.nb_prepare_native_emulation(ctypes.byref(x), ctypes.byref(result)), 0)
                self.assertEqual(result.plan.entry, 0x100004)

    def test_cluster_limit_includes_isa_hole_split(self):
        for extra, expected in ((28, 0), (29, -1)):
            with self.subTest(extra=extra):
                x, args, mmap, kernel, bootinfo, usable, reserved, write, zero, calls = self.integration_fixture()
                raw = bytearray(mmap.raw[:1920])
                # The conventional range crosses the 0xa0000-0x100000 ISA
                # hole, adding one cluster below it. The other three low
                # clusters are separated by stack and bootinfo reservations.
                struct.pack_into('<I4xQQQQ', raw, 0, 7, 0, 0, 0x300, 8)
                for i in range(extra):
                    raw += struct.pack('<I4xQQQQ8x', 7, 0x200000000 + i * 0x2000, 0, 1, 8)
                expanded = ctypes.create_string_buffer(bytes(raw))
                x.efi_map = ctypes.addressof(expanded)
                x.efi_map_length = len(raw)
                struct.pack_into('<I', args, 0x408, len(raw))
                result = Result()
                self.assertEqual(self.lib.nb_prepare_native_emulation(ctypes.byref(x), ctypes.byref(result)), expected)
                if expected:
                    self.assertEqual(calls, [])
                    self.assertEqual(bootinfo.raw[:4096], b'X' * 4096)

    def test_integration_rejects_inconsistent_map_stack_and_overlap_before_writes(self):
        for change in ('restricted-overlap-desc', 'runtime-desc', 'short-stack', 'outside-stack',
                       'loader-stack', 'reserved-stack', 'table-straddle', 'map-mismatch',
                       'kernel-map', 'kernel-args', 'args-map', 'small-bootinfo'):
            with self.subTest(change=change):
                x, args, mmap, kernel, bootinfo, usable, reserved, write, zero, calls = self.integration_fixture()
                if change == 'restricted-overlap-desc':
                    struct.pack_into('<I4xQQQQ', mmap, 48, 6, 0x180000, 0, 1, (1 << 63) | 8)
                elif change == 'runtime-desc':
                    struct.pack_into('<Q', mmap, 32, (1 << 63) | 8)
                elif change == 'short-stack':
                    x.stack = Range(0x290000, 0x293ffc)
                elif change == 'outside-stack':
                    x.stack = Range(0x300000, 0x304000)
                elif change == 'loader-stack':
                    x.loader = Range(0x290000, 0x2a0000)
                elif change == 'reserved-stack':
                    reserved[0] = Range(0x290000, 0x2a0000)
                elif change == 'table-straddle':
                    struct.pack_into('<I', args, 0x444, 0x2b57f84)
                elif change == 'kernel-map':
                    x.kernel_pa = x.efi_map_pa
                elif change == 'kernel-args':
                    x.kernel_pa = x.apple_args_pa
                elif change == 'args-map':
                    x.apple_args_pa = x.efi_map_pa
                elif change == 'small-bootinfo':
                    x.bootinfo_capacity = 64
                else:
                    struct.pack_into('<I', args, 0x404, 0x2b08000)
                result = Result()
                self.assertEqual(self.lib.nb_prepare_native_emulation(ctypes.byref(x), ctypes.byref(result)), -1)
                self.assertEqual((result.plan.entry, result.plan.segment_count, result.bootinfo_size), (0, 0, 0))
                self.assertEqual(bootinfo.raw[:4096], b'X' * 4096)
                self.assertEqual(calls, [])

    def test_integration_rejects_aliases_without_touching_any_input(self):
        for change in ('result-input', 'result-bootinfo', 'bootinfo-kernel', 'bootinfo-args'):
            with self.subTest(change=change):
                x, args, mmap, kernel, bootinfo, usable, reserved, write, zero, calls = self.integration_fixture()
                before_args, before_kernel, before_output = args.raw, kernel.raw, bootinfo.raw
                before_input = ctypes.string_at(ctypes.byref(x), ctypes.sizeof(x))
                result = Result()
                result_ptr = ctypes.pointer(result)
                if change == 'result-input':
                    result_ptr = ctypes.cast(ctypes.byref(x), ctypes.POINTER(Result))
                elif change == 'result-bootinfo':
                    result_ptr = ctypes.cast(bootinfo, ctypes.POINTER(Result))
                elif change == 'bootinfo-kernel':
                    x.bootinfo = ctypes.addressof(kernel)
                    before_input = ctypes.string_at(ctypes.byref(x), ctypes.sizeof(x))
                else:
                    x.bootinfo = ctypes.addressof(args)
                    before_input = ctypes.string_at(ctypes.byref(x), ctypes.sizeof(x))
                self.assertEqual(self.lib.nb_prepare_native_emulation(ctypes.byref(x), result_ptr), -1)
                self.assertEqual((args.raw, kernel.raw, bootinfo.raw), (before_args, before_kernel, before_output))
                self.assertEqual(ctypes.string_at(ctypes.byref(x), ctypes.sizeof(x)), before_input)
                self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
