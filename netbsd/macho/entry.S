/* boot.efi passes the address of the x86 boot arguments in EAX. */
.text
.globl _start
_start:
    cld
    pushl %eax
    calll diagnostic_main
1:
    cli
    hlt
    jmp 1b
