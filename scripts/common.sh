#!/bin/bash

# (c) 2014-2015 Sam Nazarko
# email@samnazarko.co.uk

function check_platform()
{
    if grep -q "debian" /etc/os-release
    then
       return 0
    else
       return 1
    fi
}

function verify_action()
{
	code=$?
	if [ $code != 0 ]; then echo -e "Exiting build with return code ${code}" && exit 1; fi
}

function update_sources()
{
	echo -e "Updating sources"
	apt-get update > /dev/null 2>&1
	if [ $? != 0 ]; then echo -e "Failed to update sources" && return 1; else echo -e "Sources updated successfully" && return 0; fi
}

function install_package()
{
	echo -e "Installing package ${1}..."
	# Check if our package is installed
	# Although this may seem duplicated in handle_dep. handle_dep is used for packages only, where as installers/ and other parts will call this function directly. handle_dep purely exists to tell us when we need to build first or add an apt repo.
	if dpkg-query -W -f='${Status}' "${1}" 2>/dev/null | grep -q "ok installed" >/dev/null 2>&1
	then
		echo -e "Package already installed."
	else
	if [ ! -z "$2" ]
	then
		if [ "$2" -eq 1 ]; then EMD=$(find /usr/lib | grep libeatmydata | tail -n 1); fi
	fi
	LD_PRELOAD=${EMD} apt-get -y --no-install-recommends install $1
		if [ $? != 0 ]; then echo -e "Failed to install" && return 1; else echo -e "Package installed successfully" && return 0; fi
	fi
}

function fetch_filesystem()
{
	echo -e "Fetching base filesystem for building target\nPlease be patient"
	debootstrap $1
	if [ $? == 0 ]
	then
	echo -e "Filesystem base install successful"
	return 0
	else
	echo -e "Filesystem base install failed"
	return 1
	fi
}

function configure_filesystem()
{
	echo -e "Configuring filesystem\nPlease be patient"
	chroot $1 /debootstrap/debootstrap --second-stage
	if [ $? == 0 ]
	then
	echo -e "Filesystem configured successfully"
	return 0
	else
	echo -e "Filesystem configuration failed"
	fi
}

function cleanup_filesystem()
{
	echo -e "Cleaning up filesystem"
	# rm -f ${1}/etc/resolv.conf
	# rm -f ${1}/etc/network/interfaces
	rm -rf ${1}/usr/share/man/*
	rm -rf ${1}/var/lib/apt/lists/*
	rm -f ${1}/var/log/*.log
	rm -f ${1}/var/log/apt/*.log
	rm -f ${1}/tmp/reboot-needed
	chroot ${1} apt-get clean
}

function remove_existing_filesystem()
{
	if [ -d "$1" ]; then echo -e "Removing old filesystem" && rm -rf "$1"; fi
}

export -f check_platform
export -f verify_action
export -f update_sources
export -f install_package
export -f fetch_filesystem
export -f cleanup_filesystem
export -f remove_existing_filesystem
