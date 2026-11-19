#include "firmware.h"

#define FW_LIMIT ((nb_u64)1 << 32)
#define FW_MAX_DESC 256u
#define FW_MAX_CONFIG 64u
#define FW_MAX_TABLE 4096u
#define FW_MAX_CHILD (1024u * 1024u)

static nb_u32 u32(const nb_u8 *p) {
    return (nb_u32)p[0] | (nb_u32)p[1] << 8 | (nb_u32)p[2] << 16 | (nb_u32)p[3] << 24;
}
static nb_u64 u64(const nb_u8 *p) { return u32(p) | (nb_u64)u32(p+4) << 32; }
static int equal(const nb_u8 *a, const nb_u8 *b, nb_u32 n) {
    nb_u32 i; for (i=0; i<n; ++i) if (a[i]!=b[i]) return 0; return 1;
}
static int checksum(const nb_u8 *p, nb_u32 n) {
    nb_u32 s=0, i; for (i=0; i<n; ++i) s+=p[i]; return (s & 255u)==0;
}
static nb_u32 crc(const nb_u8 *p, nb_u32 n) {
    nb_u32 c=~0u, i, j;
    for(i=0;i<n;++i) { c ^= i>=16 && i<20 ? 0 : p[i];
        for(j=0;j<8;++j) c=(c>>1) ^ (0xedb88320u & (0u-(c&1u))); }
    return ~c;
}
static int ptr_overlap(const void *a, nb_u64 alen, const void *b, nb_u64 blen) {
    nb_uptr x=(nb_uptr)a, y=(nb_uptr)b;
    nb_u64 limit=(nb_u64)(nb_uptr)-1;
    if(alen>limit-x || blen>limit-y) return 1;
    return (nb_u64)x<(nb_u64)y+blen && (nb_u64)y<(nb_u64)x+alen;
}
struct fw_state {
    const nb_u8 *map;
    nb_u32 length, stride;
    const struct nb_range *protected;
    nb_u32 protected_count;
    target_fw_read_fn read;
    void *context;
    struct target_fw_result result;
};
/* Return only bounded, descriptor-backed objects. Conventional overlap is
 * tolerated, but never counts as data coverage. Full allocated descriptors
 * are reserved, including any partially intersecting duplicate descriptor. */
static int object(struct fw_state *s, nb_u32 address, nb_u32 length) {
    nb_u64 start=address, end=start+length;
    nb_u32 i, allocated_type=0; int covered=0;
    if(start<4096 || !length || end>FW_LIMIT) return 0;
    for(i=0;i<s->protected_count;++i)
        if(start<s->protected[i].end && s->protected[i].start<end) return 0;
    for(i=0;i<s->length;i+=s->stride) {
        const nb_u8 *d=s->map+i;
        nb_u64 base=u64(d+8), stop=base+(u64(d+24)<<12);
        nb_u32 type=u32(d), j;
        if(base>=end || start>=stop) continue;
        if(type==7) continue;
        if(type!=2 && type!=4 && type!=6 && type!=9 && type!=10) return 0;
        if(stop>FW_LIMIT) return 0;
        if(allocated_type && allocated_type!=type) return 0;
        allocated_type=type;
        if(base<=start && stop>=end) covered=1;
        for(j=0;j<s->result.count;++j)
            if(s->result.reservations[j].start==base && s->result.reservations[j].end==stop) break;
        if(j==s->result.count) {
            if(j>=TARGET_FW_MAX_RANGES) return 0;
            s->result.reservations[j].start=base;
            s->result.reservations[j].end=stop;
            ++s->result.count;
        }
    }
    return covered;
}
static int read_object(struct fw_state *s, nb_u32 address, void *out, nb_u32 length) {
    return object(s,address,length) && !s->read(s->context,address,out,length);
}
/* Header is copied from the final checksum pass; callers must guarantee a
 * stable snapshot through all callback reads. This bounds stack usage while
 * permitting real AML tables larger than one page. */
static int child_sdt(struct fw_state *s, nb_u64 address, nb_u8 header[148], nb_u32 *length) {
    nb_u8 buf[256]; nb_u32 size, pos, sum=0, i;
    if(!address || address>=FW_LIMIT || !read_object(s,(nb_u32)address,buf,36)) return 0;
    size=u32(buf+4);
    if(size<36 || size>FW_MAX_CHILD || !object(s,(nb_u32)address,size)) return 0;
    for(pos=0;pos<size;) {
        nb_u32 n=size-pos; if(n>sizeof(buf)) n=sizeof(buf);
        if(s->read(s->context,(nb_u32)address+pos,buf,n)) return 0;
        for(i=0;i<n;++i) { sum+=buf[i]; if(pos+i<148) header[pos+i]=buf[i]; }
        pos+=n;
    }
    if((sum&255) || u32(header+4)!=size) return 0;
    *length=size;
    return 1;
}
static int facs(struct fw_state *s, nb_u64 address) {
    nb_u8 buf[256]; nb_u32 len, pos;
    if(!address || address>=FW_LIMIT || !read_object(s,(nb_u32)address,buf,8) ||
       !equal(buf,(const nb_u8 *)"FACS",4)) return 0;
    len=u32(buf+4);
    if(len<64 || len>FW_MAX_CHILD || !object(s,(nb_u32)address,len)) return 0;
    for(pos=0;pos<len;) {
        nb_u32 n=len-pos; if(n>sizeof(buf)) n=sizeof(buf);
        if(s->read(s->context,(nb_u32)address+pos,buf,n)) return 0;
        if(!pos && (!equal(buf,(const nb_u8 *)"FACS",4) || u32(buf+4)!=len)) return 0;
        pos+=n;
    }
    return 1;
}
static int dsdt(struct fw_state *s, nb_u64 address) {
    nb_u8 header[148]; nb_u32 size;
    return child_sdt(s,address,header,&size) && equal(header,(const nb_u8 *)"DSDT",4);
}
/* Only known fixed-length x86 MADT records are accepted. The common table
 * header is 36 bytes followed by LAPIC address and flags (8 bytes). Bounds
 * checks are structural; they do not establish that APIC MMIO is safe. */
static int madt(struct fw_state *s, nb_u32 address, nb_u32 size) {
    nb_u32 pos=44;
    if(size<44) return 0;
    while(pos<size) {
        nb_u8 sub[2]; nb_u32 expected;
        if(size-pos<2 || s->read(s->context,address+pos,sub,2)) return 0;
        switch(sub[0]) {
        case 0: expected=8; break;  /* local APIC */
        case 1: expected=12; break; /* I/O APIC */
        case 2: expected=10; break; /* interrupt override */
        case 3: expected=8; break;  /* NMI source */
        case 4: expected=6; break;  /* local APIC NMI */
        case 5: expected=12; break; /* local APIC address override */
        case 9: expected=16; break; /* local x2APIC */
        case 10: expected=12; break; /* local x2APIC NMI */
        default: return 0;
        }
        if(sub[1]!=expected || expected>size-pos) return 0;
        pos+=expected;
    }
    return pos==size;
}
static int child(struct fw_state *s, nb_u64 address, int *has_fadt) {
    nb_u8 header[148]; nb_u32 len; nb_u64 f32, d32, f64=0, d64=0;
    if(!child_sdt(s,address,header,&len)) return 0;
    if(equal(header,(const nb_u8 *)"APIC",4)) return madt(s,(nb_u32)address,len);
    if(equal(header,(const nb_u8 *)"SSDT",4)) return 1;
    if(!equal(header,(const nb_u8 *)"FACP",4) || *has_fadt || len<116 || (len>116 && len<148)) return 0;
    *has_fadt=1;
    f32=u32(header+36); d32=u32(header+40);
    if(len>=148) { f64=u64(header+132); d64=u64(header+140); }
    if(!d32 && !d64) return 0;
    if(d32 && !dsdt(s,d32)) return 0;
    if(d64 && d64!=d32 && !dsdt(s,d64)) return 0;
    if(f32 && !facs(s,f32)) return 0;
    if(f64 && f64!=f32 && !facs(s,f64)) return 0;
    return 1;
}
static int root_table(struct fw_state *s, nb_u64 address, int xsdt, nb_u8 *scratch) {
    nb_u32 len, i, step=xsdt?8u:4u; int has_fadt=0;
    const nb_u8 *sig=(const nb_u8 *)(xsdt ? "XSDT" : "RSDT");
    if(!address || address>=FW_LIMIT || !read_object(s,(nb_u32)address,scratch,36)) return 0;
    len=u32(scratch+4);
    if(len<36 || len>FW_MAX_TABLE || (len-36)%(xsdt?8u:4u)) return 0;
    if(!read_object(s,(nb_u32)address,scratch,len) || !equal(scratch,sig,4) ||
       u32(scratch+4)!=len || !checksum(scratch,len)) return 0;
    for(i=36;i<len;i+=step)
        if(!child(s,xsdt?u64(scratch+i):u32(scratch+i),&has_fadt)) return 0;
    return has_fadt;
}
static int rsdp(struct fw_state *s, nb_u32 address, nb_u8 *scratch) {
    nb_u8 rsdp_bytes[256]; nb_u32 len=20, rsdt; nb_u64 xsdt=0;
    if(!read_object(s,address,rsdp_bytes,20) ||
       !equal(rsdp_bytes,(const nb_u8 *)"RSD PTR ",8) || !checksum(rsdp_bytes,20)) return 0;
    if(rsdp_bytes[15]==1) return 0;
    if(rsdp_bytes[15]>=2) {
        if(!read_object(s,address,rsdp_bytes,36)) return 0;
        len=u32(rsdp_bytes+20);
        if(len<36 || len>sizeof(rsdp_bytes) || !read_object(s,address,rsdp_bytes,len) ||
           !equal(rsdp_bytes,(const nb_u8 *)"RSD PTR ",8) || rsdp_bytes[15]<2 ||
           u32(rsdp_bytes+20)!=len || !checksum(rsdp_bytes,20) || !checksum(rsdp_bytes,len)) return 0;
        xsdt=u64(rsdp_bytes+24);
    }
    rsdt=u32(rsdp_bytes+16);
    if(!rsdt && !xsdt) return 0;
    if(rsdt && !root_table(s,rsdt,0,scratch)) return 0;
    if(xsdt && !root_table(s,xsdt,1,scratch)) return 0;
    return 1;
}
int target_validate_firmware(const void *map, nb_u32 map_length,
    nb_u32 stride, nb_u32 version, nb_u32 system_pa,
    const struct nb_range *protected, nb_u32 protected_count,
    target_fw_read_fn read_fn, void *context, struct target_fw_result *out) {
    static const nb_u8 acpi10[16]={0x30,0x2d,0x9d,0xeb,0x88,0x2d,0xd3,0x11,0x9a,0x16,0x00,0x90,0x27,0x3f,0xc1,0x4d};
    static const nb_u8 acpi20[16]={0x71,0xe8,0x68,0x88,0xf1,0xe4,0xd3,0x11,0xbc,0x22,0x00,0x80,0xc7,0x3c,0x88,0x81};
    struct fw_state s; nb_u8 table[128], configs[FW_MAX_CONFIG*20], scratch[FW_MAX_TABLE];
    nb_u32 i, count, length, config_pa, seen=0;
    if(!map || !read_fn || !out || (protected_count && !protected) || protected_count>256 ||
       version!=1 || stride<40 || (stride&3) || !map_length || map_length%stride ||
       map_length/stride>FW_MAX_DESC || (system_pa&3)) return -1;
    if(ptr_overlap(out,sizeof(*out),map,map_length) ||
       (protected_count && ptr_overlap(out,sizeof(*out),protected,
                                       (nb_u64)protected_count*sizeof(*protected)))) return -1;
    s.map=(const nb_u8 *)map; s.length=map_length; s.stride=stride;
    s.protected=protected; s.protected_count=protected_count; s.read=read_fn; s.context=context;
    s.result.count=0;
    for(i=0;i<protected_count;++i)
        if(protected[i].start>=protected[i].end || protected[i].end>FW_LIMIT) return -1;
    for(i=0;i<map_length;i+=stride) {
        nb_u64 base=u64(s.map+i+8), pages=u64(s.map+i+24);
        if((base&4095) || !pages || pages>((~(nb_u64)0-base)>>12)) return -1;
    }
    if(!read_object(&s,system_pa,table,72) || !equal(table,(const nb_u8 *)"IBI SYST",8)) return -1;
    length=u32(table+12);
    if(length<72 || length>sizeof(table) || !read_object(&s,system_pa,table,length) ||
       !equal(table,(const nb_u8 *)"IBI SYST",8) || u32(table+12)!=length || crc(table,length)!=u32(table+16)) return -1;
    count=u32(table+64); config_pa=u32(table+68);
    if(!count || count>FW_MAX_CONFIG || (config_pa&3) ||
       !read_object(&s,config_pa,configs,count*20)) return -1;
    for(i=0;i<count;++i) {
        const nb_u8 *entry=configs+i*20; nb_u32 bit;
        if(equal(entry,acpi10,16)) bit=1; else if(equal(entry,acpi20,16)) bit=2; else return -1;
        if((seen&bit) || !rsdp(&s,u32(entry+16),scratch)) return -1;
        seen|=bit;
    }
    out->count=s.result.count;
    for(i=0;i<s.result.count;++i) {
        out->reservations[i].start=s.result.reservations[i].start;
        out->reservations[i].end=s.result.reservations[i].end;
    }
    return 0;
}

#ifdef TARGET_EMULATION_ONLY
static int init_state(struct fw_state *s, const void *map, nb_u32 length,
    nb_u32 stride, nb_u32 version, const struct nb_range *protected,
    nb_u32 protected_count, target_fw_read_fn read_fn, void *context,
    const void *out, nb_u32 out_size) {
    nb_u32 i;
    if(!map || !read_fn || !out || (protected_count && !protected) || protected_count>256 ||
       version!=1 || stride<40 || (stride&3) || !length || length%stride ||
       length/stride>FW_MAX_DESC || ptr_overlap(out,out_size,map,length) ||
       (protected_count && ptr_overlap(out,out_size,protected,
                                     (nb_u64)protected_count*sizeof(*protected)))) return 0;
    s->map=(const nb_u8 *)map; s->length=length; s->stride=stride;
    s->protected=protected; s->protected_count=protected_count;
    s->read=read_fn; s->context=context; s->result.count=0;
    for(i=0;i<protected_count;++i)
        if(protected[i].start>=protected[i].end || protected[i].end>FW_LIMIT) return 0;
    for(i=0;i<length;i+=stride) {
        nb_u64 base=u64(s->map+i+8), pages=u64(s->map+i+24);
        if((base&4095) || !pages || pages>((~(nb_u64)0-base)>>12)) return 0;
    }
    return 1;
}
int target_validate_acpi(const void *map, nb_u32 length, nb_u32 stride,
    nb_u32 version, nb_u32 rsdp_pa, const struct nb_range *protected,
    nb_u32 protected_count, target_fw_read_fn read_fn, void *context,
    struct target_fw_result *out) {
    struct fw_state s; nb_u8 scratch[FW_MAX_TABLE]; nb_u32 i;
    if(!init_state(&s,map,length,stride,version,protected,protected_count,
                   read_fn,context,out,sizeof(*out)) || !rsdp(&s,rsdp_pa,scratch)) return -1;
    out->count=s.result.count;
    for(i=0;i<s.result.count;++i) out->reservations[i]=s.result.reservations[i];
    return 0;
}
int target_read_efi_sources(const void *map, nb_u32 length, nb_u32 stride,
    nb_u32 version, nb_u32 system_pa, const struct nb_range *protected,
    nb_u32 protected_count, target_fw_read_fn read_fn, void *context,
    struct target_efi_sources *out) {
    struct fw_state s; struct target_efi_sources tmp; nb_u32 count, i;
    if(!init_state(&s,map,length,stride,version,protected,protected_count,
                   read_fn,context,out,sizeof(*out)) || (system_pa&3) ||
       !read_object(&s,system_pa,tmp.system,72) ||
       !equal(tmp.system,(const nb_u8 *)"IBI SYST",8) || u32(tmp.system+12)!=72 ||
       crc(tmp.system,72)!=u32(tmp.system+16)) return -1;
    count=u32(tmp.system+64); tmp.config_pa=u32(tmp.system+68);
    if(!count || count>FW_MAX_CONFIG || (tmp.config_pa&3)) return -1;
    tmp.config_length=count*20;
    if(!read_object(&s,tmp.config_pa,tmp.config,tmp.config_length)) return -1;
    tmp.firmware.count=s.result.count;
    for(i=0;i<s.result.count;++i) tmp.firmware.reservations[i]=s.result.reservations[i];
    for(i=0;i<72;++i) out->system[i]=tmp.system[i];
    for(i=0;i<tmp.config_length;++i) out->config[i]=tmp.config[i];
    out->config_pa=tmp.config_pa; out->config_length=tmp.config_length;
    out->firmware.count=tmp.firmware.count;
    for(i=0;i<tmp.firmware.count;++i) out->firmware.reservations[i]=tmp.firmware.reservations[i];
    return 0;
}
#endif
