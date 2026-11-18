/* Multiboot 1 enters in 32-bit protected mode with an undefined stack. */
.section .text.entry,"ax",@progbits
.code32
.globl checkpoint_entry
.type checkpoint_entry,@function
checkpoint_entry:
    movl %esp, saved_stack
    movl $checkpoint_stack_top, %esp
    pushal
    pushfl
    cld
    subl $4, %esp
    pushl %ebx
    pushl %eax
    call atv_checkpoint
    addl $12, %esp
    popfl
    popal
    movl saved_stack, %esp
    jmp netbsd_start
.size checkpoint_entry, .-checkpoint_entry

.section .bss.stack,"aw",@nobits
.p2align 4
saved_stack:
    .long 0
.p2align 4
    .skip 4096
checkpoint_stack_top:

.section .note.GNU-stack,"",@progbits
