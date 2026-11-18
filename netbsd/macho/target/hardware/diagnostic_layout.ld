/* Returning probe: file-back all zero-initialized workspace and stack. This
 * avoids a separate high-segment BSS-clearing write before firmware checks.
 * It still trusts boot.efi to own the pages where it loaded this Mach-O. */
ENTRY(_start)
PHDRS { all PT_LOAD FLAGS(7); }
SECTIONS {
  . = 0x04000000;
  __image_start = . - 4096;
  .text : { *(.text*) *(.rodata*) } :all
  .data : { *(.data*) } :all
  .payload : { *(.payload) } :all
  __bss_start = .;
  .workspace : {
    BYTE(0)
    *(.bss*) *(COMMON)
    . = ALIGN(16);
    . += 65536;
    __bootstrap_stack_end = .;
    BYTE(0)
  } :all
  __bss_end = .;
  . = ALIGN(4096);
  __image_end = .;
  /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) }
}
