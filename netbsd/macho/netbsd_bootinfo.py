#!/usr/bin/env python3
"""Serialize a NetBSD/i386 native bootinfo block without touching memory.

The caller supplies the intended physical address and raw EFI descriptors.
This does not establish that any address is usable, that the firmware tables
remain valid, or that a boot handoff is safe.

Layout follows NetBSD netbsd-10 source at dd8a5c6bee76646606c5ab9220eb446c42d32496:
sys/arch/i386/stand/lib/bootinfo.h, sys/arch/x86/include/bootinfo.h and
sys/arch/i386/stand/efiboot/efiboot.c (efi_cleanup).
"""
import struct

ADDRESS_LIMIT = 1 << 32
BOOTINFO_MAXSIZE = 16384
BTINFO_EFI = 14
BTINFO_EFIMEMMAP = 15
BI_EFI_32BIT = 1
EFI_DESCRIPTOR_MIN_SIZE = 40


def serialize_efi_bootinfo(base_address, system_table_address,
                           descriptors, descriptor_size, descriptor_version):
    """Return bytes for a two-entry pointer array and its i386 EFI records.

    Pointer values are physical addresses relative to ``base_address``. Raw
    descriptors are copied verbatim, including any per-descriptor padding.
    The caller must arrange and reserve the actual memory and keep all table
    contents alive as required by NetBSD. No firmware pointer is dereferenced.
    """
    for value, name in ((base_address, 'base address'),
                        (system_table_address, 'system table address')):
        if not isinstance(value, int) or not 0 < value < ADDRESS_LIMIT or value % 4:
            raise ValueError(f'{name} must be nonzero, 4-byte aligned, and 32-bit')
    if not isinstance(descriptors, bytes):
        raise ValueError('descriptors must be immutable bytes')
    if (not isinstance(descriptor_size, int) or descriptor_size < EFI_DESCRIPTOR_MIN_SIZE
            or descriptor_size >= ADDRESS_LIMIT or descriptor_size % 4):
        raise ValueError('invalid EFI descriptor size')
    if not isinstance(descriptor_version, int) or not 0 <= descriptor_version < ADDRESS_LIMIT:
        raise ValueError('invalid EFI descriptor version')
    if not descriptors or len(descriptors) % descriptor_size:
        raise ValueError('EFI map must contain complete descriptors')
    count = len(descriptors) // descriptor_size
    if count >= ADDRESS_LIMIT:
        raise ValueError('too many descriptors')

    efi_record = struct.pack('<IIQI12s', 32, BTINFO_EFI,
                             system_table_address, BI_EFI_32BIT, bytes(12))
    # On i386 sizeof(btinfo_efimemmap) is 24, including tail padding.
    # NetBSD's efi_cleanup allocates sizeof(struct) - 1 + raw map size;
    # the descriptor array starts at offset 20, leaving 3 bytes at the end.
    map_size = 23 + len(descriptors)
    map_record = (struct.pack('<IIIII', map_size, BTINFO_EFIMEMMAP, count,
                              descriptor_version, descriptor_size)
                  + descriptors + bytes(3))
    if len(efi_record) + len(map_record) > BOOTINFO_MAXSIZE - 4:
        raise ValueError('records exceed the kernel bootinfo buffer')

    array_size = 12  # nentries plus two uint32 physical record pointers
    efi_address = base_address + array_size
    map_address = efi_address + len(efi_record)
    total_size = array_size + len(efi_record) + len(map_record)
    if base_address + total_size > ADDRESS_LIMIT:
        raise ValueError('bootinfo block extends beyond 32-bit physical space')
    pointer_array = struct.pack('<III', 2, efi_address, map_address)
    return pointer_array + efi_record + map_record
