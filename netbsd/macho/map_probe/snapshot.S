/* Returning ATV1 entry probe. No firmware calls or device access.
 * Destination is patched by package.py to an 8192-byte initramfs file.
 * Header: magic, status, args, map_pa, map_size, stride, version,
 * table_pa, cr0, cr3, eflags, copied_map_size, copied_table_size,
 * EFI mode, revision/version, hook ESP.
 * System-table bytes start at 64, map bytes at 192. Marker written last.
 * If the map is at most 7936 bytes, the optional 64-byte trailer at 8128
 * contains XREG/version, hook EAX/EBX/ECX/EDX/ESI/EDI/EBP, segment
 * selectors CS/DS/SS/ES/FS/GS, CR4, and six-byte GDTR and IDTR values.
 */
.text
.globl _probe
_probe:
    pushfl
    pushal
    cld
    movl $0xfeedc0de, %edi
    /* pushal/pushfl plus our later one-word pushes must not alias output.
     * These initial pushes have already used the inherited hook stack. */
    cmpl $4, %esp
    jb return_unmodified
    movl %esp, %edx
    addl $36, %edx
    jc return_unmodified
    cmpl %edi, %edx
    jbe stack_safe
    leal -4(%esp), %edx
    movl %edi, %eax
    addl $8192, %eax
    jc return_unmodified
    cmpl %eax, %edx
    jb return_unmodified
stack_safe:
    /* pushal's saved EAX is the hook's boot-arguments pointer. */
    movl 28(%esp), %eax
    movl %cr0, %edx
    testl $0x80000000, %edx    /* identity address assumption: PG must be off */
    jnz return_unmodified
    cmpl $0x1000, %eax
    jb return_unmodified
    cmpl $0x0ffffbb4, %eax     /* args + 0x44c below 256 MiB */
    ja return_unmodified
    movl %eax, %ebp
    leal 0x44c(%ebp), %edx
    cmpl %edi, %edx
    jbe args_safe
    leal 8192(%edi), %edx
    cmpl %edx, %ebp
    jb return_unmodified
args_safe:
    movl 0x404(%ebp), %esi
    movl 0x408(%ebp), %ecx
    movl 0x40c(%ebp), %ebx
    cmpl $0x1000, %esi
    jb return_unmodified
    testl $3, %esi
    jnz return_unmodified
    testl %ecx, %ecx
    jz return_unmodified
    cmpl $8000, %ecx
    ja return_unmodified
    cmpl $40, %ebx
    jb return_unmodified
    testl $3, %ebx
    jnz return_unmodified
    cmpl $1, 0x410(%ebp)
    jne return_unmodified
    /* Complete descriptors only. */
    movl %eax, %edx
    movl %ecx, %eax
    pushl %edx
    xorl %edx, %edx
    divl %ebx
    testl %edx, %edx
    popl %eax
    jnz return_unmodified
    movl %esi, %edx
    addl %ecx, %edx
    jc return_unmodified
    cmpl $0x10000000, %edx
    ja return_unmodified
    /* A source intersecting the entire snapshot cannot be copied safely. */
    cmpl %edi, %edx
    jbe map_safe
    leal 8192(%edi), %eax
    cmpl %eax, %esi
    jb return_unmodified
map_safe:
    /* A table pointer overlapping the destination must not be damaged even
     * if the later table validation fails. */
    movl 0x444(%ebp), %eax
    testl %eax, %eax
    jz sources_safe
    movl %eax, %edx
    addl $128, %edx
    jc return_unmodified
    cmpl %edi, %edx
    jbe sources_safe
    leal 8192(%edi), %edx
    cmpl %edx, %eax
    jb return_unmodified
sources_safe:
    movl $3, 4(%edi)           /* map captured; table not validated */
    movl %ebp, 8(%edi)
    movl %esi, 12(%edi)
    movl %ecx, 16(%edi)
    movl %ebx, 20(%edi)
    movl 0x410(%ebp), %eax
    movl %eax, 24(%edi)
    movl 0x444(%ebp), %eax
    movl %eax, 28(%edi)
    movl %cr0, %eax
    movl %eax, 32(%edi)
    movl %cr3, %eax
    movl %eax, 36(%edi)
    movl 32(%esp), %eax
    movl %eax, 40(%edi)
    movzbl 0x448(%ebp), %eax
    movl %eax, 52(%edi)
    movl (%ebp), %eax
    movl %eax, 56(%edi)
    movl 12(%esp), %eax        /* pushal saved ESP after the initial pushfl */
    addl $4, %eax              /* recover ESP at the hook */
    movl %eax, 60(%edi)
    /* Never overwrite map bytes: the unmodified map starts at offset 192. */
    cmpl $7936, %ecx
    ja no_xreg
    movl $1, 8132(%edi)
    movl 28(%esp), %eax
    movl %eax, 8136(%edi)
    movl 16(%esp), %eax
    movl %eax, 8140(%edi)
    movl 24(%esp), %eax
    movl %eax, 8144(%edi)
    movl 20(%esp), %eax
    movl %eax, 8148(%edi)
    movl 4(%esp), %eax
    movl %eax, 8152(%edi)
    movl 0(%esp), %eax
    movl %eax, 8156(%edi)
    movl 8(%esp), %eax
    movl %eax, 8160(%edi)
    movw %cs, 8164(%edi)
    movw %ds, 8166(%edi)
    movw %ss, 8168(%edi)
    movw %es, 8170(%edi)
    movw %fs, 8172(%edi)
    movw %gs, 8174(%edi)
    movl %cr4, %eax
    movl %eax, 8176(%edi)
    sgdt 8180(%edi)
    sidt 8186(%edi)
    movl $0x47455258, 8128(%edi) /* XREG; publish trailer last */
no_xreg:
    movl %ecx, 44(%edi)
    pushl %edi
    addl $192, %edi
    rep movsb
    popl %edi
    movl 28(%edi), %ebx
    cmpl $0x1000, %ebx
    jb finish
    testl $3, %ebx
    jnz finish
    cmpl $0x0fffff80, %ebx     /* table header extent below 256 MiB */
    ja finish
    /* Only read the table when a copied data-memory descriptor covers it. */
    leal 192(%edi), %esi
    movl 44(%edi), %ecx
    movl 20(%edi), %ebp
next_desc:
    cmpl %ebp, %ecx
    jb finish
    movl (%esi), %eax
    cmpl $2, %eax              /* LoaderData */
    je type_ok
    cmpl $4, %eax              /* BootServicesData */
    je type_ok
    cmpl $6, %eax              /* RuntimeServicesData */
    je type_ok
    cmpl $7, %eax              /* ConventionalMemory */
    jne advance
 type_ok:
    cmpl $0, 12(%esi)          /* physical start high 32 */
    jne advance
    movl 8(%esi), %eax
    cmpl %ebx, %eax
    ja advance
    cmpl $0, 28(%esi)          /* conservative: pages high 32 == 0 */
    jne advance
    movl 24(%esi), %edx
    cmpl $0x000fffff, %edx
    ja advance
    shll $12, %edx
    addl %eax, %edx
    jc advance
    movl %ebx, %eax
    addl $128, %eax
    jc finish
    cmpl %eax, %edx
    jb advance
    /* Refuse source/destination overlap. */
    cmpl %edi, %eax
    jbe table_safe
    leal 8192(%edi), %edx
    cmpl %edx, %ebx
    jb finish
 table_safe:
    cmpl $0x20494249, (%ebx)   /* EFI_SYSTEM_TABLE_SIGNATURE */
    jne finish
    cmpl $0x54535953, 4(%ebx)
    jne finish
    movl 12(%ebx), %ecx       /* EFI_TABLE_HEADER.HeaderSize */
    cmpl $72, %ecx             /* full EFI 1.x IA-32 system table */
    jb finish
    cmpl $128, %ecx
    ja finish
    movl %ecx, 48(%edi)
    pushl %edi
    leal 64(%edi), %edi
    movl %ebx, %esi
    rep movsb
    popl %edi
    movl $0, 4(%edi)           /* complete map and validated table header */
    jmp finish
advance:
    addl %ebp, %esi
    subl %ebp, %ecx
    jmp next_desc
finish:
    movl $0x50414345, (%edi)   /* ECAP; completion marker written last */
return_unmodified:
    popal
    popfl
    jmp 0x02001010
