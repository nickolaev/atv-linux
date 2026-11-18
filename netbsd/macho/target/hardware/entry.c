/* Experimental one-way hardware entry; identity reads are platform assumptions. */
#ifndef TARGET_EMULATION_ONLY
#error Experimental validated preparation support is required
#endif
#include "guarded.h"
#include "project_efi.h"
#include "smbios.h"
#ifdef TARGET_NATIVE_CHECKPOINT
#ifndef TARGET_DIAGNOSTIC_ACTUAL_COPY
#error Native checkpoint requires the returning actual-copy diagnostic
#endif
#include "checkpoint.h"
#endif
extern const nb_u8 kernel_start[], kernel_end[], __image_start[], __image_end[];
static struct target_plan plan;
static struct nb_emulation_inputs input;
static struct nb_emulation_result result;
static struct target_efi_sources sources;
static struct target_project_result projected;
static nb_u8 projected_pages[8192] __attribute__((aligned(4096)));
static nb_u8 apple_copy[0x44c];
static nb_u8 map_copy[8000];
static struct nb_range reservations[32];
static nb_u32 reservation_count;
volatile nb_u32 target_emulated_status;
volatile nb_u32 target_emulated_bootinfo;
volatile nb_u32 target_emulated_projected;

/* Optional diagnostic record in this loader's own image. A transport must
 * independently copy it before the image is reused; it is not persistent. */
#ifdef TARGET_DIAGNOSTIC
struct target_diagnostic_status {
    nb_u32 magic, version, stage, error;
    nb_u32 apple_pa, map_pa, map_length, system_pa;
    nb_u32 selected_kind, selected_pa, projected_pa, bootinfo_pa;
};
volatile struct target_diagnostic_status target_diagnostic_record;
static struct nb_range diagnostic_linux_image;
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
static nb_u32 diagnostic_hook_sp;
static nb_u32 diagnostic_copied, diagnostic_zeroed;
#ifdef TARGET_NATIVE_CHECKPOINT
static nb_u8 checkpoint_expected_bootinfo[NB_BOOTINFO_MAX];
#endif
#else
static nb_u8 diagnostic_bootinfo[NB_BOOTINFO_MAX];
#endif
#define DIAG_STAGE(value) (target_diagnostic_record.stage = (value))
#define DIAG_FIELD(field, value) (target_diagnostic_record.field = (value))
static int diagnostic_failed(nb_u32 code) {
    target_diagnostic_record.error = code;
    return 1;
}
#define DIAG_FAIL(expr, code) ((expr) ? diagnostic_failed(code) : 0)
#else
#define DIAG_STAGE(value) ((void)0)
#define DIAG_FIELD(field, value) ((void)0)
#define DIAG_FAIL(expr, code) (expr)
#endif

static nb_u32 u32(const nb_u8 *p) {
    return p[0] | (nb_u32)p[1] << 8 | (nb_u32)p[2] << 16 | (nb_u32)p[3] << 24;
}
static int physical_read(void *context, nb_u32 address, void *dest, nb_u32 length) {
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
    DIAG_FIELD(selected_kind, kind);
    DIAG_FIELD(selected_pa, address);
    if (owned_start != (nb_u32)(nb_uptr)projected_pages ||
        owned_end != owned_start + sizeof(projected_pages)) return -1;
    if (kind == TARGET_PROJECT_ACPI1 || kind == TARGET_PROJECT_ACPI2) {
        nb_u8 revision;
        status = target_validate_acpi(v->map, v->len, v->stride, v->version,
                    address, reservations, reservation_count, physical_read, 0, &fw);
        if (status || physical_read(0, address + 15, &revision, 1) ||
            (kind == TARGET_PROJECT_ACPI1 && revision != 0) ||
            (kind == TARGET_PROJECT_ACPI2 && revision < 2)) return -1;
    } else if (kind == TARGET_PROJECT_SMBIOS2)
        status = target_validate_smbios2(v->map, v->len, v->stride, v->version,
                    address, reservations, reservation_count, physical_read, 0, &fw);
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
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
/* On stage-6/error-10 only, reuse the four trailing status words as:
 * protection kind, start, length, and reason:8 / descriptor index:16 / type:8.
 * Index 0xffff and type 0xff mean no descriptor was involved. */
static int protection_failed(nb_u32 kind, nb_u64 begin, nb_u64 end,
                             nb_u32 reason, nb_u32 index, nb_u32 type) {
    nb_u64 size = end >= begin ? end - begin : 0;
    DIAG_FIELD(selected_kind, kind);
    DIAG_FIELD(selected_pa, begin > 0xffffffffu ? 0xffffffffu : (nb_u32)begin);
    DIAG_FIELD(projected_pa, size > 0xffffffffu ? 0xffffffffu : (nb_u32)size);
    DIAG_FIELD(bootinfo_pa, (reason << 24) | ((index & 0xffffu) << 8) | (type & 0xffu));
    return -1;
}
/* Preserve every descriptor touching live return-state memory. The guard
 * band is a conservative platform assumption, not a proven stack extent. */
static int protect_live(const nb_u8 *map, nb_u32 length, nb_u32 stride,
                        nb_u64 begin, nb_u64 end, nb_u32 kind) {
    nb_u32 off; int covered = 0, allocated = 0;
    if (begin < 0x1000 || begin >= end || end > 0x10000000)
        return protection_failed(kind, begin, end, 1, 0xffff, 0xff);
    for (off = 0; off < length; off += stride) {
        const nb_u8 *d = map + off;
        nb_u64 base = u32(d + 8) | (nb_u64)u32(d + 12) << 32;
        nb_u64 pages = u32(d + 24) | (nb_u64)u32(d + 28) << 32;
        nb_u64 stop; nb_u32 type = u32(d);
        if ((base & 4095) || !pages || pages > (((nb_u64)-1 - base) >> 12))
            return protection_failed(kind, begin, end, 2, off / stride, type);
        stop = base + (pages << 12);
        if (base >= end || begin >= stop) continue;
        if (!((type >= 1 && type <= 7) || type == 9 || type == 10))
            return protection_failed(kind, begin, end, 3, off / stride, type);
        if (stop > ((nb_u64)1 << 32))
            return protection_failed(kind, begin, end, 4, off / stride, type);
        if (base <= begin && stop >= end) {
            covered = 1;
            if (type != 7) allocated = 1;
        }
    }
    if (!covered) return protection_failed(kind, begin, end, 5, 0xffff, 0xff);
    for (off = 0; off < length; off += stride) {
        const nb_u8 *d = map + off;
        nb_u64 base = u32(d + 8) | (nb_u64)u32(d + 12) << 32;
        nb_u64 pages = u32(d + 24) | (nb_u64)u32(d + 28) << 32;
        nb_u64 stop = base + (pages << 12);
        if (base >= end || begin >= stop) continue;
        /* Apple reports broad conventional ranges overlapping runtime data.
         * A complete non-conventional backing allocation protects the object;
         * avoid unnecessarily reserving the overlapping broad range. */
        if (u32(d) == 7 && allocated) continue;
        if (reserve((struct nb_range){base, stop}))
            return protection_failed(kind, begin, end, 6, off / stride, u32(d));
    }
    return 0;
}
static int protect_return_state(const nb_u8 *map, nb_u32 length, nb_u32 stride) {
    struct descriptor_register { unsigned short limit; nb_u32 base; } __attribute__((packed));
    struct descriptor_register gdtr, idtr;
    __asm__ volatile("sgdt %0" : "=m"(gdtr));
    __asm__ volatile("sidt %0" : "=m"(idtr));
    if (diagnostic_hook_sp < 8192)
        return protection_failed(1, diagnostic_hook_sp, diagnostic_hook_sp, 1, 0xffff, 0xff);
    if (protect_live(map, length, stride, (nb_u64)diagnostic_hook_sp - 4096,
                     (nb_u64)diagnostic_hook_sp + 4096, 1) ||
        protect_live(map, length, stride, gdtr.base, (nb_u64)gdtr.base + gdtr.limit + 1, 2) ||
        protect_live(map, length, stride, idtr.base, (nb_u64)idtr.base + idtr.limit + 1, 3)) return -1;
    return 0;
}
#ifdef TARGET_NATIVE_CHECKPOINT
/* The exact kernel's native entry changes the warm-boot word in page zero.
 * Accept only a full conventional write-back page with no restricted
 * overlap, and keep the entire page outside all planned writes. */
static int protect_bda(const nb_u8 *map, nb_u32 length, nb_u32 stride) {
    nb_u32 off, i; int covered = 0;
    for (i = 0; i < reservation_count; ++i)
        if (reservations[i].start < 4096 && reservations[i].end > 0) return -1;
    for (off = 0; off < length; off += stride) {
        const nb_u8 *d = map + off;
        nb_u64 base = u32(d + 8) | (nb_u64)u32(d + 12) << 32;
        nb_u64 pages = u32(d + 24) | (nb_u64)u32(d + 28) << 32;
        nb_u64 attrs = u32(d + 32) | (nb_u64)u32(d + 36) << 32;
        nb_u64 stop;
        if ((base & 4095) || !pages || pages > (((nb_u64)-1 - base) >> 12)) return -1;
        stop = base + (pages << 12);
        if (base >= 4096 || stop == 0) continue;
        if (u32(d) != 7 || !(attrs & 8) || (attrs >> 63)) return -1;
        if (base == 0 && stop >= 4096) covered = 1;
    }
    return covered ? reserve((struct nb_range){0, 4096}) : -1;
}
#endif
/* The returning Linux loader still consumes the original EFI table/map,
 * selected configuration pointers and framebuffer. Preserve all direct
 * firmware references, even entries omitted from the projected NetBSD table.
 * Unknown objects are protected by their entire current EFI descriptors;
 * unsupported or unbacked references fail closed. */
static int protect_return_sources(const nb_u8 *apple, const nb_u8 *map,
                                  nb_u32 length, nb_u32 stride,
                                  const struct target_efi_sources *saved) {
    static const nb_u8 pointer_offsets[] = {24, 32, 36, 40, 44, 48, 52, 56, 60};
    static const nb_u8 acpi1[16]={0x30,0x2d,0x9d,0xeb,0x88,0x2d,0xd3,0x11,0x9a,0x16,0,0x90,0x27,0x3f,0xc1,0x4d};
    static const nb_u8 acpi2[16]={0x71,0xe8,0x68,0x88,0xf1,0xe4,0xd3,0x11,0xbc,0x22,0,0x80,0xc7,0x3c,0x88,0x81};
    static const nb_u8 smbios2[16]={0x31,0x2d,0x9d,0xeb,0x88,0x2d,0xd3,0x11,0x9a,0x16,0,0x90,0x27,0x3f,0xc1,0x4d};
    nb_u32 ptr, size, i, j, base, pitch, height, suffix = 0; nb_u64 end;
    /* mach_boot_parms: devtree_ptr/len at 0x42c/0x430. */
    ptr = u32(apple + 0x42c); size = u32(apple + 0x430);
    if (!!ptr != !!size) return protection_failed(4, ptr, (nb_u64)ptr + size, 7, 0xffff, 0xff);
    if (ptr && protect_live(map, length, stride, ptr, (nb_u64)ptr + size, 4)) return -1;
    /* Kernel/source allocation and EFI runtime ranges, when provided. */
    ptr = u32(apple + 0x434); size = u32(apple + 0x438);
    if (!!ptr != !!size) return protection_failed(5, ptr, (nb_u64)ptr + size, 7, 0xffff, 0xff);
    /* Apple's kaddr/ksize spans the loaded Mach-O envelope, which can cover
     * several EFI descriptors and gaps. Preserve the entire envelope without
     * reading it or requiring one descriptor to describe the whole span. */
    if (ptr && (ptr < 0x1000 || (nb_u64)ptr + size > ((nb_u64)1 << 32)))
        return protection_failed(5, ptr, (nb_u64)ptr + size, 1, 0xffff, 0xff);
    if (ptr && reserve((struct nb_range){ptr, (nb_u64)ptr + size}))
        return protection_failed(5, ptr, (nb_u64)ptr + size, 6, 0xffff, 0xff);
    ptr = u32(apple + 0x43c); size = u32(apple + 0x440);
    if (!!ptr != !!size) return protection_failed(6, (nb_u64)ptr << 12,
                                           ((nb_u64)ptr + size) << 12, 7, 0xffff, 0xff);
    if (ptr && protect_live(map, length, stride, (nb_u64)ptr << 12,
                            ((nb_u64)ptr + size) << 12, 6)) return -1;
    if (saved->config_length % 20)
        return protection_failed(0x0700, 0, saved->config_length, 7, 0xffff, 0xff);
    for (i = 0; i < saved->config_length; i += 20) {
        int is_acpi1 = 1, is_acpi2 = 1, is_smbios2 = 1;
        for (j = 0; j < 16; ++j) {
            if (saved->config[i+j] != acpi1[j]) is_acpi1 = 0;
            if (saved->config[i+j] != acpi2[j]) is_acpi2 = 0;
            if (saved->config[i+j] != smbios2[j]) is_smbios2 = 0;
        }
        ptr = u32(saved->config + i + 16);
        if (!ptr || ptr >= 0x10000000u) continue;
        if (protect_live(map, length, stride, ptr, (nb_u64)ptr + 1,
                         0x0700 | (i / 20))) return -1;
        /* Dropped entries have no known object length. Their data might
         * extend through later EFI descriptors into scratch or PT_LOAD. */
        if (!(is_acpi1 || is_acpi2 || is_smbios2) && (!suffix || ptr < suffix)) suffix = ptr;
    }
    for (i = 0; i < sizeof(pointer_offsets); ++i) {
        ptr = u32(saved->system + pointer_offsets[i]);
        if (!ptr || ptr >= 0x10000000u) continue;
        if (protect_live(map, length, stride, ptr, (nb_u64)ptr + 1,
                         0x0800 | pointer_offsets[i])) return -1;
        if (!suffix || ptr < suffix) suffix = ptr;
    }
    /* Reserve the suffix to the highest permitted target address, not only
     * the first descriptor holding an unknown-length direct object. */
    if (suffix && reserve((struct nb_range){suffix, 0x10000000u}))
        return protection_failed(9, suffix, 0x10000000u, 6, 0xffff, 0xff);
    /* The original loader clears and passes the framebuffer to Linux after
     * returning. It can be MMIO, so reserve its span without dereferencing. */
    base = u32(apple + 0x414); pitch = u32(apple + 0x41c); height = u32(apple + 0x424);
    if (base || pitch || height) {
        if (!base || !pitch || !height)
            return protection_failed(10, base, base, 7, 0xffff, 0xff);
        end = (nb_u64)base + (nb_u64)pitch * height;
        if (end <= base || end > ((nb_u64)1 << 32))
            return protection_failed(10, base, end, 1, 0xffff, 0xff);
        if (reserve((struct nb_range){base, end}))
            return protection_failed(10, base, end, 6, 0xffff, 0xff);
    }
    return 0;
}
#endif
static void put32(nb_u8 *p, nb_u32 value) {
    p[0] = value; p[1] = value >> 8; p[2] = value >> 16; p[3] = value >> 24;
}
/* Reject writes outside the already-validated destination load segments. */
static int allowed(nb_u32 address, nb_u32 length) {
    nb_u32 i;
    nb_u64 end = (nb_u64)address + length;
    for (i = 0; i < plan.kernel.segment_count; ++i) {
        const struct nb_segment *s = &plan.kernel.segments[i];
        if (address >= s->physical_address &&
            end <= (nb_u64)s->physical_address + s->memory_size) return 1;
    }
    return 0;
}
static int hardware_write(void *context, nb_u32 address, const nb_u8 *bytes, nb_u32 length) {
    nb_u8 *dest = (nb_u8 *)(nb_uptr)address; nb_u32 i; (void)context;
    if (!allowed(address, length)) return -1;
    for (i = 0; i < length; ++i) dest[i] = bytes[i];
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
    diagnostic_copied += length;
#endif
    return 0;
}
static int hardware_zero(void *context, nb_u32 address, nb_u32 length) {
    nb_u8 *dest = (nb_u8 *)(nb_uptr)address; nb_u32 i; (void)context;
    if (!allowed(address, length)) return -1;
    for (i = 0; i < length; ++i) dest[i] = 0;
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
    diagnostic_zeroed += length;
#endif
    return 0;
}
#if defined(TARGET_DIAGNOSTIC) && !defined(TARGET_DIAGNOSTIC_ACTUAL_COPY)
/* Exercise native preparation, but never write a planned kernel destination. */
static int diagnostic_write(void *context, nb_u32 address, const nb_u8 *bytes, nb_u32 length) {
    (void)context; (void)bytes;
    return allowed(address, length) ? 0 : -1;
}
static int diagnostic_zero(void *context, nb_u32 address, nb_u32 length) {
    (void)context;
    return allowed(address, length) ? 0 : -1;
}
#endif
void target_emulated_start(const nb_u8 *apple)
{
    nb_u32 map_pa, map_length, stride, version, system_pa;
    const nb_u32 kernel_pa = (nb_u32)(nb_uptr)kernel_start;
    const nb_u32 kernel_length = (nb_u32)(kernel_end - kernel_start);
    struct nb_range loader = {(nb_u32)(nb_uptr)__image_start, (nb_u32)(nb_uptr)__image_end};
    struct validation_context context;
    nb_u32 i;
    nb_u32 apple_pa = (nb_u32)(nb_uptr)apple;
#ifdef TARGET_DIAGNOSTIC
    target_diagnostic_record.magic = 0x47414944; /* DIAG */
    target_diagnostic_record.version = 1;
    target_diagnostic_record.error = 0;
#endif
    DIAG_FIELD(apple_pa, apple_pa);
    DIAG_STAGE(1); /* boot-argument address */
    /* Conservative identity-readable window, as used by the working probe.
     * No physical access can prove firmware mapping or object lifetime. */
    if (apple_pa < 0x1000 || (nb_u64)apple_pa + 0x44c > 0x10000000 ||
        (apple_pa < loader.end && loader.start < (nb_u64)apple_pa + 0x44c)) {
        DIAG_FIELD(error, 1); target_emulated_status = 0xbad; return;
    }
    DIAG_STAGE(2); /* boot-argument fields and memory-map bounds */
    map_pa = u32(apple + 0x404); map_length = u32(apple + 0x408);
    stride = u32(apple + 0x40c); version = u32(apple + 0x410);
    system_pa = u32(apple + 0x444);
    DIAG_FIELD(map_pa, map_pa);
    DIAG_FIELD(map_length, map_length);
    DIAG_FIELD(system_pa, system_pa);
    if (apple[0x448] != 32 || map_pa < 0x1000 || (map_pa & 3) || !map_length ||
        map_length > sizeof(map_copy) || stride < 40 || (stride & 3) ||
        map_length % stride || version != 1 ||
        (nb_u64)map_pa + map_length > 0x10000000 ||
        ((nb_u64)map_pa < loader.end && loader.start < (nb_u64)map_pa + map_length) ||
        ((nb_u64)map_pa < (nb_u64)apple_pa + 0x44c && apple_pa < (nb_u64)map_pa + map_length)) {
        DIAG_FIELD(error, 2); target_emulated_status = 0xbad; return;
    }
    DIAG_STAGE(3); /* copying the current argument and map snapshots */
    for (i = 0; i < sizeof(apple_copy); ++i) apple_copy[i] = apple[i];
    for (i = 0; i < map_length; ++i) map_copy[i] = ((const nb_u8 *)(nb_uptr)map_pa)[i];
    context.map = map_copy; context.len = map_length; context.stride = stride; context.version = version;
    DIAG_STAGE(4); /* source reservation and EFI system/config snapshots */
    if (
        DIAG_FAIL(reserve(loader), 3) ||
#ifdef TARGET_DIAGNOSTIC
        DIAG_FAIL(reserve(diagnostic_linux_image), 3) ||
#endif
        DIAG_FAIL(reserve((struct nb_range){(nb_u32)(nb_uptr)apple,
                       (nb_u64)(nb_u32)(nb_uptr)apple + 0x44c}), 3) ||
        DIAG_FAIL(reserve((struct nb_range){map_pa, (nb_u64)map_pa + map_length}), 3) ||
        DIAG_FAIL(target_read_efi_sources(context.map, map_length, stride, version, system_pa,
                                reservations, reservation_count, physical_read, 0, &sources), 4)) {
        target_emulated_status = 0xbad; return;
    }
    DIAG_STAGE(5); /* ACPI/SMBIOS checks and EFI projection */
    if (target_project_efi(sources.system, 72, system_pa, sources.config,
                sources.config_length, sources.config_pa, (nb_u32)(nb_uptr)projected_pages,
                validate_entry, &context, projected_pages, &projected)) {
        DIAG_FIELD(error, 5); target_emulated_status = 0xbad; return;
    }
    DIAG_FIELD(projected_pa, (nb_u32)(nb_uptr)projected_pages);
    DIAG_STAGE(6); /* retain firmware reservations */
    for (i = 0; i < sources.firmware.count; ++i)
        if (reserve(sources.firmware.reservations[i])) { DIAG_FIELD(error, 6); target_emulated_status = 0xbad; return; }
    for (i = 0; i < projected.reservation_count; ++i)
        if (reserve(projected.reservations[i])) { DIAG_FIELD(error, 6); target_emulated_status = 0xbad; return; }
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
    /* Protect live return-state descriptors before planning any real write. */
    if (protect_return_state(context.map, map_length, stride) ||
        protect_return_sources(apple_copy, context.map, map_length, stride, &sources)) {
        DIAG_FIELD(error, 10); target_emulated_status = 0xbad; return;
    }
#ifdef TARGET_NATIVE_CHECKPOINT
    if (protect_bda(context.map, map_length, stride)) {
        DIAG_FIELD(error, 12); target_emulated_status = 0xbad; return;
    }
#endif
#endif
    DIAG_STAGE(7); /* kernel destinations and scratch-space planning */
    if (target_plan_memory(kernel_start, kernel_length, kernel_pa, context.map, map_length,
                stride, version, reservations, reservation_count,
#ifdef HARDWARE_TEST
                0x08000000,
#else
                0x10000000,
#endif
                &plan)) {
        DIAG_FIELD(error, 7); target_emulated_status = 0xbad; return;
    }
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
    /* The unknown-pointer suffix rule is bounded at 256 MiB; enforce the
     * same limit on actual kernel writes, not just on scratch placement. */
    for (i = 0; i < plan.kernel.segment_count; ++i) {
        const struct nb_segment *s = &plan.kernel.segments[i];
        if ((nb_u64)s->physical_address + s->memory_size > 0x10000000u) {
            DIAG_FIELD(error, 7); target_emulated_status = 0xbad; return;
        }
    }
#endif
    put32(apple_copy + 0x404, (nb_u32)(nb_uptr)map_copy);
    put32(apple_copy + 0x444, (nb_u32)(nb_uptr)projected_pages);
    input.apple_args = apple_copy; input.apple_args_pa = (nb_u32)(nb_uptr)apple_copy;
    input.apple_args_length = 0x44c;
    input.efi_map = map_copy; input.efi_map_pa = (nb_u32)(nb_uptr)map_copy;
    input.efi_map_length = map_length;
    input.kernel = kernel_start; input.kernel_pa = kernel_pa; input.kernel_length = kernel_length;
#if defined(TARGET_DIAGNOSTIC) && !defined(TARGET_DIAGNOSTIC_ACTUAL_COPY)
    input.bootinfo = diagnostic_bootinfo;
#else
    input.bootinfo = (void *)(nb_uptr)plan.scratch.bootinfo.start;
#endif
    input.bootinfo_pa = (nb_u32)plan.scratch.bootinfo.start; input.bootinfo_capacity = NB_BOOTINFO_MAX;
    input.loader = loader; input.stack = plan.scratch.stack;
    input.usable = plan.usable; input.usable_count = plan.usable_count;
    input.reserved = plan.protected; input.reserved_count = plan.protected_count;
#if defined(TARGET_DIAGNOSTIC) && !defined(TARGET_DIAGNOSTIC_ACTUAL_COPY)
    input.write_fn = diagnostic_write; input.zero_fn = diagnostic_zero;
#else
    input.write_fn = hardware_write; input.zero_fn = hardware_zero;
#endif
    DIAG_STAGE(8); /* bootinfo construction and kernel copy */
    if (nb_prepare_native_emulation(&input, &result)) { DIAG_FIELD(error, 8); target_emulated_status = 0xbad; return; }
    target_emulated_bootinfo = result.bootinfo_pa;
    target_emulated_projected = (nb_u32)(nb_uptr)projected_pages;
    target_emulated_status = 0x600d;
    DIAG_FIELD(bootinfo_pa, result.bootinfo_pa);
    DIAG_STAGE(9); /* preparation complete; not proof of kernel execution */
#ifdef TARGET_DIAGNOSTIC
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
    for (i = 0; i < plan.kernel.segment_count; ++i) {
        const struct nb_segment *s = &plan.kernel.segments[i];
        const nb_u8 *destination = (const nb_u8 *)(nb_uptr)s->physical_address;
        nb_u32 j;
        for (j = 0; j < s->file_size; ++j)
            if (destination[j] != kernel_start[s->source_offset + j]) {
                DIAG_FIELD(error, 11); return;
            }
        for (j = s->file_size; j < s->memory_size; ++j)
            if (destination[j]) { DIAG_FIELD(error, 11); return; }
    }
    DIAG_FIELD(selected_kind, diagnostic_copied);
    DIAG_FIELD(selected_pa, diagnostic_zeroed);
    DIAG_STAGE(10); /* real planned destinations copied and verified */
#ifdef TARGET_NATIVE_CHECKPOINT
    /* This diagnostic accepts only the exact hashed 11.1 heartbeat kernel.
     * Copy the generated pointer array and records into disjoint owned memory
     * before checkpoint_run verifies it and temporarily enters that kernel. */
    if (!result.bootinfo_size || result.bootinfo_size > NB_BOOTINFO_MAX) {
        DIAG_FIELD(error, 13); return;
    }
    for (i = 0; i < result.bootinfo_size; ++i)
        checkpoint_expected_bootinfo[i] = ((const nb_u8 *)(nb_uptr)result.bootinfo_pa)[i];
    if (checkpoint_run(kernel_start, kernel_length, result.bootinfo_pa,
                       (nb_u32)plan.scratch.stack.end, 1,
                       checkpoint_expected_bootinfo, result.bootinfo_size)) {
        DIAG_FIELD(error, 13); return;
    }
    /* Fixed symbols belong only to the source-hash-pinned test kernel.
     * native_loader stores count and concatenated records, dropping the
     * loader-side physical pointer array. */
    {
        const nb_u8 *kernel_info = (const nb_u8 *)(nb_uptr)0x0150d9e0;
        if (u32(kernel_info) != 2 ||
            u32((const nb_u8 *)(nb_uptr)0x0153afe4) != 0x00020002 ||
            u32((const nb_u8 *)(nb_uptr)0x00fa63d8) != 0 ||
            u32((const nb_u8 *)(nb_uptr)0x00fa63dc) != 0 ||
            u32((const nb_u8 *)(nb_uptr)0x014f3c34) != 0 ||
            u32((const nb_u8 *)(nb_uptr)0x014f3c2c) != 1 ||
            result.bootinfo_size < 12) {
            DIAG_FIELD(error, 14); return;
        }
        for (i = 0; i < result.bootinfo_size - 12; ++i)
            if (kernel_info[4 + i] != checkpoint_expected_bootinfo[12 + i]) {
                DIAG_FIELD(error, 14); return;
            }
    }
    DIAG_STAGE(11); /* native_loader returned and copied records verified */
#endif
#endif
    return;
#endif
    /* Single-user installer, verbose; do not request the kernel debugger. */
    nb_enter_native(result.plan.entry, (nb_u32)plan.scratch.stack.end, 0x00020002,
                    result.bootinfo_pa, 0, 0, 0);
}

#ifdef TARGET_DIAGNOSTIC
/* The caller derives these exact bounds from the validated original Mach-O
 * mappings. Its trampoline must provide a disjoint stack, preserve machine
 * state, and copy the exported record before Linux can reuse this image. */
void target_diagnostic_run(const nb_u8 *apple, nb_u32 linux_start, nb_u32 linux_end
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
                           , nb_u32 hook_sp
#endif
                           )
{
    nb_u32 i;
    volatile nb_u32 *fields = (volatile nb_u32 *)&target_diagnostic_record;
    for (i = 0; i < sizeof(target_diagnostic_record) / sizeof(*fields); ++i)
        fields[i] = 0;
    if (linux_start < 0x1000 || linux_end <= linux_start ||
        ((nb_u64)linux_start < (nb_u64)(nb_uptr)__image_end &&
         (nb_u64)(nb_uptr)__image_start < linux_end)) {
        target_diagnostic_record.magic = 0x47414944;
        target_diagnostic_record.version = 1;
        target_diagnostic_record.stage = 1;
        target_diagnostic_record.error = 9; /* invalid original image bounds */
        return;
    }
    diagnostic_linux_image.start = linux_start;
    diagnostic_linux_image.end = linux_end;
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
    diagnostic_hook_sp = hook_sp;
#endif
    target_emulated_start(apple);
}
#endif
