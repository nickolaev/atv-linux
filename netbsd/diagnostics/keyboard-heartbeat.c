/* NetBSD wscons USB keyboard LED indicator: a late-userland milestone only. */
#include <sys/ioctl.h>
#include <dev/wscons/wsconsio.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>

#define KEYBOARDS 8
#define CYCLES 3

int
main(void)
{
    int fds[KEYBOARDS], saved[KEYBOARDS];
    int count = 0, i, cycle, failed = 0;
    char path[32];

    /* Write-only opens leave wscons input attached to its existing mux. */
    for (i = 0; i < KEYBOARDS; i++) {
        int fd, type, leds;
        (void)snprintf(path, sizeof(path), "/dev/wskbd%d", i);
        fd = open(path, O_WRONLY);
        if (fd < 0)
            continue;
        if (ioctl(fd, WSKBDIO_GTYPE, &type) < 0 || type != WSKBD_TYPE_USB ||
            ioctl(fd, WSKBDIO_GETLEDS, &leds) < 0) {
            close(fd);
            continue;
        }
        fds[count] = fd;
        saved[count++] = leds;
    }
    if (!count) {
        fprintf(stderr, "keyboard-heartbeat: no usable USB wskbd device\n");
        return 1;
    }
    for (cycle = 0; cycle < CYCLES; cycle++) {
        int leds = WSKBD_LED_CAPS | WSKBD_LED_NUM | WSKBD_LED_SCROLL;
        for (i = 0; i < count; i++)
            if (ioctl(fds[i], WSKBDIO_SETLEDS, &leds) < 0) failed = 1;
        sleep(1);
        leds = 0;
        for (i = 0; i < count; i++)
            if (ioctl(fds[i], WSKBDIO_SETLEDS, &leds) < 0) failed = 1;
        sleep(1);
    }
    for (i = 0; i < count; i++) {
        if (ioctl(fds[i], WSKBDIO_SETLEDS, &saved[i]) < 0) failed = 1;
        close(fds[i]);
    }
    if (failed)
        fprintf(stderr, "keyboard-heartbeat: at least one LED request failed\n");
    return failed ? 1 : 0;
}
