/* thrmon <pid> [interval_ms]: per interval, per-thread CPU ms (by name, summed over same-name
 * threads), cur/base priority, the process P-core share of CPU time (rusage v6), and the process
 * effective clock (cycles / CPU time, GHz) and IPC (rusage ri_cycles / ri_instructions): a clock that
 * falls when more cores are busy is thermal/power throttling, not the code. therm= is the system
 * thermal pressure level (notify com.apple.system.thermalpressurelevel: 0 nominal, 1 moderate, 2 heavy,
 * 3 trapping, 4 sleeping; -1 = unavailable). */
#include <libproc.h>
#include <sys/proc_info.h>
#include <sys/resource.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <mach/mach_time.h>
#include <notify.h>
#define MAXT 512
typedef struct { uint64_t id; uint64_t cpu; } prev_t;
static prev_t prev[MAXT]; static int nprev;
static uint64_t prev_of(uint64_t id){ for(int i=0;i<nprev;i++) if(prev[i].id==id) return prev[i].cpu; return (uint64_t)-1; }
int main(int argc,char**argv){
  int pid=atoi(argv[1]); int ms=argc>2?atoi(argv[2]):1000;
  struct timespec t0; clock_gettime(CLOCK_MONOTONIC,&t0);
  uint64_t pt_prev=0, tt_prev=0, cy_prev=0, in_prev=0;
  mach_timebase_info_data_t tb; mach_timebase_info(&tb);
  int thtok=-1; if(notify_register_check("com.apple.system.thermalpressurelevel",&thtok)!=NOTIFY_STATUS_OK) thtok=-1;
  for(;;){
    uint64_t ids[MAXT]; int n=proc_pidinfo(pid,PROC_PIDLISTTHREADS,0,ids,sizeof ids);
    if(n<=0) break; n/=sizeof(uint64_t);
    struct { char name[64]; double ms; int cur, base, run, cnt; } agg[MAXT]; int na=0;
    prev_t cur[MAXT]; int nc=0;
    for(int i=0;i<n;i++){
      struct proc_threadinfo ti; if(proc_pidinfo(pid,PROC_PIDTHREADINFO,ids[i],&ti,sizeof ti)!=sizeof ti) continue;
      uint64_t c=ti.pth_user_time+ti.pth_system_time; cur[nc].id=ids[i]; cur[nc].cpu=c; nc++;
      uint64_t p=prev_of(ids[i]); double d= (p==(uint64_t)-1)?0:(double)(c-p)/1e6;
      const char* nm=ti.pth_name[0]?ti.pth_name:"?";
      int k; for(k=0;k<na;k++) if(!strcmp(agg[k].name,nm)) break;
      if(k==na){ snprintf(agg[k].name,64,"%s",nm); agg[k].ms=0; agg[k].cnt=0; agg[k].cur=0; agg[k].base=0; agg[k].run=0; na++; }
      agg[k].ms+=d; agg[k].cnt++; if(ti.pth_curpri>agg[k].cur) agg[k].cur=ti.pth_curpri; agg[k].base=ti.pth_priority;
      if(ti.pth_run_state==1) agg[k].run++;
    }
    memcpy(prev,cur,sizeof(prev_t)*nc); nprev=nc;
    struct rusage_info_v6 ru; double pfrac=-1, ghz=-1, ipc=-1;
    if(proc_pid_rusage(pid,RUSAGE_INFO_V6,(rusage_info_t*)&ru)==0){
      uint64_t pt=ru.ri_user_ptime+ru.ri_system_ptime, tt=ru.ri_user_time+ru.ri_system_time;
      if(tt_prev && tt>tt_prev) pfrac=(double)(pt-pt_prev)/(double)(tt-tt_prev);
      if(cy_prev && ru.ri_cycles>cy_prev && tt>tt_prev){
        double cpu_ns=(double)(tt-tt_prev)*tb.numer/tb.denom;
        ghz=(double)(ru.ri_cycles-cy_prev)/cpu_ns;
        ipc=(double)(ru.ri_instructions-in_prev)/(double)(ru.ri_cycles-cy_prev); }
      cy_prev=ru.ri_cycles; in_prev=ru.ri_instructions;
      pt_prev=pt; tt_prev=tt; }
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
    double el=(t.tv_sec-t0.tv_sec)+(t.tv_nsec-t0.tv_nsec)/1e9;
    /* sort by ms desc */
    for(int a=0;a<na;a++) for(int b=a+1;b<na;b++) if(agg[b].ms>agg[a].ms){ __typeof__(agg[0]) x=agg[a]; agg[a]=agg[b]; agg[b]=x; }
    double tot=0; for(int a=0;a<na;a++) tot+=agg[a].ms;
    int therm=-1; if(thtok>=0){ uint64_t st=0; if(notify_get_state(thtok,&st)==NOTIFY_STATUS_OK) therm=(int)st; }
    printf("[THR] t=%.1f tot_ms=%.0f pcore=%.2f ghz=%.2f ipc=%.2f therm=%d nthr=%d |",el,tot,pfrac,ghz,ipc,therm,n);
    for(int a=0;a<na && a<14;a++) if(agg[a].ms>=5) printf(" %s x%d=%.0f(p%d/%d r%d)",agg[a].name,agg[a].cnt,agg[a].ms,agg[a].cur,agg[a].base,agg[a].run);
    printf("\n"); fflush(stdout);
    usleep(ms*1000);
  }
  return 0;
}
