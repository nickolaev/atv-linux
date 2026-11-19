# Experimental Mach-O entry diagnostic

This minimal 32-bit Mach-O program tests entry from the Apple `boot.efi`
path. It reads the Apple boot arguments pointer in EAX and draws a blue screen
with a white rectangle above a green rectangle using the supplied 32-bit
framebuffer, then halts. It makes no EFI calls, loads no kernel, and is not a
NetBSD bootloader. No hardware boot has been verified.

The boot argument and video field ordering follows
[u-boot-atvstub's boot_args.h](https://github.com/DistroHopper39B/u-boot-atvstub/blob/master/include/boot_args.h)
and its [entry point](https://github.com/DistroHopper39B/u-boot-atvstub/blob/master/start.S),
which point to the XNU x86 boot protocol. The loader is designed to match that
ABI; an actual Apple TV run is required to validate it. Only depth 32 is
supported. If the display information is invalid or unsupported, it halts
without displaying the pattern.

Run `make` on a host with Clang, `ld.lld` with ELF i386 support, and Python 3.
`make test` exercises the framebuffer bounds and the ELF-to-Mach-O conversion.
The generated `mach_kernel` has a fixed 0x00800000 physical address and must
be tested as a disposable USB image; the address and firmware behavior remain
hardware-validation assumptions. The Mach-O wrapper is deliberately limited
to the single ELF load segment produced by `layout.ld`.
