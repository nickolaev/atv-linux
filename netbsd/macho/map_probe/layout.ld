ENTRY(_probe)
PHDRS { image PT_LOAD FLAGS(5); }
SECTIONS {
    . = 0x02000500;
    .text : { *(.text*) *(.rodata*) } :image
    /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
