/* Return immediately after NetBSD 11.1 native_loader; experimental only. */
#ifdef TARGET_NATIVE_CHECKPOINT
.text
.globl checkpoint_enter
.type checkpoint_enter,@function
checkpoint_enter:
    pushfl
    pushal
    cli
    movl %esp, cp_saved_esp
    sgdt cp_saved_gdtr
    sidt cp_saved_idtr
    movl %cr0, %eax
    movl %eax, cp_cr0
    andl $0x80000001, %eax
    cmpl $1, %eax               /* protected mode; paging disabled */
    jne cp_reject
    movl %cr3, %eax
    movl %eax, cp_cr3
    movl %cr4, %eax
    movl %eax, cp_cr4
    movw %cs, %ax
    cmpw $0x10, %ax
    jne cp_reject
    movw %ds, %ax
    cmpw $0x18, %ax
    jne cp_reject
    movw %es, %ax
    cmpw $0x18, %ax
    jne cp_reject
    movw %ss, %ax
    cmpw $0x18, %ax
    jne cp_reject
    movw %fs, %ax
    cmpw $0x18, %ax
    jne cp_reject
    movw %gs, %ax
    cmpw $0x18, %ax
    jne cp_reject
    cmpw $31, cp_saved_gdtr
    jb cp_reject
    movl cp_saved_gdtr+2, %esi
    cmpl $0x1000, %esi
    jb cp_reject
    cmpl $0x0fffffe0, %esi
    ja cp_reject
    movl $cp_old_gdt_clone, %edi
    movl $32, %ecx
    cld
    rep movsb
    /* Require exactly flat, present 32-bit ring-0 code/data descriptors;
     * their accessed bits may already be set. */
    cmpl $0x0000ffff, cp_old_gdt_clone+16
    jne cp_reject
    movl cp_old_gdt_clone+20, %eax
    andl $0xfffffeff, %eax
    cmpl $0x00cf9a00, %eax
    jne cp_reject
    cmpl $0x0000ffff, cp_old_gdt_clone+24
    jne cp_reject
    movl cp_old_gdt_clone+28, %eax
    andl $0xfffffeff, %eax
    cmpl $0x00cf9200, %eax
    jne cp_reject
    cli
    lgdt cp_native_gdtr
    movw $0x10, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %ss
    movl cp_saved_esp, %ebp
    movl 44(%ebp), %esp          /* stack_top */
    pushl $0                    /* biosbasemem */
    pushl $0                    /* biosextmem */
    pushl $0                    /* esym */
    pushl 52(%ebp)              /* bootinfo */
    pushl $0                    /* bootdev */
    pushl 48(%ebp)              /* boothowto */
    pushl $0                    /* dummy return */
    pushl $0x08
    pushl 40(%ebp)              /* entry */
    xorl %eax, %eax
    lret

/* The copied kernel is patched to jump here after native_loader returns. */
.globl checkpoint_return
checkpoint_return:
    cli
    movl %cr0, %eax
    cmpl cp_cr0, %eax
    jne cp_fatal
    movl %cr3, %eax
    cmpl cp_cr3, %eax
    jne cp_fatal
    movl %cr4, %eax
    cmpl cp_cr4, %eax
    jne cp_fatal
    lgdt cp_clone_gdtr
    ljmp $0x10, $cp_original_cs
cp_original_cs:
    movw $0x18, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %fs
    movw %ax, %gs
    movw %ax, %ss
    movl cp_saved_esp, %esp
    lgdt cp_saved_gdtr
    lidt cp_saved_idtr
    popal
    popfl
    movl $0, %eax
    ret
cp_reject:
    popal
    popfl
    movl $-1, %eax
    ret
cp_fatal:
    hlt
    jmp cp_fatal
.size checkpoint_enter,.-checkpoint_enter

.section .data
.balign 8
cp_native_gdt:
    .quad 0
    .quad 0x00cf9a000000ffff
    .quad 0x00cf92000000ffff
cp_native_gdt_end:
cp_native_gdtr:
    .word cp_native_gdt_end-cp_native_gdt-1
    .long cp_native_gdt
cp_clone_gdtr:
    .word 31
    .long cp_old_gdt_clone
.balign 8
cp_old_gdt_clone: .space 32
cp_saved_gdtr: .space 6
cp_saved_idtr: .space 6
cp_saved_esp: .long 0
cp_cr0: .long 0
cp_cr3: .long 0
cp_cr4: .long 0
#endif
.section .note.GNU-stack,"",@progbits
