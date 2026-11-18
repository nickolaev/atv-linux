# Returning EFI map snapshot probe

This diagnostic extends the known returning ATV1 Mach-O entry path. It takes a
bounded snapshot while paging is disabled, then resumes the unmodified Linux
bootloader. It does **not** call EFI services, access storage, or boot NetBSD.
The snapshot describes only the boot in which it was captured; its addresses
and descriptor contents must not be assumed valid after a reboot.

`package.py MENU_MACHO SHIM_ELF NEW_MACHO` adds an uncompressed `newc` archive
containing `atv-probe.bin` after the existing gzip member in the existing
initrd section's zero padding. It rejects a preexisting conflicting cpio entry,
malformed gzip, insufficient padding, an unexpected Mach-O mapping or entry,
and any output that already exists. It preserves the original gzip bytes and
patches only the verified entry's NOPs and mapped header padding for the shim.

The 8192-byte payload contains little-endian 32-bit words. An untouched zero
file means the probe did not complete its initial validation, including a null,
out-of-range, oversized, malformed or overlapping source. The destination is
not written for these cases. On successful completion the magic `ECAP`
(`0x50414345`) is written last. Status `0` means the EFI map and a validated
32-bit system-table header were copied; status `3` means the map was copied
but the table was absent, not covered by a suitable data descriptor, had an
invalid signature or size, or was otherwise unsupported. These are diagnostic
checks; the table CRC is not checked, and they do not prove that the firmware
data are correct or safe to execute.

| Offset | Meaning |
| --- | --- |
| 0 | completion magic `ECAP` |
| 4 | status |
| 8, 12, 16 | Apple boot-args address, EFI map address and map length |
| 20, 24, 28 | descriptor stride, descriptor version, system-table address |
| 32, 36, 40 | CR0, CR3, entry EFLAGS |
| 44, 48 | copied map length and copied table-header length |
| 52, 56 | EFI mode and packed boot-args revision/version |
| 60 | hook ESP (zero in older snapshots; stack bounds are unknown) |
| 64–191 | EFI system-table bytes, up to validated header size 128 |
| 192–8191 | original raw EFI descriptor bytes, at most 8000 bytes |

When the map is at most 7936 bytes, the final 64 bytes instead contain an
optional `XREG` version-1 trailer with general registers, segment
selectors, CR4, GDTR and IDTR. Larger maps use the full descriptor area and
omit the trailer. The trailer is an observation, not proof that referenced
memory is safe to read or overwrite. The values are observed at the loader
hook, after the original setup changed the low half of EBX, EBP and ES, not at
the Mach-O entry.

The probe requires the captured pointers to be aligned and in the conservative
physical range `[0x1000, 0x10000000)`, and requires map descriptors to have a
stride of at least 40, version 1, and complete bounded contents. It refuses
source/destination overlap and validates the EFI table signature and 72–128
byte header before copying it; it does not follow table pointers. An invalid
but non-null firmware pointer within the allowed physical window can still
fault on actual hardware: physical readability cannot be proved from the
pointer alone. The caller must test only on the target and treat a failed or
partial snapshot as inconclusive.

Build the shim on Linux with Clang and LLD:

```sh
clang --target=i386-unknown-none-elf -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -c netbsd/macho/map_probe/snapshot.S -o /tmp/atv-map-snapshot.o
ld.lld -m elf_i386 -T netbsd/macho/map_probe/layout.ld /tmp/atv-map-snapshot.o -o /tmp/atv-map-snapshot.elf
python3 netbsd/macho/map_probe/package.py /path/to/menu-mach_kernel /tmp/atv-map-snapshot.elf /path/to/new-mach_kernel
```

The menu-enabled input is generated from the known repository loader using
`image/embed_boot_menu.py` and `netbsd/macho/map_probe/menu.sh`. Page 1 shows
capture status; repeated selections of page 5 page through eight EFI memory
descriptors at a time, and page 6 shows the captured EFI table. Page 7
optionally configures wired `eth0` using DHCP and serves only a copy of the
capture from a dedicated temporary directory over HTTP port 8080. This network
export is started only when selected and still needs hardware validation.
If the optional preflight is present, page 7 also writes its output to
`/tmp/atv-capture/preflight.txt` and serves it at
`http://<eth0 IPv4 address>:8080/preflight.txt`; the raw snapshot remains
available at `http://<eth0 IPv4 address>:8080/atv-probe.bin`.
If the optional firmware observer is included, selecting page 13 runs it once
and pages its cached report. It opens `/dev/mem` read-only and observes memory
after Linux has started; Linux may have changed or reused those addresses.
It can report data as unavailable and cannot prove entry-time pointer validity
or hardware handoff safety. Select page 13 before page 7 to include the
cached report in optional Ethernet export as `firmware-observation.txt`.
Decode a retrieved capture with
`python3 netbsd/macho/map_probe/decode.py /path/to/atv-probe.bin`. Output is
JSON and explicitly reports its validation limits. A valid checksum or a
data-descriptor match does not prove that EFI runtime services are safe to call.
The decoder reports overlapping physical descriptors because the photographed
ATV1 map contains them; it does not turn the raw map into usable-memory ranges.
Package this
Mach-O using the existing image builder; never write directly to a device from
these commands. Run `python3 -m unittest discover -s netbsd/macho/map_probe -p
"test*.py"` for host checks. Setting `SNAPSHOT_ELF` to the linked shim and
installing Unicorn enables emulation of the real IA-32 instructions and their
valid, invalid, short-table and overlapping-source cases.

For optional menu page 8, build the freestanding Linux i386 preflight and pass
it as the fourth argument to `package.py`:

```sh
clang --target=i386-unknown-linux-gnu -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 -ffreestanding -fno-stack-protector -fno-pic -fno-pie -fno-builtin -Oz -nostdlib -no-pie -fuse-ld=lld -Wl,-static,-e,_start,--build-id=none,--no-dynamic-linker netbsd/macho/map_probe/preflight.c -o /tmp/atv-preflight
python3 netbsd/macho/map_probe/package.py /path/to/menu-mach_kernel /tmp/atv-map-snapshot.elf /path/to/new-mach_kernel /tmp/atv-preflight
```

To include the optional Linux-time observer, compile it with the same options
as the preflight (`observe_firmware.c` in place of `preflight.c`) to
`/tmp/atv-observe-firmware`, and pass that executable as the fifth argument to
`package.py`, after `/tmp/atv-preflight`. This diagnostic does not write
physical memory or boot NetBSD; failed or denied reads are reported explicitly.

Page 8 reports conventional write-back portions after conflicting firmware
descriptors are excluded. Its two segment checks use **embedded metadata** for
the official NetBSD 11.1 i386 INSTALL ELF (uncompressed SHA-256
`0e8b7f1e0ae2dc8722b6438e477037bd6ee89aee00c66fbf2c493de99fdedce4`): no
kernel file is read. It does not check loader, stack, firmware tables or other
live allocations and cannot determine whether a handoff is safe. It inspects
only the captured map from this boot, after Linux has started; it does not
perform or validate a NetBSD boot.
