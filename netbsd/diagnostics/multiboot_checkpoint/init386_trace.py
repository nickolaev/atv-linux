#!/usr/bin/env python3
"""Add mapped, transient-framebuffer markers to the verified seven-stage ELF."""
import argparse
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile

BASE = 0xc0ac5c20
OFFSET = 0x9c6c20
# Marker, call-site VA, original destination, meaning.
HOOKS = [
    (8, 0xc012d592, 0xc08d4a56, 'init386 entered'),
    (9, 0xc012d59e, 0xc04a992d, 'uarea installed, entering cpu_probe'),
    (10, 0xc012d5b2, 0xc0496a5c, 'cpu_probe returned, entering cpu_init_msrs'),
    (11, 0xc012d5be, 0xc0133e98, 'MSRs initialized, entering speculation setup'),
    (12, 0xc012d5d5, 0xc08d4c60, 'speculation setup returned, entering uvm_md_init'),
    (13, 0xc012d5fb, 0xc04a6180, 'bus space initialized, entering consinit'),
    (14, 0xc012d60d, 0xc04b1463, 'consinit returned, entering pmap_bootstrap'),
]

PMAP_HOOKS = [
    (0, 0xc012d60d, 0xc04b1463, 'consinit returned, entering pmap_bootstrap'),
    (1, 0xc04b14f0, 0xc09143cd, 'pmap_bootstrap entered, initializing its mutex'),
    (2, 0xc04b15a3, 0xc094c592, 'pmap kernel object initialized, creating CPU sets'),
    (3, 0xc04b1603, 0xc04b03c3, 'pmap CPU features configured, allocating per-CPU mappings'),
    (4, 0xc04b16c2, 0xc012a8fe, 'pmap virtual ranges set, reserving dump pages'),
    (5, 0xc04b16f2, 0xc012bc10, 'pmap bootstrap mappings prepared, flushing TLB'),
    (6, 0xc012d612, 0xc04979d4, 'pmap_bootstrap returned, entering cpu_rng_init'),
    (7, 0xc012d617, 0xc04b9078, 'CPU RNG initialized, entering x86_rndseed'),
    (8, 0xc012d620, 0xc04b9396, 'seed processing returned, entering init_x86_clusters'),
    (9, 0xc012d62d, 0xc04b961f, 'memory clusters initialized, entering init_x86_vm'),
    (10, 0xc012d632, 0xc04b9800, 'VM pages loaded, entering init_x86_msgbuf'),
    (11, 0xc012d664, 0xc04b3ed3, 'message buffer initialized, updating BIOS mappings'),
    (12, 0xc012d89c, 0xc012d2eb, 'descriptor memory prepared, entering IDT setup'),
    (13, 0xc012da10, 0xc012bc60, 'IDT gates prepared, loading permanent GDT'),
    (14, 0xc012da71, 0xc04ac21b, 'symbol setup returned, entering default interrupts'),
]

GDT_HOOKS = [
    (0, 0xc012da10, 0xc012bc60, 'IDT gates ready, entering permanent lgdt'),
    (5, 0xc012da1c, 0xc012bbe0, 'lgdt returned, entering lldt'),
    (6, 0xc012da3d, 0xc0127ce0, 'lldt returned, entering lidt'),
    (7, 0xc012da4f, 0xc0129396, 'lidt returned, entering debugger setup'),
    (8, 0xc012da54, 0xc0126579, 'debugger setup returned, entering Multiboot 1 symbols'),
    (9, 0xc012dab7, 0xc01277a7, 'Multiboot 1 symbols absent, entering Multiboot 2 symbols'),
    (10, 0xc012dadd, 0xc04b8fb1, 'entering fallback symbol boot-info lookup'),
    (11, 0xc012db10, 0xc090d9b9, 'fallback symbol boot-info found, registering symbols'),
    (12, 0xc012db36, 0xc01419d7, 'symbol handling complete, entering MCA bus probe'),
    (13, 0xc012da71, 0xc04ac21b, 'entering default interrupt setup'),
    (14, 0xc012daaa, 0xc01328d3, 'interrupt setup passed, initializing debug registers'),
]
# Complete instructions replayed after each guarded JMP.
GDT_INLINE = [
    (1, 0xc012bc60, '8b4424040f0110',
     'movl 4(%esp),%eax; lgdt (%eax)', 'GDT pointer received, executing lgdt'),
    (2, 0xc012bc6a, 'b810000000',
     'movl $0x10,%eax', 'lgdt instruction completed, preparing data selector'),
    (3, 0xc012bc71, '8ec08ee88ed0',
     'movl %eax,%es; movl %eax,%gs; movl %eax,%ss', 'DS reloaded, reloading ES GS SS'),
    (4, 0xc012bc7e, 'e98dc2ffff',
     'jmp 0xc0127f10', 'FS reloaded, entering far code-segment flush'),
]

MCA_HOOKS = [
    (0, 0xc012db36, 0xc01419d7, 'entering MCA bus probe'),
    (1, 0xc0141a0c, 0xc0137780, 'MCA registers prepared, entering BIOS INT 15 call'),
    (2, 0xc013778e, 0xc0497706, 'preemption disabled, entering BIOS page-map switch'),
    (5, 0xc01377b5, 0xc092dc39, 'kernel page map restored, re-enabling preemption'),
    (7, 0xc012da71, 0xc04ac21b, 'MCA probe returned, entering default interrupt setup'),
    (8, 0xc04ac232, 0xc04ae084, 'default interrupt setup entered, reserving vector'),
    (9, 0xc04ac250, 0xc04ae0d8, 'interrupt vector reserved, installing its handler'),
    (10, 0xc04ac25d, 0xc04ab083, 'vectors installed, entering PIC setup'),
    (11, 0xc04ac279, 0xc09143cd, 'PIC setup returned, initializing interrupt mutex'),
    (12, 0xc012daaa, 0xc01328d3, 'default interrupts returned, initializing debug registers'),
]
MCA_INLINE = [
    (3, 0xc0137796, 'b800100000', 'movl $0x1000,%eax',
     'BIOS page map active, about to invoke real-mode trampoline'),
    (4, 0xc01377a3, '83c40864a108030000',
     'addl $8,%esp; movl %fs:0x308,%eax',
     'real-mode trampoline returned, preparing kernel page map'),
]

def branch(op, source, target):
    return struct.pack('<BI', op, (target-source-5)&0xffffffff)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('kernel',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--sha256',required=True)
    p.add_argument('--fb-base',required=True,type=lambda s:int(s,0))
    p.add_argument('--stride',required=True,type=lambda s:int(s,0))
    p.add_argument('--phase', choices=('init386', 'pmap', 'gdt', 'mca'), default='init386')
    p.add_argument('--cc',default='/opt/homebrew/opt/llvm/bin/clang')
    p.add_argument('--ld',required=True)
    p.add_argument('--objcopy',default='/opt/homebrew/opt/llvm/bin/llvm-objcopy')
    a=p.parse_args()
    hooks = {'init386': HOOKS, 'pmap': PMAP_HOOKS, 'gdt': GDT_HOOKS, 'mca': MCA_HOOKS}[a.phase]
    data=bytearray(a.kernel.read_bytes())
    if hashlib.sha256(data).hexdigest()!=a.sha256: p.error('input SHA mismatch')
    if not 0x10000000 <= a.fb_base < 0xffff0000 or a.fb_base&3 or a.stride<400: p.error('invalid framebuffer')
    if any(((a.fb_base+y*a.stride)&4095)+112>4096 for y in range(44)): p.error('glyph crosses framebuffer page')
    wrappers=''
    for n,va,dst,_ in hooks:
        off=va-0xc0100000+0x1000
        if data[off:off+5]!=branch(0xe8,va,dst): p.error(f'unexpected instruction {va:x}')
        wrappers+=f'''\n.globl marker_{n}\nmarker_{n}:\n pushfl\n cli\n pushal\n movl ${n},%eax\n call draw\n popal\n popfl\n jmp 0x{dst:x}\n'''
    inline_hooks = {'gdt': GDT_INLINE, 'mca': MCA_INLINE}.get(a.phase, [])
    for n, va, original_hex, replay, _ in inline_hooks:
        original = bytes.fromhex(original_hex)
        off = va - 0xc0100000 + 0x1000
        if data[off:off + len(original)] != original:
            p.error(f'unexpected inline instruction {va:x}')
        wrappers += f'\n.globl marker_{n}\nmarker_{n}:\n pushfl\n cli\n pushal\n movl ${n},%eax\n call draw\n popal\n popfl\n {replay}\n jmp 0x{va + len(original):x}\n'
    if data[0x159a:0x15a3]!=bytes.fromhex('83c40481c4b8000000'): p.error('unexpected init386 return')
    wrappers+='''\n.globl marker_15\nmarker_15:\n pushfl\n cli\n pushal\n movl $15,%eax\n call draw\n popal\n popfl\n addl $4,%esp\n addl $0xb8,%esp\n jmp 0xc01005a3\n'''
    asm=f'''.code32
.section .text,"ax",@progbits
{wrappers}
draw:
 movzbl masks(%eax),%ebp
 movl $0xbff00000,%esi
 pushl (%esi)
 movl $0,%ebx
row:
 movl %ebx,%eax
 imull ${a.stride},%eax
 addl ${a.fb_base},%eax
 movl %eax,%edx
 andl $0xfffff000,%eax
 orl $0x1b,%eax
 movl %eax,(%esi)
 movl $0xc0000000,%edi
 invlpg (%edi)
 andl $4095,%edx
 addl %edx,%edi
 movl %ebx,%eax
 shrl $2,%eax
 movl %eax,%edx
 movl $0,%ecx
pixel:
 movl %ecx,%eax
 shrl $2,%eax
 pushl %ecx
 xorl %ecx,%ecx
 cmpl $2,%edx
 jb horizontal
 cmpl $5,%edx
 je middle
 cmpl $9,%edx
 jae bottom
 cmpl $2,%eax
 jb left
 cmpl $5,%eax
 jb selected
 movl $2,%ecx
 cmpl $5,%edx
 jb selected
 movl $4,%ecx
 jmp selected
left:
 movl $32,%ecx
 cmpl $5,%edx
 jb selected
 movl $16,%ecx
 jmp selected
horizontal:
 movl $1,%ecx
 jmp hcheck
middle:
 movl $64,%ecx
 jmp hcheck
bottom:
 movl $8,%ecx
hcheck:
 cmpl $1,%eax
 jb clear
 cmpl $5,%eax
 jbe selected
clear:
 xorl %ecx,%ecx
selected:
 testl %ebp,%ecx
 movl $0xffff8000,%eax
 jz paint
 xorl %eax,%eax
paint:
 popl %ecx
 stosl
 incl %ecx
 cmpl $28,%ecx
 jb pixel
 incl %ebx
 cmpl $44,%ebx
 jb row
 popl %eax
 movl %eax,(%esi)
 movl $0xc0000000,%eax
 invlpg (%eax)
 sfence
 ret
masks:
.byte 0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f,0x77,0x7c,0x39,0x5e,0x79,0x71
'''
    with tempfile.TemporaryDirectory() as d:
        d=Path(d); (d/'trace.S').write_text(asm)
        subprocess.run([a.cc,'--target=i386-none-elf','-c',str(d/'trace.S'),'-o',str(d/'trace.o')],check=True)
        subprocess.run([a.ld,'-m','elf_i386','-e',f'marker_{hooks[0][0]}','-Ttext',hex(BASE),'-o',str(d/'trace.elf'),str(d/'trace.o')],check=True)
        subprocess.run([a.objcopy,'-O','binary','--only-section=.text',str(d/'trace.elf'),str(d/'trace.bin')],check=True)
        code=(d/'trace.bin').read_bytes()
        if len(code)>0x3e0 or any(x!=0xcc for x in data[OFFSET:OFFSET+len(code)]): p.error('occupied text padding')
        symbols=subprocess.check_output(['/opt/homebrew/opt/llvm/bin/llvm-nm',str(d/'trace.elf')],text=True)
        addresses={fields[2]:int(fields[0],16) for line in symbols.splitlines() if len(fields:=line.split())==3}
        for n,va,_,meaning in hooks:
            off=va-0xc0100000+0x1000
            data[off:off+5]=branch(0xe8,va,addresses[f'marker_{n}'])
            print(f'{n:X}: {meaning}')
        for n, va, original_hex, _, meaning in inline_hooks:
            original = bytes.fromhex(original_hex)
            off = va - 0xc0100000 + 0x1000
            data[off:off + len(original)] = branch(0xe9, va, addresses[f'marker_{n}']) + b'\x90' * (len(original) - 5)
            print(f'{n:X}: {meaning}')
        data[0x159a:0x15a3]=branch(0xe9,0xc010059a,addresses['marker_15'])+b'\x90'*4
        data[OFFSET:OFFSET+len(code)]=code
    with a.output.open('xb') as f: f.write(data)
    print('F: init386 returned')
    print(hashlib.sha256(data).hexdigest())
if __name__=='__main__': main()
