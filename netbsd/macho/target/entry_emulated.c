/* Identity-addressed synthetic fixture. NOT an ATV1 hardware loader. */
#ifndef TARGET_EMULATION_ONLY
#error This entry is restricted to controlled emulation
#endif
#include "guarded.h"
#include "project_efi.h"
#include "smbios.h"
extern const nb_u8 kernel_start[], kernel_end[], __image_start[], __image_end[];
extern int fixture_write(void *, nb_u32, const nb_u8 *, nb_u32);
extern int fixture_zero(void *, nb_u32, nb_u32);
static struct target_plan plan;
static struct nb_emulation_inputs input;
static struct nb_emulation_result result;
static struct target_efi_sources sources;
static struct target_project_result projected;
static nb_u8 projected_pages[8192] __attribute__((aligned(4096)));
static nb_u8 apple_copy[0x44c];
static struct nb_range reservations[32];
static nb_u32 reservation_count;
volatile nb_u32 target_emulated_status;
volatile nb_u32 target_emulated_bootinfo;
volatile nb_u32 target_emulated_projected;

static nb_u32 u32(const nb_u8 *p) {
    return p[0] | (nb_u32)p[1] << 8 | (nb_u32)p[2] << 16 | (nb_u32)p[3] << 24;
}
static int synthetic_read(void *context, nb_u32 address, void *dest, nb_u32 length) {
    const nb_u8 *source = (const nb_u8 *)(nb_uptr)address;
    nb_u8 *out = (nb_u8 *)dest; nb_u32 i;
    (void)context;
    for (i = 0; i < length; ++i) out[i] = source[i];
    return 0;
}
struct validation_context { const void *map; nb_u32 len, stride, version; };
static int validate_entry(void *context, nb_u32 kind, nb_u32 address,
                          nb_u64 owned_start, nb_u64 owned_end,
                          struct nb_range *out, nb_u32 *count) {
    const struct validation_context *v = context;
    struct target_fw_result fw;
    nb_u32 i; int status;
    if (owned_start != (nb_u32)(nb_uptr)projected_pages ||
        owned_end != owned_start + sizeof(projected_pages)) return -1;
    if (kind == TARGET_PROJECT_ACPI1 || kind == TARGET_PROJECT_ACPI2) {
        nb_u8 revision;
        status = target_validate_acpi(v->map, v->len, v->stride, v->version,
                    address, reservations, reservation_count, synthetic_read, 0, &fw);
        if (status || synthetic_read(0, address + 15, &revision, 1) ||
            (kind == TARGET_PROJECT_ACPI1 && revision != 0) ||
            (kind == TARGET_PROJECT_ACPI2 && revision < 2)) return -1;
    } else if (kind == TARGET_PROJECT_SMBIOS2)
        status = target_validate_smbios2(v->map, v->len, v->stride, v->version,
                    address, reservations, reservation_count, synthetic_read, 0, &fw);
    else return -1;
    if (status || !fw.count || fw.count > *count) return -1;
    *count = fw.count;
    for (i = 0; i < fw.count; ++i) out[i] = fw.reservations[i];
    return 0;
}
static int reserve(struct nb_range range) {
    nb_u32 i;
    for (i = 0; i < reservation_count; ++i)
        if (reservations[i].start == range.start && reservations[i].end == range.end) return 0;
    if (reservation_count >= 32) return -1;
    reservations[reservation_count++] = range;
    return 0;
}
static void put32(nb_u8 *p, nb_u32 value) {
    p[0] = value; p[1] = value >> 8; p[2] = value >> 16; p[3] = value >> 24;
}
void target_emulated_start(const nb_u8 *apple)
{
    const nb_u32 map_pa = u32(apple + 0x404), map_length = u32(apple + 0x408);
    const nb_u32 stride = u32(apple + 0x40c), version = u32(apple + 0x410);
    const nb_u32 system_pa = u32(apple + 0x444);
    const nb_u32 kernel_pa = (nb_u32)(nb_uptr)kernel_start;
    const nb_u32 kernel_length = (nb_u32)(kernel_end - kernel_start);
    struct nb_range loader = {(nb_u32)(nb_uptr)__image_start, (nb_u32)(nb_uptr)__image_end};
    struct validation_context context = {(const void *)(nb_uptr)map_pa, map_length, stride, version};
    nb_u32 i;
    if ((nb_u64)map_pa + map_length > ((nb_u64)1 << 32) ||
        (nb_u64)(nb_u32)(nb_uptr)apple + 0x44c > ((nb_u64)1 << 32) ||
        reserve(loader) || reserve((struct nb_range){(nb_u32)(nb_uptr)apple,
                       (nb_u64)(nb_u32)(nb_uptr)apple + 0x44c}) ||
        reserve((struct nb_range){map_pa, (nb_u64)map_pa + map_length}) ||
        target_read_efi_sources(context.map, map_length, stride, version, system_pa,
                                reservations, reservation_count, synthetic_read, 0, &sources)) {
        target_emulated_status = 0xbad; return;
    }
    if (target_project_efi(sources.system, 72, system_pa, sources.config,
                sources.config_length, sources.config_pa, (nb_u32)(nb_uptr)projected_pages,
                validate_entry, &context, projected_pages, &projected)) {
        target_emulated_status = 0xbad; return;
    }
    for (i = 0; i < sources.firmware.count; ++i)
        if (reserve(sources.firmware.reservations[i])) { target_emulated_status = 0xbad; return; }
    for (i = 0; i < projected.reservation_count; ++i)
        if (reserve(projected.reservations[i])) { target_emulated_status = 0xbad; return; }
    if (target_plan_memory(kernel_start, kernel_length, kernel_pa, context.map, map_length,
                stride, version, reservations, reservation_count, 0x08000000, &plan)) {
        target_emulated_status = 0xbad; return;
    }
    for (i = 0; i < sizeof(apple_copy); ++i) apple_copy[i] = apple[i];
    put32(apple_copy + 0x444, (nb_u32)(nb_uptr)projected_pages);
    input.apple_args = apple_copy; input.apple_args_pa = (nb_u32)(nb_uptr)apple_copy;
    input.apple_args_length = 0x44c;
    input.efi_map = (const void *)(nb_uptr)map_pa; input.efi_map_pa = map_pa;
    input.efi_map_length = map_length;
    input.kernel = kernel_start; input.kernel_pa = kernel_pa; input.kernel_length = kernel_length;
    input.bootinfo = (void *)(nb_uptr)plan.scratch.bootinfo.start;
    input.bootinfo_pa = (nb_u32)plan.scratch.bootinfo.start; input.bootinfo_capacity = NB_BOOTINFO_MAX;
    input.loader = loader; input.stack = plan.scratch.stack;
    input.usable = plan.usable; input.usable_count = plan.usable_count;
    input.reserved = plan.protected; input.reserved_count = plan.protected_count;
    input.write_fn = fixture_write; input.zero_fn = fixture_zero;
    if (nb_prepare_native_emulation(&input, &result)) { target_emulated_status = 0xbad; return; }
    target_emulated_bootinfo = result.bootinfo_pa;
    target_emulated_projected = (nb_u32)(nb_uptr)projected_pages;
    target_emulated_status = 0x600d;
    nb_enter_native(result.plan.entry, (nb_u32)plan.scratch.stack.end, 0x42,
                    result.bootinfo_pa, 0, 0, 0);
}
