#!/usr/bin/env python3
"""Decode an ATV1 EFI snapshot offline; never dereference captured pointers."""
import argparse
import json
import struct
import zlib
from pathlib import Path

CAPTURE_SIZE = 8192
MAP_OFFSET = 192
TABLE_OFFSET = 64
PAGE_SIZE = 4096
UINT64_LIMIT = 1 << 64
SIGNATURE = 0x5453595320494249


def decode(data):
    """Validate and report snapshot contents without asserting firmware safety."""
    if len(data) != CAPTURE_SIZE:
        raise ValueError('capture must be exactly 8192 bytes')
    words = struct.unpack_from('<15I', data)
    (magic, status, args_pa, map_pa, map_size, stride, version, table_pa,
     cr0, cr3, eflags, copied_map, copied_table, efi_mode, revision) = words
    hook_esp = struct.unpack_from('<I', data, 60)[0]
    extended = None
    trailer_magic, trailer_version = struct.unpack_from('<II', data, 8128)
    if copied_map <= 7936 and trailer_magic == 0x47455258 and trailer_version == 1:
        # Only present when the captured descriptor map leaves the trailer free.
        regs = struct.unpack_from('<7I', data, 8136)
        selectors = struct.unpack_from('<6H', data, 8164)
        gdtr_limit, gdtr_base, idtr_limit, idtr_base = struct.unpack_from('<HIHI', data, 8180)
        extended = {'gpr': dict(zip(('eax', 'ebx', 'ecx', 'edx', 'esi', 'edi', 'ebp'), regs)),
                    'selectors': dict(zip(('cs', 'ds', 'ss', 'es', 'fs', 'gs'), selectors)),
                    'cr4': struct.unpack_from('<I', data, 8176)[0],
                    'gdtr': {'base': gdtr_base, 'limit': gdtr_limit},
                    'idtr': {'base': idtr_base, 'limit': idtr_limit}}
    if magic != 0x50414345:
        raise ValueError('missing completion marker')
    if status not in (0, 3):
        raise ValueError('unsupported capture status')
    if (not 0x1000 <= args_pa <= 0x10000000 - 0x44c or
            not 0x1000 <= map_pa < 0x10000000 or map_pa % 4 or
            not map_size or map_size > CAPTURE_SIZE - MAP_OFFSET or
            map_pa + map_size > 0x10000000):
        raise ValueError('invalid captured boot-argument or map span')
    if stride < 40 or stride % 4 or map_size % stride or version != 1:
        raise ValueError('invalid EFI map stride, version or length')
    if copied_map != map_size:
        raise ValueError('captured EFI map is incomplete')
    if status == 3 and copied_table != 0:
        raise ValueError('partial capture cannot contain table bytes')
    if status == 0 and (not 0x1000 <= table_pa <= 0x10000000 - 128 or
                        table_pa % 4 or not 72 <= copied_table <= 128):
        raise ValueError('invalid captured system table span')

    descriptors = []
    for index in range(map_size // stride):
        offset = MAP_OFFSET + index * stride
        raw = data[offset:offset + stride]
        typ, padding, phys, virt, pages, attrs = struct.unpack_from('<IIQQQQ', raw)
        length = pages * PAGE_SIZE
        if not pages or phys % PAGE_SIZE or (virt and virt % PAGE_SIZE):
            raise ValueError(f'descriptor {index} has invalid pages or alignment')
        if phys + length > UINT64_LIMIT or (virt and virt + length > UINT64_LIMIT):
            raise ValueError(f'descriptor {index} overflows 64-bit address space')
        descriptors.append({'index': index, 'type': typ, 'padding': padding,
                            'physical_start': phys, 'virtual_start': virt,
                            'page_count': pages, 'attributes': attrs,
                            'raw_hex': raw.hex()})
    # Real ATV1 firmware reports overlapping conventional/runtime ranges.
    # Preserve that evidence instead of rejecting the entire capture. These
    # observations are not normalized or safe to use for allocation.
    by_address = sorted(descriptors, key=lambda d: d['physical_start'])
    overlaps = []
    for index, previous in enumerate(by_address):
        previous_end = previous['physical_start'] + previous['page_count'] * PAGE_SIZE
        for current in by_address[index + 1:]:
            if current['physical_start'] >= previous_end:
                break
            overlaps.append({'first_index': previous['index'], 'second_index': current['index'],
                             'start': current['physical_start'],
                             'end': min(previous_end, current['physical_start'] + current['page_count'] * PAGE_SIZE)})

    def covered_by_data_descriptor(start, length):
        return any(d['type'] in (2, 4, 6, 7) and
                   d['physical_start'] <= start and
                   start + length <= d['physical_start'] + d['page_count'] * PAGE_SIZE
                   for d in descriptors)

    table = None
    if status == 0:
        raw = data[TABLE_OFFSET:TABLE_OFFSET + copied_table]
        signature, revision_table, header_size, crc32, reserved = struct.unpack_from('<QIIII', raw)
        if signature != SIGNATURE or header_size != copied_table:
            raise ValueError('invalid EFI system table signature or header size')
        crc_input = bytearray(raw)
        crc_input[16:20] = bytes(4)
        calculated = zlib.crc32(crc_input) & 0xffffffff
        fields = struct.unpack_from('<12I', raw, 24)
        labels = ('firmware_vendor', 'firmware_revision', 'console_in_handle',
                  'console_in', 'console_out_handle', 'console_out',
                  'standard_error_handle', 'standard_error', 'runtime_services',
                  'boot_services', 'configuration_table_entries', 'configuration_table')
        table = {'physical_address': table_pa, 'revision': revision_table,
                 'header_size': header_size, 'crc32': crc32,
                 'calculated_crc32': calculated, 'crc_valid': crc32 == calculated,
                 'reserved': reserved, 'fields': dict(zip(labels, fields)),
                 'raw_hex': raw.hex()}

    return {'status': 'complete' if status == 0 else 'map_only',
            'boot_args_address': args_pa,
            'boot_args_revision': revision & 0xffff,
            'boot_args_version': revision >> 16, 'efi_mode': efi_mode,
            'registers': {'cr0': cr0, 'cr3': cr3, 'eflags': eflags,
                          'hook_esp': hook_esp or None, 'extended': extended},
            'memory_map': {'physical_address': map_pa, 'byte_length': map_size,
                           'descriptor_size': stride, 'descriptor_version': version,
                           'physical_overlaps': overlaps,
                           'source_covered_by_data_descriptor': covered_by_data_descriptor(map_pa, map_size),
                           'descriptors': descriptors},
            'system_table': table,
            'system_table_address': table_pa,
            'system_table_128_bytes_covered_by_data_descriptor':
                covered_by_data_descriptor(table_pa, 128) if table_pa else False,
            'limitations': ['Snapshot is specific to this boot.',
                            'EFI boot-services and runtime-services availability are not proven.',
                            'Descriptor coverage, captured addresses and CRC validity do not establish memory safety.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path, help='captured atv-probe.bin')
    args = parser.parse_args()
    try:
        print(json.dumps(decode(args.capture.read_bytes()), indent=2))
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f'cannot decode capture: {error}\n')


if __name__ == '__main__':
    main()
