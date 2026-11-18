.section .text,"ax",@progbits
.code32

.macro mark name, arg
    pushal
    pushfl
    cld
    movl %esp, %ebp
    andl $-16, %esp
    subl $12, %esp
    pushl \arg
    call \name
    movl %ebp, %esp
    popfl
    popal
.endm

.globl visual_stage_pre_multiboot
visual_stage_pre_multiboot:
    mark visual_stage_physical, $0
    call netbsd_multiboot1_pre_reloc
    jmp netbsd_after_multiboot1_pre_call

.globl visual_stage_pre_reloc
visual_stage_pre_reloc:
    mark visual_stage_physical, $1
    jmp netbsd_start_common

.globl visual_stage_pre_paging
visual_stage_pre_paging:
    mark visual_stage_prepare_paging, %esi
    movl %cr0, %eax
    orl $0x8005002b, %eax
    jmp netbsd_set_cr0

.section .note.GNU-stack,"",@progbits
