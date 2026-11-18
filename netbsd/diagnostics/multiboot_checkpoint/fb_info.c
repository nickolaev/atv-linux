/* Read the Linux/i386 fbdev ABI without libc or framebuffer writes. */
#include <stddef.h>
#include <stdint.h>

enum {
    SYS_WRITE = 4,
    SYS_OPEN = 5,
    SYS_CLOSE = 6,
    SYS_IOCTL = 54,
    FBIOGET_VSCREENINFO = 0x4600,
    FBIOGET_FSCREENINFO = 0x4602,
};

/* i386 layouts from Linux include/linux/fb.h. */
struct fixed_info {
    char id[16];
    uint32_t smem_start, smem_len, type, type_aux, visual;
    uint16_t xpanstep, ypanstep, ywrapstep;
    uint32_t line_length, mmio_start, mmio_len, accel;
    uint16_t reserved[3];
};

struct channel {
    uint32_t offset, length, msb_right;
};

struct variable_info {
    uint32_t xres, yres, xres_virtual, yres_virtual, xoffset, yoffset;
    uint32_t bits_per_pixel, grayscale;
    struct channel red, green, blue, transp;
    uint32_t nonstd;
    uint32_t unused[19];
};

_Static_assert(sizeof(void *) == 4, "i386 Linux target required");
_Static_assert(sizeof(struct fixed_info) == 68, "Linux i386 fixed info size");
_Static_assert(offsetof(struct fixed_info, line_length) == 44, "Linux i386 stride offset");
_Static_assert(sizeof(struct variable_info) == 160, "Linux variable info size");
_Static_assert(offsetof(struct variable_info, red) == 32, "Linux color offset");

static int syscall3(int number, int first, uintptr_t second, uintptr_t third)
{
    int result;
    __asm__ volatile("int $0x80" : "=a"(result)
        : "0"(number), "b"(first), "c"(second), "d"(third) : "memory", "cc");
    return result;
}

static int write_all(int fd, const char *data, unsigned int length)
{
    while (length) {
        int written = syscall3(SYS_WRITE, fd, (uintptr_t)data, length);

        if (written == -4) /* EINTR */
            continue;
        if (written <= 0 || (unsigned int)written > length)
            return 1;
        data += written;
        length -= written;
    }
    return 0;
}

static char *append(char *out, const char *text)
{
    while (*text)
        *out++ = *text++;
    return out;
}

static char *field(char *out, const char *name, uint32_t value)
{
    static const char digits[] = "0123456789abcdef";

    out = append(out, name);
    out = append(out, "=0x");
    for (int shift = 28; shift >= 0; shift -= 4)
        *out++ = digits[(value >> shift) & 15];
    *out++ = '\n';
    return out;
}

__attribute__((used, noinline)) static int run(int argc, char **argv)
{
    static const char usage[] = "Usage: fb_info [framebuffer-device]\n";
    static const char open_error[] = "Could not open framebuffer device read-only\n";
    static const char ioctl_error[] = "Could not read framebuffer parameters\n";
    struct fixed_info fixed;
    struct variable_info variable;

    if (argc < 1 || argc > 2) {
        write_all(2, usage, sizeof(usage) - 1);
        return 2;
    }
    const char *path = argc == 2 ? argv[1] : "/dev/fb0";
    int fd = syscall3(SYS_OPEN, (uintptr_t)path, 0, 0); /* O_RDONLY */
    if (fd < 0) {
        write_all(2, open_error, sizeof(open_error) - 1);
        return 1;
    }
    int valid = syscall3(SYS_IOCTL, fd, FBIOGET_FSCREENINFO, (uintptr_t)&fixed) == 0 &&
        syscall3(SYS_IOCTL, fd, FBIOGET_VSCREENINFO, (uintptr_t)&variable) == 0;
    syscall3(SYS_CLOSE, fd, 0, 0);
    if (!valid) {
        write_all(2, ioctl_error, sizeof(ioctl_error) - 1);
        return 1;
    }

    char output[1024];
    char *out = append(output, "fb_id=");
    for (unsigned int i = 0; i < sizeof(fixed.id) && fixed.id[i]; i++) {
        unsigned char ch = fixed.id[i];
        *out++ = ch >= 0x20 && ch <= 0x7e ? ch : '?';
    }
    *out++ = '\n';
    out = field(out, "fb_smem_start", fixed.smem_start);
    out = field(out, "fb_smem_len", fixed.smem_len);
    out = field(out, "fb_type", fixed.type);
    out = field(out, "fb_visual", fixed.visual);
    out = field(out, "fb_line_length", fixed.line_length);
    out = field(out, "fb_xres", variable.xres);
    out = field(out, "fb_yres", variable.yres);
    out = field(out, "fb_xres_virtual", variable.xres_virtual);
    out = field(out, "fb_yres_virtual", variable.yres_virtual);
    out = field(out, "fb_xoffset", variable.xoffset);
    out = field(out, "fb_yoffset", variable.yoffset);
    out = field(out, "fb_bits_per_pixel", variable.bits_per_pixel);
    out = field(out, "fb_grayscale", variable.grayscale);
    out = field(out, "fb_nonstd", variable.nonstd);
    out = field(out, "fb_red_offset", variable.red.offset);
    out = field(out, "fb_red_length", variable.red.length);
    out = field(out, "fb_red_msb_right", variable.red.msb_right);
    out = field(out, "fb_green_offset", variable.green.offset);
    out = field(out, "fb_green_length", variable.green.length);
    out = field(out, "fb_green_msb_right", variable.green.msb_right);
    out = field(out, "fb_blue_offset", variable.blue.offset);
    out = field(out, "fb_blue_length", variable.blue.length);
    out = field(out, "fb_blue_msb_right", variable.blue.msb_right);
    out = field(out, "fb_transp_offset", variable.transp.offset);
    out = field(out, "fb_transp_length", variable.transp.length);
    out = field(out, "fb_transp_msb_right", variable.transp.msb_right);
    return write_all(1, output, out - output);
}

__attribute__((naked, noreturn)) void _start(void)
{
    __asm__ volatile(
        "movl (%esp),%eax\n\t"
        "leal 4(%esp),%edx\n\t"
        "andl $-16,%esp\n\t"
        "subl $8,%esp\n\t"
        "pushl %edx\n\t"
        "pushl %eax\n\t"
        "call run\n\t"
        "movl %eax,%ebx\n\t"
        "movl $1,%eax\n\t"
        "int $0x80\n\t"
        "ud2");
}
