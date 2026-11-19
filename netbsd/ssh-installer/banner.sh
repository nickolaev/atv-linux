#!/bin/sh
# Show a compact accent on interactive login; the MOTD has the instructions.
if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ -z "${NO_COLOR:-}" ]; then
    printf '\033[36m  +--------------------------------------+\033[0m\n'
    printf '\033[36m  |\033[0m  \033[1mAPPLE TV\033[0m  \033[35m/\033[0m  NETBSD                \033[36m|\033[0m\n'
    printf '\033[36m  +--------------------------------------+\033[0m\n\n'
fi
