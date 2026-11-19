import io
import struct
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import zlib

import package


def ref_mbr():
    data = bytearray(512)
    data[510:512] = b'\x55\xaa'
    data[450], data[466] = 0xee, 0xda
    data[467:470] = b'\xfe\xff\xff'
    struct.pack_into('<II', data, 454, 1, 39)
    struct.pack_into('<II', data, 470, 40, 62461)
    return bytes(data)


def gpt_image(last=196607, already_hybrid=False):
    data = bytearray(64 * 1024 * 1024)
    # Use a 64 MiB image and a recovery partition ending below its backup GPT.
    last = min(last, len(data) // 512 - 34)
    mbr = bytearray(ref_mbr())
    if already_hybrid:
        struct.pack_into('<II', mbr, 470, 40, last - 39)
    else:
        mbr[462:510] = bytes(48)
        struct.pack_into('<I', mbr, 458, len(data) // 512 - 1)
    data[:512] = mbr
    entries = bytearray(128 * 128)
    entries[:16] = package.RECOVERY_GUID
    struct.pack_into('<QQ', entries, 32, 40, last)
    data[1024:1024 + len(entries)] = entries
    header = bytearray(512)
    header[:8] = b'EFI PART'
    struct.pack_into('<IIII', header, 8, 0x10000, 92, 0, 0)
    struct.pack_into('<QQQQ', header, 24, 1, len(data) // 512 - 1, 34, len(data) // 512 - 34)
    struct.pack_into('<QIII', header, 72, 2, 128, 128, zlib.crc32(entries) & 0xffffffff)
    struct.pack_into('<I', header, 16, zlib.crc32(header[:92]) & 0xffffffff)
    data[512:1024] = header
    backup_lba = len(data) // 512 - 1
    backup_entries_lba = backup_lba - len(entries) // 512
    data[backup_entries_lba * 512:backup_lba * 512] = entries
    backup = bytearray(header)
    struct.pack_into('<I', backup, 16, 0)
    struct.pack_into('<QQ', backup, 24, backup_lba, 1)
    struct.pack_into('<Q', backup, 72, backup_entries_lba)
    struct.pack_into('<I', backup, 16, zlib.crc32(backup[:92]) & 0xffffffff)
    data[backup_lba * 512:] = backup
    return io.BytesIO(data), last


def elf():
    header = struct.pack('<16sHHIIIIIHHHHHH', b'\x7fELF\x01\x01\x01' + bytes(9),
                         2, 3, 1, 0xc0100000, 52, 0, 0, 52, 32, 1, 0, 0, 0)
    load = struct.pack('<8I', 1, 84, 0xc0100000, 0x100000, 6, 6, 5, 1)
    return header + load + b'kernel'


def macho(kernel):
    header = struct.pack('<7I', 0xfeedface, 7, 3, 2, 2, 136, 1)
    content = header + bytes(136) + kernel
    segment = struct.pack('<II16s8I', 1, 56, b'__TEXT', 0x4000000, len(content),
                          0, len(content), 7, 5, 0, 0)
    regs = [0] * 16
    regs[10] = 0x4000000 + len(header) + 136
    thread = struct.pack('<4I16I', 5, 80, 0xffffffff, 16, *regs)
    return header + segment + thread + kernel


class PackagingTests(unittest.TestCase):
    def test_hybrid_uses_actual_gpt_partition_extent(self):
        image, last = gpt_image(last=100000)
        result = package.hybrid_mbr(ref_mbr(), image)
        self.assertEqual(struct.unpack_from('<II', result, 470), (40, last - 39))
        self.assertEqual(result[446:462], ref_mbr()[446:462])
        self.assertEqual(result[478:510], bytes(32))
        already, _ = gpt_image(last=100000, already_hybrid=True)
        self.assertEqual(result, package.hybrid_mbr(ref_mbr(), already))

    def test_rejects_corrupt_gpt_and_unrelated_mbr(self):
        for where, value in ((512 + 16, 1), (1024, 0), (478, 1), (64 * 1024 * 1024 - 496, 1)):
            image, _ = gpt_image()
            image.seek(where); image.write(bytes([value]))
            with self.subTest(where=where), self.assertRaises(ValueError):
                package.hybrid_mbr(ref_mbr(), image)

    def test_rejects_crc_valid_primary_entries_overlapping_usable_space(self):
        image, _ = gpt_image(last=100000)
        data = bytearray(image.getvalue())
        # Keep the array and both CRCs valid but relocate the primary array to
        # sector 20, where its 32 sectors extend into the recovery partition.
        entries = bytes(data[1024:1024 + 128 * 128])
        data[20 * 512:20 * 512 + len(entries)] = entries
        struct.pack_into('<Q', data, 512 + 72, 20)
        struct.pack_into('<I', data, 512 + 16, 0)
        crc = zlib.crc32(data[512:512 + 92]) & 0xffffffff
        struct.pack_into('<I', data, 512 + 16, crc)
        with self.assertRaises(ValueError):
            package.hybrid_mbr(ref_mbr(), io.BytesIO(data))

    def test_exact_kernel_must_be_in_mapped_segment(self):
        with tempfile.TemporaryDirectory() as td:
            kernel = Path(td, 'kernel'); wrapper = Path(td, 'wrapper')
            kernel.write_bytes(elf()); wrapper.write_bytes(macho(elf()))
            self.assertEqual(len(package.validate_payload(wrapper, kernel)), 64)
            wrapper.write_bytes(macho(elf() + elf()))
            with self.assertRaises(ValueError): package.validate_payload(wrapper, kernel)
            wrapper.write_bytes(macho(b'other'))
            with self.assertRaises(ValueError): package.validate_payload(wrapper, kernel)
            wrapper.write_bytes(macho(elf()))
            modified = bytearray(wrapper.read_bytes()); struct.pack_into('<I', modified, 28 + 44, 1)
            wrapper.write_bytes(modified)
            with self.assertRaises(ValueError): package.validate_payload(wrapper, kernel)

    def test_source_and_output_are_regular_files(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td, 'target'); target.write_bytes(b'123')
            link = Path(td, 'link'); link.symlink_to(target)
            with self.assertRaises(ValueError): package.regular(link)

    def test_preflight_keeps_existing_output_and_rejects_missing_headroom(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); kernel = root / 'kernel'; wrapper = root / 'wrapper'
            reference = root / 'reference'; output = root / 'out.img'
            recovery = root / 'recovery'
            recovery.mkdir()
            for name in ('boot.efi', 'BootLogo.png', 'com.apple.Boot.plist'):
                (recovery / name).write_bytes(b'x')
            kext = recovery / 'System/Library/Extensions/KernelMemoryAccess.kext/Contents'
            (kext / 'MacOS').mkdir(parents=True)
            (kext / 'Info.plist').write_bytes(b'x')
            (kext / 'MacOS/KernelMemoryAccess').write_bytes(b'x')
            kernel.write_bytes(elf()); wrapper.write_bytes(macho(elf())); reference.write_bytes(ref_mbr())
            digest = package.package(wrapper, kernel, reference, output, recovery, 128, 96, True)
            self.assertEqual(len(digest), 64)
            self.assertFalse(output.exists())
            output.write_bytes(b'preserved')
            with self.assertRaises(ValueError):
                package.package(wrapper, kernel, reference, output, recovery, 128, 96, True)
            self.assertEqual(output.read_bytes(), b'preserved')
            output.unlink()
            with self.assertRaises(ValueError):
                package.package(wrapper, kernel, reference, output, recovery, 32, 31, True)
            self.assertFalse(output.exists())

    def test_rejects_macho_change_during_staging_before_builder_runs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); kernel = root / 'kernel'; wrapper = root / 'wrapper'
            reference = root / 'reference'; output = root / 'out.img'
            kernel.write_bytes(elf()); wrapper.write_bytes(macho(elf())); reference.write_bytes(ref_mbr())
            real_copy = package.shutil.copyfile
            def modified_copy(source, destination):
                result = real_copy(source, destination)
                if Path(source) == wrapper:
                    data = bytearray(Path(destination).read_bytes())
                    data[24] ^= 1  # Change Mach-O flags, preserving valid kernel and entry.
                    Path(destination).write_bytes(data)
                return result
            with mock.patch.object(package.shutil, 'copyfile', side_effect=modified_copy), \
                 mock.patch.object(package.subprocess, 'run') as builder:
                with self.assertRaisesRegex(ValueError, 'changed during packaging'):
                    package.package(wrapper, kernel, reference, output, root, 128, 96, False)
                builder.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
