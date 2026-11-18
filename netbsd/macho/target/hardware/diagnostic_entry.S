/* Returning high-segment entry. The low hook has saved flags and registers,
 * cleared DF, checked protected mode with paging off, and provided flat
 * DS/ES/SS plus a disjoint 48-byte output in EDX. It calls us with EAX
 * pointing at the current Apple boot arguments. No firmware calls. */
.text
.globl _start
_start:
    movl %esp, %ebx              /* low hook's saved-frame stack */
    movl %eax, %esi              /* current boot arguments */
    movl %edx, %ebp              /* checked result location */
    /* Static workspace and this stack are zero-filled in the Mach-O file. */
    movl $__bootstrap_stack_end, %esp
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
    pushl %ebx                  /* inherited live stack point */
#endif
    /* These are valid only for the exact original loader mappings checked by
     * the packer. The original Linux loader and initrd remain reserved. */
    pushl $0x02afd000
    pushl $0x02000000
    pushl %esi
    call target_diagnostic_run
#ifdef TARGET_DIAGNOSTIC_ACTUAL_COPY
    addl $16, %esp
#else
    addl $12, %esp
#endif
    movl $target_diagnostic_record, %esi
    movl %ebp, %edi
    movl $48, %ecx
    rep movsb
    movl %ebx, %esp
    ret
.section .rodata
.globl target_returning_signature
target_returning_signature:
    .asciz "ATV1_RETURN_DIAG_V1"
