# NetBSD on first-generation Apple TV

A USB image that installs NetBSD 11.1 i386 on the Apple TV's internal disk. It
boots through ATV1sm, rEFInd and the standard NetBSD EFI loader. Boot the USB,
log in over SSH and run the installer script. No other operating systems or
live systems are included. It is independent of the Debian/Alpine image.

Tested on one Apple TV: the unattended installer repartitioned the internal
disk, installed NetBSD 11.1 and booted it without the USB. The interactive SSH
mode and first-boot package provisioning still need hardware testing.

## Build the unattended NetBSD installer

On a Linux host install `makefs`, `sgdisk`, `parted`, `dosfstools`, `mtools`,
Python 3 and the usual core utilities. Supply the extracted Apple diagnostic
`System` directory, unpacked ATV1sm release, and the official NetBSD 11.1/i386
`binary/sets` files `base.tgz`, `etc.tgz`, `kern-GENERIC.tgz`, `modules.tgz`, `comp.tgz`, `man.tgz`, `text.tgz`
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
`/usr/local/sbin/atv-provision-packages` as root to install additional packages `tmux`, `micro`, `vim`, `mc` and `git`. The installer
attempts to install `pkgin`, `pkg_chk` and `git` and fetch current pkgsrc and
a Git-updateable pkgsrc-wip checkout into the target during installation. It reports a
failure if those steps do not complete; the provisioning command can retry
them after boot. Package progress and failures are reported to the same network
collector and logged in `/var/log/atv-packages.log`. Downloads require Internet
access.

Add `--interactive-ssh` after the output path and optional public key to boot
the USB into an SSH-accessible installer instead of starting the disk install
automatically. Log in to the USB as `root` with password `netbsd`, then run
`atv-install` to install to the internal disk. These credentials apply only to
the temporary installer USB; use this mode only on a trusted network. The
command runs the installation inside a persistent `tmux` session, so you can
reconnect and run `atv-install` again to reattach after an SSH disconnect.
It asks for an administrator username and separate administrator and root
passwords before changing the disk. The administrator joins `wheel` and must
change their password at first login; the root password can be used with `su`.
After partitioning, the installer activates the new 1 GiB swap wedge to help
the memory-limited machine while it extracts the distribution sets.

The original hardware test wrote the internal disk, then a USB-free boot
reported `result=ready`, the `atv` hostname, DHCP IPv4 and 1,048,576 KiB of
active swap. The first-boot SSH and package additions require hardware testing.

## Lower-level builder

`netbsd/build.sh` (called by `build-installer.sh`) assembles the GPT image from
the Apple diagnostic `System` directory, an unpacked ATV1sm release and the
NetBSD `INSTALL` kernel and IA32 `bootia32.efi`. It runs on Linux with `parted`,
`dosfstools`, `mtools` and Python 3, needs no root, and refuses to overwrite an
existing output. `--check` validates inputs only. Apple diagnostic files and
ATV1sm binaries stay outside the repository.
