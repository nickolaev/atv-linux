#ifndef ATV_NETBSD_TARGET_SMBIOS_H
#define ATV_NETBSD_TARGET_SMBIOS_H

#include "firmware.h"

/* Test-only SMBIOS 2.x framing validator. The map and callback-provided bytes
 * must be immutable snapshots from the same boot. The callback must already
 * guarantee readable, identity-mapped physical memory. The caller must reserve
 * all returned complete descriptors for their entire lifetime. Protected ranges
 * include loader, stack, kernel and output storage. A successful result checks
 * entry checksums, the complete NetBSD page-rounded mapping of its entry, and
 * record framing, not per-type semantics, pointer lifetime,
 * or the safety of passing firmware objects to a kernel. No hardware handoff
 * may be authorized on this basis. Failure leaves out unchanged. */
#ifdef TARGET_EMULATION_ONLY
int target_validate_smbios2(const void *map, nb_u32 map_length,
    nb_u32 stride, nb_u32 version, nb_u32 entry_pa,
    const struct nb_range *protected, nb_u32 protected_count,
    target_fw_read_fn read_fn, void *context, struct target_fw_result *out);
#endif
#endif
