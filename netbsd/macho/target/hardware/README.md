# Experimental Apple TV native entry

This one-way USB-test payload embeds an uncompressed NetBSD/i386 kernel in a
fixed-address Mach-O. It does not read or write disks and it is not a live
system or installer image. Apple firmware acceptance and physical hardware
behavior remain untested. On failure it halts; the display may remain black.

The entry requires protected mode with paging disabled, assumes the incoming
code and data segments address the loaded Mach-O correctly long enough to load
its own flat GDT, and switches to a 64 KiB stack inside that image. It copies
the current boot arguments and memory map, checks their bounds and rejects
aliases with the loaded image. The handoff plans destination and scratch
memory from that map, projects ACPI and SMBIOS records into owned pages, and
uses callbacks restricted to the validated NetBSD ELF load segments. It does
not pass EFI runtime mappings. It does not request the kernel debugger.

The image's actual placement and the readability and lifetime of firmware
pointers cannot be proved by the loader: the firmware has already placed the
Mach-O before this code starts. Its experimental policy accepts unknown ACPI
SDT signatures when the complete bounded table is descriptor-backed and has a
valid checksum, but it does **not** validate unknown semantics or nested
references. Strict ACPI and SMBIOS checks can reject otherwise working
firmware. The keyboard heartbeat is a late positive signal, and its absence
does not identify the failure stage. Never install or write an internal disk
automatically. Review and test on a disposable USB only.

Build on Linux with clang, lld, Python, and objdump. The destination directory
must not exist. The explicitly named emulation macros enable the current
prototype preparation routines; no test fixture copy callbacks are linked.

```sh
sh netbsd/macho/target/hardware/build.sh /path/to/netbsd-INSTALL /path/to/new-build
```

The result is `fixture.macho`; this name does not establish hardware
functionality. `HARDWARE_TEST=1` restricts scratch to 128 MiB for the standard
Unicorn harness and must not be used to produce a test image. The regular
build was separately executed with 256 MiB of synthetic memory and the
modified 11.1 heartbeat kernel through return from the real `native_loader`.
This emulation is neither a full kernel boot nor hardware validation.

For the non-`HARDWARE_TEST` build, run the standard harness with its simulated
memory limit set to 256 MiB, plus the owned-page rejection check:

```sh
PYTHONPATH=/path/to/unicorn python3 -c 'import sys; sys.path.insert(0, "netbsd/macho/target"); import run_emulated as t; t.MEMORY_END=0x10000000; sys.argv=["test", "--native", sys.argv[1], "--macho", sys.argv[2], "--kernel", sys.argv[3]]; t.main()' /path/to/build/fixture.elf /path/to/build/fixture.macho /path/to/netbsd-INSTALL
PYTHONPATH=/path/to/unicorn python3 netbsd/macho/target/hardware/run_owned_unicorn.py --native /path/to/build/fixture.elf --macho /path/to/build/fixture.macho --kernel /path/to/netbsd-INSTALL
```

## Returning actual-copy diagnostic

`DIAGNOSTIC_ACTUAL_COPY=1` on `build_diagnostic.sh` builds a separate returning
diagnostic. Unlike the original no-write dry run, it writes the planned
bootinfo and NetBSD ELF load destinations in RAM, checks every copied byte and
zeroed BSS byte, and returns to Linux without entering NetBSD or writing a
disk. A successful status is stage 10/error 0; in that status the two selected
entry fields contain the file-byte and zero-byte counts. Error 10 means the
live return-state reservation could not be established; error 11 means the
destination readback failed. Other stage/error meanings remain unchanged.

The diagnostic reserves every EFI descriptor intersecting a 4 KiB guard band
above and below the inherited hook stack pointer, and every descriptor touching
the current GDT and IDT. It requires complete descriptor coverage before any
kernel write. It also reserves descriptor-backed boot-argument device-tree,
kernel and EFI-runtime ranges; the targets of every original configuration
entry and nonzero EFI system-table pointer; and the framebuffer span. For
Apple's overlapping conventional and firmware allocations, a complete
non-conventional backing descriptor is reserved without also reserving the
entire overlapping conventional range. Unbacked or ambiguous references
fail closed. Unknown-length discarded configuration entries and original EFI
system pointers below the 256 MiB limit also reserve the following address
space up to that limit, so a cross-descriptor object cannot reach a planned
kernel or scratch write. Unknown objects can themselves contain nested
pointers that this diagnostic does not follow or protect.

The inherited stack's actual allocation bounds are unknown: the
guard band and firmware descriptor ownership are experimental assumptions,
not proof that all return state has been captured. Firmware places the image
before the loader can inspect its map. A fatal read or copy fault can prevent
return and cannot produce an on-screen error.

The optional `test_actual_copy_unicorn.py` exercises the combined Mach-O with
synthetic descriptors and firmware, checks full destination bytes and BSS,
actual bootinfo, original Linux and firmware bytes, and restored registers.
Run it only with an actual-copy build and a combined returning Mach-O:

```sh
DIAGNOSTIC_ACTUAL_COPY=1 sh netbsd/macho/target/hardware/build_diagnostic.sh /path/to/netbsd-INSTALL /path/to/new-build
PYTHONPATH=/path/to/unicorn RETURNING_COMBINED_MACHO=/path/to/combined.macho ATV_DIAG_ELF=/path/to/new-build/diagnostic.elf ATV_DIAG_KERNEL=/path/to/netbsd-INSTALL python3 netbsd/macho/target/hardware/test_actual_copy_unicorn.py -v
```
