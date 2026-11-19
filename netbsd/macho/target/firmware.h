#ifndef ATV_NETBSD_TARGET_FIRMWARE_H
#define ATV_NETBSD_TARGET_FIRMWARE_H

#include "../native/handoff.h"

#define TARGET_FW_MAX_RANGES 32u
struct target_fw_result {
    nb_u32 count;
    struct nb_range reservations[TARGET_FW_MAX_RANGES];
};
typedef int (*target_fw_read_fn)(void *, nb_u32, void *, nb_u32);

/* Prototype: map is a fresh, immutable EFI descriptor snapshot. read_fn must
 * already guarantee the requested physical addresses are readable, stable,
 * and identity mapped. protected ranges include all live loader, stack,
 * kernel and output storage. The caller must keep every returned full EFI
 * descriptor reserved. Only ACPI 1.0/2.0 EFI config GUIDs are supported;
 * unknown entries are rejected. RSDPs, root tables, and supported root
 * children (FACP, APIC, SSDT) are checked; APIC accepts only known fixed-size
 * x86 record types. FADT DSDT and FACS addresses are
 * validated and reserved; other root-child signatures are rejected. AML,
 * register addresses and device behavior are not validated. Success is not
 * sufficient to hand firmware tables to a real kernel.
 * Scratch stack needs more than 8 KiB; output is untouched on failure. */
int target_validate_firmware(const void *map, nb_u32 map_length,
    nb_u32 stride, nb_u32 version, nb_u32 system_pa,
    const struct nb_range *protected, nb_u32 protected_count,
    target_fw_read_fn read_fn, void *context, struct target_fw_result *out);

#ifdef TARGET_EMULATION_ONLY
/* Selected-entry and source snapshot helpers for synthetic projection tests.
 * They retain the same callback, lifetime, and hardware-safety limitations. */
struct target_efi_sources {
    nb_u8 system[72];
    nb_u8 config[1280];
    nb_u32 config_pa, config_length;
    struct target_fw_result firmware;
};
int target_read_efi_sources(const void *map, nb_u32 map_length, nb_u32 stride,
    nb_u32 version, nb_u32 system_pa, const struct nb_range *protected,
    nb_u32 protected_count, target_fw_read_fn read_fn, void *context,
    struct target_efi_sources *out);
int target_validate_acpi(const void *map, nb_u32 map_length, nb_u32 stride,
    nb_u32 version, nb_u32 rsdp_pa, const struct nb_range *protected,
    nb_u32 protected_count, target_fw_read_fn read_fn, void *context,
    struct target_fw_result *out);
#endif
#endif
