#include <stdint.h>

#define VISIBLE_BYTES (((uint64_t)ATV_FB_HEIGHT - 1) * ATV_FB_STRIDE + \
    (uint64_t)ATV_FB_WIDTH * sizeof(uint32_t))

_Static_assert((uint64_t)ATV_FB_BASE >= 0x10000000u &&
    (uint64_t)ATV_FB_BASE <= UINT32_MAX && (ATV_FB_BASE & 3u) == 0,
    "framebuffer must start at a DWORD-aligned physical device address");
_Static_assert(ATV_FB_WIDTH >= 64 && ATV_FB_WIDTH <= 4096 &&
    ATV_FB_HEIGHT >= 64 && ATV_FB_HEIGHT <= 4096, "invalid visible dimensions");
_Static_assert((ATV_FB_STRIDE & 3u) == 0 &&
    ATV_FB_STRIDE >= ATV_FB_WIDTH * sizeof(uint32_t), "invalid row stride");
_Static_assert(VISIBLE_BYTES <= 64u * 1024 * 1024 &&
    (uint64_t)ATV_FB_BASE + VISIBLE_BYTES <= UINT64_C(0x100000000),
    "framebuffer span exceeds the allowed physical range");
void visual_checkerboard(void)
{
    for (unsigned int y = 0; y < ATV_FB_HEIGHT; y++) {
        volatile uint32_t *row = (volatile uint32_t *)(uintptr_t)
            (ATV_FB_BASE + y * ATV_FB_STRIDE);
        unsigned int band = y * 4 / ATV_FB_HEIGHT;
        for (unsigned int tile = 0; tile < 8; tile++) {
            unsigned int start = tile * ATV_FB_WIDTH / 8;
            unsigned int end = (tile + 1) * ATV_FB_WIDTH / 8;
            /* Magenta and green are unchanged by swapping red and blue. */
            uint32_t color = ((band + tile) & 1) ? 0xffff00ffu : 0xff00ff00u;
            for (unsigned int x = start; x < end; x++)
                row[x] = color;
        }
    }
    /* Drain write-combining stores before halting. */
    __asm__ volatile("sfence" ::: "memory");
}

#ifndef ATV_VISUAL_PROGRESS
_Noreturn void atv_checkpoint(uint32_t mb_magic, uint32_t mb_info)
{
    (void)mb_magic;
    (void)mb_info;
    visual_checkerboard();
    __asm__ volatile("cli" ::: "memory");
    for (;;)
        __asm__ volatile("hlt");
}
#endif
