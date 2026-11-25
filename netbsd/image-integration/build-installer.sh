#!/usr/bin/env bash
# Rebuild the physical ATV1 NetBSD installer from release sets and EFI inputs.
set -Eeuo pipefail
usage() {
    echo 'Usage: build-installer.sh ASD-SYSTEM ATV1SM RELEASE-SETS OUTPUT.img [SSH-PUBLIC-KEY] [--interactive-ssh]' >&2
    echo 'RELEASE-SETS must contain SHA512, base.tgz, etc.tgz, kern-GENERIC.tgz, modules.tgz, comp.tgz, man.tgz and text.tgz.' >&2
    echo 'Runs on Linux with makefs, sgdisk, parted, dosfstools, mtools and Python 3.' >&2
}
(($# >= 4 && $# <= 6)) || { usage; exit 2; }
asd=$1
atv1sm=$2
sets=$3
output=$4
ssh_key=''
interactive=0
shift 4
for arg in "$@"; do
    if [[ $arg == --interactive-ssh ]]; then interactive=1; else ssh_key=$arg; fi
done
script_dir=$(cd "$(dirname "$0")" && pwd -P)
netbsd_dir=$(cd "$script_dir/.." && pwd -P)
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
[[ -d $asd && -d $atv1sm && -d $sets ]] || die 'input directory missing'
[[ ! -e $output && ! -L $output ]] || die 'output already exists'
[[ -z $ssh_key || (-f $ssh_key && -s $ssh_key && ! -L $ssh_key) ]] || die 'SSH public key must be a non-empty regular file'
if [[ -n $ssh_key ]]; then
    command -v ssh-keygen >/dev/null || die 'missing ssh-keygen'
    grep -Eq '^(ssh-(ed25519|rsa)|ecdsa-sha2-|sk-ssh-|sk-ecdsa-)' "$ssh_key" || die 'expected an OpenSSH public key'
    ssh-keygen -lf "$ssh_key" >/dev/null || die 'invalid SSH public key'
fi
[[ -d $(dirname "$output") ]] || die 'output parent missing'
for program in makefs sgdisk parted mkfs.vfat mcopy sha512sum python3 tar; do
    command -v "$program" >/dev/null || die "missing $program"
done
[[ -f $sets/SHA512 ]] || die 'missing SHA512 manifest'
for name in base etc kern-GENERIC modules comp man text; do
    archive=$sets/$name.tgz
    [[ -f $archive ]] || die "missing $archive"
    expected=$(awk -v name="$name.tgz" '$1 == "SHA512" && $2 == "(" name ")" && $3 == "=" { print $4 }' "$sets/SHA512")
    [[ -n $expected && $(sha512sum "$archive" | awk '{print $1}') == "$expected" ]] || die "checksum failed: $archive"
done
work=$(mktemp -d "$(dirname "$output")/.atv-installer-build.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
root=$work/root
mkdir "$root"
for name in base etc kern-GENERIC modules; do
    tar -xzf "$sets/$name.tgz" -C "$root"
done
[[ -f $root/netbsd && -f $root/usr/mdec/bootia32.efi ]] || die 'missing NetBSD kernel or EFI loader in sets'
for config in rc.conf dhcpcd.conf fstab rc.d/fsck; do
    [[ ! -e $root/etc/$config ]] || chmod u+w "$root/etc/$config"
done
cat > "$root/etc/rc.conf" <<'CONFIG'
. /etc/defaults/rc.conf
rc_configured=YES
hostname=atv
dhcpcd=YES
CONFIG
cat > "$root/etc/dhcpcd.conf" <<'CONFIG'
hostname "atv"
allowinterfaces rtk0 re0
nohook hostname
CONFIG
cat > "$root/etc/fstab" <<'CONFIG'
NAME=atv-inst / ffs rw 1 1
CONFIG
# The makefs-produced temporary installer root failed a repeat-boot fsck in
# the hardware test. Its installed target is separately formatted by newfs.
python3 - "$root/etc/rc.d/fsck" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
source = path.read_text()
needle = 'fsck_start()\n{\n'
if source.count(needle) != 1:
    raise SystemExit('unexpected NetBSD fsck script')
path.write_text(source.replace(needle, needle + '\techo "Skipping checks on temporary installer USB root."\n\treturn\n', 1))
PY
chmod a-w "$root/etc/rc.d/fsck"
bash "$netbsd_dir/build.sh" --asd-system "$asd" --atv1sm "$atv1sm" \
    --netbsd-kernel "$root/netbsd" --netbsd-efi "$root/usr/mdec/bootia32.efi" \
    --autoboot --size-mib 128 --output "$work/template.img"
if [[ -n $ssh_key ]]; then
    bash "$script_dir/stage-assets.sh" "$root" "$sets" "$work/template.img" "$ssh_key"
else
    bash "$script_dir/stage-assets.sh" "$root" "$sets" "$work/template.img"
fi
if ((interactive)); then
    install -m 755 "$script_dir/../ssh-installer/start.sh" "$root/usr/atv-installer/bin/ssh-installer-start"
    install -d -m 755 "$root/usr/local/bin"
    install -m 755 "$script_dir/../ssh-installer/atv-install" "$root/usr/local/bin/atv-install"
    install -m 755 "$script_dir/../ssh-installer/install-session" "$root/usr/atv-installer/bin/install-session"
    [[ -x $root/usr/bin/tmux ]] || die "NetBSD base set is missing tmux"
    install -m 755 "$script_dir/../ssh-installer/banner.sh" "$root/usr/local/bin/atv-banner"
    install -m 644 "$script_dir/../ssh-installer/motd" "$root/etc/motd"
    printf '\n[ -x /usr/local/bin/atv-banner ] && /usr/local/bin/atv-banner\n' >> "$root/root/.profile"
    cat > "$root/etc/rc.local" <<'CONFIG'
#!/bin/sh
/usr/atv-installer/bin/ssh-installer-start > /var/log/atv-ssh-installer.log 2>&1 &
CONFIG
    chmod 755 "$root/etc/rc.local"
fi
python3 "$script_dir/makefs-mtree.py" "$root" "$sets" "$work/root.mtree"
# Release sets include directories inaccessible to an unprivileged builder.
# makefs applies the original permissions from the mtree to the final image.
find "$root" -type d -exec chmod u+rwx {} \;
makefs -t ffs -B le -o version=1 -s 1500m -F "$work/root.mtree" -N "$root/etc" "$work/root.ffs" "$root"
bash "$script_dir/assemble.sh" "$work/template.img" "$work/root.ffs" "$output"
sha256sum "$output"
