/* HMAC-SHA256 primitive for bounded canonical job manifests.
 * Caller supplies a 32-byte pinned key and exact canonical message bytes.
 * This authenticates neither transport nor replay state; see auth.h. */
#include "auth.h"
typedef __UINT8_TYPE__ u8;
typedef __UINT32_TYPE__ u32;
typedef __UINT64_TYPE__ u64;
static u32 rr(u32 a, u32 n) { return (a >> n) | (a << (32-n)); }
static const u32 k[64] = {
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
static void block(u32 h[8], const u8 *p) {
    u32 w[64],a,b,c,d,e,f,g,z,i,t1,t2;
    for (i=0;i<16;i++) w[i]=(u32)p[4*i]<<24|(u32)p[4*i+1]<<16|(u32)p[4*i+2]<<8|p[4*i+3];
    for (;i<64;i++) { u32 x=w[i-15],y=w[i-2]; w[i]=(rr(x,7)^rr(x,18)^(x>>3))+w[i-16]+(rr(y,17)^rr(y,19)^(y>>10))+w[i-7]; }
    a=h[0];b=h[1];c=h[2];d=h[3];e=h[4];f=h[5];g=h[6];z=h[7];
    for(i=0;i<64;i++){ t1=z+(rr(e,6)^rr(e,11)^rr(e,25))+((e&f)^((~e)&g))+k[i]+w[i]; t2=(rr(a,2)^rr(a,13)^rr(a,22))+((a&b)^(a&c)^(b&c)); z=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2; }
    h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=z;
}
void atv_sha256_init(struct atv_sha256 *c) {
    static const u32 initial[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    u32 i; for(i=0;i<8;i++) c->h[i]=initial[i]; c->used=0; c->total=0;
}
void atv_sha256_update(struct atv_sha256 *c,const u8 *p,u32 len) {
    u32 n,i; c->total+=len;
    while(len) { n=64-c->used; if(n>len)n=len;
        for(i=0;i<n;i++)c->tail[c->used+i]=p[i];
        c->used+=n;p+=n;len-=n;
        if(c->used==64){block(c->h,c->tail);c->used=0;}
    }
}
void atv_sha256_final(struct atv_sha256 *c,u8 out[32]) {
    u64 bits=c->total*8;u32 i;
    c->tail[c->used++]=0x80;
    if(c->used>56){while(c->used<64)c->tail[c->used++]=0;block(c->h,c->tail);c->used=0;}
    while(c->used<56)c->tail[c->used++]=0;
    for(i=0;i<8;i++)c->tail[63-i]=(u8)(bits>>(8*i));
    block(c->h,c->tail);
    for(i=0;i<8;i++){out[4*i]=c->h[i]>>24;out[4*i+1]=c->h[i]>>16;out[4*i+2]=c->h[i]>>8;out[4*i+3]=c->h[i];}
}
void atv_hmac_init(struct atv_sha256 *c,const u8 key[32]) {
    u8 pad[64];u32 i;for(i=0;i<64;i++)pad[i]=(i<32?key[i]:0)^0x36;
    atv_sha256_init(c);atv_sha256_update(c,pad,64);
    for(i=0;i<64;i++)((volatile u8 *)pad)[i]=0;
}
void atv_hmac_final(struct atv_sha256 *c,const u8 key[32],u8 out[32]) {
    u8 pad[64],inner[32];u32 i;atv_sha256_final(c,inner);
    for(i=0;i<64;i++)pad[i]=(i<32?key[i]:0)^0x5c;
    atv_sha256_init(c);atv_sha256_update(c,pad,64);atv_sha256_update(c,inner,32);atv_sha256_final(c,out);
    for(i=0;i<64;i++)((volatile u8 *)pad)[i]=0;
    for(i=0;i<32;i++)((volatile u8 *)inner)[i]=0;
}
static void sha256(const u8 *p,u32 length,u8 out[32]) {
    u32 h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    u8 tail[128]; u32 remain=length%64,i,n; u64 bits=(u64)length*8;
    for(i=0;i<length-remain;i+=64) block(h,p+i);
    for(i=0;i<128;i++) tail[i]=0;
    for(i=0;i<remain;i++) tail[i]=p[length-remain+i];
    tail[remain]=0x80; n=remain<56?64:128;
    for(i=0;i<8;i++) tail[n-1-i]=(u8)(bits>>(8*i));
    block(h,tail); if(n==128) block(h,tail+64);
    for(i=0;i<8;i++){out[4*i]=h[i]>>24;out[4*i+1]=h[i]>>16;out[4*i+2]=h[i]>>8;out[4*i+3]=h[i];}
}

int atv_auth_verify(const u8 key[32], const u8 *message, u32 length, const u8 tag[32]) {
    u8 buffer[64 + ATV_AUTH_MAX_MESSAGE], inner[32], actual[32];
    u32 i, mismatch = 0;
    if (!key || !message || !tag || length > ATV_AUTH_MAX_MESSAGE) return -1;
    for(i=0;i<64;i++) buffer[i]=(i<32?key[i]:0)^0x36;
    for(i=0;i<length;i++) buffer[64+i]=message[i];
    sha256(buffer,64+length,inner);
    for(i=0;i<64;i++) buffer[i]=(i<32?key[i]:0)^0x5c;
    for(i=0;i<32;i++) buffer[64+i]=inner[i];
    sha256(buffer,96,actual);
    for(i=0;i<32;i++) mismatch |= actual[i]^tag[i];
    for(i=0;i<sizeof(buffer);i++) ((volatile u8 *)buffer)[i]=0;
    return mismatch ? -1 : 0;
}
void atv_auth_sha256(const unsigned char *data, unsigned int length, unsigned char out[32]) {
    sha256(data, length, out);
}
