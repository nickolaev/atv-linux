/* Experimental fixed-address Mach-O layout; real firmware acceptance unproven. */
ENTRY(_start)
PHDRS { all PT_LOAD FLAGS(7); }
SECTIONS {
  . = 0x04000000;
  __image_start = . - 4096;
  .text : { *(.text*) *(.rodata*) } :all
  .data : { *(.data*) } :all
  .payload : { *(.payload) } :all
  __bss_start = .;
  .bss : { *(.bss*) *(COMMON) . = ALIGN(16); . += 65536; __bootstrap_stack_end = .; } :all
  __bss_end = .;
  . = ALIGN(4096);
  __image_end = .;
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
