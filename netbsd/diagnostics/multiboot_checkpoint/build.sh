#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
    echo 'usage: sh build.sh OUTPUT.bin -DATV_... [more definitions]' >&2
    exit 2
fi
output=$1
shift
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
variant=${ATV_CHECKPOINT:-ethernet}
case $variant in
    ethernet) implementation=checkpoint.c ;;
    visual) implementation=visual.c ;;
    stages) implementation=visual.c; set -- -DATV_VISUAL_PROGRESS=1 "$@" ;;
    *) echo 'ATV_CHECKPOINT must be ethernet, visual, or stages' >&2; exit 2 ;;
esac
build=$(mktemp -d)
trap 'rm -rf -- "$build"' EXIT
trap 'exit 1' HUP INT TERM

compile() {
    "${CC:-clang}" --target=i386-none-elf -march=pentium-m \
    -mno-sse -mno-sse2 -mno-mmx -mno-80387 -Os -Wall -Wextra -Werror \
    -ffreestanding -fno-builtin -fno-pic -fno-pie -fno-stack-protector \
    -fno-asynchronous-unwind-tables -fno-unwind-tables \
    -c "$@"
}

compile "$src/entry.S" -o "$build/entry.o"
compile "$@" "$src/$implementation" -o "$build/checkpoint.o"
if [ "$variant" = stages ]; then
    compile "$@" "$src/stages.c" -o "$build/stages.o"
    compile "$@" "$src/stages_paged.S" -o "$build/stages_paged.o"
    compile "$src/stages_physical.S" -o "$build/stages_physical.o"
fi
set -- "$build/entry.o" "$build/checkpoint.o"
if [ "$variant" = stages ]; then
    set -- "$@" "$build/stages.o" "$build/stages_paged.o" "$build/stages_physical.o"
fi
"${LD:-ld.lld}" -m elf_i386 -T "$src/layout.ld" --no-undefined \
    -o "$build/checkpoint.elf" "$@"
"${OBJCOPY:-objcopy}" -O binary --only-section=.checkpoint \
    "$build/checkpoint.elf" "$build/checkpoint.bin"
(set -C; cat "$build/checkpoint.bin" > "$output")
if [ "$variant" = stages ]; then
    "${NM:-nm}" "$build/checkpoint.elf" | awk '
        $3 == "visual_stage_pre_multiboot" { print "pre-multiboot=0x" $1; names++ }
        $3 == "visual_stage_pre_reloc" { print "pre-reloc=0x" $1; names++ }
        $3 == "visual_stage_pre_paging" { print "pre-paging=0x" $1; names++ }
        $3 == "visual_stage_first_paged" { print "post-paging=0x" $1; names++ }
        $3 == "visual_stage_post_reloc" { print "post-reloc=0x" $1; names++ }
        $3 == "visual_stage_after_gdt" { print "after-gdt=0x" $1; names++ }
        $3 == "visual_stage_before_init386" { print "before-init386=0x" $1; names++ }
        END { if (names != 7) exit 1 }
    '
fi
