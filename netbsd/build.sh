#!/usr/bin/env bash
# Build only the ATV1sm/rEFInd hardware-gate image; it contains no NetBSD OS.
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: bash netbsd/build.sh --asd-system DIR --atv1sm DIR --output NEW.img
                            [--size-mib N] [--check]

DIR arguments are the extracted Apple diagnostic System directory and the
unpacked ATV1sm release directory. --check validates inputs without building.
Building requires root and a Linux host with parted, dosfstools and loop devices.
The output must not already exist. No physical device is written.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
asd='' release='' output='' size=512 check=0
while (($#)); do
    case "$1" in
        --asd-system|--atv1sm|--output|--size-mib)
            (($# >= 2)) || die "missing value for $1"
            case "$1" in
                --asd-system) asd=$2 ;;
                --atv1sm) release=$2 ;;
                --output) output=$2 ;;
                --size-mib) size=$2 ;;
            esac
            shift 2 ;;
        --check) check=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

[[ -n $asd && -n $release && -n $output ]] || { usage >&2; die 'all three paths are required'; }
[[ $size =~ ^[0-9]+$ && ${#size} -le 5 ]] || die 'size must be an integer in MiB'
size=$((10#$size))
((size >= 128 && size <= 32768)) || die 'size must be between 128 and 32768 MiB'
[[ -d $asd && -d $release ]] || die 'input directories do not exist'
[[ -f $asd/Library/CoreServices/ASD.acm/Contents/MacOS/ASD ]] || die 'missing diagnostic System/Library/CoreServices/ASD.acm/Contents/MacOS/ASD'
[[ -f $release/ASD && -f $release/GopShimDxe.efi && -f $release/EFI/boot/bootia32.efi ]] || die 'release must contain ASD, GopShimDxe.efi and EFI/boot/bootia32.efi'
# FAT cannot represent symbolic links or Unix special files. Refuse them rather
# than following links into unrelated files or silently producing broken input.
for dir in "$asd" "$release/EFI"; do
    invalid=$(find "$dir" ! -type d ! -type f -print -quit) || die "cannot inspect $dir"
    [[ -z $invalid ]] || die "unsupported symbolic link or special file in $dir"
done
[[ ! -L $release/ASD && ! -L $release/GopShimDxe.efi ]] || die 'release payloads must be regular files, not symlinks'
[[ ! -e $output && ! -L $output ]] || die 'output already exists'
outdir=$(dirname -- "$output")
name=$(basename -- "$output")
[[ -d $outdir && $name != . && $name != .. ]] || die 'output parent must be an existing directory'
outdir=$(cd -- "$outdir" && pwd -P)
case "$outdir/" in /dev/*|/proc/*|/sys/*) die 'output must not be on a device or virtual filesystem' ;; esac
output=$outdir/$name
[[ ! -e $output && ! -L $output ]] || die 'output already exists'

if ((check)); then
    printf 'Input preflight passed; no image created. This is not a NetBSD live image.\n'
    exit 0
fi
[[ $(uname -s) == Linux ]] || die 'image creation requires Linux'
((EUID == 0)) || die 'image creation requires root for loop devices and mounts'
for cmd in parted losetup mkfs.vfat mount umount truncate cp find mktemp ln; do
    command -v "$cmd" >/dev/null || die "missing required command: $cmd"
done

work=$(mktemp -d "$outdir/.atv1sm-build.XXXXXXXX")
image=$work/image
mountpoint=$work/mount
loop='' mounted=0
cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if ((mounted)); then
        if ! umount "$mountpoint"; then
            printf 'error: failed to unmount %s; retained %s and %s for manual cleanup\n' "$mountpoint" "$work" "$loop" >&2
            exit 1
        fi
    fi
    if [[ -n $loop ]] && ! losetup -d "$loop"; then
        printf 'error: failed to detach %s; retained %s for manual cleanup\n' "$loop" "$work" >&2
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
truncate -s "${size}M" "$image"
parted -s "$image" mklabel gpt
parted -s "$image" mkpart primary fat32 1MiB 100%
parted -s "$image" set 1 atvrecv on
loop=$(losetup --find --partscan --show "$image")
part=${loop}p1
[[ -b $part ]] || die "partition device did not appear: $part"
mkfs.vfat -F 32 -n ATV1SM "$part"
mount "$part" "$mountpoint"
mounted=1
cp -R -- "$asd" "$mountpoint/System"
cp -R -- "$release/EFI" "$mountpoint/EFI"
cp -- "$release/ASD" "$mountpoint/System/Library/CoreServices/ASD.acm/Contents/MacOS/ASD"
mkdir -p -- "$mountpoint/System/Library/CoreServices/Runtime_Files/EFI/Drivers"
cp -- "$release/GopShimDxe.efi" "$mountpoint/System/Library/CoreServices/Runtime_Files/EFI/Drivers/GopShimDxe.efi"
umount "$mountpoint"
mounted=0
losetup -d "$loop"
loop=
# A hard link fails atomically if a file or symlink appears at the output path.
ln -- "$image" "$output" || die 'could not publish image without overwriting output'
printf 'Created %s (ATV1sm/rEFInd gate only; no NetBSD OS).\n' "$output"
