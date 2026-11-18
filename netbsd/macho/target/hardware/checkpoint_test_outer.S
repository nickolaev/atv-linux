/* Emulates the returning hook's outer register/EFLAGS preservation. */
#ifdef TARGET_NATIVE_CHECKPOINT
.text
.globl checkpoint_test_outer
checkpoint_test_outer:
    pushfl
    pushal
    movl %esp, %ebp
    pushl 64(%ebp)
    pushl 60(%ebp)
    pushl 56(%ebp)
    pushl 52(%ebp)
    pushl 48(%ebp)
    pushl 44(%ebp)
    pushl 40(%ebp)
    call checkpoint_run
    movl %eax, checkpoint_outer_status
    movl %ebp, %esp
    popal
    popfl
    ret
.data
.globl checkpoint_outer_status
checkpoint_outer_status: .long 0xffffffff
#endif
.section .note.GNU-stack,"",@progbits
