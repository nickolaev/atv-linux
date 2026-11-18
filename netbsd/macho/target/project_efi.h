#ifndef ATV_NETBSD_PROJECT_EFI_H
#define ATV_NETBSD_PROJECT_EFI_H

#include "firmware.h"

#define TARGET_PROJECT_MAX_RANGES 32u
#define TARGET_PROJECT_ACPI1 1u
#define TARGET_PROJECT_ACPI2 2u
#define TARGET_PROJECT_SMBIOS2 3u

/* Experimental projection only. The validator must validate the selected
 * entry and all objects the kernel might follow, return their complete physical
 * reservations, and reject any overlap with [owned_start, owned_end). It must
 * guarantee all reads use stable, current-boot data, and must not mutate the
 * input snapshots or output. No validator for the observed SMBIOS entry is
 * provided by this component. */
typedef int (*target_project_validate_fn)(void *context, nb_u32 kind,
    nb_u32 address, nb_u64 owned_start, nb_u64 owned_end,
    struct nb_range *reservations, nb_u32 *count);

struct target_project_result {
    nb_u32 count, reservation_count;
    struct nb_range reservations[TARGET_PROJECT_MAX_RANGES];
};

/* Buffers must be immutable snapshots from the same boot. The caller must
 * independently validate their descriptor coverage, the current map and
 * physical readability, and reserve both page-aligned output pages and all
 * returned ranges. owned_pages points to exactly 8192 writable bytes at
 * physical owned_pa; NetBSD maps one page from each of these anchors.
 * Result metadata is separate and must also remain protected while in use.
 * Integration must measure and validate stack capacity for this function,
 * its validator callbacks, and their nested callees; 16 KiB is not assumed
 * sufficient. Caller-provided storage and callback context must not alias
 * either output or input snapshots.
 * Results cannot authorize a hardware handoff. Unknown
 * GUIDs are dropped without following their pointers. SMBIOS3 is rejected.
 * Output is unchanged on failure. */
#ifdef TARGET_EMULATION_ONLY
int target_project_efi(const void *system, nb_u32 system_length, nb_u32 system_pa,
    const void *config, nb_u32 config_length, nb_u32 config_pa, nb_u32 owned_pa,
    target_project_validate_fn validate, void *context, void *owned_pages,
    struct target_project_result *out);
#endif
#endif
