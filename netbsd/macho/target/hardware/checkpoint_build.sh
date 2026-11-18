#!/bin/sh
# Build a freestanding checkpoint test ELF, never a hardware image.
set -eu
[ "$#" -eq 1 ] || { echo 'usage: checkpoint_build.sh NEW_OUTPUT_DIRECTORY' >&2; exit 1; }
src=$(cd "$(dirname "$0")" && pwd)
mkdir "$1"
out=$(cd "$1" && pwd)
flags='--target=i386-unknown-none-elf -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -fno-stack-protector -fno-pic -fno-builtin -O2 -DTARGET_NATIVE_CHECKPOINT'
clang $flags -c "$src/checkpoint.c" -o "$out/checkpoint-c.o"
clang $flags -c "$src/checkpoint.S" -o "$out/checkpoint-asm.o"
clang $flags -c "$src/checkpoint_test_outer.S" -o "$out/checkpoint-outer.o"
ld.lld -m elf_i386 -Ttext=0x04000000 -e checkpoint_test_outer "$out/checkpoint-c.o" "$out/checkpoint-asm.o" "$out/checkpoint-outer.o" -o "$out/checkpoint.elf"
