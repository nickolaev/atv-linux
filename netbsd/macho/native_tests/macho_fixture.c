/* Synthetic Mach-O entry fixture. This is not a hardware loader. */
#include "../native/handoff.h"

extern const nb_u8 kernel_start[], kernel_end[], __image_end[];
extern int fixture_write(void *, nb_u32, const nb_u8 *, nb_u32);
extern int fixture_zero(void *, nb_u32, nb_u32);
static struct nb_emulation_inputs in;
static struct nb_emulation_result result;
static const struct nb_range usable[] = {
    {0x00100000, 0x02000000}, {0x02b58000, 0x08000000}
};
volatile nb_u32 fixture_status;

static nb_u32 read32(const nb_u8 *p)
{
    return p[0] | ((nb_u32)p[1] << 8) | ((nb_u32)p[2] << 16) | ((nb_u32)p[3] << 24);
}

void fixture_start(const nb_u8 *apple)
{
    nb_u32 map_pa = read32(apple + 0x404);
    in.apple_args = apple;
    in.apple_args_length = 0x44c;
    in.apple_args_pa = (nb_u32)(nb_uptr)apple;
    in.efi_map = (const void *)(nb_uptr)map_pa;
    in.efi_map_pa = map_pa;
    in.efi_map_length = read32(apple + 0x408);
    in.kernel = kernel_start;
    in.kernel_pa = (nb_u32)(nb_uptr)kernel_start;
    in.kernel_length = (nb_u32)(kernel_end - kernel_start);
    in.bootinfo = (void *)(nb_uptr)0x03010000;
    in.bootinfo_pa = 0x03010000;
    in.bootinfo_capacity = 16384;
    in.loader.start = 0x03fff000;
    in.loader.end = (nb_u32)(nb_uptr)__image_end;
    in.stack.start = 0x03004000;
    in.stack.end = 0x03008000;
    in.usable = usable;
    in.usable_count = 2;
    in.write_fn = fixture_write;
    in.zero_fn = fixture_zero;
    if (nb_prepare_native_emulation(&in, &result)) {
        fixture_status = 0xbad;
        return;
    }
    fixture_status = 0x600d;
    nb_enter_native(result.plan.entry, 0x03008000, 0x42, result.bootinfo_pa, 0, 0, 0);
}
