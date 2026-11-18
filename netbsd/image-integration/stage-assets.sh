#!/usr/bin/env bash
# Stage installer payloads into an offline NetBSD root tree.
set -Eeuo pipefail

if (($# != 3 && $# != 4)); then
    echo "Usage: $0 ROOT-DIRECTORY RELEASE-SETS-DIRECTORY EFI-TEMPLATE.img [SSH-PUBLIC-KEY]" >&2
    exit 2
fi
root=$1
sets=$2
template=$3
ssh_key=${4-}
script_dir=$(cd "$(dirname "$0")" && pwd -P)
destination=$root/usr/atv-installer
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
[[ -d $root && -d $sets && -f $template ]] || die 'missing input'
[[ -z $ssh_key || (-f $ssh_key && -s $ssh_key && ! -L $ssh_key) ]] || die 'invalid SSH public key'
if [[ -n $ssh_key ]]; then
    command -v ssh-keygen >/dev/null || die 'missing ssh-keygen'
    grep -Eq '^(ssh-(ed25519|rsa)|ecdsa-sha2-|sk-ssh-|sk-ecdsa-)' "$ssh_key" || die 'expected an OpenSSH public key'
    ssh-keygen -lf "$ssh_key" >/dev/null || die 'invalid SSH public key'
fi
[[ -f $script_dir/../maintenance-packages/provision.sh && -f $script_dir/../maintenance-packages/fetch-sources.sh ]] || die 'missing package provisioning scripts'
[[ ! -e $destination && ! -L $destination ]] || die 'installer assets already exist'
for name in SHA512 base.tgz etc.tgz kern-GENERIC.tgz modules.tgz; do
    [[ -f $sets/$name && ! -L $sets/$name ]] || die "missing release set $name"
done
for name in check-target.sh populate-root.sh install.sh startup.sh ready.sh; do
    [[ -f $script_dir/../installer/$name ]] || die "missing installer script $name"
done
command -v sgdisk >/dev/null || die 'missing sgdisk'
esp=$(sgdisk -i 1 "$template")
recovery=$(sgdisk -i 2 "$template")
[[ $esp == *'C12A7328-F81F-11D2-BA4B-00A0C93EC93B'* && $esp == *'First sector: 83968 '* && $esp == *'Last sector: 260095 '* ]] || die 'unexpected EFI partition layout'
[[ $recovery == *'5265636F-7665-11AA-AA11-00306543ECAC'* && $recovery == *'First sector: 2048 '* && $recovery == *'Last sector: 83967 '* ]] || die 'unexpected recovery partition layout'

mkdir -p "$root/usr"
work=$(mktemp -d "$root/usr/.atv-installer.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
mkdir "$work/sets" "$work/boot" "$work/bin"
for name in SHA512 base.tgz etc.tgz kern-GENERIC.tgz modules.tgz; do
    cp "$sets/$name" "$work/sets/$name"
done
for name in check-target.sh populate-root.sh install.sh startup.sh ready.sh; do
    cp "$script_dir/../installer/$name" "$work/bin/$name"
    chmod 755 "$work/bin/$name"
done
cp "$script_dir/../maintenance-packages/provision.sh" "$work/bin/provision.sh"
cp "$script_dir/../maintenance-packages/fetch-sources.sh" "$work/bin/fetch-sources.sh"
chmod 755 "$work/bin/provision.sh"
chmod 755 "$work/bin/fetch-sources.sh"
if [[ -n $ssh_key ]]; then
    cp "$ssh_key" "$work/authorized_keys"
    chmod 644 "$work/authorized_keys"
fi
dd if="$template" of="$work/boot/recovery.fat" bs=512 skip=2048 count=81920 status=none
dd if="$template" of="$work/boot/efi.fat" bs=512 skip=83968 count=176128 status=none
(cd "$work/boot" && sha512sum recovery.fat efi.fat > SHA512)
mv "$work" "$destination"
cat > "$root/etc/rc.local" <<'CONFIG'
#!/bin/sh
/usr/atv-installer/bin/startup.sh >/var/log/atv-installer-startup.log 2>&1 &
CONFIG
chmod 755 "$root/etc/rc.local"
printf 'Staged installer inputs in %s\n' "$destination"
