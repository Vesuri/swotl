/* Program entry, in place of the shared gcc8 _start (renamed at compile time,
 * amiga/Makefile), which neither takes a Workbench message nor returns main's
 * result (docs/amiga-lessons.md L84, L86). Without pr_CLI (an icon start) the
 * WBStartup message is taken before anything else runs, so before dos.library
 * opens, and replied after the finalizers, under Forbid: once Workbench has it
 * back it may unload this code (RKM Libraries ch. 14). A Shell and the WHDLoad
 * slave (a CLI process) have no message. The link puts _start at the hunk
 * start, where DOS enters (amiga/Makefile checks it). */
#include <proto/exec.h>
#include <dos/dosextens.h>
#include <workbench/startup.h>
#include "amiga_platform.h"

typedef void (*init_fn)(void);
extern init_fn __preinit_array_start[] __attribute__((weak));
extern init_fn __preinit_array_end[] __attribute__((weak));
extern init_fn __init_array_start[] __attribute__((weak));
extern init_fn __init_array_end[] __attribute__((weak));
extern init_fn __fini_array_start[] __attribute__((weak));
extern init_fn __fini_array_end[] __attribute__((weak));
int main(int argc, char **argv);

struct WBStartup *amiga_wb_startup = 0;

/* Audit seam (amiga/workbench_check.sh): the result DOS or Workbench gets. */
void __attribute__((noinline)) amiga_start_return(int result)
{
    __asm__ volatile("" : : "r"(result) : "memory");
}

__attribute__((used, section(".text.unlikely"))) int _start(void)
{
    /* The constructors set the global SysBase; read through asm (GCCRuntime.cpp). */
    struct ExecBase *SysBase;
    __asm__ volatile("move.l 4.w,%0" : "=r"(SysBase));
    struct Process *self = (struct Process *)FindTask(0);
    if (!self->pr_CLI) {
        WaitPort(&self->pr_MsgPort);
        amiga_wb_startup = (struct WBStartup *)GetMsg(&self->pr_MsgPort);
    }
    for (init_fn *p = __preinit_array_start; p != __preinit_array_end; ++p) (*p)();
    for (init_fn *p = __init_array_start; p != __init_array_end; ++p) (*p)();
    int result = main(0, 0);
    for (init_fn *p = __fini_array_end; p != __fini_array_start;) (*--p)();
    amiga_start_return(result);
    if (amiga_wb_startup) {
        Forbid();
        ReplyMsg(&amiga_wb_startup->sm_Message);
    }
    return result;
}
