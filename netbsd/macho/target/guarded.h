#ifndef ATV_NETBSD_TARGET_GUARDED_H
#define ATV_NETBSD_TARGET_GUARDED_H
#include "firmware.h"
#include "plan.h"

/* Synthetic test only: firmware guard checks only a subset of ACPI tables and
 * cannot prove physical readability or pointer translation. This symbol is
 * absent unless TARGET_EMULATION_ONLY is explicitly set at build time. */
#ifdef TARGET_EMULATION_ONLY
int target_guarded_plan_emulation(const void *kernel, nb_u32 kernel_length,
    nb_u32 kernel_pa, const void *map, nb_u32 map_pa, nb_u32 map_length,
    nb_u32 stride, nb_u32 version, nb_u32 system_pa,
    const struct nb_range *protected, nb_u32 protected_count,
    target_fw_read_fn read_fn, void *context, nb_u64 address_limit,
    struct target_plan *out);
#endif
#endif
