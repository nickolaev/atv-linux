#!/bin/sh
# Open the console explicitly for keyboard input and visible output.
exec </dev/console >/dev/console 2>&1

while :; do
    printf '\nChoose a distribution:\n'
    printf '  1) Debian 12\n'
    printf '  2) Alpine Linux 3.24\n'
    printf 'Choose 1 or 2: '
    if ! IFS= read -r choice; then
        printf '\nUnable to read from the console. Power off to exit.\n'
        while :; do sleep 3600; done
    fi
    case "$choice" in
        1) selected='Debian 12' ;;
        2) selected='Alpine Linux 3.24' ;;
        *) printf 'Invalid choice. Please enter 1 or 2.\n'; continue ;;
    esac
    printf '\nSelected: %s\n' "$selected"
    printf 'Booting is not implemented yet. Power off to exit.\n'
    # Stay here until the device is powered off.
    while :; do sleep 3600; done
done
