# NetBSD on first-generation Apple TV: EFI validation

This is an independent experiment alongside the existing Debian image. The
current builder creates **only an ATV1sm and rEFInd boot test image**. It does
not include NetBSD, a live filesystem, installation sets, or an installer.
Do not use it to install or modify an internal disk.

The first hardware gate is a cold boot to rEFInd with a working USB keyboard.
ATV1sm's author reports that NetBSD 10.1 i386 can boot and install with
`nouveau` disabled, but the i386 install medium needed an IA32 EFI loader
from the matching amd64 media. This report must be reproduced on the target
before a NetBSD image is designed around it. See the [ATV1sm instructions and
compatibility report](https://distrohopper39b.com/atv1sm/).

ATV1sm's author also reports possible firmware soft-bricking with certain
operating systems and describes recovery involving the CMOS battery and an
NVRAM reset. Review the upstream warning before testing; whether it applies
to NetBSD is not established.

## Inputs and build

Use a disposable Linux build VM with `parted`, `dosfstools`, `util-linux`,
and standard core utilities. Creating the image uses root, loop devices and a
temporary mount. A sufficiently large new output file and free disk space are
required. Supply these separately obtained inputs; do not commit them:

* An extracted Apple Service Diagnostic `System` directory for Apple TV 1,
  obtained with appropriate rights. It must include the diagnostic bundle and
  runtime files described upstream.
* The unpacked ATV1sm release directory, containing `ASD`, `GopShimDxe.efi`
  and the `EFI` directory. The upstream instructions describe release 0.1.2.

Record the exact input sources, versions and checksums in your test notes.
This repository does not distribute Apple diagnostic files. The existing
Debian `boot.efi` is not a substitute for the diagnostics environment.

Run a non-mutating input check, then build the image, using absolute paths:

```sh
make netbsd-efi-check ASD_SYSTEM=/path/to/System ATV1SM=/path/to/ATV1sm NETBSD_IMAGE=/path/to/new-atv1-efi.img
make netbsd-efi ASD_SYSTEM=/path/to/System ATV1SM=/path/to/ATV1sm NETBSD_IMAGE=/path/to/new-atv1-efi.img
```

The output must be a new regular image file, not a physical disk. Build the
default Debian image with `make` as before; the NetBSD target is separate.
Flashing the image erases the chosen USB device: verify the device identity
and size independently, unmount it, and follow your host's image-writing
procedure. Do not select the internal disk. Back up the internal disk before
experiments and confirm it still boots with the USB removed.

## Remaining work

1. Confirm this image reaches rEFInd on actual ATV1 hardware with keyboard and
   display working. Record the exact inputs, firmware, hardware and result.
2. Reproduce the reported NetBSD 10.1 installer boot, including an actual IA32
   NetBSD EFI loader and `userconf disable nouveau`; verify installer media,
   storage and input before attempting a write.
3. Create and validate a single-stick persistent NetBSD live root and installer
   with local distribution sets. Keep rEFInd's `EFI/BOOT/BOOTIA32.EFI` separate
   from the NetBSD loader, and verify the boot and root paths on hardware.
4. Only after an independently verified backup and an explicit installation
   choice, provision the internal disk and prove it cold-boots without USB.

The current implementation has not passed any of these hardware gates. The
NetBSD [x86 boot manual](https://man.netbsd.org/NetBSD-10.1/x86/boot.8)
documents the IA32 EFI bootstrap and `/EFI/NetBSD/boot.cfg`; it does not by
itself establish the Apple diagnostic boot path.
