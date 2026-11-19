/* Synthetic one-segment layout, deliberately not an ATV1 load-address claim. */
ENTRY(_start)
PHDRS { all PT_LOAD FLAGS(7); }
SECTIONS {
  . = 0x04000000;
  .text : { *(.text*) *(.rodata*) } :all
  .data : { *(.data*) } :all
  .payload : { *(.payload) } :all
  __bss_start = .;
  .bss : { *(.bss*) *(COMMON) } :all
  __bss_end = .;
  __image_end = .;
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
