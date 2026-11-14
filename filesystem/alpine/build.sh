#!/bin/bash
# Build the Alpine 3.24 x86 USB-backed root from verified upstream artifacts.
set -euo pipefail
version=3.24.4
base_url="https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86"
iso="alpine-standard-${version}-x86.iso"
miniroot="alpine-minirootfs-${version}-x86.tar.gz"
iso_hash=426bf774f9b311e2c86839fdc482242a74be841d6f70c55f87ea86af998488b2
root_hash=df793865bf166c10acaad3a4d5d40498f9ee3f89fa405d39c7f540464fb3b0c1
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cache="$script_dir/cache"
output="$script_dir/../alpine-${version}-x86.tar"
work=$(mktemp -d)
tmp_output="${output}.tmp.$$"
trap 'rm -rf -- "$work"; rm -f -- "$tmp_output"' EXIT
mkdir -p "$cache"
fetch() {
    local name=$1 hash=$2
    if [ -f "$cache/$name" ] && printf '%s  %s\n' "$hash" "$cache/$name" | sha256sum -c --status; then return; fi
    echo "Downloading $name"
    curl -fsSL --retry 3 -o "$work/$name" "$base_url/$name"
    printf '%s  %s\n' "$hash" "$work/$name" | sha256sum -c --status || { echo "Checksum mismatch: $name" >&2; return 1; }
    mv -f -- "$work/$name" "$cache/$name"
}
fetch "$iso" "$iso_hash"
fetch "$miniroot" "$root_hash"
root="$work/root"
mkdir -p "$root"
tar -xzf "$cache/$miniroot" -C "$root"
mkdir -p "$root/opt" "$root/boot" "$root/dev"
xorriso -osirrox on -indev "$cache/$iso" \
    -extract /apks "$root/opt/alpine-apks" \
    -extract /boot/vmlinuz-lts "$root/boot/vmlinuz-lts" \
    -extract /boot/initramfs-lts "$root/boot/initramfs-lts" \
    -extract /boot/modloop-lts "$root/boot/modloop-lts"
for path in opt/alpine-apks/x86/APKINDEX.tar.gz boot/vmlinuz-lts boot/initramfs-lts boot/modloop-lts; do
    [ -f "$root/$path" ] || { echo "Missing Alpine payload: $path" >&2; exit 1; }
done
# The minirootfs has no device nodes. apk and its scripts require these.
mknod -m 666 "$root/dev/null" c 1 3
mknod -m 666 "$root/dev/urandom" c 1 9
# APK verifies packages with the keys from the pinned Alpine minirootfs.
chroot "$root" /sbin/apk --no-network --repositories-file /dev/null \
    --repository /opt/alpine-apks add alpine-base ifupdown-ng dhcpcd
for service in devfs dmesg mdev modloop hwdrivers; do
    chroot "$root" /sbin/rc-update add "$service" sysinit
done
for service in modules sysctl hostname bootmisc syslog networking; do
    chroot "$root" /sbin/rc-update add "$service" boot
done
for service in mount-ro killprocs; do
    chroot "$root" /sbin/rc-update add "$service" shutdown
done
# Keep the module image read-only; avoid a RAM-heavy depmod pass.
sed -i 's/^overlay_size=.*/overlay_size=/' "$root/etc/conf.d/modloop"

# Match local live-media login; no SSH server is installed.
chroot "$root" /usr/bin/passwd -d root
printf 'alpine-atv\n' > "$root/etc/hostname"
cat > "$root/etc/network/interfaces" <<'NET'
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
NET
sed -i '1i/opt/alpine-apks' "$root/etc/apk/repositories"
printf '\nttyS0::respawn:/sbin/getty -L 115200 ttyS0 vt100\n' >> "$root/etc/inittab"
tar -C "$root" -cf "$tmp_output" .
mv -f -- "$tmp_output" "$output"
echo "Alpine root built: $output"
