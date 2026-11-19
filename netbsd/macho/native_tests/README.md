# Native handoff emulator

`run_unicorn.py` executes the actual compiled `nb_prepare_native_emulation`,
`nb_enter_native` and their helper functions and the real, uncompressed NetBSD/i386 installer
kernel's early entry through return from `native_loader`. It checks the entry
stack, paging state, kernel warm-boot marker, copied EFI identity and native
memory-map boot-info records and
the kernel's boot arguments. It checks the 36-byte transient transfer stack
with a lower-bound canary, and tests that a conflicting reserved range is
rejected before any kernel memory is written. The map fixture transcribes the
photographed conventional and runtime overlap, but is not a complete raw
capture; allocations and the system table pointer are synthetic. It does not
validate a live ATV1 memory map or firmware runtime services, and it is not a
complete NetBSD boot.

The test requires the Unicorn Python module, an i386 ELF executable containing
the native handoff functions linked to a nonconflicting physical address, and
the uncompressed official NetBSD 11.1 i386 INSTALL kernel with symbols.
Enable `NB_ENABLE_EXPERIMENTAL_HANDOFF` only for this controlled test.

From the repository root, with `clang`, `ld.lld` and Unicorn installed, build
the test executable in an isolated directory:

```bash
TEST_DIR=$(mktemp -d)
printf 'ENTRY(nb_enter_native)\nSECTIONS { . = 0x02000000; .text : { *(.text*) *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } /DISCARD/ : { *(.comment) *(.eh_frame*) *(.note*) } }\n' > "$TEST_DIR/layout.ld"
clang --target=i386-unknown-none-elf -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -fno-stack-protector -fno-pic -fno-builtin -O2 -DNB_ENABLE_EXPERIMENTAL_HANDOFF -c netbsd/macho/native/handoff.c -o "$TEST_DIR/handoff.o"
clang --target=i386-unknown-none-elf -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -fno-stack-protector -fno-pic -fno-builtin -O2 -DNB_ENABLE_EXPERIMENTAL_HANDOFF -c netbsd/macho/native/loader.c -o "$TEST_DIR/loader.o"
clang --target=i386-unknown-none-elf -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -DNB_ENABLE_EXPERIMENTAL_HANDOFF -c netbsd/macho/native/enter.S -o "$TEST_DIR/enter.o"
clang --target=i386-unknown-none-elf -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -fno-stack-protector -fno-pic -fno-builtin -O2 -c netbsd/macho/native_tests/copy_fixture.c -o "$TEST_DIR/copy_fixture.o"
ld.lld -m elf_i386 -T "$TEST_DIR/layout.ld" "$TEST_DIR/handoff.o" "$TEST_DIR/loader.o" "$TEST_DIR/enter.o" "$TEST_DIR/copy_fixture.o" -o "$TEST_DIR/native-test.elf"
objdump -d "$TEST_DIR/native-test.elf" > "$TEST_DIR/native-test.dis"
if grep -Eiq 'xmm|%mm[0-7]|[[:space:]](fld|fst|fadd|fsub|fmul|fdiv)' "$TEST_DIR/native-test.dis"; then
    echo 'Unexpected SIMD or FPU instruction' >&2
    exit 1
fi
python3 netbsd/macho/native_tests/run_unicorn.py --native "$TEST_DIR/native-test.elf" --kernel /path/to/netbsd-INSTALL
```

`copy_fixture.c` writes into Unicorn's simulated address space and must not be
used for a hardware build. On the existing `mbp` staging environment, Unicorn
is installed at `/home/nickolaev/atv-netbsd-small-probe/unicorn`, the kernel is
`/home/nickolaev/atv-netbsd-inputs/netbsd-11.1-i386/netbsd-INSTALL`, and setting
`PYTHONPATH` to that Unicorn directory permits the final command to run. The
test reports `PASS` only after NetBSD's real `native_loader` has returned.

## Packaged Mach-O entry fixture

`build_macho_fixture.sh` creates a separate **emulation-only** one-segment
Mach-O with the supplied kernel embedded in it. `run_macho_unicorn.py` loads
the Mach-O's `__TEXT` and executes its `LC_UNIXTHREAD` entry. The fixture sets
up a synthetic stack, clears BSS, calls the real preparation code, and enters
the supplied kernel. Its build directory must not exist; the script refuses
to overwrite one. It checks the embedded kernel against the supplied file,
rejects a malformed map without touching kernel or bootinfo memory, and stops
after the real `native_loader` returns. This is a test harness with synthetic
callbacks and memory addresses, **not a bootable Apple TV image**.

```sh
sh netbsd/macho/native_tests/build_macho_fixture.sh /path/to/netbsd-INSTALL /path/to/test-build
python3 netbsd/macho/native_tests/run_macho_unicorn.py \
  --native /path/to/test-build/fixture.elf \
  --macho /path/to/test-build/fixture.macho --kernel /path/to/netbsd-INSTALL
```

The synthetic map partially transcribes the photographed overlap; all object
placements, firmware arguments, and the Mach-O load address are fixtures. It
does not prove Apple firmware accepts that layout, pointer lifetimes, display
or post-entry behavior, nor that the complete kernel boots.
