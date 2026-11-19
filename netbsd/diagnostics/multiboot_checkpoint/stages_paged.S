#include "stages_layout.h"

/* These routines execute through the first page's temporary high alias. */
.section .text.stages_paged,"ax",@progbits
.code32

.macro paint_tile tile, color
    pushfl
    pushal
    movl %esp, %ebp
    cld
    andl $-16, %esp
    leal -4(%esp), %esp
    pushl $\color
    pushl $\tile
    pushl $STAGES_VIRTUAL_FB
    call visual_stage_draw
    movl %ebp, %esp
    popal
    popfl
.endm

.globl visual_stage_first_paged
.type visual_stage_first_paged,@function
visual_stage_first_paged:
    paint_tile 3, STAGES_COLOR(255, 255, 255)
    /* Replay the displaced first instruction at the stock high entry. */
    movl 0xc14bdda8, %ecx
    ret
.size visual_stage_first_paged, .-visual_stage_first_paged

.globl visual_stage_post_reloc
.type visual_stage_post_reloc,@function
visual_stage_post_reloc:
    /* Keep the stock call alignment and invoke both post-relocation routines. */
    leal -12(%esp), %esp
    movl $0xc0125da9, %eax  /* multiboot1_post_reloc */
    call *%eax
    movl $0xc0126b66, %eax  /* multiboot2_post_reloc */
    call *%eax
    leal 12(%esp), %esp

    pushfl
    pushal
    /* The installer kernel's bootinfo_add uses GCC regparm(3). */
    movl $(framebuffer_record - STAGES_PHYSICAL_CODE + STAGES_VIRTUAL_CODE), %eax
    movl $12, %edx          /* BTINFO_FRAMEBUFFER */
    movl $(framebuffer_record_end - framebuffer_record), %ecx
    movl $0xc0126620, %ebx  /* bootinfo_add */
    leal -8(%esp), %esp
    call *%ebx
    leal 8(%esp), %esp
    popal
    popfl
    paint_tile 4, STAGES_COLOR(255, 128, 0)
    ret
.size visual_stage_post_reloc, .-visual_stage_post_reloc

.globl visual_stage_after_gdt
.type visual_stage_after_gdt,@function
visual_stage_after_gdt:
    /* Forward the original stack argument with the same call alignment. */
    leal -8(%esp), %esp
    pushl 12(%esp)
    movl $0xc012c690, %eax  /* initgdt */
    call *%eax
    leal 12(%esp), %esp
    paint_tile 5, STAGES_COLOR(192, 128, 255)
    ret
.size visual_stage_after_gdt, .-visual_stage_after_gdt

.globl visual_stage_before_init386
.type visual_stage_before_init386,@function
visual_stage_before_init386:
    paint_tile 6, STAGES_COLOR(0, 255, 0)
    /* Drop the MMIO mappings while preserving the alias used by this code. */
    pushfl
    pushal
    cld
    leal (STAGES_VIRTUAL_CODE + STAGES_KERNEL_PT_OFFSET + 4)(%esi), %edi
    xorl %eax, %eax
    movl $STAGES_MMIO_PAGES, %ecx
    rep stosl
    movl %cr3, %eax
    movl %eax, %cr3
    popal
    popfl

    /* The caller clears the code alias and invalidates its VA from kernel text. */
    movl $0, %ecx
    leal (STAGES_VIRTUAL_CODE + STAGES_KERNEL_PT_OFFSET)(%esi), %edx
    movl $STAGES_VIRTUAL_CODE, %eax
    ret
.size visual_stage_before_init386, .-visual_stage_before_init386

.p2align 2
framebuffer_record:
    .long 56, 12                 /* btinfo_common */
    .quad ATV_FB_BASE
    .long 0                      /* flags */
    .long ATV_FB_WIDTH, ATV_FB_HEIGHT
    .short ATV_FB_STRIDE
    .byte 32, 8, 8, 8             /* depth and RGB channel widths */
    .byte ATV_FB_RED_OFFSET, ATV_FB_GREEN_OFFSET, ATV_FB_BLUE_OFFSET
    .byte 0                      /* padding before vbemode */
    .short 0                     /* vbemode */
    .zero 16                     /* reserved[14] and i386 struct padding */
framebuffer_record_end:
.if framebuffer_record_end - framebuffer_record != 56
.error "unexpected i386 framebuffer bootinfo layout"
.endif

.globl visual_stage_paged_end
visual_stage_paged_end:

.section .note.GNU-stack,"",@progbits
