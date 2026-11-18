#ifndef ATV_NETBSD_TARGET_PLAN_H
#define ATV_NETBSD_TARGET_PLAN_H
#include "scratch.h"

/* Testable construction of current-map placement, not a hardware entry.
 * The caller must protect ALL live objects including firmware objects and
 * prove pointer readability before providing inputs. No physical writes. */
struct target_plan {
    struct nb_plan kernel;
    struct target_scratch scratch;
    struct nb_range usable[NB_MAX_SEGMENTS + 1];
    nb_u32 usable_count;
    struct nb_range protected[32];
    nb_u32 protected_count;
};
int target_plan_memory(const void *kernel, nb_u32 kernel_length, nb_u32 kernel_pa,
                       const void *map, nb_u32 map_length, nb_u32 stride, nb_u32 version,
                       const struct nb_range *protected, nb_u32 protected_count,
                       nb_u64 address_limit, struct target_plan *out);
#endif
