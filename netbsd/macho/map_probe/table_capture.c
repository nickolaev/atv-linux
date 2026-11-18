#include "table_capture.h"

static tc_u32 le32(const tc_u8 *p) {
    return (tc_u32)p[0] | ((tc_u32)p[1] << 8) |
           ((tc_u32)p[2] << 16) | ((tc_u32)p[3] << 24);
}
static tc_u64 le64(const tc_u8 *p) { return le32(p) | ((tc_u64)le32(p + 4) << 32); }
static int equal(const tc_u8 *a, const tc_u8 *b, tc_u32 n) {
    tc_u32 i; for (i = 0; i < n; ++i) if (a[i] != b[i]) return 0; return 1;
}
static int checksum(const tc_u8 *p, tc_u32 n) {
    tc_u32 i, s = 0; for (i = 0; i < n; ++i) s += p[i]; return (s & 255) == 0;
}
static int system_crc_ok(const tc_u8 *p, tc_u32 length) {
    tc_u32 i, j, crc = 0xffffffffu, size = le32(p + 12);
    if (size < 72 || size > 128 || size > length) return 0;
    for (i = 0; i < size; ++i) {
        crc ^= i >= 16 && i < 20 ? 0 : p[i];
        for (j = 0; j < 8; ++j) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return (crc ^ 0xffffffffu) == le32(p + 16);
}
static int safe(const tc_u8 *map, tc_u32 length, tc_u32 stride,
                const struct tc_range *protected, tc_u32 n, tc_u32 addr, tc_u32 size) {
    tc_u64 end = (tc_u64)addr + size; tc_u32 i; int covered = 0;
    if (addr < 0x1000 || !size || end > 0x10000000u) return 0;
    for (i = 0; i < n; ++i) {
        if (protected[i].start >= protected[i].end || protected[i].end > 0x100000000ULL)
            return 0;
        if (addr < protected[i].end && protected[i].start < end) return 0;
    }
    for (i = 0; i < length; i += stride) {
        const tc_u8 *d = map + i; tc_u64 start = le64(d + 8), pages = le64(d + 24), stop;
        tc_u32 type = le32(d);
        if ((start & 4095) || !pages || pages > (((tc_u64)-1 - start) >> 12)) return 0;
        stop = start + (pages << 12);
        if (addr >= stop || start >= end) continue;
        if (type != 2 && type != 4 && type != 6 && type != 7 && type != 9 && type != 10)
            return 0;
        if (start <= addr && stop >= end) covered = 1;
    }
    return covered;
}
int tc_capture_tables(const tc_u8 *map, tc_u32 map_length, tc_u32 stride,
                      const tc_u8 *system, tc_u32 system_length,
                      const struct tc_range *protected, tc_u32 protected_count,
                      tc_read_fn read, void *context, struct tc_capture *out) {
    static const tc_u8 acpi10[16] = {0x30,0x2d,0x9d,0xeb,0x88,0x2d,0xd3,0x11,0x9a,0x16,0x00,0x90,0x27,0x3f,0xc1,0x4d};
    static const tc_u8 acpi20[16] = {0x71,0xe8,0x68,0x88,0xf1,0xe4,0xd3,0x11,0xbc,0x22,0x00,0x80,0xc7,0x3c,0x88,0x81};
    static const tc_u8 signature[8] = {'R','S','D',' ','P','T','R',' '};
    tc_u8 config[TC_CONFIG_MAX], rsdp[TC_RSDP_MAX];
    tc_u32 count, addr, size, i, selected = 0, selected_version = 0, rsdp_size = 0;
    if (!map || !system || !protected || !protected_count || protected_count > 64 || !read || !out ||
        stride < 40 || (stride & 3) || !map_length || map_length % stride || map_length / stride > 256 ||
        system_length < 72 || !equal(system, (const tc_u8 *)"IBI SYST", 8) ||
        !system_crc_ok(system, system_length)) return -1;
    count = le32(system + 64); addr = le32(system + 68);
    if (!count || count > TC_CONFIG_MAX / 20) return -1;
    size = count * 20;
    if (!safe(map, map_length, stride, protected, protected_count, addr, size) ||
        read(context, addr, config, size)) return -1;
    for (i = 0; i < count; ++i) {
        const tc_u8 *p = config + i * 20; tc_u32 version = 0;
        if (equal(p, acpi20, 16)) version = 2;
        else if (equal(p, acpi10, 16)) version = 1;
        if (version && version > selected_version) {
            selected = le32(p + 16); selected_version = version;
        } else if (version && version == selected_version) return -1;
    }
    if (!selected || !safe(map, map_length, stride, protected, protected_count, selected, 20) ||
        read(context, selected, rsdp, 20) || !equal(rsdp, signature, 8) || !checksum(rsdp, 20)) return -1;
    rsdp_size = 20;
    if (rsdp[15] == 1) return -1;
    if (rsdp[15] >= 2) {
        if (!safe(map, map_length, stride, protected, protected_count, selected, 36) ||
            read(context, selected, rsdp, 36)) return -1;
        rsdp_size = le32(rsdp + 20);
        if (rsdp_size < 36 || rsdp_size > TC_RSDP_MAX ||
            !safe(map, map_length, stride, protected, protected_count, selected, rsdp_size) ||
            read(context, selected, rsdp, rsdp_size) || !equal(rsdp, signature, 8) ||
            rsdp[15] < 2 || le32(rsdp + 20) != rsdp_size ||
            !checksum(rsdp, 20) || !checksum(rsdp, rsdp_size)) return -1;
    }
    /* All sources were checked and copied into scratch before touching output. */
    out->config_address = addr; out->config_length = size;
    out->rsdp_address = selected; out->rsdp_length = rsdp_size;
    for (i = 0; i < size; ++i) out->config[i] = config[i];
    for (i = 0; i < rsdp_size; ++i) out->rsdp[i] = rsdp[i];
    return 0;
}
