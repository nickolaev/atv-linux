OUTPUT_FORMAT(elf32-i386)
ENTRY(checkpoint_entry)

netbsd_start = 0x00100000;
PROVIDE(netbsd_multiboot1_pre_reloc = 0x00125a0c);
PROVIDE(netbsd_after_multiboot1_pre_call = 0x00100072);
PROVIDE(netbsd_start_common = 0x001001db);
PROVIDE(netbsd_set_cr0 = 0x00100519);
SECTIONS
{
    . = 0x01c00000;
    .checkpoint : {
        KEEP(*(.text.entry))
        *(.text .text.*)
        *(.rodata .rodata.*)
        marker_code_end = .;
        *(.data .data.*)
        *(.bss .bss.* COMMON)
        BYTE(0)
    }
    /DISCARD/ : { *(.comment .note* .eh_frame*) }
}
ASSERT(checkpoint_entry == 0x01c00000, "checkpoint entry must start at the load address")
ASSERT(SIZEOF(.checkpoint) <= 0x10000, "checkpoint exceeds its 64 KiB budget")
ASSERT(!DEFINED(visual_stage_first_paged) || marker_code_end <= 0x01c01000,
    "temporary high alias covers only the first checkpoint page")
