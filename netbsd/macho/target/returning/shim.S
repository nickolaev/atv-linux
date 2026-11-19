/* Returning probe hook. Sentinels are replaced by the isolated packer. */
.text
.globl _probe
_probe:
    pushfl
    pushal
    cld
    movl %cr0, %ecx
    testl $1, %ecx
    jz finish
    testl $0x80000000, %ecx
    jnz finish
    testl $0x200, 32(%esp) /* observed firmware hook has interrupts disabled */
    jnz finish
    movw %cs, %cx
    cmpw $0x10, %cx
    jne finish
    movw %ds, %cx
    cmpw $0x18, %cx
    jne finish
    movw %es, %cx
    cmpw $0x18, %cx
    jne finish
    movw %ss, %cx
    cmpw $0x18, %cx
    jne finish
    movl $0xfeedc0de, %edx /* mapped 48-byte status destination */
    movl $0xfeedface, %esi /* high payload mapping start */
    movl $0xfeedbeef, %edi /* high payload mapping end */
    /* Initial pushfl/pushal precede this check, as in the known probe. */
    leal -32(%esp), %ebx /* bounded scan and helper-call scratch */
    leal 36(%esp), %ecx
    cmpl %ecx, %edx
    jae 1f
    leal 48(%edx), %eax
    cmpl %ebx, %eax
    ja finish
1:  cmpl %ecx, %esi
    jae 2f
    cmpl %ebx, %edi
    ja finish
2:
    /* Validate the actual GDT descriptors, not only selector numbers.
     * The pointer is bounded to the same conservative physical window as
     * the existing entry probe; descriptor memory must still be readable. */
    subl $8, %esp
    sgdt (%esp)
    movzwl (%esp), %ebx
    movl 2(%esp), %ebp
    addl $8, %esp
    cmpl $31, %ebx
    jb finish
    cmpl $0x1000, %ebp
    jb finish
    cmpl $0x0fffffe0, %ebp
    ja finish
    /* Flat 4 GiB, present, ring-0 32-bit code/data. Ignore accessed and AVL. */
    cmpw $0xffff, 0x10(%ebp)
    jne finish
    cmpw $0, 0x12(%ebp)
    jne finish
    movl 0x14(%ebp), %ebx
    testl $0xff0000ff, %ebx
    jnz finish
    movl %ebx, %ecx
    andl $0x0000fe00, %ecx
    cmpl $0x00009a00, %ecx
    jne finish
    andl $0x00ef0000, %ebx
    cmpl $0x00cf0000, %ebx
    jne finish
    cmpw $0xffff, 0x18(%ebp)
    jne finish
    cmpw $0, 0x1a(%ebp)
    jne finish
    movl 0x1c(%ebp), %ebx
    testl $0xff0000ff, %ebx
    jnz finish
    movl %ebx, %ecx
    andl $0x0000fe00, %ecx
    cmpl $0x00009200, %ecx
    jne finish
    andl $0x00ef0000, %ebx
    cmpl $0x00cf0000, %ebx
    jne finish
    /* Recover the complete GDT range; descriptor checks used EBX. */
    subl $8, %esp
    sgdt (%esp)
    movzwl (%esp), %ebx
    movl 2(%esp), %ebp
    addl $8, %esp
    /* Reject status or high mapping over the GDT. */
    movl %ebp, %ecx
    addl %ebx, %ecx
    jc finish
    incl %ecx
    jz finish
    cmpl $0x10000000, %ecx
    ja finish
    cmpl %ecx, %edx
    jae 21f
    leal 48(%edx), %ebx
    cmpl %ebp, %ebx
    ja finish
21: cmpl %ecx, %esi
    jae 22f
    cmpl %ebp, %edi
    ja finish
22: /* Preserve the entire IDT too; synchronous faults may use it. */
    subl $8, %esp
    sidt (%esp)
    movzwl (%esp), %ebx
    movl 2(%esp), %ebp
    addl $8, %esp
    cmpl $0x1000, %ebp
    jb finish
    movl %ebp, %ecx
    addl %ebx, %ecx
    jc finish
    incl %ecx
    jz finish
    cmpl $0x10000000, %ecx
    ja finish
    cmpl %ecx, %edx
    jae 23f
    leal 48(%edx), %ebx
    cmpl %ebp, %ebx
    ja finish
23: cmpl %ecx, %esi
    jae 24f
    cmpl %ebp, %edi
    ja finish
24: movl 28(%esp), %eax /* original hook EAX = boot_args */
    cmpl $0x1000, %eax
    jb finish
    cmpl $0x0ffffbb4, %eax
    ja finish
    leal 0x44c(%eax), %ecx
    /* Full args range must not intersect high image or status. */
    cmpl %edi, %eax
    jae 3f
    cmpl %esi, %ecx
    ja finish
3:  leal 48(%edx), %ebx
    cmpl %ebx, %eax
    jae 4f
    cmpl %edx, %ecx
    ja finish
4:  movl 0x404(%eax), %ebx
    movl 0x408(%eax), %ecx
    cmpl $0x1000, %ebx
    jb finish
    testl $3, %ebx
    jnz finish
    testl %ecx, %ecx
    jz finish
    cmpl $8000, %ecx
    ja finish
    addl %ebx, %ecx
    jc finish
    cmpl $0x10000000, %ecx
    ja finish
    cmpl %edi, %ebx
    jae 5f
    cmpl %esi, %ecx
    ja finish
5:  leal 48(%edx), %ebp
    cmpl %ebp, %ebx
    jae 6f
    cmpl %edx, %ecx
    ja finish
6:  /* Require full LoaderData coverage of high image, and reject every
     * intersecting runtime or other restricted EFI descriptor. Apple has
     * reported overlapping ConventionalMemory and LoaderData descriptors;
     * that overlap is allowed. This is not proof of nested object lifetime. */
    cmpl $40, 0x40c(%eax)
    jb finish
    testl $3, 0x40c(%eax)
    jnz finish
    cmpl $1, 0x410(%eax)
    jne finish
    pushl %eax
    pushl $0 /* full LoaderData coverage found */
25: cmpl %ecx, %ebx
    je 30f
    ja 29f
    leal 40(%ebx), %ebp
    cmpl %ecx, %ebp
    ja 29f
    cmpl $0, 12(%ebx) /* physical start high */
    jne 28f
    cmpl $0, 28(%ebx) /* pages high */
    jne 29f
    movl 24(%ebx), %ebp
    testl %ebp, %ebp
    jz 29f
    cmpl $0x000fffff, %ebp
    ja 29f
    shll $12, %ebp
    movl 8(%ebx), %eax
    testl $4095, %eax
    jnz 29f
    addl %eax, %ebp
    jc 29f
    cmpl %edi, %eax
    jae 28f
    cmpl %esi, %ebp
    jbe 28f
    testl $0x80000000, 36(%ebx)
    jnz 29f
    cmpl $7, (%ebx)
    je 28f
    cmpl $2, (%ebx)
    jne 29f
    cmpl %esi, %eax
    ja 28f
    cmpl %edi, %ebp
    jb 28f
    movl $1, (%esp)
28: movl 4(%esp), %eax
    addl 0x40c(%eax), %ebx
    jc 29f
    jmp 25b
29: addl $8, %esp
    jmp finish
30: cmpl $1, (%esp)
    jne 29b
    addl $8, %esp
    movl 28(%esp), %eax
    leal 48(%edx), %ebp
    /* Do not overwrite even an unsupported table before C can reject it. */
    movl 0x444(%eax), %ebx
    testl %ebx, %ebx
    jz 8f
    cmpl $0x1000, %ebx
    jb finish
    cmpl $0x0fffff80, %ebx
    ja finish
    leal 128(%ebx), %ecx
    cmpl %edi, %ebx
    jae 7f
    cmpl %esi, %ecx
    ja finish
7:  cmpl %ebp, %ebx
    jae 8f
    cmpl %edx, %ecx
    ja finish
8:  /* Before using high writable state, check the live system/config array
     * and its direct pointers. Nested ACPI/SMBIOS sources remain an explicit
     * platform allocation assumption. Do not call firmware services. */
    testl %ebx, %ebx
    jz finish
    movl %ebx, %ecx
    addl $128, %ecx
    call data_covered
    jc finish
    cmpl $0x20494249, (%ebx)
    jne finish
    cmpl $0x54535953, 4(%ebx)
    jne finish
    movl 64(%ebx), %ecx
    testl %ecx, %ecx
    jz finish
    cmpl $64, %ecx
    ja finish
    imull $20, %ecx, %ecx
    movl 68(%ebx), %ebx
    cmpl $0x1000, %ebx
    jb finish
    addl %ebx, %ecx
    jc finish
    cmpl $0x10000000, %ecx
    ja finish
    cmpl %edi, %ebx
    jae 31f
    cmpl %esi, %ecx
    ja finish
31: cmpl %ebp, %ebx
    jae 32f
    cmpl %edx, %ecx
    ja finish
32: call data_covered
    jc finish
    /* A conservative 4 KiB around each nonzero direct config pointer must
     * not overlap high state or the status file. Never follow unknown GUIDs. */
33: cmpl %ecx, %ebx
    je 35f
    ja finish
    movl 16(%ebx), %ebp
    testl %ebp, %ebp
    jz 34f
    cmpl $0x10000000, %ebp
    jae 34f /* high image and status both lie below this bound */
    movl %ebp, %eax
    addl $4096, %eax
    jc finish
    cmpl %edi, %ebp
    jae 341f
    cmpl %esi, %eax
    ja finish
341: leal 48(%edx), %ebp
    cmpl %ebp, 16(%ebx)
    jae 34f
    cmpl %edx, %eax
    ja finish
34: addl $20, %ebx
    jmp 33b
35: movl 28(%esp), %eax
    /* C entry is called with EAX=boot_args and EDX=status address. */
    movl $0x31574f4c, (%edx) /* LOW1: guarded high call began */
    movl $0xfeedbabe, %ecx /* high payload entry */
    call *%ecx
finish:
    popal
    popfl
    jmp 0x02001010

/* EBX..ECX is a bounded physical object. Check entire coverage by one
 * data descriptor and reject restricted overlaps; allow conventional overlap
 * because the observed map has that firmware quirk. Return carry on failure.
 * Preserves all caller registers. */
data_covered:
    pushl %eax
    pushl %edx
    pushl %esi
    pushl %edi
    pushl %ebp
    movl 0x404(%eax), %edi
    movl 0x408(%eax), %edx
    addl %edi, %edx
    jc 39f
    xorl %esi, %esi
36: cmpl %edx, %edi
    je 38f
    ja 39f
    leal 40(%edi), %ebp
    cmpl %edx, %ebp
    ja 39f
    cmpl $0, 12(%edi)
    jne 37f
    cmpl $0, 28(%edi)
    jne 39f
    movl 24(%edi), %eax
    testl %eax, %eax
    jz 39f
    cmpl $0x000fffff, %eax
    ja 39f
    shll $12, %eax
    movl 8(%edi), %ebp
    testl $4095, %ebp
    jnz 39f
    addl %ebp, %eax
    jc 39f
    cmpl %ecx, %ebp
    jae 37f
    cmpl %ebx, %eax
    jbe 37f
    cmpl $7, (%edi)
    je 37f
    cmpl $2, (%edi)
    je 361f
    cmpl $4, (%edi)
    je 361f
    cmpl $6, (%edi)
    jne 39f
361:cmpl %ebx, %ebp
    ja 37f
    cmpl %ecx, %eax
    jb 37f
    movl $1, %esi
37: movl 16(%esp), %eax /* saved apple boot_args */
    addl 0x40c(%eax), %edi
    jc 39f
    jmp 36b
38: testl %esi, %esi
    jz 39f
    popl %ebp
    popl %edi
    popl %esi
    popl %edx
    popl %eax
    clc
    ret
39: popl %ebp
    popl %edi
    popl %esi
    popl %edx
    popl %eax
    stc
    ret
