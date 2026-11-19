ENTRY(_start)
PHDRS { image PT_LOAD FLAGS(7); }
SECTIONS {
    /* Match the repository's existing bootable Mach-O __text address. */
    . = 0x02001000;
    .text : { *(.text*) *(.rodata*) } :image
    .data : { *(.data*) } :image
    .bss : { *(.bss*) *(COMMON) } :image
    /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
