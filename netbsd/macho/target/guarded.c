#include "guarded.h"

#ifdef TARGET_EMULATION_ONLY
#define LIMIT ((nb_u64)1 << 32)
#define MAX_PROTECTED 32u
static int aliases(const void *a, nb_u64 alen, const void *b, nb_u64 blen) {
    nb_uptr ap = (nb_uptr)a, bp = (nb_uptr)b;
    if (alen > (nb_uptr)-1 - ap || blen > (nb_uptr)-1 - bp) return 1;
    return (nb_u64)ap < (nb_u64)bp + blen && (nb_u64)bp < (nb_u64)ap + alen;
}

int target_guarded_plan_emulation(const void *kernel, nb_u32 kernel_length,
    nb_u32 kernel_pa, const void *map, nb_u32 map_pa, nb_u32 map_length,
    nb_u32 stride, nb_u32 version, nb_u32 system_pa,
    const struct nb_range *protected, nb_u32 protected_count,
    target_fw_read_fn read_fn, void *context, nb_u64 address_limit,
    struct target_plan *out)
{
    struct nb_range reservations[MAX_PROTECTED];
    struct target_fw_result firmware;
    struct target_plan result;
    nb_u32 n = 0, i;
    if (!kernel || !kernel_length || !map || !map_length || !protected ||
        !protected_count || protected_count > MAX_PROTECTED - 2 || !read_fn || !out ||
        (nb_u64)kernel_pa + kernel_length > LIMIT || (nb_u64)map_pa + map_length > LIMIT ||
        aliases(out, sizeof(*out), kernel, kernel_length) ||
        aliases(out, sizeof(*out), map, map_length) ||
        aliases(out, sizeof(*out), protected, (nb_u64)protected_count * sizeof(*protected))) return -1;
    for (i = 0; i < protected_count; ++i) reservations[n++] = protected[i];
    reservations[n++] = (struct nb_range){kernel_pa, (nb_u64)kernel_pa + kernel_length};
    reservations[n++] = (struct nb_range){map_pa, (nb_u64)map_pa + map_length};
    if (target_validate_firmware(map, map_length, stride, version, system_pa,
                                 reservations, n, read_fn, context, &firmware)) return -1;
    if (firmware.count > MAX_PROTECTED - n) return -1;
    for (i = 0; i < firmware.count; ++i) reservations[n++] = firmware.reservations[i];
    if (target_plan_memory(kernel, kernel_length, kernel_pa, map, map_length, stride,
                           version, reservations, n, address_limit, &result)) return -1;
    *out = result;
    return 0;
}
#endif
