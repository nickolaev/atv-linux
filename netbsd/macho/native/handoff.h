#ifndef ATV_NETBSD_HANDOFF_H
#define ATV_NETBSD_HANDOFF_H

/* Freestanding IA-32 native NetBSD handoff primitives. */
typedef __UINT8_TYPE__ nb_u8;
typedef __UINT32_TYPE__ nb_u32;
typedef __UINT64_TYPE__ nb_u64;
typedef __UINTPTR_TYPE__ nb_uptr;

#define NB_MAX_SEGMENTS 16u
#define NB_BOOTINFO_MAX 16384u

/* Physical ranges are half-open; an end of 0x100000000 is representable. */
struct nb_range { nb_u64 start, end; };
struct nb_segment {
    nb_u32 source_offset, physical_address, file_size, memory_size;
};
struct nb_plan {
    nb_u32 entry, segment_count;
    struct nb_segment segments[NB_MAX_SEGMENTS];
};

/*
 * The caller must derive usable ranges from the actual firmware memory map,
 * and reserve all live state: loader, stack, bootargs, map, bootinfo, EFI
 * system/runtime tables, modules, and device memory. This routine always
 * protects the complete ELF source itself. It does not interpret EFI memory
 * types or verify the caller's range provenance.
 *
 * On failure, out is unchanged; no destination memory is touched.
 */
int nb_plan_elf(const void *elf, nb_u32 length, nb_u32 source_pa,
                const struct nb_range *usable, nb_u32 usable_count,
                const struct nb_range *reserved, nb_u32 reserved_count,
                struct nb_plan *out);

typedef int (*nb_write_fn)(void *context, nb_u32 physical_address,
                           const nb_u8 *bytes, nb_u32 length);
typedef int (*nb_zero_fn)(void *context, nb_u32 physical_address,
                          nb_u32 length);

/* A callback failure may leave a partially copied kernel; never boot it. */
int nb_copy_kernel(const struct nb_plan *plan, const void *elf, nb_u32 length,
                   nb_write_fn write_fn, nb_zero_fn zero_fn, void *context);

/*
 * Build loader-side pointer-array bootinfo, including EFI map and EFI table.
 * The caller must reserve the destination and confirm table lifetime. This
 * rejects physical overlap between destination and map, and host-pointer
 * overlap among destination, map and used. It never dereferences
 * system_table_pa or invokes any firmware service.
 * NetBSD may itself invoke EFI runtime services when this record is present;
 * the caller must independently establish that those services and mappings
 * are valid before ever passing these records to a real kernel.
 */
int nb_build_bootinfo(void *destination, nb_u32 capacity, nb_u32 destination_pa,
                      nb_u32 system_table_pa, const void *map, nb_u32 map_length,
                      nb_u32 map_pa, nb_u32 descriptor_size,
                      nb_u32 descriptor_version, nb_u32 *used);

#ifdef NB_ENABLE_EXPERIMENTAL_HANDOFF
/* Emulation-only integration input; no firmware pointer is dereferenced. */
struct nb_emulation_inputs {
    const void *apple_args;
    nb_u32 apple_args_length, apple_args_pa;
    const void *efi_map;
    nb_u32 efi_map_length, efi_map_pa;
    const void *kernel;
    nb_u32 kernel_length, kernel_pa;
    void *bootinfo;
    nb_u32 bootinfo_capacity, bootinfo_pa;
    struct nb_range loader, stack;
    const struct nb_range *usable;
    nb_u32 usable_count;
    const struct nb_range *reserved;
    nb_u32 reserved_count;
    nb_write_fn write_fn;
    nb_zero_fn zero_fn;
    void *context;
};
struct nb_emulation_result {
    struct nb_plan plan;
    nb_u32 bootinfo_pa, bootinfo_size;
};

/*
 * Experimental integration: validates supplied usable ranges against EFI
 * ConventionalMemory + WB and emits a conservative native BTINFO_MEMMAP
 * without BTINFO_EFIMEMMAP. The map is not evidence of firmware table safety.
 * Failure during a write
 * callback can still leave partial data; result remains unchanged and must
 * not then be used. Buffers, input/result objects and range arrays must be
 * disjoint; callbacks must not mutate these objects or the ELF source.
 * This is not permission to use a captured EFI table on real hardware.
 */
int nb_prepare_native_emulation(const struct nb_emulation_inputs *input,
                                struct nb_emulation_result *result);
#endif

/*
 * Enter a previously verified kernel. The caller must establish a protected
 * flat identity mapping, disabled paging, a safe writable stack (at least
 * 16 KiB below stack_top for early kernel execution), disjoint current and new
 * stacks, and valid physical arguments. Does not return. This minimum is an
 * emulation limit, not a proof of kernel stack requirements or EFI safety.
 * Legacy extmem_kb and basemem_kb arguments are ignored and passed as zero,
 * so NetBSD 11.1 selects BTINFO_MEMMAP.
 */
#ifdef NB_ENABLE_EXPERIMENTAL_HANDOFF
__attribute__((noreturn))
void nb_enter_native(nb_u32 entry_pa, nb_u32 stack_top_pa, nb_u32 howto,
                     nb_u32 bootinfo_pa, nb_u32 esym_pa, nb_u32 extmem_kb,
                     nb_u32 basemem_kb);
#endif

#endif
