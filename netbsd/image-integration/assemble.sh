#!/usr/bin/env bash
# Assemble an installer USB file from a tested EFI template and an FFS root.
set -Eeuo pipefail

if (($# != 3)); then
    echo "Usage: $0 EFI-TEMPLATE.img INSTALLER-ROOT.ffs NEW-OUTPUT.img" >&2
    exit 2
fi
template=$1
root=$2
output=$3
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

for program in dd sgdisk mcopy mktemp stat truncate; do
    command -v "$program" >/dev/null || die "missing $program"
done
[[ -f $template && ! -L $template && -f $root && ! -L $root ]] || die 'inputs must be regular files'
[[ ! -e $output && ! -L $output ]] || die 'output already exists'
[[ -d $(dirname "$output") ]] || die 'output directory does not exist'
root_bytes=$(stat -c %s "$root")
((root_bytes > 0 && root_bytes % 512 == 0)) || die 'root size must be a positive multiple of 512 bytes'

# The source template is the verified ATV1sm EFI image. Check both GUIDs and
# exact extents before copying, so a different layout cannot silently slip in.
esp=$(sgdisk -i 1 "$template")
recovery=$(sgdisk -i 2 "$template")
[[ $esp == *'C12A7328-F81F-11D2-BA4B-00A0C93EC93B'* && $esp == *'First sector: 83968 '* && $esp == *'Last sector: 260095 '* ]] || die 'unexpected EFI partition layout'
[[ $recovery == *'5265636F-7665-11AA-AA11-00306543ECAC'* && $recovery == *'First sector: 2048 '* && $recovery == *'Last sector: 83967 '* ]] || die 'unexpected recovery partition layout'

work=$(mktemp -d "$(dirname "$output")/.atv-installer.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
image=$work/image
efi=$work/efi.fat
root_sectors=$((root_bytes / 512))
last_root_sector=$((262144 + root_sectors - 1))
# Reserve 2048 sectors after root for the secondary GPT and alignment.
truncate -s "$(((last_root_sector + 2049) * 512))" "$image"
sgdisk --clear \
    --new=1:83968:260095 --typecode=1:ef00 --change-name=1:NETBSD11 \
    --new=2:2048:83967 --typecode=2:5265636F-7665-11AA-AA11-00306543ECAC --change-name=2:ATV1SM \
    --new=3:262144:"$last_root_sector" --typecode=3:a902 --change-name=3:atv-inst "$image" >/dev/null
dd if="$template" of="$efi" bs=512 skip=83968 count=176128 status=none
cat > "$work/boot.cfg" <<'EOF'
timeout=5
banner=NetBSD 11.1 Apple TV installer
default=1
menu=NetBSD installer:userconf disable nouveau;root NAME=atv-inst;boot esp:/netbsd -v
menu=Boot prompt:prompt
EOF
mcopy -o -i "$efi" "$work/boot.cfg" ::/EFI/NetBSD/boot.cfg
dd if="$template" of="$image" bs=512 skip=2048 seek=2048 count=81920 conv=notrunc status=none
dd if="$efi" of="$image" bs=512 seek=83968 conv=notrunc status=none
dd if="$root" of="$image" bs=512 seek=262144 conv=notrunc,sparse status=none
sgdisk -v "$image" | grep -q 'No problems found' || die 'GPT verification failed'
ln "$image" "$output" || die 'failed to publish output'
printf 'Created %s\n' "$output"
