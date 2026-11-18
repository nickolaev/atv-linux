# NetBSD installer Ethernet report

`reporter.c` runs from the NetBSD 11.1/i386 installer ramdisk. It sets a
static IPv4 address on the selected Ethernet interface, then sends its
startup milestone, interface status, and kernel log to a controller on
the same subnet. Selecting `rtk0` also checks `re0` when `rtk0` is absent,
to cover both NetBSD drivers for RTL8139 revisions. The reporter leaves
storage untouched. Its 15-second deadline bounds the transfer attempt.

Cross-build with Clang, LLD, and the verified NetBSD 11.1/i386 sysroot.
Choose a fresh report ID for each hardware diagnostic. The following
settings are for a QEMU guest with `-nic user,model=rtl8139` and a receiver
listening on TCP port 8083 on the host loopback address.

```sh
clang --target=i386-unknown-netbsd --sysroot="$NETBSD_SYSROOT" \
  -march=pentium-m -mno-sse -mno-sse2 -mno-mmx -mno-80387 \
  -Wall -Wextra -Werror -Os -static -fuse-ld=lld -Wl,-s \
  '-DATV_REPORT_ID="qemu-netbsd11"' '-DATV_REPORT_IF="re0"' \
  '-DATV_REPORT_ADDR="10.0.2.15"' '-DATV_REPORT_NETMASK="255.255.255.0"' \
  '-DATV_REPORT_HOST="10.0.2.2"' -o atv-net-report reporter.c
```

Install the executable in a copy of the embedded ramdisk filesystem. Start
it in the background from `/.profile` before `sysinst`. The experimental
heartbeat ramdisk already invokes `/keyboard-heartbeat &` at that point,
so replacing that executable in a separate kernel copy also works.

For the QEMU build above, start the collector before booting the installer
with `root=md0a`.

```sh
python3 netbsd/diagnostics/net_report/receiver.py \
  --source 127.0.0.1 --launch-id qemu-netbsd11 --timeout 60 report.txt
```

For the Apple TV build, set `ATV_REPORT_IF` to `rtk0`, use the Apple TV's
leased IPv4 address and netmask, and set `ATV_REPORT_HOST` to the collector
address. Pass that address to `--bind` and the Apple TV address to `--source`.
The collector saves one report in a new mode-0600 file and exits.

The receiver reads the ASCII header `ATVNETBSD1 <report-id>` followed by a
newline, up to 65536 bytes of payload, and then EOF. A complete payload
ends in `report=complete` and a newline. An oversized payload ends in the
additional suffix `\nreport=truncated\n`. A partial transfer without either
suffix is inconclusive. The report ID correlates the stream with a launch.
The collector checks the sender address and ID. The TCP stream is unencrypted
and has no message authentication. Use it on the diagnostic network.

For the native EFI path, retain the installer's original ELF entry
`0xc0100000`. Supply the reporter-equipped installer kernel directly to
the ATV1sm image builder as `--netbsd-kernel`; the physical-entry adjustment
below applies only to the Linux `kexec` path. Start the receiver before
booting the Apple TV: the reporter runs once from the installer profile,
and its transfer attempt has a 15-second deadline.

The existing `netbsd-INSTALL-report-atv-v2` artifact on mbp uses report ID
`atv-netbsd11-70b8c38a66`, source `192.168.100.191/24`, and collector
`192.168.100.246:8083`. Its SHA-256 is
`55461b4f7bdfcd9dd4fa6d75c55ed3f2017f6ce583de99840e65c8acc6511dc9`.
This is a static-address diagnostic; it does not install NetBSD or configure
the eventual installed system's DHCP client.

The native EFI automatic-boot image was checked in QEMU with the matching
QEMU reporter configuration and an RTL8139 adapter. It reached the
NetBSD/i386 11.1 installer language menu and sent a complete 15,715-byte
report containing `milestone=installer-profile`, `ifconfig_status=0`,
`dmesg_status=0`, and `report=complete`. This verifies the EFI-to-installer
reporting path in the emulator.

Physical Apple TV reporting succeeded on 2026-11-18 at 00:48:19 +02:00.
The receiver saved 17,490 bytes from `192.168.100.191`, with
`milestone=installer-profile`, `ifconfig_status=0`, `dmesg_status=0`, and
`report=complete`. The kernel detected the internal FUJITSU MHW2040AT as
`wd0`, the SanDisk USB as `sd0`, and Ethernet as `rtk0`; root was `md0a`.
The initial interface snapshot said `no carrier`, but the subsequent TCP
transfer succeeded. The report is stored on `mbp` at
`/home/nickolaev/atv-network-private.BogmBCP5/efi-headless-1794955143.txt`.
This test booted the installer RAM filesystem without changing the internal
disk. It did not validate DHCP or an installed-system boot.

The Apple TV bootstrap's `kexec-tools 2.0.1` jumps to the kernel ELF entry
with paging disabled. The NetBSD 11.1 i386 installer declares a virtual
entry of `0xc0100000` and loads the entry code at physical `0x00100000`.
Prepare a separate copy for this `kexec` path with
`netbsd/macho/prepare_kexec_kernel.py` and the input kernel's verified SHA-256.
Run the load with `--type=multiboot-x86 --command-line='root=md0a'`.
The corrected kernel was tested in QEMU using the Apple TV bootstrap's
Linux 2.6.39 and kexec-tools 2.0.1. It started the installer from `md0a`
and returned a complete Ethernet report with `dmesg`.
