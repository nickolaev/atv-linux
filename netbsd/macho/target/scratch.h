#ifndef ATV_NETBSD_TARGET_SCRATCH_H
#define ATV_NETBSD_TARGET_SCRATCH_H

#include "../native/handoff.h"

/* Prototype only. The caller must already have safely captured and validated
 * the live map, and must reserve every live object and kernel destination.
 * Stack and bootinfo sizes are page-aligned and nonzero. Nothing is written
 * on failure. This function does not establish pointer readability, table
 * lifetime, or the safety of its own stack; it is not a hardware entry. */
struct target_scratch {
    struct nb_range usable, stack, bootinfo;
};
int target_find_scratch(const void *map, nb_u32 length, nb_u32 stride,
                        nb_u32 version, const struct nb_range *reserved,
                        nb_u32 reserved_count, nb_u64 address_limit,
                        nb_u32 stack_size, nb_u32 info_size,
                        struct target_scratch *out);
#endif
