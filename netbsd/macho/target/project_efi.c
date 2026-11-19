#include "project_efi.h"

#ifdef TARGET_EMULATION_ONLY
#define LIMIT ((nb_u64)1 << 32)
#define MAX_CONFIG 64u
static nb_u32 u32(const nb_u8 *p) {
    return (nb_u32)p[0] | (nb_u32)p[1]<<8 | (nb_u32)p[2]<<16 | (nb_u32)p[3]<<24;
}
static void put32(nb_u8 *p, nb_u32 v) {
    p[0]=(nb_u8)v; p[1]=(nb_u8)(v>>8); p[2]=(nb_u8)(v>>16); p[3]=(nb_u8)(v>>24);
}
static int eq(const nb_u8 *a, const nb_u8 *b, nb_u32 n) {
    nb_u32 i; for(i=0;i<n;++i) if(a[i]!=b[i]) return 0; return 1;
}
static nb_u32 crc(const nb_u8 *p, nb_u32 n) {
    nb_u32 c=~0u,i,j;
    for(i=0;i<n;++i) { c^=(i>=16 && i<20)?0:p[i];
        for(j=0;j<8;++j) c=(c>>1)^(0xedb88320u & (0u-(c&1u))); }
    return ~c;
}
static int overlap(nb_u64 a, nb_u64 ae, nb_u64 b, nb_u64 be) {
    return a<be && b<ae;
}
static int aliases(const void *a, nb_u64 an, const void *b, nb_u64 bn) {
    nb_uptr x=(nb_uptr)a,y=(nb_uptr)b;
    if(an>(nb_uptr)-1-x || bn>(nb_uptr)-1-y) return 1;
    return overlap(x,(nb_u64)x+an,y,(nb_u64)y+bn);
}
int target_project_efi(const void *system, nb_u32 system_length, nb_u32 system_pa,
    const void *config, nb_u32 config_length, nb_u32 config_pa, nb_u32 owned_pa,
    target_project_validate_fn validate, void *context, void *owned_pages,
    struct target_project_result *out) {
    static const nb_u8 acpi1[16]={0x30,0x2d,0x9d,0xeb,0x88,0x2d,0xd3,0x11,0x9a,0x16,0,0x90,0x27,0x3f,0xc1,0x4d};
    static const nb_u8 acpi2[16]={0x71,0xe8,0x68,0x88,0xf1,0xe4,0xd3,0x11,0xbc,0x22,0,0x80,0xc7,0x3c,0x88,0x81};
    static const nb_u8 smbios2[16]={0x31,0x2d,0x9d,0xeb,0x88,0x2d,0xd3,0x11,0x9a,0x16,0,0x90,0x27,0x3f,0xc1,0x4d};
    static const nb_u8 smbios3[16]={0x44,0x15,0xfd,0xf2,0x94,0x97,0x2c,0x4a,0x99,0x2e,0xe5,0xbb,0xcf,0x20,0xe3,0x94};
    const nb_u8 *st=system,*cfg=config;
    nb_u8 header[72], projected_config[60];
    struct target_project_result result;
    struct nb_range ranges[TARGET_PROJECT_MAX_RANGES];
    nb_u32 count,seen=0,i,j,k,n;
    nb_u64 owned_end=(nb_u64)owned_pa+8192u, source_end;
    if(!system || !config || !validate || !owned_pages || !out || system_length!=72 ||
       system_pa<4096 || config_pa<4096 || owned_pa<4096 ||
       ((system_pa|config_pa)&3) || (owned_pa&4095u) || owned_end>=LIMIT ||
       (nb_u64)system_pa+72>LIMIT || (nb_u64)config_pa+config_length>LIMIT ||
       aliases(out,sizeof(*out),system,system_length) || aliases(out,sizeof(*out),config,config_length) ||
       aliases(owned_pages,8192,system,system_length) ||
       aliases(owned_pages,8192,config,config_length) ||
       aliases(owned_pages,8192,out,sizeof(*out))) return -1;
    if(!eq(st,(const nb_u8 *)"IBI SYST",8) || u32(st+12)!=72 || crc(st,72)!=u32(st+16)) return -1;
    count=u32(st+64); if(!count || count>MAX_CONFIG || config_length!=count*20 || u32(st+68)!=config_pa) return -1;
    source_end=(nb_u64)config_pa+config_length;
    if(overlap(owned_pa,owned_end,system_pa,(nb_u64)system_pa+72) ||
       overlap(owned_pa,owned_end,config_pa,source_end) ||
       overlap(system_pa,(nb_u64)system_pa+72,config_pa,source_end)) return -1;
    for(i=0;i<sizeof(result);++i) ((nb_u8 *)&result)[i]=0;
    for(i=0;i<sizeof(header);++i) header[i]=0;
    for(i=0;i<sizeof(projected_config);++i) projected_config[i]=0;
    for(i=0;i<count;++i) {
        const nb_u8 *entry=cfg+i*20; nb_u32 kind=0, bit=0, addr=u32(entry+16);
        if(eq(entry,acpi1,16)) { kind=TARGET_PROJECT_ACPI1; bit=1; }
        else if(eq(entry,acpi2,16)) { kind=TARGET_PROJECT_ACPI2; bit=2; }
        else if(eq(entry,smbios2,16)) { kind=TARGET_PROJECT_SMBIOS2; bit=4; }
        else if(eq(entry,smbios3,16)) return -1;
        else continue; /* Do not follow dropped firmware pointers. */
        if((seen&bit) || addr<4096) return -1;
        seen|=bit; n=TARGET_PROJECT_MAX_RANGES;
        if(validate(context,kind,addr,owned_pa,owned_end,ranges,&n) ||
           !n || n>TARGET_PROJECT_MAX_RANGES) return -1;
        { int covers=0;
          for(j=0;j<n;++j) {
            if(ranges[j].start>=ranges[j].end || ranges[j].end>LIMIT ||
               overlap(owned_pa,owned_end,ranges[j].start,ranges[j].end)) return -1;
            if(ranges[j].start<=addr && addr<ranges[j].end) covers=1;
            for(k=0;k<result.reservation_count;++k)
                if(result.reservations[k].start==ranges[j].start && result.reservations[k].end==ranges[j].end) break;
            if(k==result.reservation_count) {
                if(k>=TARGET_PROJECT_MAX_RANGES) return -1;
                result.reservations[k].start=ranges[j].start;
                result.reservations[k].end=ranges[j].end;
                ++result.reservation_count;
            }
          }
          if(!covers) return -1;
        }
        for(j=0;j<20;++j) projected_config[result.count*20+j]=entry[j];
        ++result.count;
    }
    if(!(seen&3) || !(seen&4)) return -1;
    /* EFI system header retained, all unneeded original service pointers zero.
     * The owned config is nonzero even when optional original entries drop. */
    for(i=0;i<24;++i) header[i]=st[i];
    put32(header+64,result.count); put32(header+68,owned_pa+4096);
    put32(header+16,crc(header,72));
    for(i=0;i<8192;++i) ((nb_u8 *)owned_pages)[i]=0;
    for(i=0;i<sizeof(header);++i) ((nb_u8 *)owned_pages)[i]=header[i];
    for(i=0;i<sizeof(projected_config);++i) ((nb_u8 *)owned_pages)[4096+i]=projected_config[i];
    for(i=0;i<sizeof(result);++i) ((nb_u8 *)out)[i]=((const nb_u8 *)&result)[i];
    return 0;
}
#endif
