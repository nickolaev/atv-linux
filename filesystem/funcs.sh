#!/bin/bash

# (c) 2014-2015 Sam Nazarko
# email@samnazarko.co.uk

. ../scripts/common.sh

function setup_debian_user()
{
	# Sets user and password to 'debian'
	chroot ${1} useradd -p $(openssl passwd -1 debian) debian -k /etc/skel -d /home/debian -m -s /bin/bash
	# Locks root
	chroot ${1} passwd -l root
	# Makes 'debian' username and password never expire
	chroot ${1} chage -I -1 -m 0 -M 99999 -E -1 debian
	# Adds 'debian' to sudoers with no password prompt
	mkdir -p ${1}/etc/sudoers.d
	echo "debian     ALL= NOPASSWD: ALL" >${1}/etc/sudoers.d/debian-no-sudo-password
	echo "Defaults        !secure_path" >${1}/etc/sudoers.d/debian-no-secure-path
	chmod 0440 ${1}/etc/sudoers.d/debian-no-sudo-password
	chmod 0440 ${1}/etc/sudoers.d/debian-no-secure-path
	# Groups for permissions
	chroot ${1} usermod -G disk,cdrom,lp,dialout,video,audio,adm debian

	chroot ${1} chown -R debian:debian /home/debian/
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
    local root=$1 name=$2
    if ! (set -o pipefail; cd "$root" && tar -cf - . | xz -9 -c > "../${name}.tar.xz"); then
        rm -f "${name}.tar.xz"
        return 1
    fi
    md5sum "${name}.tar.xz" > "${name}.md5" || return 1
    rm -rf -- "$root"
}

function create_base_fstab()
{
	>${1}/etc/fstab
}

export -f setup_debian_user
export -f setup_hostname
export -f setup_hosts
export -f create_fs_tarball
export -f create_base_fstab