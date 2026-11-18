/* Experimental ATV1 entry. The Mach-O image must already be loaded at its
 * linked address by Apple boot.efi. No firmware services or disk I/O. */
.text
.globl _start
_start:
    cli
    cld
    movl %eax, %ebp              /* live Apple boot_args physical pointer */
    movl %cr0, %eax
    testl $1, %eax               /* protected mode */
    jz target_emulated_failed
    testl $0x80000000, %eax      /* paging must be disabled */
    jnz target_emulated_failed
    lgdt hardware_gdtr
    ljmp $0x08, $1f
1:  movw $0x10, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %fs
    movw %ax, %gs
    movw %ax, %ss
    movl $__bootstrap_stack_end, %esp
    xorl %eax, %eax
    movl $__bss_start, %edi
    movl $__bss_end, %ecx
    subl %edi, %ecx
    rep stosb
    pushl %ebp
    call target_emulated_start
.globl target_emulated_failed
target_emulated_failed:
    hlt
    jmp target_emulated_failed
.balign 8
hardware_gdt:
    .quad 0x0000000000000000
    .quad 0x00cf9a000000ffff
    .quad 0x00cf92000000ffff
hardware_gdt_end:
hardware_gdtr:
    .word hardware_gdt_end - hardware_gdt - 1
    .long hardware_gdt
