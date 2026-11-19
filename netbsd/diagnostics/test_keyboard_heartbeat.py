"""Host-side behavior test; this does not emulate NetBSD or a USB device."""
import pathlib
import subprocess
import tempfile
import unittest

SOURCE = pathlib.Path(__file__).with_name('keyboard-heartbeat.c')

HARNESS = r'''
#include <sys/ioctl.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <unistd.h>
static int mode, opens, closes, sets, delays, bad;
static int sequence[8];
static int fake_open(const char *path, int flags, ...) {
    if (flags != O_WRONLY) bad = 1;
    opens++;
    if (path[10] == '0') return 10;
    if (path[10] == '1') return 11;
    return -1;
}
static int fake_close(int fd) { (void)fd; closes++; return 0; }
static unsigned fake_sleep(unsigned seconds) { if (seconds != 1) bad = 1; delays++; return 0; }
static int fake_ioctl(int fd, unsigned long request, ...) {
    va_list ap; int *v;
    va_start(ap, request); v = va_arg(ap, int *); va_end(ap);
    if (request == 1) { *v = (mode == 1 || fd == 11) ? 0 : 42; return 0; }
    if (request == 2) { *v = 2; return 0; }
    if (request == 3) {
        if (fd != 10 || sets >= 8) bad = 1;
        sequence[sets++] = *v;
        return mode == 2 && sets == 1 ? -1 : 0;
    }
    bad = 1; return -1;
}
#define open fake_open
#define close fake_close
#define sleep fake_sleep
#define ioctl fake_ioctl
#define main heartbeat_main
#include "keyboard-heartbeat.c"
#undef main
int main(void) {
    int i, result;
    mode = 0; result = heartbeat_main();
    if (result || bad || opens != 8 || closes != 2 || sets != 7 || delays != 6) return 1;
    for (i = 0; i < 6; i++) if (sequence[i] != (i % 2 ? 0 : 7)) return 2;
    if (sequence[6] != 2) return 3;
    mode = 1; sets = 0; result = heartbeat_main();
    if (result != 1 || sets) return 4;
    mode = 2; sets = 0; result = heartbeat_main();
    if (result != 1 || sets != 7 || sequence[6] != 2) return 5;
    return 0;
}
'''


class HeartbeatTest(unittest.TestCase):
    def test_usb_filter_pattern_restore_and_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            header = root / 'dev/wscons/wsconsio.h'
            header.parent.mkdir(parents=True)
            header.write_text('#define WSKBDIO_GTYPE 1\n#define WSKBDIO_GETLEDS 2\n'
                              '#define WSKBDIO_SETLEDS 3\n#define WSKBD_TYPE_USB 42\n'
                              '#define WSKBD_LED_CAPS 1\n#define WSKBD_LED_NUM 2\n'
                              '#define WSKBD_LED_SCROLL 4\n')
            (root / 'harness.c').write_text(HARNESS)
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-I', str(root), '-I', str(SOURCE.parent),
                            str(root / 'harness.c'), '-o', str(root / 'test')], check=True)
            subprocess.run([str(root / 'test')], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
