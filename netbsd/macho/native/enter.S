/*
 * Experimental native NetBSD i386 transfer. Not linked unless explicitly
 * enabled for controlled emulation: EFI runtime safety is not established.
 * The caller must provide a safe stack and flat, paging-disabled addresses.
 */
#ifdef NB_ENABLE_EXPERIMENTAL_HANDOFF
.text
.globl nb_enter_native
.type nb_enter_native,@function
nb_enter_native:
    movl %esp, %ebp
    cli
    cld
    lgdt nb_gdt_descriptor
    movw $0x10, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %ss
    movl 8(%ebp), %esp

    /* Native entry stack: dummy return, howto, bootdev, bootinfo, esym,
       extended KiB, base KiB. Arguments are pushed in reverse order. */
    /* Force the native memory-map path in NetBSD 11.1, regardless of
       caller-provided legacy memory estimates. */
    pushl $0
    pushl $0
    pushl 20(%ebp)
    pushl 16(%ebp)
    pushl $0
    pushl 12(%ebp)
    pushl $0
    pushl $0x08
    pushl 4(%ebp)
    /* Avoid matching NetBSD's Multiboot dispatch magic in EAX. */
    xorl %eax, %eax
    lret
.size nb_enter_native, .-nb_enter_native

.section .rodata
.p2align 3
nb_gdt:
    .quad 0x0000000000000000
    .quad 0x00cf9a000000ffff /* flat ring-0 32-bit code */
    .quad 0x00cf92000000ffff /* flat ring-0 32-bit data */
nb_gdt_end:
nb_gdt_descriptor:
    .word nb_gdt_end - nb_gdt - 1
    .long nb_gdt
#endif

.section .note.GNU-stack,"",@progbits
