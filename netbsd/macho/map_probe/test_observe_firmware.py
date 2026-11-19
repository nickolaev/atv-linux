"""Read-only, Linux-time observation of synthetic EFI data."""
import struct
import subprocess
import tempfile
import unittest
import uuid
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def checksum(data, offset):
    data[offset] = 0
    data[offset] = (-sum(data)) & 255


def fixture():
    snap = bytearray(8192)
    struct.pack_into('<15I', snap, 0, 0x50414345, 0, 0x1000, 0x2000,
                     96, 48, 1, 0x4000, 0x13, 0, 2, 96, 72, 32, 0x10004)
    # An Apple-style overlap between a conventional range and runtime data.
    struct.pack_into('<IIQQQQ', snap, 192, 7, 0, 0x4000, 0, 8, 15)
    struct.pack_into('<IIQQQQ', snap, 240, 6, 0, 0x4000, 0, 8, 0x800000000000000f)
    systab = bytearray(72)
    struct.pack_into('<QIIII', systab, 0, 0x5453595320494249, 0x1000a, 72, 0, 0)
    struct.pack_into('<II', systab, 64, 2, 0x6000)
    struct.pack_into('<I', systab, 16, zlib.crc32(systab))
    snap[64:136] = systab
    mem = bytearray(0xc000)
    mem[0x4000:0x4048] = systab
    mem[0x6000:0x6010] = uuid.UUID('8868e871-e4f1-11d3-bc22-0080c73c8881').bytes_le
    struct.pack_into('<I', mem, 0x6010, 0x8000)
    mem[0x6014:0x6024] = uuid.UUID('12345678-1234-1234-1234-1234567890ab').bytes_le
    struct.pack_into('<I', mem, 0x6024, 0xb000)
    rsdp = bytearray(36)
    rsdp[:8] = b'RSD PTR '
    rsdp[15] = 2
    struct.pack_into('<I', rsdp, 16, 0xa000)
    struct.pack_into('<I', rsdp, 20, 36)
    rsdp[8] = (-sum(rsdp[:20])) & 255
    checksum(rsdp, 32)
    mem[0x8000:0x8024] = rsdp
    root = bytearray(36)
    root[:4] = b'RSDT'
    struct.pack_into('<I', root, 4, len(root))
    checksum(root, 9)
    mem[0xa000:0xa024] = root
    return snap, mem


class ObserveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name)
        cls.exe = cls.path / 'observer'
        subprocess.run(['cc', '-DOBSERVE_HOST', '-Wall', '-Wextra', '-Werror', '-O2',
                        str(HERE / 'observe_firmware.c'), '-o', str(cls.exe)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, snap, mem):
        s, m = self.path / 'snapshot', self.path / 'memory'
        s.write_bytes(snap); m.write_bytes(mem)
        result = subprocess.run([str(self.exe), str(s), str(m)], capture_output=True, text=True)
        self.assertEqual(m.read_bytes(), mem, 'observer modified its source')
        return result

    def test_valid_config_and_acpi(self):
        s, m = fixture()
        result = self.run_case(s, m)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('Linux-time observation only', result.stdout)
        self.assertIn('8868e871-e4f1-11d3-bc22-0080c73c8881', result.stdout)
        self.assertIn('12345678-1234-1234-1234-1234567890ab', result.stdout)
        self.assertIn('checksum valid; revision=0x02', result.stdout)
        self.assertIn('RSDT address=0x0000a000 length=0x00000024 checksum=valid', result.stdout)
        self.assertIn('table semantics remain unproven', result.stdout)

    def test_children_and_fadt_references(self):
        s, m = fixture()
        root = bytearray(40)
        root[:4] = b'RSDT'
        struct.pack_into('<II', root, 4, len(root), 0)  # checksum filled below
        struct.pack_into('<I', root, 36, 0x9000)
        checksum(root, 9)
        m[0xa000:0xa028] = root
        fadt = bytearray(148)
        fadt[:4] = b'FACP'
        struct.pack_into('<I', fadt, 4, len(fadt))
        struct.pack_into('<II', fadt, 36, 0x7000, 0xb000)
        checksum(fadt, 9)
        m[0x9000:0x9000+len(fadt)] = fadt
        facs = bytearray(64); facs[:4] = b'FACS'; struct.pack_into('<I', facs, 4, 64)
        m[0x7000:0x7040] = facs
        dsdt = bytearray(36); dsdt[:4] = b'DSDT'; struct.pack_into('<I', dsdt, 4, 36)
        checksum(dsdt, 9); m[0xb000:0xb024] = dsdt
        r = self.run_case(s, m)
        self.assertIn('child 0x00 address=0x00009000 signature=FACP length=0x00000094 checksum=valid', r.stdout)
        self.assertIn('FACS=0x00007000 length=0x00000040 (header only; no checksum)', r.stdout)
        self.assertIn('DSDT=0x0000b000 length=0x00000024 checksum=valid', r.stdout)
        m[0x9009] ^= 1
        r = self.run_case(s, m)
        self.assertIn('signature=FACP length=0x00000094 checksum=invalid', r.stdout)
        self.assertNotIn('FACS=', r.stdout)

    def test_smbios_header_and_uncovered_structure_table(self):
        s, m = fixture()
        m[0x6014:0x6024] = uuid.UUID('eb9d2d31-2d88-11d3-9a16-0090273fc14d').bytes_le
        struct.pack_into('<I', m, 0x6024, 0x7000)
        entry = bytearray(31)
        entry[:4] = b'_SM_'; entry[5] = 31; entry[6:8] = b'\x02\x06'
        entry[16:21] = b'_DMI_'
        struct.pack_into('<HIH', entry, 22, 16, 0xb000, 1)
        entry[21] = (-sum(entry[16:31])) & 255
        checksum(entry, 4)
        m[0x7000:0x701f] = entry
        r = self.run_case(s, m)
        self.assertIn('SMBIOS2 entry=0x00007000 entry_checksum=valid dmi_checksum=valid', r.stdout)
        self.assertIn('structures=0x0000b000 bytes=0x0010 count=0x0001 descriptor-covered', r.stdout)
        struct.pack_into('<I', m, 0x7000+24, 0xc000)
        entry = bytearray(m[0x7000:0x701f])
        entry[21] = 0; entry[21] = (-sum(entry[16:31])) & 255; checksum(entry, 4)
        m[0x7000:0x701f] = entry
        self.assertIn('unavailable/uncovered', self.run_case(s, m).stdout)

    def test_bad_root_does_not_follow_child_and_high_xsdt_is_unavailable(self):
        s, m = fixture()
        root = bytearray(40); root[:4] = b'RSDT'
        struct.pack_into('<I', root, 4, 40)
        struct.pack_into('<I', root, 36, 0x9000)
        checksum(root, 9); root[9] ^= 1
        m[0xa000:0xa028] = root
        r = self.run_case(s, m)
        self.assertIn('checksum=invalid; children not read', r.stdout)
        self.assertNotIn('child 0x', r.stdout)
        s, m = fixture()
        rsdp = bytearray(m[0x8000:0x8024]); struct.pack_into('<Q', rsdp, 24, 1 << 32)
        checksum(rsdp, 32); m[0x8000:0x8024] = rsdp
        self.assertIn('XSDT address=above 32-bit; unavailable', self.run_case(s, m).stdout)

    def test_stale_table_prevents_following_config(self):
        s, m = fixture(); m[0x4018] ^= 1
        r = self.run_case(s, m)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('live system table unavailable or changed', r.stdout)
        self.assertNotIn('GUID ', r.stdout)

    def test_bad_snapshot_crc_rejects_before_memory_access(self):
        s, m = fixture(); s[64+24] ^= 1
        r = self.run_case(s, m)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('CRC or header invalid', r.stdout)
        self.assertNotIn('GUID ', r.stdout)

    def test_uncovered_or_conflicting_data_does_not_follow(self):
        s, m = fixture(); struct.pack_into('<I', s, 240, 5)
        r = self.run_case(s, m)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('GUID ', r.stdout)
        s, m = fixture(); struct.pack_into('<I', s, 240, 7)
        self.assertNotEqual(self.run_case(s, m).returncode, 0)

    def test_missing_or_bad_acpi_is_explicit(self):
        s, m = fixture(); m[0x8000] ^= 1
        r = self.run_case(s, m)
        self.assertEqual(r.returncode, 0)
        self.assertIn('RSDP=0x00008000 invalid/unavailable', r.stdout)
        self.assertNotIn('RSDT address=', r.stdout)
        s, m = fixture(); struct.pack_into('<I', m, 0xa004, 4097)
        self.assertIn('invalid/unavailable', self.run_case(s, m).stdout)

    def test_bad_descriptor_and_short_physical_file(self):
        s, m = fixture(); struct.pack_into('<Q', s, 240+24, 0)
        self.assertIn('invalid EFI descriptor', self.run_case(s, m).stdout)
        s, m = fixture(); self.assertNotEqual(self.run_case(s, m[:0x4004]).returncode, 0)


if __name__ == '__main__': unittest.main()
