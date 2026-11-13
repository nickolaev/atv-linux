# Debian on first-generation Apple TV

This project builds an i386 Debian 12 (Bookworm) disk image using the existing Apple TV legacy bootloader. Bookworm is oldstable/LTS, not current Debian stable. The image is a writable system for USB boot; it is not yet a multi-OS live environment or an installer.

## Build

Use a Debian-compatible Linux build host with a current Debian archive keyring. The build runs as root, installs host packages, creates loop devices and mounts filesystems. Run it in a dedicated VM or disposable build environment:

```sh
make
```

The output is `image/atv-linux.img`. The filesystem build creates `filesystem/debian-appletv-filesystem.tar.xz` and its checksum; an existing archive is reused. Run `make clean` only when those local build outputs may be removed.

The root partition is labeled `ATVTESTROOT`, so avoid attaching multiple copies at once. The legacy boot menu still assumes `(hd1,1)`; other disk orders have not been validated.

**Test image credentials:** the system creates a `debian` account with password `debian`, passwordless sudo, and an SSH server. Keep it off untrusted networks. Change credentials before any networked use; this image is not hardened for deployment.

## Validation

```sh
bash -n scripts/common.sh filesystem/*.sh image/build.sh
```

A Debian 12 image built from the legacy boot chain was reported to boot on first-generation Apple TV hardware. The exact hardware-tested build used a container-specific keyring and other temporary build fixes; the portable scripts should also be rebuilt and tested on target hardware. Multi-OS live boot and installation are not implemented.
