/* Compiler-generated struct copies in the isolated freestanding test. */
#ifndef TARGET_EMULATION_ONLY
#error This helper is restricted to controlled emulation
#endif
void *memcpy(void *destination, const void *source, __SIZE_TYPE__ count)
{
    unsigned char *d = destination;
    const unsigned char *s = source;
    __SIZE_TYPE__ i;
    for (i = 0; i < count; ++i) d[i] = s[i];
    return destination;
}
