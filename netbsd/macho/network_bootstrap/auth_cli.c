/* Linux/i386 freestanding verifier. No output until verification succeeds. */
#include "auth.h"
typedef unsigned char u8;
typedef unsigned int u32;
#define MAX_PAYLOAD (32u*1024u*1024u)
static u8 manifest[256], key[33];
static int sc3(int n,int a,int b,int c){int r; __asm__ volatile("int $0x80":"=a"(r):"0"(n),"b"(a),"c"(b),"d"(c):"memory");return r;}
static int openfile(const char *p){return sc3(5,(int)p,0x20000,0);}
static int readall(const char *p,u8 *out,u32 cap,int secret){
    int fd=openfile(p),n;u32 count=0;u8 extra,statbuf[128];
    if(fd<0)return -1;
    if(secret && (sc3(197,fd,(int)statbuf,0)<0 || ((*(u32 *)(statbuf+16))&0177777)!=0100600)){sc3(6,fd,0,0);return -1;}
    while(count<cap){n=sc3(3,fd,(int)(out+count),cap-count);if(n<0){sc3(6,fd,0,0);return -1;}if(!n)break;count+=(u32)n;}
    if(count==cap){n=sc3(3,fd,(int)&extra,1);if(n!=0){sc3(6,fd,0,0);return -1;}}
    sc3(6,fd,0,0);return (int)count;
}
static int hashfile(const char *p,u32 size,u8 out[32]){
    struct atv_sha256 ctx;u8 buf[4096],extra;u32 remain=size;int fd=openfile(p),n;
    if(fd<0)return -1;atv_sha256_init(&ctx);
    while(remain){u32 want=remain<sizeof(buf)?remain:sizeof(buf);n=sc3(3,fd,(int)buf,want);
        if(n<=0||(u32)n>want){sc3(6,fd,0,0);return -1;}
        atv_sha256_update(&ctx,buf,(u32)n);remain-=(u32)n;
    }
    n=sc3(3,fd,(int)&extra,1);sc3(6,fd,0,0);if(n!=0)return -1;
    atv_sha256_final(&ctx,out);return 0;
}
static int hex(u8 c){if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;return -1;}
static int fixedhex(const u8 *p,u32 n){u32 i;for(i=0;i<n;i++)if(hex(p[i])<0)return 0;return 1;}
static int exacthex(const u8 *p,u32 n){u32 i;for(i=0;i<n;i++)if(!p[i]||hex(p[i])<0)return 0;return p[n]==0;}
static int match(const u8 *a,const char *b,u32 n){u32 i;for(i=0;i<n;i++)if(a[i]!=(u8)b[i])return 0;return 1;}
static int isequal(const char *a,const char *b){while(*a&&*a==*b){a++;b++;}return *a==*b;}
static int decode(const u8 *p,u8 *out,u32 n){u32 i;for(i=0;i<n;i++){int a=hex(p[i*2]),b=hex(p[i*2+1]);if(a<0||b<0)return 0;out[i]=(u8)((a<<4)|b);}return 1;}
static int sign_report(char **argv){
    static const u8 domain[]="ATV1-REPORT";
    static const char digits[]="0123456789abcdef";
    struct atv_sha256 c;u8 buf[4096],mac[32];char out[65];u32 total=0,i;int fd,n;
    if(!exacthex((u8*)argv[3],32)||!exacthex((u8*)argv[4],16)||readall(argv[2],key,33,1)!=32)return 1;
    fd=openfile(argv[5]);if(fd<0)return 1;
    atv_hmac_init(&c,key);atv_sha256_update(&c,domain,sizeof(domain));
    atv_sha256_update(&c,(u8*)argv[3],32);atv_sha256_update(&c,(u8*)argv[4],16);
    while((n=sc3(3,fd,(int)buf,sizeof(buf)))>0){
        if((u32)n>sizeof(buf)||total>8u*1024u*1024u-(u32)n){sc3(6,fd,0,0);return 1;}
        total+=(u32)n;atv_sha256_update(&c,buf,(u32)n);
    }
    sc3(6,fd,0,0);if(n<0)return 1;atv_hmac_final(&c,key,mac);
    for(i=0;i<32;i++){out[2*i]=digits[mac[i]>>4];out[2*i+1]=digits[mac[i]&15];}
    out[64]='\n';return sc3(4,1,(int)out,65)==65?0:1;
}
__attribute__((used,noinline)) static int run(int argc,char **argv){
    int kn,mn,gt=0;u32 i,size=0,diff=0;u8 expected[32],actual[32],tag[32];
    if(argc!=6)return 2; /* key manifest payload session last-sequence */
    if(isequal(argv[1],"sign-report"))return sign_report(argv);
    if(!exacthex((u8*)argv[4],32)||!exacthex((u8*)argv[5],16))return 2;
    kn=readall(argv[1],key,33,1);mn=readall(argv[2],manifest,sizeof(manifest),0);
    if(kn!=32||mn!=200)return 1;
    if(!match(manifest,"ATV1 ",5)||manifest[37]!=' '||manifest[54]!=' '||!match(manifest+55,"shell ",6)||manifest[69]!=' '||manifest[134]!=' '||manifest[199]!='\n')return 1;
    if(!fixedhex(manifest+5,32)||!fixedhex(manifest+38,16)||!fixedhex(manifest+61,8)||!fixedhex(manifest+70,64)||!fixedhex(manifest+135,64))return 1;
    if(!match(manifest+5,argv[4],32))return 1;
    for(i=0;i<16;i++){ if(manifest[38+i]!=(u8)argv[5][i]){gt=manifest[38+i]>(u8)argv[5][i];break;} }
    if(!gt)return 1;
    for(i=0;i<8;i++) size=(size<<4)|(u32)hex(manifest[61+i]);
    if(!size||size>MAX_PAYLOAD||!decode(manifest+70,expected,32)||!decode(manifest+135,tag,32))return 1;
    if(atv_auth_verify(key,manifest,134,tag))return 1;
    if(hashfile(argv[3],size,actual))return 1;
    for(i=0;i<32;i++)diff|=actual[i]^expected[i];
    if(diff)return 1;
    sc3(4,1,(int)(manifest+38),16);sc3(4,1,(int)"\n",1);return 0;
}
__attribute__((naked,noreturn)) void _start(void){__asm__ volatile("movl (%esp),%eax\n\tleal 4(%esp),%edx\n\tpushl %edx\n\tpushl %eax\n\tcall run\n\tmovl %eax,%ebx\n\tmovl $1,%eax\n\tint $0x80\n\tud2");}
