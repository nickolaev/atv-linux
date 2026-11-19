#include "handoff.h"

#define ADDRESS_LIMIT ((nb_u64)1 << 32)
#define MAX_RANGES 256u

static nb_u32 get16(const nb_u8 *p)
{
    return (nb_u32)p[0] | ((nb_u32)p[1] << 8);
}

static nb_u32 get32(const nb_u8 *p)
{
    return get16(p) | (get16(p + 2) << 16);
}

static void put32(nb_u8 *p, nb_u32 value)
{
    p[0] = (nb_u8)value;
    p[1] = (nb_u8)(value >> 8);
    p[2] = (nb_u8)(value >> 16);
    p[3] = (nb_u8)(value >> 24);
}

static int valid_ranges(const struct nb_range *ranges, nb_u32 count)
{
    nb_u32 i;
    if (count > MAX_RANGES || (count && !ranges)) return 0;
    for (i = 0; i < count; ++i)
        if (ranges[i].start >= ranges[i].end || ranges[i].end > ADDRESS_LIMIT)
            return 0;
    return 1;
}

static int overlaps(nb_u64 a, nb_u64 b, nb_u64 c, nb_u64 d)
{
    return a < d && c < b;
}

static int pointer_overlaps(const void *a, nb_u64 alen, const void *b, nb_u64 blen)
{
    nb_uptr ap = (nb_uptr)a, bp = (nb_uptr)b, top = (nb_uptr)-1;
    if (!a || !b || alen > (nb_u64)(top - ap) || blen > (nb_u64)(top - bp)) return 1;
    return overlaps(ap, (nb_u64)ap + alen, bp, (nb_u64)bp + blen);
}

int nb_plan_elf(const void *elf, nb_u32 length, nb_u32 source_pa,
                const struct nb_range *usable, nb_u32 usable_count,
                const struct nb_range *reserved, nb_u32 reserved_count,
                struct nb_plan *out)
{
    const nb_u8 *data = (const nb_u8 *)elf;
    struct nb_plan plan;
    nb_u32 i, j, phoff, phnum, entry, entry_matches = 0;
    nb_u64 source_end = (nb_u64)source_pa + length;
    if (!out) return -1;
    plan.entry = 0;
    plan.segment_count = 0;
    if (!data || length < 52 || !usable_count || !reserved_count ||
        !valid_ranges(usable, usable_count) ||
        !valid_ranges(reserved, reserved_count) || source_end > ADDRESS_LIMIT ||
        pointer_overlaps(out, sizeof(*out), data, length) ||
        pointer_overlaps(out, sizeof(*out), usable, (nb_u64)usable_count * sizeof(*usable)) ||
        pointer_overlaps(out, sizeof(*out), reserved, (nb_u64)reserved_count * sizeof(*reserved)))
        return -1;
    if (data[0] != 0x7f || data[1] != 'E' || data[2] != 'L' || data[3] != 'F' ||
        data[4] != 1 || data[5] != 1 || data[6] != 1 || get16(data + 16) != 2 ||
        get16(data + 18) != 3 || get32(data + 20) != 1 || get16(data + 40) != 52 ||
        get16(data + 42) != 32)
        return -1;
    entry = get32(data + 24);
    phoff = get32(data + 28);
    phnum = get16(data + 44);
    if (!phnum || phoff < 52 || (nb_u64)phoff + (nb_u64)phnum * 32 > length)
        return -1;
    for (i = 0; i < phnum; ++i) {
        const nb_u8 *p = data + phoff + i * 32;
        nb_u32 type = get32(p), offset, vaddr, paddr, filesz, memsz, flags, align;
        nb_u64 end;
        int in_usable = 0;
        if (type == 2 || type == 3 || type == 7) return -1; /* dynamic/interpreter/TLS */
        if (type != 1) continue;
        if (plan.segment_count == NB_MAX_SEGMENTS) return -1;
        offset = get32(p + 4); vaddr = get32(p + 8); paddr = get32(p + 12);
        filesz = get32(p + 16); memsz = get32(p + 20);
        flags = get32(p + 24); align = get32(p + 28);
        end = (nb_u64)paddr + memsz;
        if (!memsz || filesz > memsz || (nb_u64)offset + filesz > length ||
            end > ADDRESS_LIMIT || (nb_u64)vaddr + memsz > ADDRESS_LIMIT ||
            (align > 1 && ((align & (align - 1)) || ((vaddr - offset) & (align - 1)))) ||
            overlaps(paddr, end, source_pa, source_end)) return -1;
        for (j = 0; j < usable_count; ++j)
            if (usable[j].start <= paddr && end <= usable[j].end) in_usable = 1;
        if (!in_usable) return -1;
        for (j = 0; j < reserved_count; ++j)
            if (overlaps(paddr, end, reserved[j].start, reserved[j].end)) return -1;
        for (j = 0; j < plan.segment_count; ++j) {
            const struct nb_segment *s = &plan.segments[j];
            if (overlaps(paddr, end, s->physical_address,
                         (nb_u64)s->physical_address + s->memory_size)) return -1;
        }
        if (entry >= vaddr && (nb_u64)entry < (nb_u64)vaddr + memsz) {
            nb_u32 delta = entry - vaddr;
            if (!(flags & 1) || delta >= filesz) return -1;
            plan.entry = paddr + delta;
            ++entry_matches;
        }
        plan.segments[plan.segment_count++] = (struct nb_segment){offset, paddr, filesz, memsz};
    }
    if (!plan.segment_count || entry_matches != 1) return -1;
    out->entry = plan.entry;
    out->segment_count = plan.segment_count;
    for (i = 0; i < plan.segment_count; ++i) {
        out->segments[i].source_offset = plan.segments[i].source_offset;
        out->segments[i].physical_address = plan.segments[i].physical_address;
        out->segments[i].file_size = plan.segments[i].file_size;
        out->segments[i].memory_size = plan.segments[i].memory_size;
    }
    return 0;
}

int nb_copy_kernel(const struct nb_plan *plan, const void *elf, nb_u32 length,
                   nb_write_fn write_fn, nb_zero_fn zero_fn, void *context)
{
    const nb_u8 *data = (const nb_u8 *)elf;
    nb_u32 i;
    if (!plan || !data || !write_fn || !zero_fn || !plan->segment_count ||
        plan->segment_count > NB_MAX_SEGMENTS) return -1;
    /* Check all segment metadata before the first callback. */
    for (i = 0; i < plan->segment_count; ++i) {
        const struct nb_segment *s = &plan->segments[i];
        if (!s->memory_size || s->file_size > s->memory_size ||
            (nb_u64)s->source_offset + s->file_size > length ||
            (nb_u64)s->physical_address + s->memory_size > ADDRESS_LIMIT)
            return -1;
    }
    for (i = 0; i < plan->segment_count; ++i) {
        const struct nb_segment *s = &plan->segments[i];
        if (s->file_size && write_fn(context, s->physical_address,
                                     data + s->source_offset, s->file_size)) return -1;
        if (s->memory_size > s->file_size &&
            zero_fn(context, s->physical_address + s->file_size,
                    s->memory_size - s->file_size)) return -1;
    }
    return 0;
}

int nb_build_bootinfo(void *destination, nb_u32 capacity, nb_u32 destination_pa,
                      nb_u32 system_table_pa, const void *map, nb_u32 map_length,
                      nb_u32 map_pa, nb_u32 descriptor_size,
                      nb_u32 descriptor_version, nb_u32 *used)
{
    nb_u8 *out = (nb_u8 *)destination;
    const nb_u8 *in = (const nb_u8 *)map;
    nb_u64 total = (nb_u64)12 + 32 + 23 + map_length;
    nb_u32 i, map_record_length;
    if (!used || !out || !in || !destination_pa || (destination_pa & 3) ||
        !system_table_pa || (system_table_pa & 3) || !map_pa ||
        descriptor_size < 40 || (descriptor_size & 3) || !map_length ||
        map_length % descriptor_size || total > capacity ||
        total - 12 > NB_BOOTINFO_MAX - 4 ||
        (nb_u64)destination_pa + total > ADDRESS_LIMIT ||
        (nb_u64)map_pa + map_length > ADDRESS_LIMIT ||
        overlaps(destination_pa, (nb_u64)destination_pa + total,
                 map_pa, (nb_u64)map_pa + map_length) ||
        pointer_overlaps(out, total, in, map_length) ||
        pointer_overlaps(used, sizeof(*used), in, map_length) ||
        pointer_overlaps(used, sizeof(*used), out, total)) return -1;
    for (i = 0; i < (nb_u32)total; ++i) out[i] = 0;
    put32(out, 2);
    put32(out + 4, destination_pa + 12);
    put32(out + 8, destination_pa + 44);
    put32(out + 12, 32); put32(out + 16, 14);
    put32(out + 20, system_table_pa); /* zero high 32 bits */
    put32(out + 28, 1);              /* BI_EFI_32BIT */
    map_record_length = 23 + map_length;
    put32(out + 44, map_record_length); put32(out + 48, 15);
    put32(out + 52, map_length / descriptor_size);
    put32(out + 56, descriptor_version); put32(out + 60, descriptor_size);
    for (i = 0; i < map_length; ++i) out[64 + i] = in[i];
    *used = (nb_u32)total;
    return 0;
}
