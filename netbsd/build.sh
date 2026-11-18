#!/usr/bin/env bash
# Build an ATV1sm/rEFInd gate or a NetBSD EFI installer image.
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: bash netbsd/build.sh --asd-system DIR --atv1sm DIR --output NEW.img
                            [--netbsd-kernel FILE --netbsd-efi FILE]
                            [--size-mib N] [--autoboot] [--check]

DIR arguments are the extracted Apple diagnostic System directory and the
unpacked ATV1sm release directory. --check validates inputs without building.
Optional NetBSD inputs are an uncompressed i386 INSTALL kernel and IA32 EFI loader.
--autoboot requires both NetBSD inputs and enables timed boot and rEFInd logging.
Building requires Linux with parted, dosfstools, mtools and Python 3.
The output must not already exist. No physical device is written.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
asd='' release='' output='' kernel='' netbsd_efi='' size=512 check=0 autoboot=0
while (($#)); do
    case "$1" in
        --asd-system|--atv1sm|--output|--size-mib|--netbsd-kernel|--netbsd-efi)
            (($# >= 2)) || die "missing value for $1"
            case "$1" in
                --asd-system) asd=$2 ;;
                --atv1sm) release=$2 ;;
                --output) output=$2 ;;
                --size-mib) size=$2 ;;
                --netbsd-kernel) kernel=$2 ;;
                --netbsd-efi) netbsd_efi=$2 ;;
            esac
            shift 2 ;;
        --check) check=1; shift ;;
        --autoboot) autoboot=1; shift ;;
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
if ((autoboot)); then
    [[ -n $kernel && -n $netbsd_efi ]] || die '--autoboot requires NetBSD kernel and EFI loader'
fi
if [[ -n $kernel || -n $netbsd_efi ]]; then
    [[ -n $kernel && -n $netbsd_efi ]] || die 'NetBSD kernel and EFI loader must be supplied together'
    for file in "$kernel" "$netbsd_efi"; do
        [[ -f $file && ! -L $file ]] || die 'NetBSD inputs must be regular files, not symlinks'
    done
    command -v python3 >/dev/null || die 'missing required command: python3'
    python3 - "$kernel" "$netbsd_efi" "$(dirname -- "$0")/macho" <<'PYVALIDATE'
from pathlib import Path
import struct
import sys
sys.path.insert(0, sys.argv[3])
from netbsd_elf import plan_elf
try:
    plan_elf(Path(sys.argv[1]).read_bytes())
    loader = Path(sys.argv[2]).read_bytes()
    if loader[:2] != b'MZ' or len(loader) < 64:
        raise ValueError('expected an IA32 EFI PE image')
    pe = struct.unpack_from('<I', loader, 60)[0]
    if (loader[pe:pe + 4] != b'PE\0\0' or
            struct.unpack_from('<H', loader, pe + 4)[0] != 0x14c or
            struct.unpack_from('<H', loader, pe + 24)[0] != 0x10b or
            struct.unpack_from('<H', loader, pe + 24 + 68)[0] != 10):
        raise ValueError('expected an IA32 EFI application')
except (OSError, ValueError, struct.error) as error:
    sys.exit(str(error))
PYVALIDATE
fi
[[ ! -e $output && ! -L $output ]] || die 'output already exists'
outdir=$(dirname -- "$output")
name=$(basename -- "$output")
[[ -d $outdir && $name != . && $name != .. ]] || die 'output parent must be an existing directory'
outdir=$(cd -- "$outdir" && pwd -P)
case "$outdir/" in /dev/*|/proc/*|/sys/*) die 'output must not be on a device or virtual filesystem' ;; esac
output=$outdir/$name
[[ ! -e $output && ! -L $output ]] || die 'output already exists'

if ((check)); then
    printf 'Input preflight passed; no image created.\n'
    exit 0
fi
[[ $(uname -s) == Linux ]] || die 'image creation requires Linux'
for cmd in parted mkfs.vfat mcopy truncate cp find mktemp ln dd; do
    command -v "$cmd" >/dev/null || die "missing required command: $cmd"
done

work=$(mktemp -d "$outdir/.atv1sm-build.XXXXXXXX")
image=$work/image
partition=$work/recovery.fat
efi_partition=$work/netbsd.fat
stage=$work/tree
netbsd_stage=$work/netbsd-tree
cleanup() {
    local status=$?
    trap - EXIT INT TERM
    rm -rf -- "$work"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -- "$stage"
truncate -s "${size}M" "$image"
parted -s "$image" mklabel gpt
# Keep the final MiB free for the backup GPT and align the FAT partition.
if [[ -n $kernel ]]; then
    # NetBSD's ESP lookup must encounter its known EFI type before recovery.
    # GPT entry order is independent of these physical partition offsets.
    parted -s "$image" mkpart primary fat32 41MiB "$((size - 1))MiB"
    parted -s "$image" set 1 esp on
    parted -s "$image" mkpart primary fat32 1MiB 41MiB
    parted -s "$image" set 2 atvrecv on
    truncate -s 40M "$partition"
    truncate -s "$((size - 42))M" "$efi_partition"
    mkfs.vfat -F 32 -n NETBSD11 "$efi_partition"
else
    parted -s "$image" mkpart primary fat32 1MiB "$((size - 1))MiB"
    truncate -s "$((size - 2))M" "$partition"
    parted -s "$image" set 1 atvrecv on
fi
mkfs.vfat -F 32 -n ATV1SM "$partition"
cp -R -- "$asd" "$stage/System"
cp -R -- "$release/EFI" "$stage/EFI"
cp -- "$release/ASD" "$stage/System/Library/CoreServices/ASD.acm/Contents/MacOS/ASD"
mkdir -p -- "$stage/System/Library/CoreServices/Runtime_Files/EFI/Drivers"
cp -- "$release/GopShimDxe.efi" "$stage/System/Library/CoreServices/Runtime_Files/EFI/Drivers/GopShimDxe.efi"
if [[ -n $kernel ]]; then
    mkdir -p -- "$netbsd_stage/EFI/NetBSD" "$netbsd_stage/EFI/BOOT"
    cp -- "$kernel" "$netbsd_stage/netbsd"
    cp -- "$netbsd_efi" "$netbsd_stage/EFI/NetBSD/bootia32.efi"
    cp -- "$netbsd_efi" "$netbsd_stage/EFI/BOOT/BOOTIA32.EFI"
    boot_timeout=-1
    if ((autoboot)); then boot_timeout=5; fi
    printf 'timeout=%s\n' "$boot_timeout" > "$netbsd_stage/EFI/NetBSD/boot.cfg"
    cat >> "$netbsd_stage/EFI/NetBSD/boot.cfg" <<'EOF'
banner=NetBSD 11.1 Apple TV EFI installer
default=1
menu=NetBSD 11.1 installer:userconf disable nouveau;boot esp:/netbsd -v
menu=Boot prompt:prompt
EOF
    if ((autoboot)); then
        # The log persists on the recovery FAT volume before loader handoff.
        cat > "$stage/EFI/boot/refind.conf" <<'EOF'
timeout 5
default_selection "NetBSD 11.1 installer"
log_level 2
use_nvram false
textonly
showtools reboot
EOF
    else
        printf 'timeout 0\n' > "$stage/EFI/boot/refind.conf"
    fi
    cat >> "$stage/EFI/boot/refind.conf" <<'EOF'
scanfor manual
menuentry "NetBSD 11.1 installer" {
    volume NETBSD11
    loader \EFI\NetBSD\bootia32.efi
}
EOF
fi
mcopy -i "$partition" -s -- "$stage/System" "$stage/EFI" ::/
if [[ -n $kernel ]]; then
    mcopy -i "$efi_partition" -s -- "$netbsd_stage/EFI" "$netbsd_stage/netbsd" ::/
    dd if="$efi_partition" of="$image" bs=1M seek=41 conv=notrunc,sparse status=none
fi
dd if="$partition" of="$image" bs=1M seek=1 conv=notrunc,sparse status=none
# A hard link fails atomically if a file or symlink appears at the output path.
ln -- "$image" "$output" || die 'could not publish image without overwriting output'
if [[ -n $kernel ]]; then
    printf 'Created %s (ATV1sm/rEFInd and NetBSD EFI installer).\n' "$output"
else
    printf 'Created %s (ATV1sm/rEFInd gate only; no NetBSD OS).\n' "$output"
fi
