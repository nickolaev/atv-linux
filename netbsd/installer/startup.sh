#!/bin/sh
# Run once from the USB root after the system enters multiuser mode.
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
assets=/usr/atv-installer
state=/var/db/atv-installer
log=/var/log/atv-install.log
report="$state/install-report.txt"
mkdir -p "$state" || exit 1

# install.sh persists this marker before it modifies the disk. Never retry an
# interrupted or completed installation automatically.
if [ -e "$state/install-started" ]; then
    if [ ! -f "$report" ]; then
        {
            echo 'ATV-NETBSD-INSTALL-1'
            if [ -e "$state/install-complete" ]; then
                echo 'result=installed'
            else
                echo 'result=interrupted'
            fi
            [ ! -f "$log" ] || cat "$log"
            echo 'report=complete'
        } > "$report"
        sync
    fi
    exit 0
fi

{
    echo 'Starting unattended installation'
    date -u
} >> "$log" 2>&1
if "$assets/bin/install.sh" wd0 "$assets" "$state" >> "$log" 2>&1; then
    result=installed
    echo 'Installer completed; remove USB and boot from the internal disk.' >> "$log"
else
    result=failed
    echo 'Installer failed; see the log and install-started marker.' >> "$log"
fi
date -u >> "$log"
sync

{
    echo 'ATV-NETBSD-INSTALL-1'
    echo "result=$result"
    cat "$log"
    echo 'report=complete'
} > "$report"
sync
