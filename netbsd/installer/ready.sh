#!/bin/sh
# Report the installed system after its network interface obtains an address.
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
report=/var/run/atv-ready-report.txt
attempt=0
while [ "$attempt" -lt 60 ]; do
    if ifconfig rtk0 2>/dev/null | grep 'inet ' | grep -qv 'TENTATIVE'; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 2
done

# The report is complete even when a readiness check fails. Keep the readiness
# result separate from the framing marker so failures remain visible remotely.
result=ready
[ "$(hostname)" = atv ] || result=degraded
ifconfig rtk0 2>/dev/null | grep 'inet ' | grep -qv 'TENTATIVE' || result=degraded
wedges=$(dkctl wd0 listwedges 2>/dev/null) || wedges=
rootdk=$(printf '%s\n' "$wedges" | awk '$2 == "atv-root," {gsub(":", "", $1); print $1}')
swapdk=$(printf '%s\n' "$wedges" | awk '$2 == "atv-swap," {gsub(":", "", $1); print $1}')
case "$rootdk:$swapdk" in
    dk[0-9]*:dk[0-9]*) ;;
    *) result=degraded ;;
esac
mounts=$(mount) || mounts=
printf '%s\n' "$mounts" | awk -v dev="/dev/$rootdk" '$1 == dev && $2 == "on" && $3 == "/" && $4 == "type" && $5 == "ffs" {found=1} END {exit !found}' || result=degraded
swapctl -lk | awk -v dev="/dev/$swapdk" '$1 == dev {found=1} END {exit !found}' || result=degraded
{
    echo 'ATV-NETBSD-READY-1'
    echo "result=$result"
    date -u
    uname -a
    echo "--- hostname ---"
    hostname
    echo "--- interfaces ---"
    ifconfig -a
    echo "--- internal disk wedges ---"
    printf '%s\n' "$wedges"
    echo "--- root ---"
    mount
    echo "--- swap ---"
    swapctl -lk
    echo "--- DHCP configuration ---"
    cat /etc/dhcpcd.conf
    echo 'report=complete'
} > "$report" 2>&1

attempt=0
while [ "$attempt" -lt 30 ]; do
    if nc -w 10 192.168.100.246 8083 < "$report"; then
        exit 0
    fi
    attempt=$((attempt + 1))
    sleep 10
done
exit 1
