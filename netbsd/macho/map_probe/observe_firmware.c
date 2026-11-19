/* Linux-time, read-only observation; never authorizes a NetBSD handoff. */
#ifdef OBSERVE_HOST
#define _XOPEN_SOURCE 700
#include <fcntl.h>
#include <unistd.h>
static int open_ro(const char *p) { return open(p, O_RDONLY); }
static int read_seq(int fd, void *p, unsigned n) { return (int)read(fd, p, n); }
static int read_at(int fd, void *p, unsigned n, unsigned addr) { return (int)pread(fd, p, n, addr); }
static void close_fd(int fd) { (void)close(fd); }
static void write_out(const char *p, unsigned n) {
    while (n) { ssize_t r=write(1,p,n); if (r<=0) return; p+=r; n-=(unsigned)r; }
}
#else
static int sys3(int n, int a, int b, int c) {
    int r; __asm__ volatile("int $0x80" : "=a"(r) : "0"(n), "b"(a), "c"(b), "d"(c) : "memory"); return r;
}
static int open_ro(const char *p) { return sys3(5,(int)p,0,0); }
static int read_seq(int fd, void *p, unsigned n) { return sys3(3,fd,(int)p,n); }
/* IA-32 Linux pread64 syscall: offset in ESI:EDI (low:high). */
static int read_at(int fd, void *p, unsigned n, unsigned addr) {
    int r; register unsigned lo __asm__("esi")=addr, hi __asm__("edi")=0;
    __asm__ volatile("int $0x80" : "=a"(r) : "0"(180), "b"(fd), "c"(p), "d"(n), "S"(lo), "D"(hi) : "memory"); return r;
}
static void close_fd(int fd) { (void)sys3(6,fd,0,0); }
static void write_out(const char *p, unsigned n) { (void)sys3(4,1,(int)p,n); }
#endif

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;
#define CAPSIZE 8192u
#define MAPOFF 192u
#define TOP 0x10000000u
#define MAXCFG 64u
#define MAXROOT 4096u
#define MAXSDT (1024u*1024u)
#define MAXCHILD 64u
static u8 capture[CAPSIZE], cfg[MAXCFG*20], cfg_again[MAXCFG*20], data[MAXROOT], roots[MAXROOT], live[128];
static u32 map_size, stride;
static u32 get32(const u8 *p) { return (u32)p[0] | (u32)p[1]<<8 | (u32)p[2]<<16 | (u32)p[3]<<24; }
static u32 get16(const u8 *p) { return (u32)p[0] | (u32)p[1]<<8; }
static u64 get64(const u8 *p) { return (u64)get32(p) | (u64)get32(p+4)<<32; }
static int same(const u8 *a, const u8 *b, u32 n) { u32 i; for(i=0;i<n;i++) if(a[i]!=b[i]) return 0; return 1; }
static int sum_ok(const u8 *p, u32 n) { u32 i,s=0; for(i=0;i<n;i++) s+=p[i]; return !(s&255); }
static u32 crc32_table(const u8 *p, u32 n) {
    u32 crc=~0u,i,j; for(i=0;i<n;i++) { crc ^= i>=16 && i<20 ? 0 : p[i];
        for(j=0;j<8;j++) crc=(crc>>1)^(0xedb88320u & (0u-(crc&1u))); } return ~crc;
}
static void text(const char *s) { const char *p=s; while(*p) ++p; write_out(s,(u32)(p-s)); }
static void hex(u32 v, u32 digits) { static const char d[]="0123456789abcdef"; char b[8]; u32 i; for(i=0;i<digits;i++) b[i]=d[(v>>((digits-i-1)*4))&15]; write_out(b,digits); }
static void guid(const u8 *p) {
    u32 i; hex(get32(p),8); text("-"); hex((u32)p[4]|(u32)p[5]<<8,4); text("-");
    hex((u32)p[6]|(u32)p[7]<<8,4); text("-");
    for(i=8;i<16;i++) { if(i==10) text("-"); hex(p[i],2); }
}
static int fail(const char *s) { text("UNAVAILABLE: "); text(s); text("\n"); return 1; }
/* Require a single covering data descriptor and reject conflicting types.
 * Conventional overlap is allowed only as additional evidence, never coverage. */
static int covered(u32 addr, u32 len) {
    u32 off, typeseen=0; int found=0; u64 end=(u64)addr+len;
    if(addr<4096 || !len || end>TOP) return 0;
    for(off=MAPOFF;off<MAPOFF+map_size;off+=stride) {
        const u8 *d=capture+off; u64 base=get64(d+8), stop=base+(get64(d+24)<<12); u32 type=get32(d);
        if(base>=end || addr>=stop) continue;
        if(type==7) continue;
        if(type!=2 && type!=4 && type!=6 && type!=9 && type!=10) return 0;
        if(typeseen && typeseen!=type) return 0;
        typeseen=type;
        if(base<=addr && stop>=end) found=1;
    }
    return found;
}
static int take(int fd, u32 addr, u8 *out, u32 n) {
    u32 done=0; int r;
    if(!covered(addr,n)) return 0;
    while(done<n) { r=read_at(fd,out+done,n-done,addr+done); if(r<=0 || (u32)r>n-done) return 0; done+=(u32)r; }
    return 1;
}
static void signature(const u8 *p) {
    u32 i; char c;
    for(i=0;i<4;i++) { c=(p[i]>=0x20 && p[i]<=0x7e)?(char)p[i]:'.'; write_out(&c,1); }
}
/* Stream the checksum without trusting a length until its full range is
 * covered. Tables and entry pointers are observations after Linux starts. */
static int sdt_sum(int fd, u32 addr, u32 n, const u8 *header) {
    u32 off=0, sum=0, i, chunk;
    if(n<36 || n>MAXSDT || !covered(addr,n)) return 0;
    while(off<n) {
        chunk=n-off; if(chunk>MAXROOT) chunk=MAXROOT;
        if(!take(fd,addr+off,data,chunk)) return 0;
        if(!off && (chunk<36 || !same(data,header,36))) return 0;
        for(i=0;i<chunk;i++) sum+=data[i];
        off+=chunk;
    }
    return (sum&255)?-1:1;
}
static void nested(int fd, const char *name, u64 address, int facs) {
    u8 header[36]; u32 i,n; int valid;
    text("    "); text(name); text("=0x");
    if(address>0xffffffffu) { text("above 32-bit; unavailable\n"); return; }
    hex((u32)address,8);
    if(!address) { text(" absent\n"); return; }
    if(!take(fd,(u32)address,data,36)) { text(" unavailable\n"); return; }
    for(i=0;i<36;i++) header[i]=data[i];
    n=get32(header+4);
    if(!same(header,(const u8 *)name,4) || n<(facs?64u:36u) || n>MAXSDT || !covered((u32)address,n)) {
        text(" invalid/unavailable\n"); return;
    }
    text(" length=0x"); hex(n,8);
    if(facs) { text(" (header only; no checksum)\n"); return; }
    valid=sdt_sum(fd,(u32)address,n,header);
    text(valid>0?" checksum=valid\n":valid<0?" checksum=invalid\n":" unavailable/changed\n");
}
static void child(int fd, u64 address, u32 index) {
    u8 header[36], fadt[148]; u32 i,n,copy; int valid;
    u64 facs=0,dsdt=0;
    text("  child 0x"); hex(index,2); text(" address=");
    if(address>0xffffffffu) { text("above 32-bit; unavailable\n"); return; }
    text("0x"); hex((u32)address,8);
    if(!address || !take(fd,(u32)address,data,36)) { text(" unavailable\n"); return; }
    for(i=0;i<36;i++) header[i]=data[i];
    n=get32(header+4); text(" signature="); signature(header);
    text(" length=0x"); hex(n,8);
    if(n<36 || n>MAXSDT || !covered((u32)address,n)) { text(" invalid/unavailable\n"); return; }
    copy=n<sizeof(fadt)?n:(u32)sizeof(fadt);
    if(same(header,(const u8 *)"FACP",4)) {
        if(!take(fd,(u32)address,fadt,copy) || !same(fadt,header,36)) { text(" unavailable/changed\n"); return; }
        if(copy>=44) { facs=get32(fadt+36); dsdt=get32(fadt+40); }
        if(copy>=148) { if(get64(fadt+132)) facs=get64(fadt+132); if(get64(fadt+140)) dsdt=get64(fadt+140); }
    }
    valid=sdt_sum(fd,(u32)address,n,header);
    text(valid>0?" checksum=valid\n":valid<0?" checksum=invalid\n":" unavailable/changed\n");
    if(valid>0 && same(header,(const u8 *)"FACP",4) && copy>=44) {
        nested(fd,"FACS",facs,1); nested(fd,"DSDT",dsdt,0);
    }
}
static void root(int fd, u64 addr, int xsdt) {
    const char *name=xsdt?"XSDT":"RSDT"; u32 n, i, count, width=xsdt?8u:4u;
    text("  "); text(name); text(" address=");
    if(addr>0xffffffffu) { text("above 32-bit; unavailable\n"); return; }
    text("0x"); hex((u32)addr,8);
    if(!addr || !take(fd,(u32)addr,data,36)) { text(" unavailable\n"); return; }
    n=get32(data+4);
    if(n<36 || n>MAXROOT || (n-36)%(xsdt?8u:4u) || !take(fd,(u32)addr,data,n) ||
       !same(data,(const u8 *)name,4) || get32(data+4)!=n) { text(" invalid/unavailable\n"); return; }
    text(" length=0x"); hex(n,8); text(" checksum=");
    if(!sum_ok(data,n)) { text("invalid; children not read\n"); return; }
    text("valid\n");
    for(i=0;i<n;i++) roots[i]=data[i];
    count=(n-36)/width;
    if(count>MAXCHILD) { text("  Children limited to first 0x"); hex(MAXCHILD,2); text(" entries.\n"); count=MAXCHILD; }
    for(i=0;i<count;i++) child(fd,xsdt?get64(roots+36+i*width):get32(roots+36+i*width),i);
}
static void inspect_smbios(int fd, u32 addr) {
    u32 n, table, size, count;
    text("  SMBIOS2 entry=0x"); hex(addr,8);
    if(!take(fd,addr,data,31) || !same(data,(const u8 *)"_SM_",4)) { text(" invalid/unavailable\n"); return; }
    n=data[5];
    if(n<31 || !take(fd,addr,data,n) || !same(data,(const u8 *)"_SM_",4) || data[5]!=n ||
       !same(data+16,(const u8 *)"_DMI_",5)) { text(" invalid/unavailable\n"); return; }
    table=get32(data+24); size=get16(data+22); count=get16(data+28);
    text(" entry_checksum="); text(sum_ok(data,n)?"valid":"invalid");
    text(" dmi_checksum="); text(sum_ok(data+16,15)?"valid":"invalid");
    text(" version=0x"); hex(data[6],2); text("."); hex(data[7],2); text("\n");
    text("  structures=0x"); hex(table,8); text(" bytes=0x"); hex(size,4);
    text(" count=0x"); hex(count,4); text(covered(table,size)?" descriptor-covered\n":" unavailable/uncovered\n");
    text("  Structure records not read or validated.\n");
}
static void inspect_rsdp(int fd, u32 addr) {
    u32 n; u8 revision; u32 rsdt; u64 xsdt=0;
    text("  RSDP=0x"); hex(addr,8);
    if(!take(fd,addr,data,20) || !same(data,(const u8 *)"RSD PTR ",8) || !sum_ok(data,20)) { text(" invalid/unavailable\n"); return; }
    revision=data[15]; rsdt=get32(data+16);
    if(revision==1) { text(" unsupported revision\n"); return; }
    if(revision>=2) {
        if(!take(fd,addr,data,36)) { text(" truncated\n"); return; }
        n=get32(data+20);
        if(n<36 || n>256 || !take(fd,addr,data,n) || !same(data,(const u8 *)"RSD PTR ",8) ||
           data[15]<2 || get32(data+20)!=n || !sum_ok(data,20) || !sum_ok(data,n)) { text(" invalid/unavailable\n"); return; }
        revision=data[15]; rsdt=get32(data+16); xsdt=get64(data+24);
    }
    text(" checksum valid; revision=0x"); hex(revision,2); text("\n");
    if(rsdt) root(fd,rsdt,0);
    if(xsdt) root(fd,xsdt,1);
    if(!rsdt && !xsdt) text("  No root table pointer.\n");
}
__attribute__((used,noinline)) static int run(const char *snapshot_path, const char *memory_path) {
    static const u8 acpi10[16]={0x30,0x2d,0x9d,0xeb,0x88,0x2d,0xd3,0x11,0x9a,0x16,0x00,0x90,0x27,0x3f,0xc1,0x4d};
    static const u8 acpi20[16]={0x71,0xe8,0x68,0x88,0xf1,0xe4,0xd3,0x11,0xbc,0x22,0x00,0x80,0xc7,0x3c,0x88,0x81};
    static const u8 smbios2[16]={0x31,0x2d,0x9d,0xeb,0x88,0x2d,0xd3,0x11,0x9a,0x16,0x00,0x90,0x27,0x3f,0xc1,0x4d};
    int fd,r; u32 done=0,off,sz,sys, count,config,i; u8 extra;
    text("Linux-time observation only; not an entry snapshot or boot-safety proof.\n");
    fd=open_ro(snapshot_path); if(fd<0) return fail("snapshot open failed");
    while(done<CAPSIZE) { r=read_seq(fd,capture+done,CAPSIZE-done); if(r<=0) break; done+=(u32)r; }
    r=read_seq(fd,&extra,1); close_fd(fd);
    if(done!=CAPSIZE || r!=0 || get32(capture)!=0x50414345 || get32(capture+4)!=0) return fail("incomplete snapshot or table");
    map_size=get32(capture+16); stride=get32(capture+20); sz=get32(capture+48); sys=get32(capture+28);
    if(!map_size || map_size>8000 || stride<40 || (stride&3) || map_size%stride || get32(capture+24)!=1 ||
       get32(capture+44)!=map_size || sz<72 || sz>128 || get32(capture+52)!=32 || (sys&3)) return fail("invalid snapshot shape");
    for(off=MAPOFF;off<MAPOFF+map_size;off+=stride) {
        u64 base=get64(capture+off+8), pages=get64(capture+off+24);
        if((base&4095) || !pages || pages>((~(u64)0-base)>>12)) return fail("invalid EFI descriptor");
    }
    if(!same(capture+64,(const u8 *)"IBI SYST",8) || get32(capture+76)!=sz ||
       crc32_table(capture+64,sz)!=get32(capture+80)) return fail("snapshot system table CRC or header invalid");
    count=get32(capture+128); config=get32(capture+132);
    if(count>MAXCFG || (count && (!config || (config&3)))) return fail("invalid config count or pointer");
    fd=open_ro(memory_path); if(fd<0) return fail("physical memory open denied");
    if(!take(fd,sys,live,sz) || !same(live,capture+64,sz)) { close_fd(fd); return fail("live system table unavailable or changed"); }
    if(count && (!take(fd,config,cfg,count*20) || !take(fd,config,cfg_again,count*20) ||
                 !same(cfg,cfg_again,count*20))) { close_fd(fd); return fail("config array unavailable or changed"); }
    if(!take(fd,sys,live,sz) || !same(live,capture+64,sz)) { close_fd(fd); return fail("live system table changed during read"); }
    text("Config entries: 0x"); hex(count,8); text("\n");
    for(i=0;i<count;i++) {
        const u8 *p=cfg+i*20; u32 address=get32(p+16);
        text("GUID "); guid(p); text(" pointer=0x"); hex(address,8); text("\n");
        if(same(p,acpi10,16) || same(p,acpi20,16)) inspect_rsdp(fd,address);
        else if(same(p,smbios2,16)) inspect_smbios(fd,address);
    }
    close_fd(fd);
    text("Captured descriptors can be stale; Linux may reuse firmware memory.\n");
    text("Readability, pointer identity, object lifetime and table semantics remain unproven.\n");
    return 0;
}
#ifdef OBSERVE_HOST
int main(int argc,char **argv) { if(argc!=3) return fail("usage: observer SNAPSHOT MEMORY-FILE"); return run(argv[1],argv[2]); }
#else
__attribute__((used)) static const char snap_default[]="/atv-probe.bin", mem_default[]="/dev/mem";
__attribute__((naked,noreturn)) void _start(void) {
    __asm__ volatile("cmpl $3, (%esp)\n\tje 1f\n\tcmpl $1, (%esp)\n\tjne 3f\n"
                     "movl $snap_default, %eax\n\tmovl $mem_default, %edx\n\tjmp 2f\n"
                     "1: movl 8(%esp), %eax\n\tmovl 12(%esp), %edx\n"
                     "2: pushl %edx\n\tpushl %eax\n\tcall run\n\tmovl %eax, %ebx\n\tjmp 4f\n"
                     "3: movl $2, %ebx\n"
                     "4: movl $1, %eax\n\tint $0x80\n\tud2");
}
#endif
