/* Fail-closed scratch placement prototype; no physical memory accesses. */
#include "scratch.h"

#define MAX_DESCRIPTORS 256u
#define MAX_RESERVED 64u
#define MAX_BOUNDARIES (2u + 2u * (MAX_DESCRIPTORS + MAX_RESERVED))
#define PAGE 4096u
#define LIMIT ((nb_u64)1 << 32)
#define EFI_RUNTIME ((nb_u64)1 << 63)

static nb_u32 rd32(const nb_u8 *p)
{
    return (nb_u32)p[0] | (nb_u32)p[1] << 8 | (nb_u32)p[2] << 16 | (nb_u32)p[3] << 24;
}
static nb_u64 rd64(const nb_u8 *p) { return rd32(p) | (nb_u64)rd32(p + 4) << 32; }
static int pointer_overlap(const void *a, nb_u64 alen, const void *b, nb_u64 blen)
{
    nb_uptr ap = (nb_uptr)a, bp = (nb_uptr)b;
    if (alen > (nb_uptr)-1 - ap || blen > (nb_uptr)-1 - bp) return 1;
    return (nb_u64)ap < (nb_u64)bp + blen && (nb_u64)bp < (nb_u64)ap + alen;
}
static int candidate(const nb_u8 *d)
{
    nb_u64 a = rd64(d + 32);
    return rd32(d) == 7 && (a & 8) && !(a & EFI_RUNTIME);
}

int target_find_scratch(const void *map, nb_u32 length, nb_u32 stride,
                        nb_u32 version, const struct nb_range *reserved,
                        nb_u32 reserved_count, nb_u64 address_limit,
                        nb_u32 stack_size, nb_u32 info_size,
                        struct target_scratch *out)
{
    const nb_u8 *bytes = (const nb_u8 *)map;
    nb_u64 boundary[MAX_BOUNDARIES], need, best_start = 0, best_end = 0;
    nb_u32 i, j, count = 0, n;
    struct target_scratch result;
    if (!map || !out || (reserved_count && !reserved) || reserved_count > MAX_RESERVED ||
        stride < 40 || (stride & 3) || !length || length % stride ||
        length / stride > MAX_DESCRIPTORS || version != 1 ||
        address_limit < PAGE || address_limit > LIMIT || (address_limit & (PAGE - 1)) ||
        !stack_size || !info_size || (stack_size & (PAGE - 1)) || (info_size & (PAGE - 1)) ||
        pointer_overlap(out, sizeof(*out), map, length) ||
        (reserved_count && pointer_overlap(out, sizeof(*out), reserved,
                                           (nb_u64)reserved_count * sizeof(*reserved)))) return -1;
    need = (nb_u64)stack_size + info_size;
    if (need > address_limit) return -1;
    /* Validate all inputs, even descriptors above the caller's address limit. */
    for (i = 0; i < length; i += stride) {
        nb_u64 start = rd64(bytes + i + 8), pages = rd64(bytes + i + 24);
        if ((start & (PAGE - 1)) || !pages || pages > (((nb_u64)-1 - start) >> 12)) return -1;
    }
    for (i = 0; i < reserved_count; ++i) {
        if (reserved[i].start >= reserved[i].end || reserved[i].end > LIMIT) return -1;
    }
    /* Each candidate must be wholly contained in one usable descriptor,
     * matching nb_prepare_native_emulation's conservative range contract. */
    for (i = 0; i < length; i += stride) {
        const nb_u8 *d = bytes + i;
        nb_u64 lo, hi, start, end;
        if (!candidate(d)) continue;
        lo = rd64(d + 8);
        hi = lo + (rd64(d + 24) << 12);
        /* Keep low BIOS/ISA memory out of scratch allocation. */
        if (lo < 0x100000u) lo = 0x100000u;
        if (lo >= address_limit) continue;
        if (hi > address_limit) hi = address_limit;
        /* A 32-bit stack/bootinfo address cannot name exclusive end 4 GiB. */
        if (hi == LIMIT) hi -= PAGE;
        if (hi <= lo) continue;
        if (hi - lo < need) continue;
        count = 0;
        boundary[count++] = lo; boundary[count++] = hi;
        for (j = 0; j < length; j += stride) {
            const nb_u8 *other = bytes + j;
            if (candidate(other)) continue;
            start = rd64(other + 8); end = start + (rd64(other + 24) << 12);
            if (start < hi && lo < end) {
                boundary[count++] = start > lo ? start : lo;
                boundary[count++] = end < hi ? end : hi;
            }
        }
        for (j = 0; j < reserved_count; ++j) {
            start = reserved[j].start & ~(nb_u64)(PAGE - 1);
            end = (reserved[j].end + PAGE - 1) & ~(nb_u64)(PAGE - 1);
            if (start < hi && lo < end) {
                boundary[count++] = start > lo ? start : lo;
                boundary[count++] = end < hi ? end : hi;
            }
        }
        for (j = 1; j < count; ++j) {
            nb_u64 value = boundary[j]; n = j;
            while (n && boundary[n - 1] > value) { boundary[n] = boundary[n - 1]; --n; }
            boundary[n] = value;
        }
        for (j = 0; j + 1 < count; ++j) {
            nb_u32 k; int blocked = 0;
            start = boundary[j]; end = boundary[j + 1];
            if (start == end) continue;
            for (k = 0; k < length; k += stride) {
                const nb_u8 *other = bytes + k;
                nb_u64 a = rd64(other + 8), b = a + (rd64(other + 24) << 12);
                if (!candidate(other) && a < end && start < b) { blocked = 1; break; }
            }
            for (k = 0; !blocked && k < reserved_count; ++k) {
                nb_u64 a = reserved[k].start & ~(nb_u64)(PAGE - 1);
                nb_u64 b = (reserved[k].end + PAGE - 1) & ~(nb_u64)(PAGE - 1);
                if (a < end && start < b) blocked = 1;
            }
            if (!blocked && end - start >= need && end > best_end) {
                best_start = start; best_end = end;
            }
        }
    }
    if (!best_end) return -1;
    result.usable.start = best_start; result.usable.end = best_end;
    result.bootinfo.end = best_end; result.bootinfo.start = best_end - info_size;
    result.stack.end = result.bootinfo.start; result.stack.start = result.stack.end - stack_size;
    *out = result;
    return 0;
}
