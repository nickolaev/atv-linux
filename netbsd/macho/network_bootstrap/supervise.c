/* Linux/i386 diagnostic supervisor; stdout/stderr are caller-owned. */
typedef unsigned int u32;
static int sc3(int n,int a,int b,int c){int r;__asm__ volatile("int $0x80":"=a"(r):"0"(n),"b"(a),"c"(b),"d"(c):"memory");return r;}
static int sc5(int n,int a,int b,int c,int d,int e){int r;__asm__ volatile("int $0x80":"=a"(r):"0"(n),"b"(a),"c"(b),"d"(c),"S"(d),"D"(e):"memory");return r;}
struct ts { int sec,nsec; };
__attribute__((used,noinline)) static int run(int argc,char **argv){
    int pid,seconds=0,i,status=0,expired=0,ready=0,pipes[2]; struct ts now,start,delay={0,100000000};
    struct { u32 handler,flags,restorer,mask[2]; } action={0,0,0,{0,0}};
    unsigned char info[128]; char *args[3],*env[1]={0};
    if(argc!=3 || !argv[1][0]) return 125;
    for(i=0;argv[1][i];i++){if(argv[1][i]<'0'||argv[1][i]>'9'||seconds>3600)return 125;seconds=seconds*10+argv[1][i]-'0';}
    if(seconds<1||seconds>3600||sc3(265,1,(int)&start,0)<0||sc5(174,17,(int)&action,0,8,0)<0||sc3(42,(int)pipes,0,0)<0)return 125;
    if(sc3(55,pipes[0],4,2048)<0){sc3(6,pipes[0],0,0);sc3(6,pipes[1],0,0);return 125;}
    pid=sc3(2,0,0,0); if(pid<0){sc3(6,pipes[0],0,0);sc3(6,pipes[1],0,0);return 125;}
    if(!pid){ int fd;char mark='R'; sc3(6,pipes[0],0,0);
#ifdef ATV_SUPERVISOR_TEST_DELAY
        {struct ts pause={3,0};sc3(162,(int)&pause,0,0);}
#endif
        if(sc3(66,0,0,0)<0||sc3(4,pipes[1],(int)&mark,1)!=1)sc3(1,125,0,0);sc3(6,pipes[1],0,0); fd=sc3(5,(int)"/dev/null",0,0); if(fd<0||sc3(63,fd,0,0)<0)sc3(1,125,0,0); if(fd)sc3(6,fd,0,0); args[0]="/bin/sh";args[1]=argv[2];args[2]=0;sc3(11,(int)args[0],(int)args,(int)env);sc3(1,125,0,0); }
    sc3(6,pipes[1],0,0);
    for(;;){
        char mark; if(!ready && sc3(3,pipes[0],(int)&mark,1)==1 && mark=='R')ready=1;
        for(i=0;i<128;i++)info[i]=0;
        /* waitid(P_PID, pid, &siginfo, WEXITED|WNOHANG|WNOWAIT, NULL). */
        /* If waitid fails we cannot prove the PID is still ours: fail
         * without signalling a potentially reused process group. */
        {int r=sc5(284,1,pid,(int)info,4|1|0x01000000,0);
         if(r==-4)continue; /* EINTR: keep supervising the unreaped child. */
         if(r<0){sc3(6,pipes[0],0,0);if(r!=-10){sc3(37,pid,9,0);sc3(37,-pid,9,0);sc3(7,pid,(int)&status,0);}return 125;}}
        if(*(int *)(info+12)==pid)break;
        if(sc3(265,1,(int)&now,0)<0){expired=1;break;}
        if(now.sec-start.sec>seconds || (now.sec-start.sec==seconds && now.nsec>=start.nsec)){expired=1;break;}
        sc3(162,(int)&delay,0,0);
    }
    /* Child remains unreaped until after group signals, preventing PID reuse. */
    sc3(6,pipes[0],0,0);
    if(expired){struct ts grace={1,0};sc3(37,ready?-pid:pid,15,0);sc3(162,(int)&grace,0,0);}
    if(!ready)sc3(37,pid,9,0);
    sc3(37,-pid,9,0);
    if(sc3(7,pid,(int)&status,0)<0)return 125;
    if(expired)return 124;
    return (status&127)?128+(status&127):(status>>8)&255;
}
__attribute__((naked,noreturn)) void _start(void){__asm__ volatile("movl %esp,%eax; leal 4(%eax),%edx; pushl %edx; pushl (%eax); call run; movl %eax,%ebx; movl $1,%eax; int $0x80; ud2");}
