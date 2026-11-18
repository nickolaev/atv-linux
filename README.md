# Debian on first-generation Apple TV

This project builds a USB image for first-generation Apple TV with Debian 12 (Bookworm) i386 and Alpine Linux 3.24.4 x86, using the existing legacy bootloader. Bookworm is oldstable/LTS, not current Debian stable. The image does not yet include an installer.

The separate [NetBSD installer](netbsd/README.md) uses the Apple TV's native EFI boot path and does not change the Debian and Alpine build. It has installed NetBSD 11.1 on the tested Apple TV's internal disk and booted it without USB.

## Build

Use an i386-compatible Debian-based Linux build host with a current Debian archive keyring; the Alpine build chroots into x86 userspace. The build runs as root, installs host packages, creates loop devices and mounts filesystems. Run it in a dedicated VM or disposable build environment:

```sh
make
```

The output is `image/atv-linux.img`. The filesystem build creates `filesystem/debian-appletv-filesystem.tar.xz` and its checksum; an existing archive is reused. Run `make clean` only when those local build outputs may be removed.

For the separate NetBSD USB image, see the [NetBSD build instructions](netbsd/README.md#build-the-unattended-netbsd-installer). The two image builders have separate outputs and inputs.

The root partitions are labeled `ATVTESTROOT` and `ATVALPINE`, so avoid attaching multiple copies at once. The legacy boot menu still assumes `(hd1,1)`; other disk orders have not been validated.

**Test image credentials:** the system creates a `debian` account with password `debian`, passwordless sudo, and an SSH server. Keep it off untrusted networks. Change credentials before any networked use; this image is not hardened for deployment.

## Boot selection

The boot menu offers Debian 12 and Alpine Linux 3.24.4. A USB keyboard is required. Each selection searches for one matching USB root partition and loads its kernel; failures return to the menu. The legacy kernel may replay the selected USB filesystem journal after an unclean shutdown.

Debian uses a writable root. Alpine uses a USB-backed read-only root with a temporary RAM overlay; **Alpine changes are lost on reboot**. Alpine provides a local `root` account with an empty password and does not install an SSH server. Keep the image off untrusted networks. Alpine 3.24.4's official x86 ISO and minirootfs are downloaded once and checked against pinned SHA-256 hashes. The Alpine packages used to build the root are installed offline from the verified ISO.

The menu-driven Debian and Alpine handoffs have not yet been verified on the Apple TV hardware.

## Validation

```sh
bash -n scripts/common.sh filesystem/*.sh image/build.sh
```

A Debian 12 image built from the legacy boot chain was reported to boot on first-generation Apple TV hardware. The exact hardware-tested build used a container-specific keyring and other temporary build fixes; the portable scripts should also be rebuilt and tested on target hardware. Automated installation is not implemented.
