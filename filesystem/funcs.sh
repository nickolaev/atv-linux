# (c) 2014-2015 Sam Nazarko
# email@samnazarko.co.uk

#!/bin/bash

. ../scripts/common.sh

function setup_osmc_user()
{
	# Sets user and password to 'osmc'
	chroot ${1} useradd -p \$y\$j9T\$YO0bsdRQoKHvOxZPFBn5q/\$D5DzjNAvfOy.ftwO5IE2FkbrZNsC2DtiNZO9Q5.9UF1 debian -k /etc/skel -d /home/debian -m -s /bin/bash
	# Locks root
	chroot ${1} passwd -l root
	# Makes 'osmc' username and password never expire
	chroot ${1} chage -I -1 -m 0 -M 99999 -E -1 osmc
	# Adds 'osmc' to sudoers with no password prompt
	mkdir -p ${1}/etc/sudoers.d
	echo "osmc     ALL= NOPASSWD: ALL" >${1}/etc/sudoers.d/osmc-no-sudo-password
	echo "Defaults        !secure_path" >${1}/etc/sudoers.d/osmc-no-secure-path
	chmod 0440 ${1}/etc/sudoers.d/osmc-no-sudo-password
	chmod 0440 ${1}/etc/sudoers.d/osmc-no-secure-path
	# Groups for permissions
	chroot ${1} usermod -G disk,cdrom,lp,dialout,video,audio,adm osmc
	# Default storage directories
	directories=( "Pictures" "Music" "Movies" "TV Shows" )
	for dir in "${directories[@]}"
	do
	mkdir -p "${1}/home/osmc/${dir}"
	done
	chroot ${1} chown -R osmc:osmc /home/osmc/
}

function setup_hostname()
{
	echo "appletv" > ${1}/etc/hostname
}

function setup_hosts()
{
	echo "::1             appletv localhost6.localdomain6 localhost6
127.0.1.1       appletv


127.0.0.1       localhost
::1             localhost ip6-localhost ip6-loopback
fe00::0         ip6-localnet
ff00::0         ip6-mcastprefix
ff02::1         ip6-allnodes
ff02::2         ip6-allrouters">${1}/etc/hosts
}

function create_fs_tarball()
{
	echo -e "Creating filesystem tarball"
	pushd ${1}
	tar -cf - * | xz -9 -c - > ../${2}-$(date +%Y%m%d).tar.xz
	echo $(md5sum ../${2}-$(date +%Y%m%d).tar.xz | cut -f 1 -d ' ') filesystem.tar.xz > ../${2}-$(date +%Y%m%d).md5
	popd
	rm -rf ${1}
}

function create_base_fstab()
{
	>${1}/etc/fstab
}

export -f setup_osmc_user
export -f setup_hostname
export -f setup_hosts
export -f create_fs_tarball
export -f create_base_fstab