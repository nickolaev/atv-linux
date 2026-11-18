# NetBSD on first-generation Apple TV

This is an independent NetBSD image alongside the Debian/Alpine USB. It uses
ATV1sm and the standard NetBSD EFI loader. The unattended installer has
installed NetBSD 11.1 and booted it from the internal disk on the tested Apple
TV. Custom Mach-O and Linux/kexec experiments are retained for diagnostics.

The current target is NetBSD 11.1 i386. Earlier NetBSD 10.1 results below are
historical reference only; they do not establish compatibility with 11.1.

Existing ATV1 bootloader code passes the boot-argument pointer in EAX and
describes the framebuffer layout differently from the original proposal. The
diagnostic uses that established layout and accesses the framebuffer directly.
The ATV1sm author reports that normal `boot.efi` kernel handoff no longer has
EFI boot services, so the existence of an EFI system-table pointer is not
evidence that EFI calls or NetBSD's EFI loader can run. A working NetBSD
handoff was explored before the successful standard EFI path.

## Build the unattended NetBSD installer

On a Linux host install `makefs`, `sgdisk`, `parted`, `dosfstools`, `mtools`,
Python 3 and the usual core utilities. Supply the extracted Apple diagnostic
`System` directory, unpacked ATV1sm release, and the official NetBSD 11.1/i386
`binary/sets` files `base.tgz`, `etc.tgz`, `kern-GENERIC.tgz`, `modules.tgz`
and `SHA512`. The builder checks the release-set checksums and produces a new
regular image file without requiring a loop mount or root privileges.

```sh
bash netbsd/image-integration/build-installer.sh \
  /path/to/FieldDiags/System /path/to/ATV1sm \
  /path/to/NetBSD-11.1-i386-sets /path/to/new-netbsd-installer.img \
  /path/to/ssh-public-key.pub
```

The image automatically repartitions the **FUJITSU MHW2040AT with 78,140,160
sectors** detected on the tested Apple TV. It erases that disk and installs
NetBSD 11.1 with a 1 GiB swap partition, hostname `atv` and DHCP. The guard
currently rejects replacement internal disks. Installation and readiness
reports are sent to `192.168.100.246:8083`; adjust the scripts and collector
for a different network. The USB's temporary root skips `fsck` because the
host `makefs` image failed a repeat-boot check. The installed root is created
with NetBSD `newfs` and retains normal filesystem checks.

The optional final argument supplies a public SSH key. When present, the
installed system enables key-based root SSH login for that key. The private
key stays on the build host. After logging in, run
`/usr/local/sbin/atv-provision-packages` as root to download the compiler,
current pkgsrc and pkgsrc-wip, and install `pkgin`, `pkg_chk`, `tmux`, `micro`,
`vim`, `mc` and `git`. Package progress and failures are reported to the same
network collector and logged in `/var/log/atv-packages.log`. Download and
installation require Internet access. The installer also attempts to fetch
current pkgsrc and pkgsrc-wip source archives during installation; a failure
is reported and the provisioning command can retry them after boot.

Add `--interactive-ssh` after the output path and optional public key to boot
the USB into an SSH-accessible installer instead of starting the disk install
automatically. Log in to the USB as `root` with password `netbsd`, then run
`atv-install` to install to the internal disk. These credentials apply only to
the temporary installer USB; use this mode only on a trusted network. The
command runs the installation inside a persistent `tmux` session, so you can
reconnect and run `atv-install` again to reattach after an SSH disconnect.
After partitioning, the installer activates the new 1 GiB swap wedge to help
the memory-limited machine while it extracts the distribution sets.

The original hardware test wrote the internal disk, then a USB-free boot
reported `result=ready`, the `atv` hostname, DHCP IPv4 and 1,048,576 KiB of
active swap. The first-boot SSH and package additions require hardware testing.

`netbsd/macho/netbsd_elf.py` inspects an uncompressed i386 ELF kernel and
reports the physical load segments and entry address. Optional `--usable` and
`--reserve` ranges check the plan against caller-supplied memory bounds; a
plan without `--usable` is explicitly not validated against hardware memory.
This tool does not boot the kernel or change an image.

`netbsd/macho/netbsd_bootinfo.py` serializes native i386 EFI boot-info records
from caller-supplied descriptor bytes for offline validation. It neither
calls firmware nor establishes that the supplied addresses and memory map are
valid on the hardware.

`netbsd/macho/native/` contains an experimental native i386 ELF loader and
handoff implementation. The integrated handoff is compiled only with the
explicit `NB_ENABLE_EXPERIMENTAL_HANDOFF` flag and is for emulation; it is not
connected to the ATV1 image builder. See
[`native_tests/README.md`](macho/native_tests/README.md) for the real-kernel
emulator test and [`native-handoff-design.md`](macho/native-handoff-design.md)
for its hardware limitations.

### Build the custom diagnostic

On a Linux host with Clang, LLD and Python 3, build the payload with
`make -C netbsd/macho`. Run `make -C netbsd/macho test` for the framebuffer and
binary-wrapper tests. Package it in a new image using root and the Linux
`parted`, `hfsprogs` and `util-linux` packages:

```sh
sudo bash netbsd/macho/build-image.sh --kernel netbsd/macho/mach_kernel --output /path/to/new-diagnostic.img
```

Add `--check` to validate inputs without creating an image. The output is a
64 MiB GPT image using the existing Apple `boot.efi` and HFS+ recovery layout.
Use `--image-mib` and `--recovery-mib` to make a larger diagnostic image and
recovery partition when needed; the image must be at least 2 MiB larger than
the recovery partition. Changing the size does not add a NetBSD system.
On hardware, a blue screen with a white rectangle above a green rectangle is
the expected success signal; the diagnostic then halts. A blank screen does
not identify which stage failed. The image is not a NetBSD live system.

If the display becomes active only after Linux starts, use the returning entry
probe instead of the halting framebuffer diagnostic. The probe preserves the
original loader, records boot-argument and CPU values in the Linux command
line, and continues to the initial Linux environment. `probe-menu.sh` displays
the values before any kexec and provides pages for device and kernel logs.
The build uses `make -C netbsd/macho probe_trampoline.elf`, followed by
`patch_probe.py` on a separate bootloader copy whose initramfs contains that
menu. The probe does not invoke EFI services or write to hardware. A small
image with the same menu but without the probe is useful as a control.

The [EFI map snapshot probe](macho/map_probe/README.md) extends this returning
approach to capture the map and system-table header for offline analysis. It
stores the capture in an initramfs file and never calls EFI services. The
snapshot describes only that particular boot and must not be reused as the
memory map for a future kernel handoff.

## ATV1sm EFI installer experiment

`netbsd/build.sh` builds a separate USB image using Apple Service Diagnostics,
ATV1sm, rEFInd and the standard NetBSD EFI loader. This lets NetBSD receive its
EFI identity and boot information from its own loader. The custom Mach-O and
Linux/kexec diagnostics remain available for comparing the handoff.

The target is NetBSD 11.1 i386. Use the unmodified `INSTALL` kernel and the
matching IA32 `bootia32.efi` loader. The installer kernel includes its RAM root
filesystem. This first-boot image starts the installer and requires an external
source for distribution sets during installation.

Supply the extracted diagnostic `System` directory and an unpacked ATV1sm
release containing `ASD`, `GopShimDxe.efi` and `EFI/boot/bootia32.efi` (rEFInd).
Record the input versions and checksums with the test image. Apple diagnostic
files and release binaries stay outside the repository.

The builder runs on Linux using `parted`, `dosfstools`, `mtools`, Python 3 and
standard core utilities. It assembles a FAT filesystem in a regular file and
copies it into a GPT image. It can run without root or loop-device mounts.
Choose a new output path.

```sh
bash netbsd/build.sh --check \
  --asd-system /path/to/FieldDiags/System --atv1sm /path/to/ATV1sm \
  --netbsd-kernel /path/to/netbsd-INSTALL --netbsd-efi /path/to/bootia32.efi \
  --size-mib 128 --output /path/to/atv1sm-netbsd-11.1.img
bash netbsd/build.sh \
  --asd-system /path/to/FieldDiags/System --atv1sm /path/to/ATV1sm \
  --netbsd-kernel /path/to/netbsd-INSTALL --netbsd-efi /path/to/bootia32.efi \
  --size-mib 128 --output /path/to/atv1sm-netbsd-11.1.img
```

Omitting both NetBSD options builds the original rEFInd hardware-gate image.
The build validates that the supplied kernel is an i386 ELF executable and
the NetBSD loader is an IA32 EFI application. `--check` validates inputs and
leaves image creation to the second command.

The image has a 40 MiB Apple TV recovery FAT32 partition containing the patched
ASD bundle, GopShim and rEFInd. A second FAT32 partition of EFI System type,
labeled `NETBSD11`, contains `/EFI/NetBSD/bootia32.efi`,
`/EFI/NetBSD/boot.cfg`, a removable-path copy at `/EFI/BOOT/BOOTIA32.EFI`,
and the kernel at `/netbsd`. The EFI System partition
type lets the NetBSD loader resolve its `esp:` paths. It is GPT entry 1, so
NetBSD finds it before scanning the Apple recovery type in GPT entry 2. rEFInd offers an explicit
NetBSD entry and waits for keyboard selection. The NetBSD menu also waits
for selection, queues `userconf disable nouveau`, and runs
`boot esp:/netbsd -v` to load the kernel from the EFI volume. A second entry
opens the boot prompt for diagnostic commands such as `version full`,
`devpath`, and `gop`.

Add `--autoboot` to select the NetBSD entry after five seconds in rEFInd and
boot the installer after a further five seconds in the NetBSD menu. This mode
uses text mode, stores rEFInd variables on the USB filesystem, and enables
level-2 logging at `/EFI/boot/refind.log` on the recovery partition. Its tools
menu contains only reboot, avoiding firmware-tool enumeration. The log covers
rEFInd startup and loader launch. The stock NetBSD EFI loader and kernel
do not append their output to this file.

Flash the image to the selected USB stick and cold-boot the Apple TV. The
expected sequence is ATV1sm output, rEFInd, the NetBSD EFI menu, then kernel
messages and the installer. Record the last visible stage if boot stops.
Hardware testing is required to establish Apple TV compatibility with 11.1.

The 128 MiB reference image was built using the existing ATV1sm 0.0.2 release,
the extracted Apple diagnostic files, and the official NetBSD 11.1/i386
INSTALL kernel and IA32 loader. The final image SHA-256 is
`347366bac6f09bdbb5ca9b51cbfa1f4356077d8e5087a367ec96a4ca615a362d`.
Its standard EFI fallback loader booted the unmodified installer to the
language menu in IA32 QEMU. The Apple diagnostic and ATV1sm portion awaits
the physical Apple TV test. This image contains the installer ramdisk;
distribution sets for installation must be fetched over the network.

The single-recovery-partition logging control was tested on the physical Apple
TV. Its USB `refind.log` identifies rEFInd 0.14.2, Apple firmware 4096.01,
EFI 1.10, and available text, UGA and GOP protocols. It reaches
`RunMainMenu` and `WaitForInput(), Timeout = 0` despite no HDMI signal.
This confirms the Apple diagnostics/ATV1sm/rEFInd entry chain on that control
image. It does not establish visible graphics or a NetBSD EFI kernel boot.

The upstream author reports that NetBSD 10.1 boots and installs using an EFI
loader and disabled Nouveau. The same report describes recovery steps for
firmware problems observed with some other operating systems.
[ATV1sm instructions and compatibility report](https://distrohopper39b.com/atv1sm/)

NetBSD documents the EFI loader's configuration path and boot commands in
[boot(8)](https://man.netbsd.org/NetBSD-11.1/x86/boot.8) and the menu syntax in
[boot.cfg(5)](https://man.netbsd.org/boot.cfg.5).

## Remaining work

The unattended installation target is a USB that provisions the Apple TV's
internal disk, installs the EFI boot chain and NetBSD, sets hostname `atv`,
and enables Ethernet DHCP with the hostname sent to the DHCP server.
The headless EFI installer-ramdisk report has been received from physical
Apple TV hardware. The completion signal for installation should include a
durable success record on the USB and a network report with the installed
hostname and address. Provisioning must identify the internal Apple TV disk
independently of the USB device's enumeration order.

The successful headless diagnostic uses the existing v2 report kernel through the
native EFI path. It retains the original virtual ELF entry, runs its reporter
from the installer RAM filesystem, and makes no installation changes. The
diagnostic uses `192.168.100.191/24` to contact `mbp` at
`192.168.100.246:8083`; DHCP belongs to the later installed-system stage.
The physical automatic-boot log confirmed rEFInd launched the stock NetBSD
EFI loader. Native EFI QEMU also reached the modified installer's profile
and returned a complete Ethernet report.

On 2026-11-18 at 00:48:19 +02:00, `mbp` received the physical Apple TV's
17,490-byte report, ending in `dmesg_status=0` and `report=complete`.
It identifies NetBSD 11.1 INSTALL, the RAM root `md0a`, Ethernet `rtk0`,
and the internal FUJITSU MHW2040AT disk `wd0` (78,140,160 sectors).
The SanDisk USB was `sd0`. This established the native EFI kernel boot and
installer-userland network path on hardware. HDMI remained without signal.

The subsequent unattended installation completed on the physical Apple TV.
A cold boot with the USB removed reported hostname `atv`, active `rtk0`, root
on the internal `atv-root` wedge, and 1 GiB of active `atv-swap`. The DHCP
configuration sends hostname `atv`; that option has not been packet-captured.
SSH access and package provisioning are under separate maintenance testing.
