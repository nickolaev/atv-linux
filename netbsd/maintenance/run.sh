#!/bin/sh
# Enable SSH on the installed ATV1 root from the maintenance USB.
set -eu
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
assets=/usr/atv-maintenance
state=/var/db/atv-maintenance
log=/var/log/atv-maintenance.log
root=/mnt/atv-installed
mkdir -p "$state" "$root"
report=$state/report.txt
mounted=no

finish() {
    status=$?
    trap - EXIT HUP INT TERM
    if [ "$mounted" = yes ]; then
        sync
        if ! umount "$root"; then
            echo 'Unable to unmount installed root.' >> "$log"
            status=1
        fi
    fi
    {
        echo 'ATV-NETBSD-MAINTENANCE-1'
        if [ "$status" -eq 0 ]; then echo 'result=ssh-configured'; else echo 'result=failed'; fi
        cat "$log"
        echo 'report=complete'
    } > "$report"
    sync
    attempt=0
    while [ "$attempt" -lt 30 ]; do
        nc -w 10 192.168.100.246 8083 < "$report" && break
        attempt=$((attempt + 1))
        sleep 10
    done
    exit "$status"
}
trap finish EXIT
trap 'exit 1' HUP INT TERM

exec >> "$log" 2>&1
echo 'Starting SSH maintenance'
date -u
[ -s "$assets/authorized_keys" ] || { echo 'Missing SSH public key'; exit 1; }
[ -s "$assets/provision.sh" ] || { echo 'Missing package provisioning script'; exit 1; }
/usr/atv-installer/bin/check-target.sh wd0
wedges=$(dkctl wd0 listwedges)
target=$(printf '%s\n' "$wedges" | awk '$2 == "atv-root," {gsub(":", "", $1); print $1}')
case "$target" in dk[0-9]*) ;; *) echo 'Installed root wedge missing or ambiguous'; exit 1 ;; esac
case "$target" in *[!0-9dk]*) echo 'Invalid wedge'; exit 1 ;; esac
[ "$(printf '%s\n' "$wedges" | awk '$2 == "atv-root," {n++} END {print n+0}')" -eq 1 ] || { echo 'Multiple installed root wedges'; exit 1; }
mounts=$(mount)
printf '%s\n' "$mounts" | awk -v dev="/dev/$target" '$1 == dev {found=1} END {exit !found}' && { echo 'Target root already mounted'; exit 1; }
(cd /dev && sh MAKEDEV "$target")
mount -t ffs "/dev/$target" "$root"
mounted=yes
[ -f "$root/etc/rc.conf" ] && [ -f "$root/etc/ssh/sshd_config" ] && [ -d "$root/root" ] || { echo 'Target is not the installed NetBSD root'; exit 1; }
mkdir -p "$root/root/.ssh"
chmod 700 "$root/root/.ssh"
touch "$root/root/.ssh/authorized_keys"
while IFS= read -r key || [ -n "$key" ]; do
    [ -n "$key" ] || continue
    grep -Fqx -- "$key" "$root/root/.ssh/authorized_keys" || printf '%s\n' "$key" >> "$root/root/.ssh/authorized_keys"
done < "$assets/authorized_keys"
chmod 600 "$root/root/.ssh/authorized_keys"
chown -R 0:0 "$root/root/.ssh"
# SSH uses the first value it sees. Set only this option ahead of the release
# configuration, removing prior explicit instances so repeated runs are stable.
config="$root/etc/ssh/sshd_config"
tmp="$root/etc/ssh/sshd_config.atv-new"
{
    echo 'PermitRootLogin prohibit-password'
    awk 'tolower($1) != "permitrootlogin" {print}' "$config"
} > "$tmp"
chmod 600 "$tmp"
chown 0:0 "$tmp"
mv "$tmp" "$config"
if ! grep -Eq '^[[:space:]]*sshd=(YES|yes|true|TRUE|1)([[:space:]]|$)' "$root/etc/rc.conf"; then
    echo 'sshd=YES' >> "$root/etc/rc.conf"
fi
mkdir -p "$root/usr/local/sbin"
cp "$assets/provision.sh" "$root/usr/local/sbin/atv-provision-packages"
chmod 755 "$root/usr/local/sbin/atv-provision-packages"
chown 0:0 "$root/usr/local/sbin/atv-provision-packages"
rc_local="$root/etc/rc.local"
[ -f "$rc_local" ] || printf '#!/bin/sh\n' > "$rc_local"
# Remove the invocation installed by earlier maintenance images while keeping
# any unrelated local startup commands intact.
awk '$0 != "/usr/local/sbin/atv-provision-packages >/var/log/atv-packages-startup.log 2>&1 &" {print}' "$rc_local" > "$rc_local.atv-new"
mv "$rc_local.atv-new" "$rc_local"
chmod 755 "$rc_local"
sync
echo 'SSH configured; run /usr/local/sbin/atv-provision-packages manually after login.'
echo 'Power off, remove the maintenance USB, and boot the internal disk.'
