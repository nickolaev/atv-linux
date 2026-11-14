#!/bin/bash
set -e

# (c) 2014-2015 Sam Nazarko
# email@samnazarko.co.uk

. ../scripts/common.sh

echo -e "Installing dependencies"
update_sources
verify_action
packages="build-essential
rsync
texinfo
libncurses5-dev
whois
bc
kpartx
dosfstools
parted
cpio
python3
curl
ca-certificates
xorriso
python-is-python3
bison
flex
libssl-dev
hfsprogs"

for package in $packages
do
	echo -e "Installing $package"
	install_package $package
	verify_action
done

if [ ! -f ../filesystem/debian-appletv-filesystem.tar.xz ]
then
	pushd ../filesystem/
	make clean
	make
	popd
fi

if [ ! -f ../filesystem/alpine-3.24.4-x86.tar ]; then
    bash ../filesystem/alpine/build.sh
fi

echo -e "Building disk image"

size=3800
disk=atv-linux.img
dd if=/dev/zero of=${disk} bs=1M count=${size}
parted -a optimal -s ${disk} mklabel gpt
parted -a optimal -s ${disk} mkpart primary hfs+ 40s 32M name 1 recovery
parted -a optimal -s ${disk} set 1 atvrecv on
# parted -a optimal -s ${disk} mkpart primary ext2 32M 256M name 2 boot
parted -a optimal -s ${disk} mkpart primary ext3 32M 2800M name 2 root
parted -a optimal -s ${disk} mkpart primary ext3 2800M 100% name 3 alpine

# Make file systems on partitions
LOOPDEV=$(losetup --find --partscan --show ${disk})
recovery_mounted=0
root_mounted=0
alpine_mounted=0
cleanup_build() {
    if [ "$recovery_mounted" -eq 1 ]; then umount mnt/recovery || true; fi
    if [ "$root_mounted" -eq 1 ]; then umount mnt/root || true; fi
    if [ "$alpine_mounted" -eq 1 ]; then umount mnt/alpine || true; fi
    if [ -n "$LOOPDEV" ]; then losetup -d "$LOOPDEV" || true; fi
}
trap cleanup_build EXIT
/sbin/partprobe "${LOOPDEV}"
for part in 1 2 3; do
    node="${LOOPDEV}p${part}"
    if [ ! -b "$node" ]; then
        numbers=$(cat "/sys/class/block/$(basename "$node")/dev")
        mknod "$node" b "${numbers%:*}" "${numbers#*:}"
    fi
done
mkfs.hfsplus "${LOOPDEV}p1"
# verify_action
# mkfs.ext2 "${LOOPDEV}p2"
verify_action
mkfs.ext3 -L ATVTESTROOT "${LOOPDEV}p2"
verify_action
mkfs.ext3 -L ATVALPINE "${LOOPDEV}p3"
verify_action

# Mount partitions
mkdir -p mnt/recovery mnt/boot mnt/root mnt/alpine
mount "${LOOPDEV}p1" mnt/recovery
recovery_mounted=1
# mount "${LOOPDEV}p2" mnt/boot
mount "${LOOPDEV}p2" mnt/root
root_mounted=1
mount "${LOOPDEV}p3" mnt/alpine
alpine_mounted=1

echo -e "Installing AppleTV files"
cp recovery/com.apple.Boot.plist mnt/recovery
# sed -e "s:BOOTFLAGS:console=tty1 root=/dev/ram0 quiet init=/init loglevel=2 video=vesafb intel_idle.max_cstate=1 processor.max_cstate=2 nohpet:" -i mnt/recovery/com.apple.Boot.plist
cp recovery/BootLogo.png mnt/recovery
cp recovery/boot.efi mnt/recovery
python3 embed_boot_menu.py recovery/mach_kernel recovery/boot-menu.sh mnt/recovery/mach_kernel
cp -r recovery/System mnt/recovery

echo -e "Installing filesystem"
tar -xJf ../filesystem/debian-appletv-filesystem.tar.xz -C mnt/root
cp ../filesystem/debian-appletv-filesystem.tar.xz mnt/root/debian-rootfs.tar.xz

echo -e "Installing Alpine filesystem"
tar -xf ../filesystem/alpine-3.24.4-x86.tar -C mnt/alpine

echo -e "Installing kernel"
# cp mnt/root/boot/vmlinuz* mnt/boot/vmlinuz
# cp mnt/root/boot/initrd.img* mnt/boot/initrd.img
mkdir mnt/root/boot/grub
cp recovery/menu.lst mnt/root/boot/grub
cp recovery/eth0 mnt/root/etc/network/interfaces.d/eth0

# Unmount partitions and detach loop device
umount mnt/alpine
alpine_mounted=0
umount mnt/recovery
recovery_mounted=0
umount mnt/root
root_mounted=0
fsck -fy "${LOOPDEV}p1" || [ $? -eq 1 ]
fsck -fy "${LOOPDEV}p2" || [ $? -eq 1 ]
fsck -fy "${LOOPDEV}p3" || [ $? -eq 1 ]
parted -s ${disk} print
losetup -d "${LOOPDEV}"
LOOPDEV=""
rm -rf mnt

echo -e "Build completed"
