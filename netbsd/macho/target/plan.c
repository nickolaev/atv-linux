#include "plan.h"
#define LIMIT ((nb_u64)1 << 32)
#define MAX_PROTECTED 32u

static nb_u32 rd32(const nb_u8 *p) {
    return p[0] | (nb_u32)p[1] << 8 | (nb_u32)p[2] << 16 | (nb_u32)p[3] << 24;
}
static nb_u64 rd64(const nb_u8 *p) { return rd32(p) | (nb_u64)rd32(p + 4) << 32; }
static int usable(const nb_u8 *d) {
    nb_u64 attrs = rd64(d + 32);
    return rd32(d) == 7 && (attrs & 8) && !(attrs & ((nb_u64)1 << 63));
}
static int aliases(const void *a, nb_u64 alen, const void *b, nb_u64 blen) {
    nb_uptr ap = (nb_uptr)a, bp = (nb_uptr)b;
    if (alen > (nb_uptr)-1 - ap || blen > (nb_uptr)-1 - bp) return 1;
    return (nb_u64)ap < (nb_u64)bp + blen && (nb_u64)bp < (nb_u64)ap + alen;
}

int target_plan_memory(const void *kernel, nb_u32 kernel_length, nb_u32 kernel_pa,
                       const void *map, nb_u32 map_length, nb_u32 stride, nb_u32 version,
                       const struct nb_range *protected, nb_u32 protected_count,
                       nb_u64 address_limit, struct target_plan *out)
{
    const nb_u8 *data = (const nb_u8 *)map;
    const struct nb_range all = {0, LIMIT};
    struct nb_range reservations[MAX_PROTECTED + NB_MAX_SEGMENTS + 1];
    struct target_plan result;
    nb_u32 i, j, n;
    if (!kernel || !map || !out || !protected || !protected_count ||
        protected_count > MAX_PROTECTED || !kernel_length ||
        (nb_u64)kernel_pa + kernel_length > LIMIT ||
        aliases(out, sizeof(*out), kernel, kernel_length) ||
        aliases(out, sizeof(*out), map, map_length) ||
        aliases(out, sizeof(*out), protected, (nb_u64)protected_count * sizeof(*protected)) ||
        !stride || stride < 40 || (stride & 3) || !map_length || map_length % stride ||
        map_length / stride > 256 || version != 1) return -1;
    for (i = 0; i < map_length; i += stride) {
        nb_u64 start = rd64(data + i + 8), pages = rd64(data + i + 24);
        if ((start & 4095) || !pages || pages > (((nb_u64)-1 - start) >> 12)) return -1;
    }
    /* Avoid copying uninitialized unused segment/range entries to output. */
    for (i = 0; i < sizeof(result); ++i) ((nb_u8 *)&result)[i] = 0;
    /* Parse and bound ELF before using its destinations; this never copies. */
    if (nb_plan_elf(kernel, kernel_length, kernel_pa, &all, 1,
                    protected, protected_count, &result.kernel)) return -1;
    n = 0;
    for (i = 0; i < protected_count; ++i) reservations[n++] = protected[i];
    reservations[n++] = (struct nb_range){kernel_pa, (nb_u64)kernel_pa + kernel_length};
    result.usable_count = 0;
    for (i = 0; i < result.kernel.segment_count; ++i) {
        const struct nb_segment *s = &result.kernel.segments[i];
        struct nb_range range = {s->physical_address, (nb_u64)s->physical_address + s->memory_size};
        int covered = 0;
        for (j = 0; j < map_length; j += stride) {
            const nb_u8 *d = data + j;
            nb_u64 start = rd64(d + 8), end = start + (rd64(d + 24) << 12);
            if (start >= range.end || range.start >= end) continue;
            if (!usable(d)) return -1;
            if (start <= range.start && end >= range.end) covered = 1;
        }
        if (!covered) return -1;
        result.usable[result.usable_count++] = range;
        reservations[n++] = range;
    }
    if (target_find_scratch(map, map_length, stride, version, reservations, n,
                            address_limit, 65536, NB_BOOTINFO_MAX, &result.scratch)) return -1;
    result.usable[result.usable_count++] = result.scratch.usable;
    result.protected_count = protected_count;
    for (i = 0; i < protected_count; ++i) result.protected[i] = protected[i];
    *out = result;
    return 0;
}
