#!/bin/sh
# Build a synthetic Mach-O/ELF test fixture. Never use it as hardware image.
set -eu
[ "$#" -eq 2 ] || { echo "usage: $0 UNCOMPRESSED_KERNEL NEW_BUILD_DIRECTORY" >&2; exit 1; }
kernel=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
# A fixture can contain a copied kernel and generated executable; never
# overwrite an existing directory or its contents.
mkdir "$2"
build=$(cd "$2" && pwd)
root=$(cd "$(dirname "$0")/../../.." && pwd)
testdir=$root/netbsd/macho/native_tests
native=$root/netbsd/macho/native
cd "$build"
cp "$kernel" kernel.elf
printf '.section .payload,"a"\n.globl kernel_start\nkernel_start:\n.incbin "kernel.elf"\n.globl kernel_end\nkernel_end:\n' > payload.S
flags='--target=i386-unknown-none-elf -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -fno-stack-protector -fno-pic -fno-builtin -O2 -DNB_ENABLE_EXPERIMENTAL_HANDOFF'
for file in "$native/handoff.c" "$native/loader.c" "$testdir/macho_fixture.c" "$testdir/copy_fixture.c"; do
    obj=$(basename "$file" .c).o
    # Intentional field splitting of fixed compiler flags.
    clang $flags -c "$file" -o "$obj"
done
for file in "$native/enter.S" "$testdir/macho_entry.S" payload.S; do
    obj=$(basename "$file" .S).o
    clang $flags -c "$file" -o "$obj"
done
ld.lld -m elf_i386 -T "$testdir/macho_fixture.ld" handoff.o loader.o macho_fixture.o copy_fixture.o enter.o macho_entry.o payload.o -o fixture.elf
python3 "$root/netbsd/macho/elf_to_macho.py" fixture.elf fixture.macho
objdump -d fixture.elf > fixture.dis
if grep -Eiq 'xmm|%mm[0-7]|[[:space:]](fld|fst|fadd|fsub|fmul|fdiv)' fixture.dis; then
    echo 'unexpected SIMD or FPU instruction' >&2; exit 1
fi
echo "Built test-only fixture at $build/fixture.macho"
