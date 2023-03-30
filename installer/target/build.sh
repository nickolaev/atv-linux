# (c) 2014-2015 Sam Nazarko
# email@samnazarko.co.uk

#!/bin/bash

. ../../scripts/common.sh

echo -e "Building target side installer"
BUILDROOT_VERSION="2014.05"

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
libssl-dev"

if true 
then
	packages="$packages gcc-9 g++-9"
fi

if [ "$1" == "appletv" ]
then
   packages="hfsprogs $packages"
fi

for package in $packages
do
	install_package $package
	verify_action
done

SIGN_KERNEL=0

if [ "$SIGN_KERNEL" -eq 1 ]
        then
                SIG_FILE_AES="/etc/osmc/kernelaes"
                SIG_FILE_AESIV="/etc/osmc/kernelaesiv"
                SIG_FILE_KERNELKEY="/etc/osmc/kernelkey.pem"
                if [ ! -f $SIG_FILE_AES ] || [ ! -f $SIG_FILES_AESIV ] || [ ! -f $SIG_FILE_KERNELKEY ]; then echo "Missing files needed for encrypting kernel image" && exit 1; fi
        fi

pushd ../../filesystem/osmc-${1}-filesystem/
make clean
make
date=$(date +%Y%m%d)
popd
yes | cp ../../filesystem/osmc-${1}-filesystem/osmc-${1}-filesystem-${date}.tar.xz filesystem.tar.xz

if [ -d buildroot-${BUILDROOT_VERSION} ]
then
	echo -e "Using local buildroot"
else
	echo -e "Downloading buildroot ${BUILDROOT_VERSION}"
	pull_source "https://buildroot.uclibc.org/downloads/buildroot-${BUILDROOT_VERSION}.tar.gz" "."
	verify_action
	pushd buildroot-${BUILDROOT_VERSION}
	install_patch "../patches" "all"
	install_patch "../patches" "$1"
	if [ "$SIGN_KERNEL" -eq 1 ]
	then
		install_patch "../patches" "signed-${1}"
	fi
	if [ "$1" == "rbp2" ] || [ "$1" == "rbp4" ]
	then
		install_patch "../patches" "rbp"
		sed s/rpi-firmware/rpi-firmware-osmc/ -i package/Config.in # Use our own firmware package
		echo "dwc_otg.fiq_fix_enable=1 sdhci-bcm2708.sync_after_dma=0 dwc_otg.lpm_enable=0 console=tty1 root=/dev/ram0 quiet init=/init loglevel=2 osmcdev=${1}" > package/rpi-firmware-osmc/cmdline.txt
	fi
	HOSTCC=gcc-9 HOSTCXX=g++-9 make osmc_defconfig
	HOSTCC=gcc-9 HOSTCXX=g++-9 make
	if [ $? != 0 ]; then echo "Build failed" && exit 1; fi
	popd
	wget -O buildroot-${BUILDROOT_VERSION}.tar.gz https://buildroot.uclibc.org/downloads/buildroot-${BUILDROOT_VERSION}.tar.gz
fi

pushd buildroot-${BUILDROOT_VERSION}/output/images
if [ -f ../../../filesystem.tar.xz ]
then
    echo -e "Using local filesystem"
else
    echo -e "Downloading latest filesystem"
    date=$(date +%Y%m%d)
    count=150
    while [ $count -gt 0 ]; do wget --spider -q ${DOWNLOAD_URL}/filesystems/osmc-${1}-filesystem-${date}.tar.xz
           if [ "$?" -eq 0 ]; then
	        wget ${DOWNLOAD_URL}/filesystems/osmc-${1}-filesystem-${date}.tar.xz -O $(pwd)/../../../filesystem.tar.xz
		wget ${DOWNLOAD_URL}/filesystems/osmc-${1}-filesystem-${date}.md5 -O $(pwd)/../../../filesystem.md5
                break
           fi
           date=$(date +%Y%m%d --date "yesterday $date")
           let count=count-1
    done
fi
if [ ! -f ../../../filesystem.tar.xz ]; then echo -e "No filesystem available for target" && exit 1; fi
echo -e "Building disk image"

if [ "$1" == "appletv" ]
then
	size=320
	date=$(date +%Y%m%d)
	dd if=/dev/zero of=OSMC_TGT_${1}_${date}.img bs=1M count=${size}
	parted -s OSMC_TGT_${1}_${date}.img mklabel gpt
	parted -s OSMC_TGT_${1}_${date}.img mkpart primary hfs+ 40s 256M
	parted -s OSMC_TGT_${1}_${date}.img set 1 atvrecv on
	kpartx -a OSMC_TGT_${1}_${date}.img
	/sbin/partprobe
	mkfs.hfsplus /dev/mapper/loop0p1
	mount /dev/mapper/loop0p1 /mnt

	echo -e "Installing AppleTV files"
	mv com.apple.Boot.plist /mnt
	sed -e "s:BOOTFLAGS:console=tty1 root=/dev/ram0 quiet init=/init loglevel=2 osmcdev=atv video=vesafb intel_idle.max_cstate=1 processor.max_cstate=2 nohpet:" -i /mnt/com.apple.Boot.plist
	mv BootLogo.png /mnt
	mv boot.efi /mnt
	mv System /mnt
	echo -e "Building mach_kernel" # Had to be done after kernel image was built
	mv bzImage ../build/atv-bootloader-master/vmlinuz
	pushd ../build/atv-bootloader-master
	make
	popd
	mv ../build/atv-bootloader-master/mach_kernel /mnt
fi
echo -e "Installing filesystem"
mv $(pwd)/../../../filesystem.tar.xz /mnt/
umount /mnt
sync
kpartx -d OSMC_TGT_${1}_${date}.img
echo -e "Compressing image"
gzip OSMC_TGT_${1}_${date}.img
md5sum OSMC_TGT_${1}_${date}.img.gz > OSMC_TGT_${1}_${date}.md5
popd
echo -e "Build completed"
