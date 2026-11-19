/* Test-only callbacks. Never link into or use for a hardware image. */
#include "../native/handoff.h"

int fixture_write(void *context, nb_u32 address, const nb_u8 *source, nb_u32 length)
{
    volatile nb_u8 *destination = (volatile nb_u8 *)(nb_uptr)address;
    nb_u32 i;
    (void)context;
    for (i = 0; i < length; ++i) destination[i] = source[i];
    return 0;
}

int fixture_zero(void *context, nb_u32 address, nb_u32 length)
{
    volatile nb_u8 *destination = (volatile nb_u8 *)(nb_uptr)address;
    nb_u32 i;
    (void)context;
    for (i = 0; i < length; ++i) destination[i] = 0;
    return 0;
}
