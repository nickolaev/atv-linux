#!/bin/sh
# Configure a temporary interactive installer account on the USB system only.
set -eu
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH

password_hash=$(pwhash netbsd)
usermod -p "$password_hash" root
if [ -s /usr/atv-installer/authorized_keys ]; then
    mkdir -p /root/.ssh
    cp /usr/atv-installer/authorized_keys /root/.ssh/authorized_keys
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/authorized_keys
fi
mount -t ptyfs ptyfs /dev/pts
config=/etc/ssh/sshd_config
{ echo 'PermitRootLogin yes'; echo 'PasswordAuthentication yes'; cat "$config"; } > "$config.atv"
chmod 600 "$config.atv"
mv "$config.atv" "$config"
ssh-keygen -A
/usr/sbin/sshd
echo 'SSH installer ready. Log in as root and run sysinst or the Apple TV installer.'
