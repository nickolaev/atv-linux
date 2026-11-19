# NetBSD USB keyboard heartbeat

`keyboard-heartbeat.c` is an experimental **late boot** indicator for a
NetBSD 11.1 installer ramdisk. After USB keyboards and wscons attach and the
ramdisk starts userland, it opens `/dev/wskbd0` through `/dev/wskbd7` in
write-only mode, selects USB keyboards, and requests three one-second LED
on/off cycles before restoring their prior LED state. It does not write to disk.
The keyboard must have visible LEDs supported by its USB report descriptor.
An ioctl success queues a USB update; it does not prove a light changed.
Failure to see a pattern is inconclusive and cannot locate an early boot failure.

On a NetBSD 11.1/i386 build host with the development sets installed, build a
static NetBSD executable (a Linux executable will not run in this ramdisk):

```sh
cc -Wall -Wextra -Werror -Os -static -o keyboard-heartbeat keyboard-heartbeat.c
file keyboard-heartbeat
```

It has also been cross-linked on Linux using Clang and LLD with an isolated
sysroot extracted from the official, SHA-512-verified 11.1/i386 `base.tgz`
and `comp.tgz` sets:

```sh
clang --target=i386-unknown-netbsd --sysroot="$NETBSD_SYSROOT" \
  -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 \
  -Wall -Wextra -Werror -Os -static -fuse-ld=lld \
  -o keyboard-heartbeat keyboard-heartbeat.c
readelf -n keyboard-heartbeat
```

The resulting binary was static i386 and carried the NetBSD 11.1 ABI note.
It was run manually under NetBSD 11.1 in QEMU: with no USB keyboard it
reported that none was available; with a virtual USB keyboard attached it
returned status 0. This verifies the guest-side ioctl path, not visible LED
transitions or Apple TV hardware behavior.

Run on a disposable NetBSD test system with a USB keyboard and verify the
pattern and restoration before using it on hardware. To use it in an installer,
first inspect a **copy** of the installer kernel's embedded filesystem with
NetBSD's `mdsetimage -x`, check available filesystem capacity and device
nodes, then add the program and arrange for the ramdisk startup to run it
after USB attachment. Re-embed only into a new kernel copy. This repository
does not yet automate that integration, and no Apple TV hardware boot has
been demonstrated. The original kernel must remain unchanged.

## Disposable 11.1 installer experiment

The verified 11.1 installer kernel was booted in local QEMU with no physical
disks or network. Direct Multiboot used `-kernel netbsd-INSTALL -append -a`;
the root, dump, filesystem and init prompts were answered with their defaults.
The installer menu appeared. The separately built heartbeat was supplied via a
read-only virtual CD and run manually with a QEMU USB keyboard. This manual
test returned 0; actual LED transitions were not observed.

For an experimental modified kernel, a separate disposable raw virtual disk
was formatted inside the guest. Official 11.1 `mdsetimage -x` extracted the
installer's FFS image. A second copy of the extracted image was attached with
`vnconfig`, mounted, and given the heartbeat binary and a `/.profile` line
`/keyboard-heartbeat &` immediately before `sysinst`. After unmounting,
NetBSD `fsck_ffs -fn` reported a clean filesystem. `mdsetimage` inserted it
into a new kernel copy; a fresh extraction compared byte-for-byte equal to
the edited FFS. The unchanged original SHA-256 is
`0e8b7f1e0ae2dc8722b6438e477037bd6ee89aee00c66fbf2c493de99fdedce4`.

The new kernel copy is preserved on `mbp` at
`/home/nickolaev/atv-netbsd-11.1-diagnostics/netbsd-INSTALL-heartbeat`, with
SHA-256 `c0bc8ceb34ad9b5f74e1ef1fd608fac2fd3da37bd56943194693ebd5203a4ae6`.
It reached the installer menu in QEMU with a virtual USB keyboard. The
automatic background heartbeat's result and LED transitions were not
observed. This kernel is not a bootable Apple TV USB image.

The host-side test uses mocked system calls and fake ioctl constants; it is
not a NetBSD build or a USB hardware test:

```sh
python3 -m unittest discover -s netbsd/diagnostics -p 'test*.py'
```

NetBSD 11.1's `wskbdopen` permits write-only ioctl access without detaching
the keyboard from its mux; `ukbd_ioctl` implements `WSKBDIO_GETLEDS` and
`WSKBDIO_SETLEDS`. Source files: `sys/dev/wscons/wskbd.c`,
`sys/dev/wscons/wsconsio.h`, and `sys/dev/usb/ukbd.c` in the official 11.1
source distribution.
