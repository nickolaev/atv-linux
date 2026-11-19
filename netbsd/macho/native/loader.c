/* Emulation-only integration. It cannot establish EFI runtime safety. */
#include "handoff.h"

#ifdef NB_ENABLE_EXPERIMENTAL_HANDOFF
#define LIMIT ((nb_u64)1 << 32)
#define MAX_USABLE 128u
#define MAX_RESERVED 48u
#define EFI_CONVENTIONAL_MEMORY 7u
#define EFI_MEMORY_WB 8u
#define EFI_MEMORY_RUNTIME ((nb_u64)1 << 63)
#define MAX_MAP_DESCRIPTORS 256u
/* NetBSD 11.1 i386 vmparam.h: VM_PHYSSEG_MAX=32 (non-Xen). */
#define NB_I386_PHYSSEG_MAX 32u
/* Conservative assumed bound for the fixed EFI 1.x IA-32 system table.
 * This routine does not validate the actual table header or size. Referenced
 * runtime/config tables must also be reserved by the caller. */
#define EFI32_SYSTEM_TABLE_BOUND 128u

static nb_u32 le32(const nb_u8 *p)
{
    return (nb_u32)p[0] | ((nb_u32)p[1] << 8) | ((nb_u32)p[2] << 16) |
           ((nb_u32)p[3] << 24);
}

static nb_u64 le64(const nb_u8 *p)
{
    return (nb_u64)le32(p) | ((nb_u64)le32(p + 4) << 32);
}

static int range(nb_u64 start, nb_u64 length, struct nb_range *out)
{
    if (!length || start >= LIMIT || length > LIMIT - start) return 0;
    out->start = start;
    out->end = start + length;
    return 1;
}

static int valid_range(struct nb_range r)
{
    return r.start < r.end && r.end <= LIMIT;
}

static int overlap(struct nb_range a, struct nb_range b)
{
    return a.start < b.end && b.start < a.end;
}

static int pointer_overlap(const void *a, nb_u64 alen, const void *b, nb_u64 blen)
{
    nb_uptr ap = (nb_uptr)a, bp = (nb_uptr)b, top = (nb_uptr)-1;
    if (!a || !b || alen > (nb_u64)(top - ap) || blen > (nb_u64)(top - bp)) return 1;
    return (nb_u64)ap < (nb_u64)bp + blen && (nb_u64)bp < (nb_u64)ap + alen;
}

/* Any restricted descriptor intersecting a usable range wins, even if a
 * conventional descriptor also covers it. Preserve overlaps elsewhere. */
static int check_map(const nb_u8 *map, nb_u32 map_length, nb_u32 stride,
                     const struct nb_range *usable, nb_u32 usable_count)
{
    nb_u32 i, j;
    if (stride < 40 || (stride & 3) || !map_length || map_length % stride ||
        map_length / stride > MAX_MAP_DESCRIPTORS)
        return 0;
    for (i = 0; i < map_length; i += stride) {
        const nb_u8 *d = map + i;
        nb_u64 base = le64(d + 8), pages = le64(d + 24);
        if ((base & 4095) || !pages || pages > (((nb_u64)-1 - base) >> 12))
            return 0;
    }
    for (j = 0; j < usable_count; ++j) {
        int covered = 0;
        if (!valid_range(usable[j])) return 0;
        for (i = 0; i < map_length; i += stride) {
            const nb_u8 *d = map + i;
            nb_u64 base = le64(d + 8), end = base + (le64(d + 24) << 12);
            if (base < usable[j].end && usable[j].start < end) {
                if (le32(d) != EFI_CONVENTIONAL_MEMORY || !(le64(d + 32) & EFI_MEMORY_WB) ||
                    (le64(d + 32) & EFI_MEMORY_RUNTIME))
                    return 0;
                if (base <= usable[j].start && end >= usable[j].end) covered = 1;
            }
        }
        if (!covered) return 0;
    }
    return 1;
}

/* Require a data allocation covering the bounded table. The Apple TV map
 * also reports ConventionalMemory on top of RuntimeServicesData; allow that
 * particular overlap, but reject other conflicting kinds. This checks only
 * descriptor coverage: it never dereferences or validates the table. */
static int check_table_coverage(const nb_u8 *map, nb_u32 length, nb_u32 stride,
                                nb_u32 table_pa)
{
    nb_u64 start = table_pa, end = start + EFI32_SYSTEM_TABLE_BOUND;
    nb_u32 i, allocated_type = 0;
    int covered = 0;
    if (end > LIMIT) return 0;
    for (i = 0; i < length; i += stride) {
        const nb_u8 *d = map + i;
        nb_u64 base = le64(d + 8), stop = base + (le64(d + 24) << 12);
        nb_u32 type = le32(d);
        if (base >= end || start >= stop) continue;
        if (type == EFI_CONVENTIONAL_MEMORY) continue;
        if (type != 2 && type != 4 && type != 6) return 0;
        if (allocated_type && allocated_type != type) return 0;
        allocated_type = type;
        if (base <= start && stop >= end) covered = 1;
    }
    return covered;
}

static void put32(nb_u8 *p, nb_u32 value)
{
    p[0] = (nb_u8)value; p[1] = (nb_u8)(value >> 8);
    p[2] = (nb_u8)(value >> 16); p[3] = (nb_u8)(value >> 24);
}

static void put64(nb_u8 *p, nb_u64 value)
{
    put32(p, (nb_u32)value); put32(p + 4, (nb_u32)(value >> 32));
}

/* Sweep all firmware and reservation boundaries, first counting and then
 * writing. Unknown, non-WB, runtime and live allocations stay reserved. */
/* x86_parse_clusters excludes the ISA compatibility hole. Count both sides
 * conservatively, including regions the kernel might later discard. */
static nb_u32 cluster_parts(nb_u64 start, nb_u64 end)
{
    return (start < 0xa0000u && end > 0) + (start < end && end > 0x100000u);
}

static nb_u32 emit_map(const nb_u8 *map, nb_u32 length, nb_u32 stride,
                       const struct nb_range *reserved, nb_u32 n, nb_u8 *out)
{
    nb_u64 pos = (nb_u64)-1, next, previous_start = 0, previous_end = 0;
    nb_u32 i, count = 0, previous_type = 0, clusters = 0;
    for (i = 0; i < length; i += stride) {
        nb_u64 base = le64(map + i + 8);
        if (base < pos) pos = base;
    }
    for (i = 0; i < n; ++i) if (reserved[i].start < pos) pos = reserved[i].start;
    while (pos != (nb_u64)-1) {
        int memory = 0, acpi = 0, nvs = 0, blocked = 0, covered = 0;
        nb_u32 type;
        next = (nb_u64)-1;
        for (i = 0; i < length; i += stride) {
            const nb_u8 *d = map + i;
            nb_u64 base = le64(d + 8), end = base + (le64(d + 24) << 12);
            nb_u64 attrs = le64(d + 32);
            nb_u32 t = le32(d);
            if (base > pos && base < next) next = base;
            if (end > pos && end < next) next = end;
            if (base > pos || end <= pos) continue;
            covered = 1;
            if ((attrs & EFI_MEMORY_RUNTIME) || (t != 7 && t != 9 && t != 10) ||
                (t == 7 && !(attrs & EFI_MEMORY_WB))) blocked = 1;
            else if (t == 7) memory = 1;
            else if (t == 9) acpi = 1;
            else nvs = 1;
        }
        for (i = 0; i < n; ++i) {
            if (reserved[i].start > pos && reserved[i].start < next) next = reserved[i].start;
            if (reserved[i].end > pos && reserved[i].end < next) next = reserved[i].end;
            if (reserved[i].start <= pos && pos < reserved[i].end) blocked = 1;
        }
        if (next == (nb_u64)-1) break;
        if (covered) {
            type = (blocked || (acpi && nvs)) ? 2u : nvs ? 4u : acpi ? 3u : memory ? 1u : 2u;
            if (count && previous_end == pos && previous_type == type) {
                if (type == 1)
                    clusters += cluster_parts(previous_start, next) -
                                cluster_parts(previous_start, previous_end);
                if (out) put64(out + (count - 1) * 20 + 8,
                               next - le64(out + (count - 1) * 20));
            } else {
                if (type == 1) clusters += cluster_parts(pos, next);
                if (out) { put64(out + count * 20, pos); put64(out + count * 20 + 8, next - pos);
                           put32(out + count * 20 + 16, type); }
                ++count;
                previous_start = pos;
            }
            previous_end = next; previous_type = type;
        }
        pos = next;
    }
    return clusters > NB_I386_PHYSSEG_MAX ? 0 : count;
}

int nb_prepare_native_emulation(const struct nb_emulation_inputs *input,
                                struct nb_emulation_result *result)
{
    const nb_u8 *args, *map;
    struct nb_range reserved[MAX_RESERVED], args_range, map_range, kernel_range;
    struct nb_range info_range, table_range;
    struct nb_plan plan;
    nb_u32 map_pa, map_length, stride, version, table_pa, i, n = 0, used, map_count;
    nb_u64 needed;
    int info_usable = 0, stack_backed = 0;
    if (!result || !input || !input->apple_args || input->apple_args_length < 0x44c ||
        !input->efi_map || !input->kernel || !input->bootinfo ||
        !input->usable || !input->usable_count || input->usable_count > MAX_USABLE ||
        input->reserved_count > MAX_RESERVED - 7 ||
        (input->reserved_count && !input->reserved) ||
        !input->write_fn || !input->zero_fn ||
        !valid_range(input->loader) || !valid_range(input->stack) ||
        input->stack.end - input->stack.start < 16384 || input->stack.end >= LIMIT ||
        (input->stack.end & 3) ||
        !range(input->apple_args_pa, input->apple_args_length, &args_range) ||
        !range(input->efi_map_pa, input->efi_map_length, &map_range) ||
        !range(input->kernel_pa, input->kernel_length, &kernel_range)) return -1;
    /* Host pointers and simulated physical addresses are independent. Check
     * output-object aliases before writing either result or bootinfo. */
    if (pointer_overlap(result, sizeof(*result), input, sizeof(*input)) ||
        pointer_overlap(result, sizeof(*result), input->apple_args, input->apple_args_length) ||
        pointer_overlap(result, sizeof(*result), input->efi_map, input->efi_map_length) ||
        pointer_overlap(result, sizeof(*result), input->kernel, input->kernel_length) ||
        pointer_overlap(result, sizeof(*result), input->bootinfo, input->bootinfo_capacity) ||
        pointer_overlap(result, sizeof(*result), input->usable, (nb_u64)input->usable_count * sizeof(*input->usable)) ||
        (input->reserved_count && pointer_overlap(result, sizeof(*result), input->reserved,
                                                 (nb_u64)input->reserved_count * sizeof(*input->reserved))) ||
        pointer_overlap(input->bootinfo, input->bootinfo_capacity, input, sizeof(*input)) ||
        pointer_overlap(input->bootinfo, input->bootinfo_capacity, input->apple_args, input->apple_args_length) ||
        pointer_overlap(input->bootinfo, input->bootinfo_capacity, input->efi_map, input->efi_map_length) ||
        pointer_overlap(input->bootinfo, input->bootinfo_capacity, input->kernel, input->kernel_length) ||
        pointer_overlap(input->bootinfo, input->bootinfo_capacity, input->usable,
                        (nb_u64)input->usable_count * sizeof(*input->usable)) ||
        (input->reserved_count && pointer_overlap(input->bootinfo, input->bootinfo_capacity, input->reserved,
                                                 (nb_u64)input->reserved_count * sizeof(*input->reserved))))
        return -1;
    args = (const nb_u8 *)input->apple_args;
    map = (const nb_u8 *)input->efi_map;
    map_pa = le32(args + 0x404); map_length = le32(args + 0x408);
    stride = le32(args + 0x40c); version = le32(args + 0x410);
    table_pa = le32(args + 0x444);
    if (map_pa != input->efi_map_pa || map_length != input->efi_map_length ||
        version != 1 || args[0x448] != 32 || !table_pa || (table_pa & 3) ||
        (table_pa & 4095u) > 4096u - EFI32_SYSTEM_TABLE_BOUND ||
        !check_map(map, map_length, stride, input->usable, input->usable_count) ||
        !check_table_coverage(map, map_length, stride, table_pa)) return -1;
    if (!range(input->bootinfo_pa, input->bootinfo_capacity, &info_range) || (input->bootinfo_pa & 3) ||
        !range(table_pa & ~4095u, 4096, &table_range)) return -1;
    for (i = 0; i < input->usable_count; ++i) {
        if (input->usable[i].start <= info_range.start && input->usable[i].end >= info_range.end)
            info_usable = 1;
        if (input->usable[i].start <= input->stack.start && input->usable[i].end >= input->stack.end)
            stack_backed = 1;
    }
    if (!info_usable || !stack_backed || overlap(input->stack, input->loader) ||
        overlap(info_range, input->loader) || overlap(info_range, input->stack) ||
        overlap(info_range, args_range) || overlap(info_range, map_range) ||
        overlap(info_range, kernel_range) || overlap(info_range, table_range) ||
        overlap(kernel_range, args_range) || overlap(kernel_range, map_range) ||
        overlap(kernel_range, table_range) || overlap(args_range, map_range) ||
        overlap(input->stack, args_range) || overlap(input->stack, map_range) ||
        overlap(input->stack, kernel_range) || overlap(input->stack, table_range)) return -1;
    reserved[n++] = input->loader;
    reserved[n++] = input->stack;
    reserved[n++] = args_range;
    reserved[n++] = map_range;
    reserved[n++] = info_range;
    reserved[n++] = table_range;
    reserved[n++] = kernel_range;
    for (i = 0; i < input->reserved_count; ++i) {
        if (!valid_range(input->reserved[i]) || overlap(info_range, input->reserved[i]) ||
            overlap(input->stack, input->reserved[i])) return -1;
        reserved[n++] = input->reserved[i];
    }
    if (nb_plan_elf(input->kernel, input->kernel_length, input->kernel_pa,
                    input->usable, input->usable_count, reserved, n, &plan)) return -1;
    for (i = 0; i < n; ++i) {
        reserved[i].start &= ~(nb_u64)4095;
        reserved[i].end = (reserved[i].end + 4095) & ~(nb_u64)4095;
    }
    map_count = emit_map(map, map_length, stride, reserved, n, 0);
    needed = (nb_u64)12 + 32 + 12 + (nb_u64)map_count * 20;
    if (!map_count || needed > input->bootinfo_capacity || needed - 12 > NB_BOOTINFO_MAX - 4)
        return -1;
    {
        nb_u8 *out = (nb_u8 *)input->bootinfo;
        used = (nb_u32)needed;
        for (i = 0; i < used; ++i) out[i] = 0;
        put32(out, 2); put32(out + 4, input->bootinfo_pa + 12);
        put32(out + 8, input->bootinfo_pa + 44);
        put32(out + 12, 32); put32(out + 16, 14);
        put32(out + 20, table_pa); put32(out + 28, 1);
        put32(out + 44, 12 + map_count * 20); put32(out + 48, 9);
        put32(out + 52, map_count);
        emit_map(map, map_length, stride, reserved, n, out + 56);
    }
    if (nb_copy_kernel(&plan, input->kernel, input->kernel_length,
                       input->write_fn, input->zero_fn, input->context)) return -1;
    result->plan.entry = plan.entry;
    result->plan.segment_count = plan.segment_count;
    for (i = 0; i < plan.segment_count; ++i) {
        result->plan.segments[i].source_offset = plan.segments[i].source_offset;
        result->plan.segments[i].physical_address = plan.segments[i].physical_address;
        result->plan.segments[i].file_size = plan.segments[i].file_size;
        result->plan.segments[i].memory_size = plan.segments[i].memory_size;
    }
    result->bootinfo_pa = input->bootinfo_pa;
    result->bootinfo_size = used;
    return 0;
}
#endif
