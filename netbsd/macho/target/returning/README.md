# Returning loader diagnostic

This is an experimental **dry-run diagnostic**, not a NetBSD boot image. It
adds a second, high Mach-O segment to the known Linux loader and runs the
instrumented target preparation with kernel-write callbacks replaced by
no-ops. The high bridge copies a 48-byte status record into an uncompressed
initrd file and returns to the original loader. Linux then displays the record
using `menu-status.sh`.

The packer accepts only the known original mapped extent
`[0x02000000, 0x02afd000)` and a high payload carrying the explicit returning
ABI marker. It checks Mach-O segments, file and address bounds, hook bytes,
header padding and initrd space. It creates a new output file; it does not
write an image or physical device.

The low hook checks protected mode, paging and interrupt state, flat GDT
descriptors, GDT/IDT and active-stack ranges, boot argument/map/system/config
direct ranges and EFI descriptor coverage. The high image must have complete
LoaderData coverage with no restricted or runtime overlap. Early rejection
before the checked status write has no marker; a `LOW1` marker means the high
call started, and `DIAG` records contain the completed return status. If the
high call faults or hangs, Linux cannot display a result.

**Limits:** Apple `boot.efi` loads the added segment before the hook can check
it; its allocation and placement are not proved. The initial `pushfl/pushal`
also uses the inherited stack before checks. EFI descriptor coverage does not
prove physical readability or nested ACPI/SMBIOS object separation within a
single LoaderData descriptor. The diagnostic makes no disk writes and does
not enter the NetBSD kernel. A black screen, missing status, or nonreturning
high call cannot uniquely identify a failure stage.

On a Linux host with clang and LLD, from the repository root, build the low
shim and combine it with the separately built, ABI-marked high diagnostic:

```sh
clang --target=i386-unknown-none-elf -march=pentium-m -ffreestanding \
  -c netbsd/macho/target/returning/shim.S -o /tmp/atv-return-shim.o
ld.lld -m elf_i386 -T netbsd/macho/target/returning/layout.ld \
  /tmp/atv-return-shim.o -o /tmp/atv-return-shim.elf
python3 image/embed_boot_menu.py image/recovery/mach_kernel \
  netbsd/macho/target/returning/menu-status.sh /tmp/atv-return-menu.macho
python3 netbsd/macho/target/returning/package.py /tmp/atv-return-menu.macho \
  /tmp/atv-return-shim.elf /path/to/diagnostic.macho /tmp/atv-returning.macho
```

The menu embedder and package output must be new files. Building and executing
the linked shim under IA-32 emulation is required for each change; packer unit
tests alone do not establish that the original Linux loader resumes.
