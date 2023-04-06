#!/bin/bash

# (c) 2014-2015 Sam Nazarko
# email@samnazarko.co.uk

. funcs.sh
wd=$(pwd)
filestub="debian-appletv-filesystem"

check_platform
verify_action

update_sources
verify_action

# Install packages needed to build filesystem for building
install_package "debootstrap"
verify_action

# Configure the target directory
ARCH="i386"
DIR="$filestub/"
RLS="bullseye"

# Remove existing build
remove_existing_filesystem "{$wd}/{$DIR}"
verify_action
mkdir -p $DIR

# Debootstrap (foreign)
DEBOOTSTRAP_ARGS="--arch=${ARCH} --foreign ${RLS} ${DIR}"
DEBOOTSTRAP_ARGS="--variant=minbase ${DEBOOTSTRAP_ARGS}"
DEBOOTSTRAP_ARGS="--components main,contrib,non-free ${DEBOOTSTRAP_ARGS}"
fetch_filesystem "${DEBOOTSTRAP_ARGS}"
verify_action

# Configure filesystem (2nd stage)
configure_filesystem "${DIR}"
verify_action

# # Set up sources.list
echo "
deb http://deb.debian.org/debian $RLS main contrib non-free

deb http://deb.debian.org/debian/ $RLS-updates main contrib non-free

deb http://deb.debian.org/debian/ $RLS-backports main contrib non-free

deb http://deb.debian.org/debian-security $RLS-security main contrib non-free
" > ${DIR}/etc/apt/sources.list

# Performing chroot operation
chroot ${DIR} mount -t proc proc /proc
verify_action
echo -e "Updating sources"
chroot ${DIR} apt-get update
chroot ${DIR} apt-get full-upgrade -y
verify_action
chroot ${DIR} apt-get install -y linux-image-686 sudo ifupdown parted xz-utils vim openssh-server
verify_action

echo -e "Configuring environment"
echo -e "	* Adding user debian"
setup_debian_user ${DIR}
verify_action
echo -e "	* Setting hostname"
setup_hostname ${DIR}
verify_action
echo -e "	* Setting up hosts"
setup_hosts ${DIR}
verify_action
echo -e "	* Configuring fstab"
create_base_fstab ${DIR}
verify_action

# Perform filesystem cleanup
chroot ${DIR} umount /proc
cleanup_filesystem "${DIR}"

# Create filesystem tarball
create_fs_tarball "${DIR}" "${filestub}"
verify_action

echo -e "Build successful"
