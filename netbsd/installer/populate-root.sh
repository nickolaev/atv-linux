#!/bin/sh
# Populate an already mounted, newly formatted NetBSD root filesystem.
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
    echo 'usage: populate-root.sh MOUNTPOINT SETS-DIRECTORY [SSH-PUBLIC-KEY [ACCOUNT-FILE]]' >&2
    exit 2
fi
root=$1
sets=$2
ssh_key=${3-}
account_file=${4-}
bindir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
[ -f "$bindir/ready.sh" ] || { echo 'missing installed-system reporter' >&2; exit 1; }
[ -f "$bindir/provision.sh" ] || { echo 'missing package provisioning script' >&2; exit 1; }
[ -d "$root" ] && [ -d "$sets" ] || { echo 'missing root or sets directory' >&2; exit 1; }
root=$(cd "$root" && pwd -P)
case "$root" in *' '*) echo 'mountpoint cannot contain spaces' >&2; exit 1 ;; esac
mounts=$(mount) || { echo 'cannot inspect mounted filesystems' >&2; exit 1; }
printf '%s\n' "$mounts" | awk -v root="$root" '$2 == "on" && $3 == root && $4 == "type" && $5 == "ffs" { found = 1 } END { exit !found }' || {
    echo 'target must be a mounted FFS filesystem' >&2
    exit 1
}
# Refuse the running system and nonempty staging directories.
[ "$root" != / ] && [ -z "$(ls -A "$root")" ] || {
    echo 'target root must be an empty mounted filesystem' >&2
    exit 1
}
for set in base etc kern-GENERIC modules; do
    [ -f "$sets/$set.tgz" ] || { echo "missing $set.tgz" >&2; exit 1; }
done
[ -f "$sets/SHA512" ] || { echo 'missing SHA512 manifest' >&2; exit 1; }
for set in base etc kern-GENERIC modules; do
    echo "Verifying $set.tgz"
    expected=$(awk -v file="$set.tgz" '$1 == "SHA512" && $2 == "(" file ")" && $3 == "=" {print $4}' "$sets/SHA512")
    actual=$(sha512 -q "$sets/$set.tgz")
    [ -n "$expected" ] && [ "$actual" = "$expected" ] || {
        echo "checksum failed: $set.tgz" >&2
        exit 1
    }
done
for set in base etc kern-GENERIC modules; do
    echo "Extracting $set.tgz"
    tar -xzpf "$sets/$set.tgz" -C "$root"
done
cat > "$root/etc/rc.conf" <<'CONFIG'
. /etc/defaults/rc.conf
rc_configured=YES
hostname=atv
dhcpcd=YES
CONFIG
cat > "$root/etc/dhcpcd.conf" <<'CONFIG'
hostname "atv"
allowinterfaces rtk0
nohook hostname
CONFIG
cat > "$root/etc/fstab" <<'CONFIG'
NAME=atv-root / ffs rw 1 1
NAME=atv-swap none swap sw 0 0
CONFIG
mkdir -p "$root/usr/local/sbin"
cp "$bindir/ready.sh" "$root/usr/local/sbin/atv-ready"
chmod 755 "$root/usr/local/sbin/atv-ready"
cp "$bindir/provision.sh" "$root/usr/local/sbin/atv-provision-packages"
chmod 755 "$root/usr/local/sbin/atv-provision-packages"
if [ -n "$account_file" ]; then
    [ -s "$account_file" ] || { echo 'missing administrator account file' >&2; exit 1; }
    username=$(sed -n '1p' "$account_file")
    password_hash=$(sed -n '2p' "$account_file")
    root_hash=$(sed -n '3p' "$account_file")
    case "$username" in ''|root|*[!a-z0-9_-]*|[!a-z]*) echo 'invalid administrator name' >&2; exit 1 ;; esac
    [ "${#username}" -le 16 ] && [ -n "$password_hash" ] && [ -n "$root_hash" ] || { echo 'invalid administrator credentials' >&2; exit 1; }
    chroot "$root" /usr/sbin/useradd -m -G wheel -s /bin/sh -p "$password_hash" "$username"
    chroot "$root" /usr/sbin/usermod -F "$username"
    chroot "$root" /usr/sbin/usermod -p "$root_hash" root
    unset password_hash root_hash
    echo 'sshd=YES' >> "$root/etc/rc.conf"
fi
if [ -n "$ssh_key" ] && [ -s "$ssh_key" ]; then
    mkdir -p "$root/root/.ssh"
    chmod 700 "$root/root/.ssh"
    cp "$ssh_key" "$root/root/.ssh/authorized_keys"
    chmod 600 "$root/root/.ssh/authorized_keys"
    chown -R 0:0 "$root/root/.ssh"
    config="$root/etc/ssh/sshd_config"
    {
        echo 'PermitRootLogin prohibit-password'
        awk 'tolower($1) != "permitrootlogin" {print}' "$config"
    } > "$config.atv-new"
    chmod 600 "$config.atv-new"
    mv "$config.atv-new" "$config"
    [ -n "$account_file" ] || echo 'sshd=YES' >> "$root/etc/rc.conf"
fi
cat > "$root/etc/rc.local" <<'CONFIG'
#!/bin/sh
/usr/local/sbin/atv-ready >/var/log/atv-ready.log 2>&1 &
CONFIG
chmod 755 "$root/etc/rc.local"
# Distribution sets provide MAKEDEV; disk wedges need devices available early.
(cd "$root/dev" && sh MAKEDEV all)
echo 'Root populated. Boot chain and on-disk installation still require verification.'
