#!/bin/sh
# Opt-in Linux-time polling agent. Reports are authenticated but not encrypted.
# Arguments: controller base URL and mode-0600 key-file path.
set -u
[ "$#" -eq 2 ] || { echo 'usage: poll.sh HTTP_BASE_URL KEY_FILE' >&2; exit 2; }
base=${1%/}; key_file=$2
case "$base" in http://*) ;; *) echo 'expected HTTP base URL' >&2; exit 2 ;; esac
umask 077
control=/tmp/atv-netdiag-control
mkdir -m 700 "$control" || { echo 'agent control already exists' >&2; exit 1; }
stop_requested=0
server_pid=''
work=''
cleanup() {
    [ -z "$server_pid" ] || { kill "$server_pid" 2>/dev/null || :; wait "$server_pid" 2>/dev/null || :; }
    [ -z "$work" ] || rm -rf -- "$work"
    rm -f "$control/busy" "$control/stop"
    rmdir "$control" 2>/dev/null || :
}
trap cleanup EXIT
trap 'stop_requested=1' TERM INT
work=$(mktemp -d /tmp/atv-poll.XXXXXX) || exit 1
chmod 700 "$work" || exit 1
mkdir "$work/export" || exit 1
# Linux 2.6.39 can expose urandom before its pool has adequate entropy.
# Never silently start a replay-sensitive session with an unready pool.
tries=0
while :; do
    entropy=$(cat /proc/sys/kernel/random/entropy_avail 2>/dev/null) || entropy=''
    case "$entropy" in ''|*[!0-9]*) echo 'entropy status unavailable' >&2; exit 1 ;; esac
    [ "$entropy" -ge 128 ] && break
    [ "$tries" -lt 30 ] || { echo 'entropy pool not ready' >&2; exit 1; }
    tries=$((tries + 1)); sleep 1
done
session=$(hexdump -v -n 16 -e '16/1 "%02x"' /dev/urandom) || exit 1
case "$session" in *[!0-9a-f]*|'') echo 'nonce unavailable' >&2; exit 1 ;; esac
[ "${#session}" -eq 32 ] || exit 1
httpd -f -p 8081 -h "$work/export" &
server_pid=$!
sleep 1
if ! kill -0 "$server_pid" 2>/dev/null; then
    wait "$server_pid" 2>/dev/null || :
    server_pid=''
    echo 'report server failed to start' >&2
    exit 1
fi
last=0000000000000000
publish_report() {
    # Sign and publish the same private snapshot, even if the log changes.
    cp "$work/status.txt" "$work/report-body" || return 1
    report_tag=$(/atv-auth sign-report "$key_file" "$session" "$id" "$work/report-body") || return 1
    case "$report_tag" in ''|*[!0-9a-f]*) return 1 ;; esac
    [ "${#report_tag}" -eq 64 ] || return 1
    { printf '%s %s %s\n' "$session" "$id" "$report_tag"; cat "$work/report-body"; } > "$work/export/report.new" || return 1
    mv -f "$work/export/report.new" "$work/export/report" || return 1
}
while :; do
    [ "$stop_requested" -eq 0 ] && [ ! -e "$control/stop" ] || break
    if (ulimit -f 4 && wget -T 10 -q -O "$work/manifest" "$base/manifest/$session"); then
        IFS=' ' read -r tag received_session id kind size digest mac < "$work/manifest" || :
        case "${id:-}" in ''|*[!0-9a-f]*) id='' ;; esac
        if [ "${#id}" -eq 16 ] && [ "$id" != "$last" ]; then
            if (ulimit -f 65536 && wget -T 120 -q -O "$work/payload" "$base/payload/$id") &&
               [ -s "$work/payload" ]; then
                verified=$(/atv-auth "$key_file" "$work/manifest" "$work/payload" "$session" "$last") || verified=''
                if [ "$verified" = "$id" ]; then
                    # Menu and poller share an atomic lock to serialize stop
                    # requests with publishing the busy state.
                    if ! mkdir "$control/lock" 2>/dev/null; then sleep 1; continue; fi
                    if [ "$stop_requested" -ne 0 ] || [ -e "$control/stop" ]; then
                        rmdir "$control/lock"; break
                    fi
                    : > "$control/busy" || { rmdir "$control/lock"; exit 1; }
                    rmdir "$control/lock" || exit 1
                    # A signal cannot interrupt wait and orphan a running job.
                    # Normal stop uses the control lock and refuses while busy.
                    trap '' TERM INT
                    # Mark only verified jobs as accepted, before execution.
                    # Failed downloads/checks retry on the next poll; jobs that
                    # ran (even with a nonzero exit) are not repeated.
                    last=$id
                    printf 'job=%s running (timeout 120s)\n' "$id" > "$work/status.txt"
                    publish_report || echo 'report signing failed' >&2
                    # The i386 supervisor keeps the group leader unreaped
                    # until all group signals have been sent, preventing PID
                    # reuse during timeout cleanup. 124/125 can also be
                    # returned deliberately by the job itself.
                    # Keep ample room below the 8 MiB report-signing limit
                    # for the final status line, irrespective of whether the
                    # shell reports file-size units as 512 or 1024 bytes.
                    (ulimit -f 2048 && exec /atv-supervise 120 "$work/payload") >> "$work/status.txt" 2>&1
                    result=$?
                    printf '\njob=%s exit=%s' "$id" "$result" >> "$work/status.txt"
                    case "$result" in
                        124) printf ' (timeout or job exit 124)' >> "$work/status.txt" ;;
                        125) printf ' (supervisor error or job exit 125)' >> "$work/status.txt" ;;
                    esac
                    printf '\nJob output is capped at 2048 file-limit blocks; it may be truncated.\n' >> "$work/status.txt"
                    publish_report || echo 'report signing failed' >&2
                    # Keep the job marked busy through supervision and final
                    # report publication; serialize clearing with the menu.
                    while ! mkdir "$control/lock" 2>/dev/null; do sleep 1; done
                    rm -f "$control/busy"
                    rmdir "$control/lock" || exit 1
                    trap 'stop_requested=1' TERM INT
                else
                    echo 'job authentication failed; retrying' >&2
                fi
            else
                echo 'job download failed; retrying' >&2
            fi
        fi
    fi
    sleep 5
done
