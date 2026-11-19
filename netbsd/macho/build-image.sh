#!/usr/bin/env bash
# Package an experimental Mach-O diagnostic; this does not contain NetBSD.
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: bash netbsd/macho/build-image.sh --kernel MACHO --output NEW.img
       [--recovery DIR] [--image-mib N] [--recovery-mib N] [--check]

The recovery directory defaults to image/recovery in this repository and must
contain boot.efi and the System kext tree. --check only validates inputs.
Building requires Linux, root, parted, hfsprogs and loop-device access.
The output must be a new regular image file, not a physical device.
The image defaults to 64 MiB, with the original recovery partition ending at
32 MB. These options change
capacity only; the image remains a diagnostic and does not boot NetBSD.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
recovery=$script_dir/../../image/recovery
kernel='' output='' check=0 image_mib=64 recovery_mib=32 recovery_end=32M
while (($#)); do
    case "$1" in
        --kernel|--output|--recovery|--image-mib|--recovery-mib)
            (($# >= 2)) || die "missing value for $1"
            case "$1" in
                --kernel) kernel=$2 ;;
                --output) output=$2 ;;
                --recovery) recovery=$2 ;;
                --image-mib) image_mib=$2 ;;
                --recovery-mib) recovery_mib=$2; recovery_end=${2}MiB ;;
            esac
            shift 2 ;;
        --check) check=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

[[ -n $kernel && -n $output ]] || { usage >&2; die 'kernel and output are required'; }
[[ $image_mib =~ ^[1-9][0-9]{0,3}$ && $recovery_mib =~ ^[1-9][0-9]{0,3}$ ]] || die 'sizes must be whole MiB values between 1 and 9999'
((recovery_mib >= 16 && image_mib >= recovery_mib + 2)) || die 'recovery must be at least 16 MiB and image at least 2 MiB larger'
[[ -f $kernel && -s $kernel && ! -L $kernel ]] || die 'kernel must be a nonempty regular file, not a symlink'
[[ -f $recovery/boot.efi && -s $recovery/boot.efi && ! -L $recovery/boot.efi ]] || die 'missing regular recovery boot.efi'
for asset in BootLogo.png com.apple.Boot.plist; do
    [[ -f $recovery/$asset && -s $recovery/$asset && ! -L $recovery/$asset ]] || die "missing regular recovery $asset"
done
kext=$recovery/System/Library/Extensions/KernelMemoryAccess.kext/Contents
[[ -s $kext/Info.plist && -s $kext/MacOS/KernelMemoryAccess ]] || die 'missing KernelMemoryAccess kext'
invalid=$(find "$recovery/System" ! -type d ! -type f -print -quit) || die 'cannot inspect recovery System tree'
[[ -z $invalid ]] || die 'recovery System tree contains a symlink or special file'
[[ ! -e $output && ! -L $output ]] || die 'output already exists'
outdir=$(dirname -- "$output")
name=$(basename -- "$output")
[[ -d $outdir && $name != . && $name != .. ]] || die 'output parent must be an existing directory'
outdir=$(cd -- "$outdir" && pwd -P)
case "$outdir/" in /dev/*|/proc/*|/sys/*) die 'output must not be on a device or virtual filesystem' ;; esac
output=$outdir/$name
[[ ! -e $output && ! -L $output ]] || die 'output already exists'

if ((check)); then
    printf 'Input preflight passed; no image created. This diagnostic does not boot NetBSD.\n'
    exit 0
fi
[[ $(uname -s) == Linux ]] || die 'image creation requires Linux'
((EUID == 0)) || die 'image creation requires root for loop devices and mounts'
for cmd in parted losetup mkfs.hfsplus mount umount truncate cp find mktemp ln; do
    command -v "$cmd" >/dev/null || die "missing required command: $cmd"
done

work=$(mktemp -d "$outdir/.atv1-macho-build.XXXXXXXX")
image=$work/image
mountpoint=$work/mount
loop='' mounted=0
cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if ((mounted)) && ! umount "$mountpoint"; then
        printf 'error: could not unmount %s; retained %s and %s for manual cleanup\n' "$mountpoint" "$work" "$loop" >&2
        exit 1
    fi
    if [[ -n $loop ]] && ! losetup -d "$loop"; then
        printf 'error: could not detach %s; retained %s for manual cleanup\n' "$loop" "$work" >&2
        exit 1
    fi
    rm -f -- "$image"
    rmdir -- "$mountpoint" "$work" 2>/dev/null || true
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -- "$mountpoint"
truncate -s "${image_mib}M" "$image"
parted -s "$image" mklabel gpt
# Match the repository's existing Apple TV recovery partition layout.
parted -s "$image" mkpart primary hfs+ 40s "$recovery_end" name 1 recovery
parted -s "$image" set 1 atvrecv on
loop=$(losetup --find --partscan --show "$image")
part=${loop}p1
[[ -b $part ]] || die "partition device did not appear: $part"
mkfs.hfsplus "$part"
mount "$part" "$mountpoint"
mounted=1
cp -- "$recovery/boot.efi" "$mountpoint/boot.efi"
cp -- "$recovery/BootLogo.png" "$mountpoint/BootLogo.png"
cp -- "$recovery/com.apple.Boot.plist" "$mountpoint/com.apple.Boot.plist"
cp -- "$kernel" "$mountpoint/mach_kernel"
cp -R -- "$recovery/System" "$mountpoint/System"
umount "$mountpoint"
mounted=0
losetup -d "$loop"
loop=''
ln -- "$image" "$output" || die 'could not publish image without overwriting output'
printf 'Created %s (Mach-O diagnostic only; no NetBSD OS).\n' "$output"
