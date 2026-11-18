#ifndef ATV_TABLE_CAPTURE_H
#define ATV_TABLE_CAPTURE_H

/* Test-only model of a two-phase capture; it does not establish that an EFI
 * address is physically readable or identity mapped on Apple TV hardware. */
typedef __UINT8_TYPE__ tc_u8;
typedef __UINT32_TYPE__ tc_u32;
typedef __UINT64_TYPE__ tc_u64;
#define TC_CONFIG_MAX 1280u
#define TC_RSDP_MAX 256u

struct tc_range { tc_u64 start, end; };
struct tc_capture {
    tc_u32 config_address, config_length, rsdp_address, rsdp_length;
    tc_u8 config[TC_CONFIG_MAX];
    tc_u8 rsdp[TC_RSDP_MAX];
};
typedef int (*tc_read_fn)(void *, tc_u32, void *, tc_u32);

/* `map` and `system` are already-copied same-boot bytes. Caller must reserve
 * the actual scratch stack, these copies and output and ensure their physical
 * ranges are disjoint from sources. `protected` lists every such range; it
 * must include the physical storage of `out`. Output is untouched on failure.
 * Only config array and at most one ACPI 2.0 (else 1.0) RSDP are followed. */
int tc_capture_tables(const tc_u8 *map, tc_u32 map_length, tc_u32 stride,
                      const tc_u8 *system, tc_u32 system_length,
                      const struct tc_range *protected, tc_u32 protected_count,
                      tc_read_fn read, void *context, struct tc_capture *out);
#endif
