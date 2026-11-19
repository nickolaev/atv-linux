/* Returning diagnostic only: classify a captured EFI map, never load NetBSD. */
#ifdef PREFLIGHT_HOST
#include <fcntl.h>
#include <unistd.h>
static int open_input(const char *p) { return open(p, O_RDONLY); }
static int read_input(int fd, void *p, unsigned n) { return (int)read(fd, p, n); }
static void close_input(int fd) { close(fd); }
static void write_text(const char *p, unsigned n) {
    while (n) {
        ssize_t written = write(1, p, n);
        if (written <= 0) return;
        p += written;
        n -= (unsigned)written;
    }
}
#else
static int syscall3(int n, int a, int b, int c) {
    int result;
    __asm__ volatile("int $0x80" : "=a"(result) : "0"(n), "b"(a), "c"(b), "d"(c) : "memory");
    return result;
}
static int open_input(const char *p) { return syscall3(5, (int)p, 0, 0); }
static int read_input(int fd, void *p, unsigned n) { return syscall3(3, fd, (int)p, n); }
static void close_input(int fd) { (void)syscall3(6, fd, 0, 0); }
static void write_text(const char *p, unsigned n) { (void)syscall3(4, 1, (int)p, n); }
#endif

typedef unsigned int u32;
typedef unsigned long long u64;
#define CAPSIZE 8192u
#define MAPOFF 192u
#define LIMIT (~(u64)0)
static unsigned char capture[CAPSIZE];
static u32 rd32(const unsigned char *p) { return (u32)p[0] | (u32)p[1]<<8 | (u32)p[2]<<16 | (u32)p[3]<<24; }
static u64 rd64(const unsigned char *p) { return (u64)rd32(p) | (u64)rd32(p+4)<<32; }
static void text(const char *s) { const char *p = s; while (*p) ++p; write_text(s, (unsigned)(p-s)); }
static void hex64(u64 v) { char b[18]; unsigned i; u32 hi=(u32)(v>>32), lo=(u32)v; static const char d[] = "0123456789abcdef"; b[0]='0'; b[1]='x'; for (i=0; i<8; ++i) { b[2+i]=d[(hi >> ((7-i)*4)) & 15]; b[10+i]=d[(lo >> ((7-i)*4)) & 15]; } write_text(b,18); }
static u32 crc32_table(const unsigned char *p, u32 n) {
    u32 crc=0xffffffffu, i, bit;
    for (i=0;i<n;++i) { crc ^= i>=16 && i<20 ? 0 : p[i];
        for (bit=0;bit<8;++bit) crc=(crc>>1)^(0xedb88320u & (0u-(crc&1u))); }
    return crc^0xffffffffu;
}
/* Describe every covering descriptor, including contradictory overlaps. */
static void show_address(const char *label, u32 address, u32 size, u32 stride) {
    u32 off, found=0;
    text(label); text(": ");
    if (!address) { text("not captured\n"); return; }
    hex64(address); text("\n");
    for (off=MAPOFF;off<MAPOFF+size;off+=stride) {
        const unsigned char *d=capture+off;
        u64 base=rd64(d+8), end=base+(rd64(d+24)<<12);
        if (base<=address && address<end) {
            text("  EFI type "); hex64(rd32(d)); text(" attrs "); hex64(rd64(d+32));
            text(" ["); hex64(base); text(", "); hex64(end); text(")\n"); ++found;
        }
    }
    if (!found) text("  no covering descriptor\n");
}
static int fail(const char *s) { text("Preflight INVALID: "); text(s); text("\n"); return 1; }

__attribute__((used, noinline)) static int run(const char *path) {
    u32 size, stride, off, got=0, n, i, j, overlap_count=0; int fd, nr;
    u64 pos=LIMIT, next, low_start=0x00100000, low_end=0x00fa14d8,
        high_start=0x00fa2000, high_end=0x015a6000;
    int low=1, high=1, regions=0;
    fd=open_input(path); if (fd<0) return fail("snapshot file unavailable");
    while (got<CAPSIZE) { nr=read_input(fd,capture+got,CAPSIZE-got); if (nr<=0) break; got+=(u32)nr; }
    { unsigned char extra; nr=read_input(fd,&extra,1); }
    close_input(fd);
    if (got!=CAPSIZE || nr!=0) return fail("snapshot size or read error");
    if (rd32(capture)!=0x50414345 || (rd32(capture+4)!=0 && rd32(capture+4)!=3)) return fail("missing completion marker or status");
    size=rd32(capture+16); stride=rd32(capture+20);
    if (!size || size>CAPSIZE-MAPOFF || stride<40 || (stride&3) || size%stride || rd32(capture+24)!=1 || rd32(capture+44)!=size) return fail("map shape or version");
    n=size/stride;
    for (i=0,off=MAPOFF;i<n;++i,off+=stride) {
        u64 base=rd64(capture+off+8), pages=rd64(capture+off+24), bytes;
        if ((base&4095) || !pages || pages>(LIMIT>>12)) return fail("descriptor alignment or size");
        bytes=pages<<12; if (base>LIMIT-bytes) return fail("descriptor overflow");
        if (base<pos) pos=base;
    }
    text("\n--- NetBSD 11.1 snapshot preflight ---\n");
    if (rd32(capture+4)==0 && rd32(capture+48)>=72 && rd32(capture+48)<=128 &&
        rd64(capture+64)==0x5453595320494249ULL && rd32(capture+76)==rd32(capture+48)) {
        const unsigned char *table=capture+64;
        text("EFI system table CRC: "); text(crc32_table(table,rd32(capture+48))==rd32(table+16)?"VALID\n":"INVALID\n");
        text("Runtime services: "); hex64(rd32(table+56)); text("  Boot services: "); hex64(rd32(table+60)); text("\n");
        text("Config count: "); hex64(rd32(table+64)); text("  Config address: "); hex64(rd32(table+68)); text("\n");
        text("Config/ACPI contents not captured; pointers not validated.\n");
    } else text("EFI system table: unavailable or malformed\n");
    show_address("Hook ESP",rd32(capture+60),size,stride);
    text("Hook ESP is a point only; stack bounds are unknown.\n");
    show_address("Known loader base (not full footprint)",0x02000000u,size,stride);
    for (i=0;i<n;++i) for (j=i+1;j<n;++j) {
        const unsigned char *a=capture+MAPOFF+i*stride, *b=capture+MAPOFF+j*stride;
        u64 ab=rd64(a+8), ae=ab+(rd64(a+24)<<12), bb=rd64(b+8), be=bb+(rd64(b+24)<<12);
        if (ab<be && bb<ae) {
            if (overlap_count<8) { text("EFI overlap "); hex64(i); text("/"); hex64(j); text(" [");
                hex64(ab>bb?ab:bb); text(", "); hex64(ae<be?ae:be); text(")\n"); }
            ++overlap_count;
        }
    }
    text("EFI overlap pairs: "); hex64(overlap_count); if (overlap_count>8) text(" (first 8 shown)"); text("\n");
    text("Write-back conventional spans after firmware overlaps:\n");
    while (pos!=LIMIT) {
        int covered=0, restricted=0; next=LIMIT;
        for (i=0,off=MAPOFF;i<n;++i,off+=stride) {
            u32 type=rd32(capture+off); u64 base=rd64(capture+off+8), end=base+(rd64(capture+off+24)<<12), attrs=rd64(capture+off+32);
            if (base>pos && base<next) next=base;
            if (end>pos && end<next) next=end;
            if (base<=pos && pos<end) { covered=1; if (type!=7 || !(attrs&8) || (attrs>>63)) restricted=1; }
        }
        if (next==LIMIT) break;
        if (covered && !restricted) { text("  "); hex64(pos); text(" - "); hex64(next); text("\n"); ++regions; }
        else {
            if (pos<low_end && low_start<next) low=0;
            if (pos<high_end && high_start<next) high=0;
        }
        pos=next;
    }
    /* Account for uncovered prefixes/suffixes, including an empty map. */
    for (i=0;i<2;++i) {
        u64 start=i?high_start:low_start, end=i?high_end:low_end, cursor=start;
        while (cursor<end) {
            int covered=0, restricted=0; next=end;
            for (off=MAPOFF;off<MAPOFF+size;off+=stride) {
                u32 type=rd32(capture+off); u64 base=rd64(capture+off+8), stop=base+(rd64(capture+off+24)<<12), attrs=rd64(capture+off+32);
                if (base>cursor && base<next) next=base;
                if (stop>cursor && stop<next) next=stop;
                if (base<=cursor && cursor<stop) { covered=1; if(type!=7 || !(attrs&8) || (attrs>>63)) restricted=1; }
            }
            if (!covered || restricted) { if (i) high=0; else low=0; break; }
            cursor=next;
        }
    }
    if (!regions) text("  none\n");
    text("11.1 INSTALL metadata segment 1: "); text(low?"MAP-CANDIDATE\n":"NOT COVERED\n");
    text("11.1 INSTALL metadata segment 2: "); text(high?"MAP-CANDIDATE\n":"NOT COVERED\n");
    text("Metadata only: no kernel file was read. Loader, stack and firmware\n");
    text("allocation extents are unknown. Not a boot-safety result.\n");
    text("This snapshot applies only to the boot in which it was captured.\n");
    return 0;
}
#ifdef PREFLIGHT_HOST
int main(int argc, char **argv) { return run(argc==2 ? argv[1] : "/atv-probe.bin"); }
#else
__attribute__((used)) static const char default_path[] = "/atv-probe.bin";
__attribute__((naked, noreturn)) void _start(void) {
    __asm__ volatile(
        "cmpl $2, (%esp)\n\t"
        "jne 1f\n\t"
        "movl 8(%esp), %eax\n\t"
        "jmp 2f\n"
        "1: movl $default_path, %eax\n"
        "2: pushl %eax\n\t"
        "call run\n\t"
        "movl %eax, %ebx\n\t"
        "movl $1, %eax\n\t"
        "int $0x80\n\t"
        "ud2");
}
#endif
