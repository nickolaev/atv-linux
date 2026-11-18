# Native NetBSD handoff: experimental design

The custom Mach-O loader is intended to load an embedded NetBSD/i386 ELF
kernel directly and hand it native boot information. It must not depend on
EFI Boot Services. This document describes validation criteria, not a claim
that the handoff or NetBSD is working on Apple TV hardware.

The NetBSD 11.1 i386 `INSTALL` kernel inspected on `mbp` has virtual entry
`0xc0100000`, mapping to physical `0x00100000`. Its ELF load ranges are
`[0x00100000, 0x00fa14d8)` and `[0x00fa2000, 0x015a6000)`, including BSS.
These addresses describe that particular binary; the loader must parse the
actual supplied ELF and validate all arithmetic, source bounds, entry,
overlaps and destination ranges against the firmware memory map at runtime.
Protect the loader, embedded kernel, stack, Apple boot arguments, EFI map,
boot-info records, firmware tables and any other live allocations until the
handoff. Do not infer usable RAM from the observed memory-map pointer or size.

The observed firmware map had 40 descriptors of 48 bytes each, version 1;
that observation is not a guarantee for another boot or larger payload. Copy
and validate the entire actual map before loading the kernel. Preserve EFI
identity and map via native NetBSD boot-info records only when their contents,
physical addresses and lifetime are validated. A nonzero EFI system-table
pointer does not establish that Boot Services are callable or that runtime
services are usable. The NetBSD 11.1 `GENERIC` configuration enables
`EFI_RUNTIME`, and its EFI initialization can map runtime descriptors and
read the runtime-services table. Therefore passing the captured system-table
address is not yet cleared for hardware use; first establish safe table and
descriptor lifetimes and kernel runtime behavior, or use a kernel built with
runtime support disabled. Fail safely on unsupported descriptors and layouts.

The photographed map includes runtime descriptors inside a larger overlapping
conventional-memory descriptor. The emulation-only integration produces a
sorted, disjoint `BTINFO_MEMMAP`, reserving every runtime or otherwise
restricted overlap, and passes it with `BTINFO_EFI` while omitting
`BTINFO_EFIMEMMAP`. Exact NetBSD 11.1 source inspection indicates that this
prevents EFI runtime initialization; it still requires validation and
preservation of the system and configuration tables. On i386 the native base
and extended memory fallback arguments must both be zero for this map to be
used when `biosmem_implicit` is not set. This strategy is not yet implemented
in the hardware loader.

The offline `efi_memmap.py` prototype normalizes and serializes a map, but does
not establish that the result is bootable. Before handoff, verify that usable
RAM covers the kernel and necessary allocations. The emulation path rejects
maps exceeding the 11.1/i386 physical-segment limit, accounting for the ISA
hole; a hardware path must retain that check. Validate and reserve all live
loader and firmware objects for the current boot.

NetBSD's native x86 entry takes a physical boot-info pointer and stack
arguments under a flat i386 protected-mode environment. The loader must match
the specific kernel source ABI, use a valid stack, pass memory values from
validated descriptors, and clear the direction flag. The kernel establishes
its own paging. Validate the actual implementation against pinned NetBSD
source and exercise byte layouts and register/stack behavior in emulation.

The ATV1 has so far shown HDMI only after Linux initializes its NVIDIA device.
NetBSD 11.1 `INSTALL` explicitly disables nouveau, so a black screen on a test
is not evidence that kernel entry failed. Establish an independent observable
success signal and a suitable console before claiming an installer works.
Neither an ELF parser nor a serializer proves an actual kernel handoff.

The 11.1 i386 kernel does provide a `BTINFO_FRAMEBUFFER`-driven generic
framebuffer console. That console draws into an already configured framebuffer;
it is not evidence that the NVIDIA output will be activated on this hardware.
The photographed display stayed off until Linux initialized the GPU, so an
independent post-handoff observation path or verified graphics initialization
is still needed. A returning Linux preflight can report checks on that boot's
snapshot, but cannot prove what occurs after a later nonreturning handoff.

Hardware testing must remain USB-only until explicit installation is chosen;
the small returning Linux-based entry diagnostic remains the recovery and
telemetry baseline. Emulation cannot reproduce Apple firmware, the captured
memory map, or actual ATV1 graphics, USB and IDE behavior.
