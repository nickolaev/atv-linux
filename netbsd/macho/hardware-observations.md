# ATV1 entry probe observations

On the user's Apple TV 1, the 64 MiB `atv1-debug-probe-64m.img` (SHA-256
`0f06bfb4c4fd3dbc00f95c929efae3711c5b56bb8fcb4128df30d29818693cb7`)
reached the initial Linux diagnostic menu. A user-supplied photograph shows
`Entry confirmed`, proving that the returning Mach-O shim executed and that
its command-line telemetry reached Linux. The shim then returned to the
existing bootloader; it did not attempt a NetBSD handoff or call EFI services.

The on-screen entry values were hexadecimal:

| Field | Value |
| --- | --- |
| Revision/version word | `00010004` (revision 4, version 1) |
| Video base / mode | `10018000` / `00000001` |
| Pitch / width / height / depth | `00000c00` / `000002d0` / `000001e0` / `00000020` |
| EFI memory map / size | `02b06000` / `00000780` |
| Descriptor size / version | `00000030` / `00000001` |
| EFI system table address | `02b57f10` |
| CR0 / CR3 / EFLAGS | `00000013` / `00000000` / `00000012` |

These values indicate a 720 × 480, 32-bit entry framebuffer with 3072-byte
pitch, and CR0.PG clear when the probe ran. The Linux diagnostic subsequently
reported `nouveaufb` at 1920 × 1080, 32 bpp and 7680-byte stride. The user
reported that the display does not acquire a signal until Linux starts. These
observations explain why a pre-Linux framebuffer-only test is inconclusive;
they do not prove the cause of its failure or that EFI boot services are live.

The photograph also reports 240900 KiB Linux `MemTotal`, an Intel family 6
model 13 CPU, detected USB devices and two disks. These disk names are runtime
enumerations and must not be assumed to identify a target for installation.

A second photograph shows the initial Linux kernel detecting the Apple IR
receiver, the attached USB keyboard and a SanDisk USB mass-storage device.
Linux assigned the stick `sdb` in that boot. Its GPT log says the backup GPT
header is at sector 131071 instead of the physical disk's final sector
120164351: the 64 MiB image was written to a larger device. The primary GPT
and recovery partition were still read and Linux started. This warning does
not establish a corrupt source image, but full-size media provisioning needs
to account for the backup GPT. Do not automatically repair or repartition the
user's stick or internal drive.

The filtered video/firmware page includes `vgaarb` and `EFI Variables Facility`
messages but does not, on its own, show when HDMI was enabled or establish
that NetBSD's graphics driver will work.

## EFI system-table snapshot

The user's subsequent test of `atv1-efi-map-probe-64m.img` reported capture
status `0`, with 40 descriptors and a 72-byte EFI system table. Transcribing
the table from the displayed hexadecimal bytes gives signature `IBI SYST`,
revision `0x0001000a`, header size 72 and CRC32 `0x01173261`. Recomputing the
CRC32 over those 72 bytes with the CRC field cleared yields the same value.
The IA-32 table reports runtime-services pointer `0x02b57a90`, boot-services
pointer `0`, and nine configuration-table entries at `0x02b56d90`. The zero
boot-services pointer is evidence that those services are unavailable at this
point. A nonzero runtime pointer and matching table CRC do not establish that
runtime services are callable or that their referenced memory remains valid.
These are observations from this particular boot, not reusable addresses.
The photographed descriptors place the 72-byte system table and the nine
20-byte IA-32 configuration-table entries inside identity-mapped runtime-data
regions. This was a range observation only; that probe did not read the
configuration-table entries or the objects they reference.

The later returning Linux-time observer displayed all nine configuration
entries. Its ACPI 1.0 RSDP at `0x0fefd000` and RSDT at `0x0fefd038` had
valid checksums; its ACPI 2.0 RSDP at `0x0fefd014`, RSDT at `0x0fefd0fc`,
and XSDT at `0x0fefd1c0` also had valid checksums. These are transcriptions
of observations after Linux started, not complete raw captures. The observer
did not read the root-table children. Pointer identity and object lifetime at
the earlier firmware handoff, or on a future boot, are not established.

## Returning register probe

The subsequent offline register diagnostic booted and displayed a successful
snapshot. In that boot the hook ESP was `0x0de805d4`, inside the EFI type-4
region `[0x0de43000, 0x0de92000)`. This is a single stack pointer, not the
stack allocation or its bounds. CR4 was `0x00000640`. The displayed selectors
were CS `0x0010` and DS, SS, ES, FS and GS `0x0018`. These are values at the
patched loader hook, after its original setup, not necessarily at Mach-O
entry. The captured table CRC was valid and the 11.1 installer metadata's
two load segments were map candidates; the probe did not read the installer
file or validate live allocations. All addresses are specific to that boot.

## Returning loader dry run

The user booted `atv1-returning-128m.img` and photographed the Linux menu
showing `stage=00000009` and `error=00000000`: preparation completed without
a reported validation error and control returned to the original Linux loader.
The photographed record contained the following hexadecimal values:

| Field | Value |
| --- | --- |
| Apple boot arguments | `0x05688000` |
| EFI map address / bytes | `0x05691000` / `0x000007e0` |
| EFI system table | `0x056e2f10` |
| Last selected kind / pointer | `3` (SMBIOS2) / `0x0febe000` |
| Projected EFI table | `0x05671000` |
| Planned bootinfo | `0x0fea7000` |

These live addresses differ from the earlier EFI snapshot; do not reuse them
on another boot. The diagnostic validated the supplied EFI and selected ACPI
and SMBIOS data according to its implemented checks, planned kernel and
scratch ranges, and exercised native bootinfo construction. Its kernel-copy
callbacks checked planned destinations but intentionally did not write them;
the bootinfo output was a loader-owned diagnostic buffer. It returned before
the native entry transfer, so neither actual kernel copying, NetBSD startup,
root mounting, nor the keyboard heartbeat was demonstrated. The combined
returning image has a different firmware allocation layout from the earlier
one-way NetBSD candidate, so this result does not establish how far that
candidate got. The dry run's firmware-pointer readability and allocation
assumptions remain specific to this experiment.

## Returning native-entry diagnostic

The user booted `atv1-returning-stage11-128m.img` and photographed the
returning Linux menu reporting `stage=00000006` and `error=0000000a`:
"Live return-state memory could not be protected." The displayed last
selected entry was kind `3` (SMBIOS2), at `0x0febe000`; the projected EFI
table address was `0x05672000`, and planned bootinfo remained zero.

Stage 6 precedes memory planning, the real kernel copy, and native entry. The
error groups multiple return-state and original-source protection checks; the
photograph does not identify which one failed. Linux resumed and displayed
the result, but this does not establish that NetBSD was entered. Firmware and
allocation addresses differ between boots and must not be reused for a later
attempt.

A later boot of the stage-6-detail diagnostic again returned to Linux with
stage `0x06`, error `0x0a`. Its detail identified protection check `0x05`,
the Apple kernel range at `0x02000000` with length `0x0371b000` (exclusive
end `0x0571b000`). Reason `5` reported that no single EFI descriptor covered
the entire range; descriptor index `65535` and type `255` indicate that no
specific descriptor was reported. This result precedes the kernel copy and
native entry. It does not establish that the range is invalid or unsafe;
the diagnostic's single-descriptor requirement rejected this boot's layout.

## Next handoff investigation

The official NetBSD 11.1 i386 `netbsd-INSTALL.gz` was staged on `mbp` and its
SHA-512 matched the release checksum. Its uncompressed kernel is an ELF32
i386 executable with entry `0xc0100000` and load segments whose physical
addresses begin at `0x00100000` and `0x00fa2000`. Those ELF addresses do not
by themselves define a working boot handoff. Before a hardware boot attempt,
the loader must implement and validate the NetBSD entry protocol, the memory
map and a usable display/input path; none has been established yet.

The previously inspected 10.1 installer has a valid Multiboot v1 header; the
11.1 native entry was separately exercised in emulation. NetBSD's i386 startup
source supports Multiboot as well as its native protocol;
protocol selection and all boot information still require implementation and
testing. In the NetBSD 11.1 `INSTALL` configuration, `nouveau` is explicitly
disabled. Since the observed Linux display is initialized by `nouveaufb`, the
installer kernel's HDMI visibility on this device is unproven and is a separate
problem from reaching kernel entry.

The user-provided memory-map photographs show a conventional region
`[0x000c0000, 0x02000000)` containing both load segments of the staged 11.1
installer. They also show a conventional region
`[0x02b07000, 0x0de43000)` overlapping runtime code/data descriptors covering
`[0x02b07000, 0x02b58000)`. Runtime regions must not be considered free merely
because a conventional descriptor overlaps them. These transcribed values are
evidence for this boot only, not a substitute for the live map on a later boot.

NetBSD's [native x86 boot-info records](https://github.com/NetBSD/src/blob/273f94b6a21206eac305acfa360a841fffef0af0/sys/arch/x86/include/bootinfo.h#L183-L251)
can describe the EFI memory map and system table without calling EFI boot
services. This is a promising handoff direction, not proof that the firmware
table remains safe to use: the captured address and lifetime must be checked.
NetBSD's [Multiboot conversion](https://github.com/NetBSD/src/blob/273f94b6a21206eac305acfa360a841fffef0af0/sys/arch/i386/i386/multiboot.c)
does not translate those EFI records, and the kernel's
[MCA probe](https://github.com/NetBSD/src/blob/273f94b6a21206eac305acfa360a841fffef0af0/sys/arch/i386/i386/machdep.c#L1578-L1579)
can take a legacy BIOS path when EFI boot information is absent. The linked
maintenance-branch files were checked against the official 11.1 source archive;
the linked commit itself is not the 11.1 release tag.
