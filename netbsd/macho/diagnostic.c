/* First-stage framebuffer experiment. This is not a NetBSD loader. */
typedef __UINT16_TYPE__ u16;
typedef __UINT32_TYPE__ u32;
typedef __UINTPTR_TYPE__ uptr;

/* xnu-1228 pexpert/i386/boot.h: display_mode precedes pitch. */
struct video {
    u32 base, display_mode, pitch, width, height, depth;
};
struct boot_args {
    u16 revision, version;
    char command_line[1024];
    u32 memory_map, memory_map_size, descriptor_size, descriptor_version;
    struct video video;
};
_Static_assert(__builtin_offsetof(struct boot_args, video) == 1044, "boot video offset");
_Static_assert(__builtin_offsetof(struct video, pitch) == 8, "video pitch offset");

/* A colored, bounded test pattern needs no firmware console or font. */
int draw_pattern(volatile u32 *pixels, u32 pitch, u32 width, u32 height, u32 depth)
{
    u32 x, y;
    if (!pixels || depth != 32 || width < 64 || height < 64 ||
        width > 4096 || height > 4096 || pitch % 4 ||
        pitch / 4 < width || pitch > 32768 ||
        (uptr)pixels > (uptr)-1 - (uptr)pitch * height)
        return 0;
    for (y = 0; y < height; y++) {
        volatile u32 *row = (volatile u32 *)((uptr)pixels + (uptr)y * pitch);
        for (x = 0; x < width; x++) {
            u32 color = 0x00102050; /* blue background */
            if (y >= height / 4 && y < height / 2 &&
                x >= width / 4 && x < width * 3 / 4)
                color = 0x00ffffff;
            else if (y >= height / 2 && y < height * 3 / 4 &&
                     x >= width / 4 && x < width * 3 / 4)
                color = 0x0000ff00;
            row[x] = color;
        }
    }
    return 1;
}

#ifndef HOST_TEST
void diagnostic_main(const struct boot_args *args)
{
    if (args)
        draw_pattern((volatile u32 *)(uptr)args->video.base, args->video.pitch,
                     args->video.width, args->video.height, args->video.depth);
    for (;;) __asm__ volatile ("cli; hlt");
}
#endif
