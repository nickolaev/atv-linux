#!/usr/bin/env python3
"""Offline EFI-to-NetBSD memory-map prototype; this never boots a kernel.

NetBSD 11.1's x86 EFI converter classifies EFI types in
``sys/arch/x86/x86/efi_machdep.c``. This prototype is more conservative: only
write-back ConventionalMemory is usable, runtime or reserved coverage wins
over it, and conflicting ACPI/NVS coverage becomes reserved. EFI loader and
boot-services pages remain reserved even though NetBSD may normally reclaim
them after ExitBootServices. The caller must supply a fresh, authentic map and
reserve all live objects; output is not proof of safe RAM.

When passing BTINFO_MEMMAP to NetBSD 11.1/i386 without BTINFO_EFIMEMMAP,
``x86_init_clusters`` may select that map only if ``biosmem_implicit`` is true
or *both* legacy base and extended memory arguments are zero. See
``sys/arch/x86/x86/x86_machdep.c``. This prototype does not perform a handoff.
"""
from dataclasses import dataclass
import struct

PAGE_SIZE = 4096
LIMIT = 1 << 64
EFI_MEMORY_WB = 0x8
EFI_MEMORY_RUNTIME = 1 << 63
BIM_MEMORY = 1
BIM_RESERVED = 2
BIM_ACPI = 3
BIM_NVS = 4
BTINFO_MEMMAP = 9
BOOTINFO_MAXSIZE = 16384
MAX_DESCRIPTORS = 1024


@dataclass(frozen=True)
class Descriptor:
    type: int
    physical_start: int
    pages: int
    attributes: int


@dataclass(frozen=True)
class Region:
    start: int
    end: int  # exclusive
    type: int


def parse_descriptors(data, stride, version=1):
    """Read complete little-endian EFI descriptors, preserving map stride."""
    if not isinstance(data, bytes):
        raise ValueError('descriptor data must be immutable bytes')
    if not isinstance(stride, int) or stride < 40 or stride % 4:
        raise ValueError('invalid EFI descriptor stride')
    if version != 1 or not data or len(data) % stride:
        raise ValueError('unsupported EFI map version or incomplete map')
    count = len(data) // stride
    if count > MAX_DESCRIPTORS:
        raise ValueError('too many EFI descriptors')
    result = []
    for offset in range(0, len(data), stride):
        typ, _, physical, _, pages, attributes = struct.unpack_from('<IIQQQQ', data, offset)
        result.append(Descriptor(typ, physical, pages, attributes))
    return result


def _descriptor_range(d):
    if not isinstance(d, Descriptor):
        raise ValueError('expected EFI Descriptor instances')
    if any(not isinstance(x, int) for x in (d.type, d.physical_start, d.pages, d.attributes)):
        raise ValueError('descriptor fields must be integers')
    if not (0 <= d.type < 1 << 32 and 0 <= d.attributes < LIMIT and
            0 <= d.physical_start < LIMIT and d.physical_start % PAGE_SIZE == 0 and
            0 < d.pages < LIMIT):
        raise ValueError('invalid EFI descriptor fields')
    end = d.physical_start + d.pages * PAGE_SIZE
    # NetBSD computes addr+size in uint64_t; do not allow wrapping to zero.
    if end >= LIMIT:
        raise ValueError('EFI physical range overflows 64 bits')
    return d.physical_start, end


def _classification(d):
    if d.attributes & EFI_MEMORY_RUNTIME:
        return BIM_RESERVED
    if d.type == 7:
        return BIM_MEMORY if d.attributes & EFI_MEMORY_WB else BIM_RESERVED
    if d.type == 9:
        return BIM_ACPI
    if d.type == 10:
        return BIM_NVS
    # Includes loader/boot-services pages, runtime, MMIO, persistent, unknown.
    return BIM_RESERVED


def normalize_descriptors(descriptors, reserved_ranges=()):
    """Return sorted, disjoint Regions, with restrictions winning overlaps.

    ``reserved_ranges`` are half-open physical ranges for live loader state.
    Non-page-aligned ranges are expanded outward to whole pages. Reservations
    only restrict covered EFI regions and never create previously absent RAM.
    Conflicting ACPI/NVS classifications are converted to reserved.
    """
    descriptors = list(descriptors)
    reserved_ranges = list(reserved_ranges)
    if not descriptors or len(descriptors) > MAX_DESCRIPTORS or len(reserved_ranges) > MAX_DESCRIPTORS:
        raise ValueError('invalid descriptor or reservation count')
    spans = []
    for d in descriptors:
        start, end = _descriptor_range(d)
        spans.append((start, end, _classification(d)))
    reservations = []
    for item in reserved_ranges:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError('reservation must be a start/end pair')
        start, end = item
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end < LIMIT:
            raise ValueError('invalid reserved physical range')
        start &= -PAGE_SIZE
        end = (end + PAGE_SIZE - 1) & -PAGE_SIZE
        if end >= LIMIT:
            raise ValueError('page-aligned reservation overflows')
        reservations.append((start, end))
    boundaries = sorted({x for start, end, _ in spans for x in (start, end)} |
                        {x for start, end in reservations for x in (start, end)})
    result = []
    for start, end in zip(boundaries, boundaries[1:]):
        classes = {typ for a, b, typ in spans if a < end and start < b}
        if not classes:
            continue
        if (BIM_RESERVED in classes or
                any(a < end and start < b for a, b in reservations) or
                (BIM_ACPI in classes and BIM_NVS in classes)):
            typ = BIM_RESERVED
        elif BIM_NVS in classes:
            typ = BIM_NVS
        elif BIM_ACPI in classes:
            typ = BIM_ACPI
        else:
            typ = BIM_MEMORY
        if result and result[-1].end == start and result[-1].type == typ:
            result[-1] = Region(result[-1].start, end, typ)
        else:
            result.append(Region(start, end, typ))
    return result


def normalize_efi_map(data, stride, version=1, reserved_ranges=()):
    return normalize_descriptors(parse_descriptors(data, stride, version), reserved_ranges)


def serialize_memmap(regions):
    """Serialize one NetBSD/i386 BTINFO_MEMMAP record, not its pointer array.

    Caller must include all other records when enforcing the kernel's total
    BOOTINFO_MAXSIZE limit. See NetBSD 11.1 x86/include/bootinfo.h.
    """
    regions = list(regions)
    if not regions or 12 + 20 * len(regions) > BOOTINFO_MAXSIZE - 4:
        raise ValueError('empty map or record exceeds kernel bootinfo capacity')
    data = bytearray(struct.pack('<III', 12 + 20 * len(regions), BTINFO_MEMMAP, len(regions)))
    previous_end = 0
    for region in regions:
        if (not isinstance(region, Region) or not isinstance(region.start, int) or
                not isinstance(region.end, int) or not isinstance(region.type, int) or
                not 0 <= region.start < region.end < LIMIT or
                region.start % PAGE_SIZE or region.end % PAGE_SIZE or
                region.start < previous_end or region.type not in (BIM_MEMORY, BIM_RESERVED, BIM_ACPI, BIM_NVS)):
            raise ValueError('invalid or overlapping normalized region')
        data.extend(struct.pack('<QQI', region.start, region.end - region.start, region.type))
        previous_end = region.end
    return bytes(data)
