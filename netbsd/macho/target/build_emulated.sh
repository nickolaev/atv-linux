#!/bin/sh
# Synthetic fixture only. Its Mach-O is NOT a hardware image.
set -eu
[ "$#" -eq 2 ] || { echo "usage: $0 UNCOMPRESSED_KERNEL NEW_DIRECTORY" >&2; exit 1; }
kernel=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
mkdir "$2"
build=$(cd "$2" && pwd)
root=$(cd "$(dirname "$0")/../../.." && pwd)
target=$root/netbsd/macho/target
native=$root/netbsd/macho/native
cd "$build"
cp "$kernel" kernel.elf
printf '.section .payload,"a"\n.globl kernel_start\nkernel_start:\n.incbin "kernel.elf"\n.globl kernel_end\nkernel_end:\n' > payload.S
flags='--target=i386-unknown-none-elf -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -fno-stack-protector -fno-pic -fno-builtin -O2 -DNB_ENABLE_EXPERIMENTAL_HANDOFF -DTARGET_EMULATION_ONLY'
for file in "$native/handoff.c" "$native/loader.c" "$target/scratch.c" "$target/plan.c" "$target/firmware.c" "$target/guarded.c" "$target/project_efi.c" "$target/smbios.c" "$target/entry_emulated.c" "$target/memcpy_emulated.c" "$root/netbsd/macho/native_tests/copy_fixture.c"; do
    obj=$(basename "$file" .c).o
    clang $flags -c "$file" -o "$obj"
done
for file in "$native/enter.S" "$target/entry_emulated.S" payload.S; do
    obj=asm_$(basename "$file" .S).o
    clang $flags -c "$file" -o "$obj"
done
ld.lld -m elf_i386 -T "$target/layout_emulated.ld" handoff.o loader.o scratch.o plan.o firmware.o guarded.o project_efi.o smbios.o entry_emulated.o memcpy_emulated.o copy_fixture.o asm_enter.o asm_entry_emulated.o asm_payload.o -o fixture.elf
python3 "$root/netbsd/macho/elf_to_macho.py" fixture.elf fixture.macho
objdump -d fixture.elf > fixture.dis
if grep -Eiq 'xmm|%mm[0-7]|[[:space:]](fld|fst|fadd|fsub|fmul|fdiv)' fixture.dis; then
    echo 'unexpected SIMD or FPU instruction' >&2; exit 1
fi
echo "Built emulation-only target fixture at $build/fixture.macho"
