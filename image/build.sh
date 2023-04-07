#!/bin/bash

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

if [ ! -f filesystem.tar.xz ]
then
	pushd ../filesystem/
	make clean
	make
	popd
fi

echo -e "Building disk image"

size=3800
disk=atv-linux.img
dd if=/dev/zero of=${disk} bs=1M count=${size}
parted -a optimal -s ${disk} mklabel gpt
parted -a optimal -s ${disk} mkpart primary hfs+ 40s 32M name 1 recovery
parted -a optimal -s ${disk} set 1 atvrecv on
# parted -a optimal -s ${disk} mkpart primary ext2 32M 256M name 2 boot
parted -a optimal -s ${disk} mkpart primary ext3 32M 100% name 3 root

# Make file systems on partitions
LOOPDEV=$(losetup --find --partscan --show ${disk})
/sbin/partprobe "${LOOPDEV}"
mkfs.hfsplus "${LOOPDEV}p1"
# verify_action
# mkfs.ext2 "${LOOPDEV}p2"
verify_action
mkfs.ext3 "${LOOPDEV}p2"
verify_action

# Mount partitions
mkdir -p mnt/recovery mnt/boot mnt/root
mount "${LOOPDEV}p1" mnt/recovery
# mount "${LOOPDEV}p2" mnt/boot
mount "${LOOPDEV}p2" mnt/root

echo -e "Installing AppleTV files"
cp recovery/com.apple.Boot.plist mnt/recovery
# sed -e "s:BOOTFLAGS:console=tty1 root=/dev/ram0 quiet init=/init loglevel=2 video=vesafb intel_idle.max_cstate=1 processor.max_cstate=2 nohpet:" -i mnt/recovery/com.apple.Boot.plist
cp recovery/BootLogo.png mnt/recovery
cp recovery/boot.efi mnt/recovery
cp recovery/mach_kernel mnt/recovery
cp -r recovery/System mnt/recovery

echo -e "Installing filesystem"
tar -xJf ../filesystem/debian-appletv-filesystem.tar.xz -C mnt/root
cp ../filesystem/debian-appletv-filesystem.tar.xz mnt/root/debian-rootfs.tar.xz

echo -e "Installing kernel"
# cp mnt/root/boot/vmlinuz* mnt/boot/vmlinuz
# cp mnt/root/boot/initrd.img* mnt/boot/initrd.img
mkdir mnt/root/boot/grub
cp recovery/menu.lst mnt/root/boot/grub
cp recovery/eth0 mnt/root/etc/network/interfaces.d/eth0

# Unmount partitions and detach loop device
umount mnt/recovery
umount mnt/boot
umount mnt/root
fsck -fy "${LOOPDEV}p1"
fsck -fy "${LOOPDEV}p2"
# fsck -fy "${LOOPDEV}p3"
parted -s ${disk} print
losetup -d "${LOOPDEV}"
rm -rf mnt

echo -e "Build completed"
