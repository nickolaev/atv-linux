/* Visual landmarks for the verified NetBSD 11.1 i386 Multiboot path. */
#include <stdint.h>
#include "stages_layout.h"

_Static_assert(STAGES_MMIO_PAGES > 0 && STAGES_MMIO_PAGES < 256,
    "temporary framebuffer alias must fit below kernel text");
_Static_assert(ATV_FB_STRIDE <= UINT16_MAX, "NetBSD bootinfo stride is 16-bit");
_Static_assert(STAGES_TILES <= 7 && ATV_FB_WIDTH / STAGES_TILES >= 7 && STAGES_ROWS >= 11,
    "the marker strip must fit its seven-segment digits");

void visual_checkerboard(void);

static uint64_t read_tsc(void)
{
    uint32_t low, high;
    __asm__ volatile("rdtsc" : "=a"(low), "=d"(high));
    return (uint64_t)high << 32 | low;
}

void atv_checkpoint(uint32_t mb_magic, uint32_t mb_info)
{
    (void)mb_magic;
    (void)mb_info;
    visual_checkerboard();
    uint64_t start = read_tsc();
    /* The Apple TV's measured TSC is 1 GHz. Also bound the iteration count. */
    for (unsigned int spin = 0; spin < (1u << 27); spin++) {
        if (read_tsc() - start >= UINT64_C(800000000))
            break;
        __asm__ volatile("pause");
    }
}

/* This routine is also called from the temporary high alias after paging. */
void visual_stage_draw(uint32_t framebuffer, unsigned int tile, uint32_t color)
{
    unsigned int start = tile * ATV_FB_WIDTH / STAGES_TILES;
    unsigned int end = (tile + 1) * ATV_FB_WIDTH / STAGES_TILES;
    for (unsigned int y = 0; y < STAGES_ROWS; y++) {
        volatile uint32_t *row = (volatile uint32_t *)(uintptr_t)
            (framebuffer + y * ATV_FB_STRIDE);
        for (unsigned int x = start; x < end; x++)
            row[x] = color;
    }

    /* Seven-segment masks for 1–4 and 5–7, kept in instruction immediates. */
    enum { TOP = 1, UPPER_RIGHT = 2, LOWER_RIGHT = 4, BOTTOM = 8,
        LOWER_LEFT = 16, UPPER_LEFT = 32, MIDDLE = 64 };
    uint32_t masks = tile < 4 ? 0x664f5b06u : 0x00077d6du;
    unsigned int digit = (masks >> ((tile & 3u) * 8)) & 0x7fu;
    unsigned int scale = (end - start) / 7;
    if (scale > STAGES_ROWS / 11)
        scale = STAGES_ROWS / 11;
    unsigned int left = start + (end - start - 7 * scale) / 2;
    unsigned int top = (STAGES_ROWS - 11 * scale) / 2;
    for (unsigned int y = 0; y < 11 * scale; y++) {
        volatile uint32_t *row = (volatile uint32_t *)(uintptr_t)
            (framebuffer + (top + y) * ATV_FB_STRIDE);
        unsigned int line = y / scale;
        for (unsigned int x = 0; x < 7 * scale; x++) {
            unsigned int column = x / scale;
            unsigned int segment = 0;
            if (line < 2 || line == 5 || line >= 9) {
                if (column >= 1 && column <= 5)
                    segment = line < 2 ? TOP : (line == 5 ? MIDDLE : BOTTOM);
            } else if (column < 2) {
                segment = line < 5 ? UPPER_LEFT : LOWER_LEFT;
            } else if (column >= 5) {
                segment = line < 5 ? UPPER_RIGHT : LOWER_RIGHT;
            }
            if (digit & segment)
                row[left + x] = STAGES_COLOR(0, 0, 0);
        }
    }
    __asm__ volatile("sfence" ::: "memory");
}

void visual_stage_physical(unsigned int tile)
{
    visual_stage_draw(ATV_FB_BASE, tile,
        tile == 0 ? STAGES_COLOR(0, 255, 255) : STAGES_COLOR(255, 255, 0));
}

void visual_stage_prepare_paging(uint32_t table_base)
{
    volatile uint32_t *pte = (volatile uint32_t *)(uintptr_t)
        (table_base + STAGES_KERNEL_PT_OFFSET);
    for (unsigned int i = 0; i <= STAGES_MMIO_PAGES; i++) {
        if (pte[i] != 0) {
            visual_stage_draw(ATV_FB_BASE, 2, STAGES_COLOR(255, 0, 0));
            __asm__ volatile("cli" ::: "memory");
            for (;;)
                __asm__ volatile("hlt");
        }
    }
    pte[0] = STAGES_PHYSICAL_CODE | 1;
    for (unsigned int i = 0; i < STAGES_MMIO_PAGES; i++)
        pte[1 + i] = (STAGES_FB_PAGE + i * 0x1000u) | 0x1bu; /* RW, PWT, PCD, present. */
    visual_stage_draw(ATV_FB_BASE, 2, STAGES_COLOR(0, 128, 255));
}
