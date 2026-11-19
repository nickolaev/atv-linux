#!/usr/bin/env python3
"""Offline inspection of copied IA-32 EFI and ACPI data, not firmware access.

Inputs are bytes captured during the same boot, supplied explicitly by the
caller. A valid checksum does not establish physical readability, object
lifetime, pointer translation, or safety of passing these tables to NetBSD.
"""
import struct
import uuid
import zlib

LIMIT = 1 << 32
EFI_SIGNATURE = b'IBI SYST'
ACPI10 = uuid.UUID('eb9d2d30-2d88-11d3-9a16-0090273fc14d').bytes_le
ACPI20 = uuid.UUID('8868e871-e4f1-11d3-bc22-0080c73c8881').bytes_le
MAX_TABLE_SIZE = 4096
MAX_CONFIG_BYTES = 4096  # NetBSD 11.1 efi_getva() maps PAGE_SIZE bytes


def _span(address, length, name):
    if (not isinstance(address, int) or not isinstance(length, int) or
            not 0 < address < LIMIT or not 0 < length <= LIMIT - address):
        raise ValueError(f'invalid {name} 32-bit span')


def validate_rsdp(data, address):
    """Validate a copied RSDP, reporting pointers but not following them."""
    if not isinstance(data, bytes) or len(data) < 20:
        raise ValueError('incomplete ACPI RSDP')
    _span(address, 20, 'RSDP')
    if data[:8] != b'RSD PTR ' or sum(data[:20]) & 255:
        raise ValueError('invalid ACPI RSDP signature or checksum')
    revision = data[15]
    rsdt = struct.unpack_from('<I', data, 16)[0]
    length, xsdt = 20, None
    if revision == 1:
        raise ValueError('unsupported ACPI RSDP revision 1')
    if revision >= 2:
        if len(data) < 36:
            raise ValueError('incomplete extended ACPI RSDP')
        length = struct.unpack_from('<I', data, 20)[0]
        if not 36 <= length <= MAX_TABLE_SIZE or len(data) < length:
            raise ValueError('invalid or incomplete extended ACPI RSDP length')
        _span(address, length, 'RSDP')
        if sum(data[:length]) & 255:
            raise ValueError('invalid extended ACPI RSDP checksum')
        xsdt = struct.unpack_from('<Q', data, 24)[0]
    return {'address': address, 'revision': revision, 'length': length,
            'rsdt_address': rsdt, 'xsdt_address': xsdt,
            'referenced_tables': 'not captured or validated'}


def inspect_tables(system_data, system_address, config_data=None, rsdp_data=None):
    """Inspect copied bytes; absent config/RSDP bytes remain explicitly unknown.

    ``rsdp_data`` maps physical addresses to same-boot copied RSDP bytes.
    It is not a memory reader, and the caller must not infer pointer safety
    from a successful result. Malformed supplied data raises ValueError.
    """
    if not isinstance(system_data, bytes) or len(system_data) < 72:
        raise ValueError('incomplete 32-bit EFI system table')
    _span(system_address, 72, 'system table')
    if system_data[:8] != EFI_SIGNATURE:
        raise ValueError('invalid EFI system table signature')
    revision, size, checksum, reserved = struct.unpack_from('<IIII', system_data, 8)
    if not 72 <= size <= MAX_TABLE_SIZE or len(system_data) < size:
        raise ValueError('invalid or incomplete EFI system table length')
    _span(system_address, size, 'system table')
    raw = bytearray(system_data[:size])
    raw[16:20] = bytes(4)
    if zlib.crc32(raw) & 0xffffffff != checksum:
        raise ValueError('invalid EFI system table CRC32')
    count, config_address = struct.unpack_from('<II', system_data, 64)
    config_length = count * 20
    if config_length > MAX_CONFIG_BYTES:
        raise ValueError('EFI configuration array exceeds NetBSD mapping bound')
    if count:
        _span(config_address, config_length, 'configuration array')
    result = {'system_table': {'address': system_address, 'revision': revision,
                               'size': size, 'reserved': reserved, 'crc_valid': True},
              'configuration': {'address': config_address, 'count': count,
                                'status': 'not captured', 'entries': []},
              'limitations': ['Inputs must come from the same boot.',
                              'Checksums do not prove pointer translation, memory lifetime or safety.',
                              'Referenced ACPI tables and firmware services are not validated.']}
    if config_data is None:
        return result
    if not isinstance(config_data, bytes) or len(config_data) < config_length:
        raise ValueError('incomplete EFI configuration array')
    if rsdp_data is None:
        rsdp_data = {}
    if not isinstance(rsdp_data, dict):
        raise ValueError('RSDP copies must be an address-to-bytes mapping')
    entries = []
    for offset in range(0, config_length, 20):
        guid = config_data[offset:offset + 16]
        address = struct.unpack_from('<I', config_data, offset + 16)[0]
        entry = {'guid': str(uuid.UUID(bytes_le=guid)), 'address': address}
        if guid in (ACPI10, ACPI20):
            entry['kind'] = 'ACPI 2.0' if guid == ACPI20 else 'ACPI 1.0'
            entry['rsdp_status'] = 'not captured'
            if address == 0:
                entry['rsdp_status'] = 'null pointer'
            elif address in rsdp_data:
                entry['rsdp'] = validate_rsdp(rsdp_data[address], address)
                entry['rsdp_status'] = 'checksum valid'
        entries.append(entry)
    result['configuration'].update(status='captured', entries=entries)
    return result
