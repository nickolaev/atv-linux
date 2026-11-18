import struct
import unittest
import zlib

import efi_tables as efi


def system_table(count=1, config_address=0x200000):
    data = bytearray(72)
    data[:8] = efi.EFI_SIGNATURE
    struct.pack_into('<II', data, 8, 0x1000a, len(data))
    struct.pack_into('<II', data, 64, count, config_address)
    struct.pack_into('<I', data, 16, zlib.crc32(data) & 0xffffffff)
    return bytes(data)


def rsdp(revision=2):
    data = bytearray(36 if revision >= 2 else 20)
    data[:8] = b'RSD PTR '
    data[9:15] = b'APPLE '
    data[15] = revision
    struct.pack_into('<I', data, 16, 0x1234000)
    if revision >= 2:
        struct.pack_into('<IQ', data, 20, len(data), 0x123456789)
    data[8] = -sum(data[:20]) & 255
    if revision >= 2:
        data[32] = -sum(data) & 255
    return bytes(data)


class TableTests(unittest.TestCase):
    def test_missing_configuration_is_unknown(self):
        result = efi.inspect_tables(system_table(9, 0x02b56d90), 0x02b57f10)
        self.assertEqual(result['configuration']['status'], 'not captured')
        self.assertEqual(result['configuration']['count'], 9)
        self.assertTrue(result['system_table']['crc_valid'])

    def test_valid_acpi2_and_unknown_other_entry(self):
        config = (efi.ACPI20 + struct.pack('<I', 0x300000) +
                  bytes(16) + struct.pack('<I', 0x400000))
        result = efi.inspect_tables(system_table(2), 0x100000, config,
                                    {0x300000: rsdp()})
        entries = result['configuration']['entries']
        self.assertEqual(entries[0]['kind'], 'ACPI 2.0')
        self.assertEqual(entries[0]['rsdp_status'], 'checksum valid')
        self.assertEqual(entries[0]['rsdp']['xsdt_address'], 0x123456789)
        self.assertEqual(entries[1]['address'], 0x400000)

    def test_acpi1_and_uncaptured_rsdp(self):
        config = efi.ACPI10 + struct.pack('<I', 0x300000)
        result = efi.inspect_tables(system_table(), 0x100000, config)
        self.assertEqual(result['configuration']['entries'][0]['rsdp_status'], 'not captured')
        self.assertEqual(efi.validate_rsdp(rsdp(0), 0x300000)['length'], 20)

    def test_system_header_and_crc_failures(self):
        table = bytearray(system_table())
        table[30] ^= 1
        with self.assertRaisesRegex(ValueError, 'CRC32'):
            efi.inspect_tables(bytes(table), 0x100000)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            efi.inspect_tables(system_table()[:71], 0x100000)
        with self.assertRaisesRegex(ValueError, 'span'):
            efi.inspect_tables(system_table(), 0xfffffff0)

    def test_configuration_bounds_and_missing_data(self):
        with self.assertRaisesRegex(ValueError, 'mapping bound'):
            efi.inspect_tables(system_table(205), 0x100000)
        with self.assertRaisesRegex(ValueError, 'span'):
            efi.inspect_tables(system_table(1, 0xfffffff8), 0x100000)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            efi.inspect_tables(system_table(), 0x100000, bytes(19))
        with self.assertRaisesRegex(ValueError, 'span'):
            efi.inspect_tables(system_table(1, 0), 0x100000)

    def test_rsdp_checksum_and_length_failures(self):
        bad = bytearray(rsdp())
        bad[24] ^= 1
        with self.assertRaisesRegex(ValueError, 'extended.*checksum'):
            efi.validate_rsdp(bytes(bad), 0x300000)
        bad = bytearray(rsdp())
        bad[9] ^= 1
        with self.assertRaisesRegex(ValueError, 'signature or checksum'):
            efi.validate_rsdp(bytes(bad), 0x300000)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            efi.validate_rsdp(rsdp()[:20], 0x300000)
        bad = bytearray(rsdp())
        struct.pack_into('<I', bad, 20, 4097)
        with self.assertRaisesRegex(ValueError, 'length'):
            efi.validate_rsdp(bytes(bad), 0x300000)

    def test_null_acpi_pointer_is_not_validated(self):
        result = efi.inspect_tables(system_table(), 0x100000, efi.ACPI20 + bytes(4))
        self.assertEqual(result['configuration']['entries'][0]['rsdp_status'], 'null pointer')


if __name__ == '__main__':
    unittest.main()
