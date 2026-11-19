#include "smbios.h"

#ifdef TARGET_EMULATION_ONLY
#define LIMIT ((nb_u64)1 << 32)
#define MAX_DESCRIPTORS 256u

static nb_u32 rd16(const nb_u8 *p) { return (nb_u32)p[0] | (nb_u32)p[1] << 8; }
static nb_u32 rd32(const nb_u8 *p) { return rd16(p) | rd16(p + 2) << 16; }
static nb_u64 rd64(const nb_u8 *p) { return rd32(p) | (nb_u64)rd32(p + 4) << 32; }
static int equal(const nb_u8 *a, const nb_u8 *b, nb_u32 n) {
    nb_u32 i; for (i=0;i<n;++i) if (a[i]!=b[i]) return 0; return 1;
}
static int sum_ok(const nb_u8 *p, nb_u32 n) {
    nb_u32 i, sum=0; for (i=0;i<n;++i) sum+=p[i]; return !(sum&255u);
}
static int ptr_overlap(const void *a, nb_u64 alen, const void *b, nb_u64 blen) {
    nb_uptr x=(nb_uptr)a, y=(nb_uptr)b;
    nb_u64 maximum=(nb_u64)(nb_uptr)-1;
    if (alen>maximum-x || blen>maximum-y) return 1;
    return (nb_u64)x<(nb_u64)y+blen && (nb_u64)y<(nb_u64)x+alen;
}

struct state {
    const nb_u8 *map;
    nb_u32 length, stride;
    const struct nb_range *protected;
    nb_u32 protected_count;
    target_fw_read_fn read;
    void *context;
    struct target_fw_result result;
};

/* Conventional overlap is tolerated but cannot prove an object is allocated.
 * Require one full data descriptor and reserve every intersecting descriptor.
 * Reject a complete descriptor if it intersects any protected allocation. */
static int object(struct state *s, nb_u32 addr, nb_u32 length) {
    nb_u64 start=addr, end=start+length; nb_u32 i, allocated_type=0; int covered=0;
    if (start<4096 || !length || end>=LIMIT) return 0;
    for (i=0;i<s->protected_count;++i)
        if (start<s->protected[i].end && s->protected[i].start<end) return 0;
    for (i=0;i<s->length;i+=s->stride) {
        const nb_u8 *d=s->map+i; nb_u64 base=rd64(d+8), stop=base+(rd64(d+24)<<12);
        nb_u32 type=rd32(d), j;
        if (base>=end || start>=stop) continue;
        if (type==7) continue;
        if (type!=2 && type!=4 && type!=6 && type!=9 && type!=10) return 0;
        if (stop>=LIMIT || (allocated_type && allocated_type!=type)) return 0;
        allocated_type=type;
        for (j=0;j<s->protected_count;++j)
            if (base<s->protected[j].end && s->protected[j].start<stop) return 0;
        if (base<=start && stop>=end) covered=1;
        for (j=0;j<s->result.count;++j)
            if (s->result.reservations[j].start==base && s->result.reservations[j].end==stop) break;
        if (j==s->result.count) {
            if (j>=TARGET_FW_MAX_RANGES) return 0;
            s->result.reservations[j].start=base;
            s->result.reservations[j].end=stop;
            ++s->result.count;
        }
    }
    return covered;
}

/* Stream through the double-NUL string area without a 64 KiB stack object. */
static int records(struct state *s, nb_u32 address, nb_u32 length, nb_u32 count) {
    nb_u32 pos=0, index;
    for (index=0;index<count;++index) {
        nb_u8 header[4], buf[256]; nb_u32 fmt, previous=0; int terminated=0;
        if (length-pos<4 || s->read(s->context,address+pos,header,4)) return 0;
        fmt=header[1];
        if (fmt<4 || fmt>length-pos || (header[0]==127 && (fmt!=4 || index+1!=count))) return 0;
        pos+=fmt;
        while (pos<length && !terminated) {
            nb_u32 i, n=length-pos; if (n>sizeof(buf)) n=sizeof(buf);
            if (s->read(s->context,address+pos,buf,n)) return 0;
            for (i=0;i<n;++i) {
                ++pos;
                if (previous && buf[i]==0) { terminated=1; break; }
                previous=(buf[i]==0);
            }
        }
        if (!terminated) return 0;
        if (header[0]==127) return pos==length;
    }
    return 0; /* Require one final type-127 end-of-table record. */
}

int target_validate_smbios2(const void *map, nb_u32 map_length,
    nb_u32 stride, nb_u32 version, nb_u32 entry_pa,
    const struct nb_range *protected, nb_u32 protected_count,
    target_fw_read_fn read_fn, void *context, struct target_fw_result *out) {
    struct state s; nb_u8 entry[255]; nb_u32 i, length, table_pa, table_len, count;
    nb_u64 map_start, map_end;
    if (!map || !read_fn || !out || (protected_count && !protected) || protected_count>256 ||
        version!=1 || stride<40 || (stride&3) || !map_length || map_length%stride ||
        map_length/stride>MAX_DESCRIPTORS) return -1;
    if (ptr_overlap(out,sizeof(*out),map,map_length) ||
        (protected_count && ptr_overlap(out,sizeof(*out),protected,
                                        (nb_u64)protected_count*sizeof(*protected)))) return -1;
    s.map=(const nb_u8 *)map; s.length=map_length; s.stride=stride;
    s.protected=protected; s.protected_count=protected_count; s.read=read_fn;
    s.context=context; s.result.count=0;
    for (i=0;i<protected_count;++i)
        if (protected[i].start>=protected[i].end || protected[i].end>LIMIT) return -1;
    for (i=0;i<map_length;i+=stride) {
        nb_u64 base=rd64(s.map+i+8), pages=rd64(s.map+i+24);
        if ((base&4095) || !pages || pages>((~(nb_u64)0-base)>>12)) return -1;
    }
    /* NetBSD efi_getva() maps PAGE_SIZE bytes starting at the physical entry
     * pointer. An unaligned pointer makes the bus mapping span two pages.
     * Prove and reserve the complete page-rounded mapping before reading. */
    map_start=(nb_u64)entry_pa & ~(nb_u64)4095;
    map_end=((nb_u64)entry_pa + 4096u + 4095u) & ~(nb_u64)4095;
    if (map_end>=LIMIT || !object(&s,(nb_u32)map_start,(nb_u32)(map_end-map_start))) return -1;
    if (!object(&s,entry_pa,31) || s.read(s.context,entry_pa,entry,31) ||
        !equal(entry,(const nb_u8 *)"_SM_",4)) return -1;
    length=entry[5];
    if (length<31 || !object(&s,entry_pa,length) || s.read(s.context,entry_pa,entry,length) ||
        !equal(entry,(const nb_u8 *)"_SM_",4) || entry[5]!=length ||
        !sum_ok(entry,length) || !equal(entry+16,(const nb_u8 *)"_DMI_",5) ||
        !sum_ok(entry+16,15)) return -1;
    table_len=rd16(entry+22); table_pa=rd32(entry+24); count=rd16(entry+28);
    if (!table_len || !count || count>table_len/6 || !object(&s,table_pa,table_len) ||
        !records(&s,table_pa,table_len,count)) return -1;
    out->count=s.result.count;
    for (i=0;i<s.result.count;++i) out->reservations[i]=s.result.reservations[i];
    return 0;
}
#endif
