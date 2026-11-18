#!/bin/sh
# Build only the returning high-segment diagnostic payload, not a USB image.
set -eu
[ "$#" -eq 2 ] || { echo "usage: $0 UNCOMPRESSED_KERNEL NEW_DIRECTORY" >&2; exit 1; }
kernel=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
mkdir "$2"
build=$(cd "$2" && pwd)
root=$(cd "$(dirname "$0")/../../../.." && pwd)
target=$root/netbsd/macho/target
hardware=$target/hardware
native=$root/netbsd/macho/native
cd "$build"
cp "$kernel" kernel.elf
printf '.section .payload,"a"\n.globl kernel_start\nkernel_start:\n.incbin "kernel.elf"\n.globl kernel_end\nkernel_end:\n' > payload.S
flags="--target=i386-unknown-none-elf -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -fno-stack-protector -fno-pic -fno-builtin -O2 -DNB_ENABLE_EXPERIMENTAL_HANDOFF -DTARGET_EMULATION_ONLY -DTARGET_DIAGNOSTIC -I$target"
if [ "${DIAGNOSTIC_ACTUAL_COPY:-0}" = 1 ]; then
    flags="$flags -DTARGET_DIAGNOSTIC_ACTUAL_COPY"
fi
checkpoint_objects=''
if [ "${DIAGNOSTIC_NATIVE_CHECKPOINT:-0}" = 1 ]; then
    [ "${DIAGNOSTIC_ACTUAL_COPY:-0}" = 1 ] || {
        echo 'native checkpoint requires actual-copy diagnostic' >&2; exit 1;
    }
    flags="$flags -DTARGET_NATIVE_CHECKPOINT"
    clang $flags -c "$hardware/checkpoint.c" -o checkpoint-c.o
    clang $flags -c "$hardware/checkpoint.S" -o checkpoint-asm.o
    checkpoint_objects='checkpoint-c.o checkpoint-asm.o'
fi
for file in "$native/handoff.c" "$native/loader.c" "$target/scratch.c" "$target/plan.c" "$hardware/firmware.c" "$target/project_efi.c" "$target/smbios.c" "$hardware/entry.c" "$hardware/memcpy.c"; do
    # Intentional splitting of fixed compiler flags.
    clang $flags -c "$file" -o "$(basename "$file" .c).o"
done
for file in "$native/enter.S" "$hardware/diagnostic_entry.S" payload.S; do
    clang $flags -c "$file" -o "asm_$(basename "$file" .S).o"
done
# Intentional splitting of the optional fixed checkpoint object list.
ld.lld -m elf_i386 -T "$hardware/diagnostic_layout.ld" handoff.o loader.o scratch.o plan.o firmware.o project_efi.o smbios.o entry.o memcpy.o asm_enter.o asm_diagnostic_entry.o asm_payload.o $checkpoint_objects -o diagnostic-unbacked.elf
# lld emits the workspace as NOBITS even with explicit zero bytes in the
# script. Convert it to zero-filled file contents before making the Mach-O.
objcopy --set-section-flags .workspace=alloc,load,contents diagnostic-unbacked.elf diagnostic.elf
python3 "$root/netbsd/macho/elf_to_macho.py" diagnostic.elf diagnostic.macho
# The linker places read-only constants in the executable segment, where
# disassembling the final image can misinterpret data bytes as instructions.
# Inspect the executable sections of the individual objects instead.
objdump -d handoff.o loader.o scratch.o plan.o firmware.o project_efi.o smbios.o entry.o memcpy.o asm_enter.o asm_diagnostic_entry.o $checkpoint_objects > diagnostic.dis
if grep -Eiq 'xmm|%mm[0-7]|[[:space:]](fld|fst|fadd|fsub|fmul|fdiv)' diagnostic.dis; then
    echo 'unexpected SIMD or FPU instruction' >&2; exit 1
fi
echo "Built returning diagnostic high segment at $build/diagnostic.macho"
