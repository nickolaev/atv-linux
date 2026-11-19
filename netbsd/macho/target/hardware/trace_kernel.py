#!/usr/bin/env python3
"""Emulation-only trace of NetBSD native start until its first CR write.

Synthetic flat segments and empty bootinfo: this does not model Apple firmware
or prove that executing further on hardware can safely be reversed.
"""
import argparse
import collections
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'native_tests'))
from run_unicorn import Elf32, MEMORY_END
from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ESP, UC_X86_REG_CR0,
                               UC_X86_REG_CR3, UC_X86_REG_GDTR, UC_X86_REG_CS,
                               UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS)

p = argparse.ArgumentParser()
p.add_argument('kernel')
args = p.parse_args()
k = Elf32(args.kernel)
u = Uc(UC_ARCH_X86, UC_MODE_32)
u.mem_map(0, MEMORY_END)
k.load(u)
u.mem_write(0x70000, struct.pack('<QQQ', 0, 0x00cf9a000000ffff, 0x00cf92000000ffff))
u.reg_write(UC_X86_REG_GDTR, (0, 0x70000, 23, 0))
for reg, value in ((UC_X86_REG_CS, 8), (UC_X86_REG_DS, 16), (UC_X86_REG_ES, 16), (UC_X86_REG_SS, 16)):
    u.reg_write(reg, value)
u.reg_write(UC_X86_REG_CR0, 0x13)
u.reg_write(UC_X86_REG_CR3, 0)
u.reg_write(UC_X86_REG_EAX, 0)
u.reg_write(UC_X86_REG_ESP, 0x3008000)
u.mem_write(0x3008000, struct.pack('<7I', 0, 0x20002, 0, 0, 0, 0, 0))
writes = collections.Counter()
def write(_u, _access, address, size, _value, _data):
    writes[address >> 12] += size
def code(uc, address, size, _):
    b = bytes(uc.mem_read(address, min(size, 8)))
    if len(b) >= 3 and b[0:2] == b'\x0f\x22':
        print(f'first control-register write at {address:#x}: {b.hex()}')
        uc.emu_stop()
u.hook_add(UC_HOOK_MEM_WRITE, write)
u.hook_add(UC_HOOK_CODE, code)
try:
    u.emu_start(k.symbol('start', physical=True), 0, count=50000000)
except UcError as error:
    print(f'emulation stopped: {error}')
for page, amount in writes.most_common(20):
    print(f'write page {page << 12:#010x}: {amount} bytes')
