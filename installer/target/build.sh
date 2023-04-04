# (c) 2014-2015 Sam Nazarko
# email@samnazarko.co.uk

#!/bin/bash

. ../../scripts/common.sh

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
#	install_package $package
#	verify_action
done

if [ ! -f filesystem.tar.xz ]
then
	pushd ../../filesystem/osmc-${1}-filesystem/
	make clean
	make
	popd
fi

date=$(date +%Y%m%d)
yes | cp ../../filesystem/osmc-${1}-filesystem/osmc-${1}-filesystem-${date}.tar.xz filesystem.tar.xz

if [ ! -f filesystem.tar.xz ]; then echo -e "No filesystem available for target" && exit 1; fi
echo -e "Building disk image"

size=2048
disk=OSMC_TGT_${1}_${date}.img
dd if=/dev/zero of=${disk} bs=1M count=${size}
parted -a optimal -s ${disk} mklabel gpt
parted -a optimal -s ${disk} mkpart primary hfs+ 1 33 name 1 recovery
parted -a optimal -s ${disk} set 1 atvrecv on
parted -a optimal -s ${disk} mkpart primary ext2 33 289 name 2 boot
parted -a optimal -s ${disk} mkpart primary ext4 289 100% name 3 root

# Make file systems on partitions
LOOPDEV=$(losetup --find --partscan --show ${disk})
/sbin/partprobe "${LOOPDEV}"
mkfs.hfsplus "${LOOPDEV}p1"
verify_action
mkfs.ext2 "${LOOPDEV}p2"
verify_action
mkfs.ext4 "${LOOPDEV}p3"
verify_action

# Mount partitions
mkdir -p mnt/recovery mnt/boot mnt/root
mount "${LOOPDEV}p1" mnt/recovery
mount "${LOOPDEV}p2" mnt/boot
mount "${LOOPDEV}p3" mnt/root

echo -e "Installing AppleTV files"
cp recovery/com.apple.Boot.plist mnt/recovery
sed -e "s:BOOTFLAGS:console=tty1 root=/dev/ram0 quiet init=/init loglevel=2 video=vesafb intel_idle.max_cstate=1 processor.max_cstate=2 nohpet:" -i mnt/recovery/com.apple.Boot.plist
cp recovery/BootLogo.png mnt/recovery
cp recovery/boot.efi mnt/recovery
# cp recovery/System mnt/recovery
cp recovery/mach_kernel mnt/recovery

echo -e "Installing filesystem"
tar -xJf filesystem.tar.xz -C mnt/root

echo -e "Installing kernel"
cp mnt/root/boot/vmlinuz* mnt/boot/vmlinuz
cp mnt/root/boot/initrd.img* mnt/boot/initrd.img
cp recovery/menu.lst mnt/boot
sync

# Unmount partitions and detach loop device
umount mnt/recovery
umount mnt/boot
umount mnt/root
losetup -d "${LOOPDEV}"

echo -e "Build completed"
