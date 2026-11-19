/* Enter after the working loader's first eight instructions. EAX is boot_args. */
.text
.globl _probe
_probe:
    pushfl
    pushal
    testl %eax, %eax
    jz done
    movl %eax, %ebp
    leal 4(%eax), %edi
    /* Leave the entire string, including NUL, within the legacy 256-byte limit. */
    movl $(256 - (marker_end - marker)), %ecx
scan:
    cmpb $0, (%edi)
    je copy_marker
    incl %edi
    decl %ecx
    jnz scan
    jmp done
copy_marker:
    movl %edi, %ebx
    movl $marker, %esi
copy_byte:
    movb (%esi), %dl
    movb %dl, (%edi)
    incl %esi
    incl %edi
    testb %dl, %dl
    jnz copy_byte
    leal (marker_values-marker)(%ebx), %edi
    movl $offsets, %esi
    movl $12, %ecx
next_field:
    movl (%esi), %edx
    movl (%ebp,%edx), %eax
    call hex8
    addl $4, %esi
    loop next_field
    movl %cr0, %eax
    call hex8
    movl %cr3, %eax
    call hex8
    movl 32(%esp), %eax       /* flags saved before pushal */
    call hex8
done:
    popal
    popfl
    jmp 0x02001010

/* Render EAX in eight hex digits and advance EDI past the comma. */
hex8:
    pushl %ecx
    movl $8, %ecx
digit:
    roll $4, %eax
    movl %eax, %edx
    andl $15, %edx
    addb $'0', %dl
    cmpb $'9', %dl
    jbe put_digit
    addb $39, %dl             /* 'a' - '9' - 1 */
put_digit:
    movb %dl, (%edi)
    incl %edi
    loop digit
    incl %edi
    popl %ecx
    ret

/* revision/version word; video base/mode/pitch/width/height/depth;
 * memory-map pointer/size/descriptor size/version; EFI system table. */
offsets:
    .long 0, 0x414, 0x418, 0x41c, 0x420, 0x424, 0x428
    .long 0x404, 0x408, 0x40c, 0x410, 0x444
marker:
    .ascii " atvprobe=entry,"
marker_values:
    .rept 14
    .ascii "00000000,"
    .endr
    .asciz "00000000"
marker_end:
