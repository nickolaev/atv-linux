/* Synthetic entry only. Never build or package this as an ATV1 image. */
#ifndef TARGET_EMULATION_ONLY
#error This entry is restricted to controlled emulation
#endif
.text
.globl _start
_start:
    cli
    cld
    movl %eax, %ebp
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
