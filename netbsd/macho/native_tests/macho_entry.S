/* Emulator fixture only; never package this entry in an ATV1 image. */
.text
.globl _start
_start:
    cli
    cld
    movl %eax, %ebp
    movl $0x03008000, %esp
    xorl %eax, %eax
    movl $__bss_start, %edi
    movl $__bss_end, %ecx
    subl %edi, %ecx
    rep stosb
    pushl %ebp
    call fixture_start
    addl $4, %esp
    /* A failed preparation must stop here; never enter NetBSD. */
.globl fixture_failed
fixture_failed:
    hlt
    jmp fixture_failed
