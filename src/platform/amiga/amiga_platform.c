/* Platform services for the runtime on AmigaOS (dos.library), and the run of
 * the translated program on its own native stack. Game files are read from
 * the current directory (the game's own data files, supplied by the user). */
#include <proto/exec.h>
#include <proto/dos.h>
#include <exec/memory.h>
#include <dos/dos.h>
#include "runtime.h"
#include "platform.h"
#include "amiga_platform.h"

struct DosLibrary *DOSBase = 0;

#define MAX_FILES 16
#define GUEST_STACK_BYTES 0x10000

static BPTR files[MAX_FILES];

int32_t amiga_guest_call(void *stack_top);

int32_t plat_open(const char *path)
{
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (!files[k]) {
            BPTR f = Open((CONST_STRPTR)path, MODE_OLDFILE);
            if (!f) {
                return -1;
            }
            files[k] = f;
            return k;
        }
    }
    return -1;
}

int32_t plat_read(int32_t handle, void *buffer, uint32_t length)
{
    return Read(files[handle], buffer, (LONG)length);
}

int32_t plat_seek(int32_t handle, int32_t offset, int32_t whence)
{
    static const LONG mode[3] = {OFFSET_BEGINNING, OFFSET_CURRENT, OFFSET_END};
    if (whence < 0 || whence > 2 || Seek(files[handle], offset, mode[whence]) < 0) {
        return -1;
    }
    return Seek(files[handle], 0, OFFSET_CURRENT);  /* Seek returns the old position */
}

void plat_close(int32_t handle)
{
    Close(files[handle]);
    files[handle] = 0;
}

void plat_log(const char *line)
{
    LONG n = 0;
    while (line[n]) {
        ++n;
    }
    BPTR out = Output();
    if (out) {
        Write(out, (APTR)line, n);
        Write(out, (APTR)"\n", 1);
    }
}

long amiga_run_guest(void)
{
    DOSBase = (struct DosLibrary *)OpenLibrary((CONST_STRPTR)"dos.library", 39);
    if (!DOSBase) {
        return -1;
    }
    /* Guest RAM plus the state block below it; Fast RAM when present (D15). */
    uint8_t *block = (uint8_t *)AllocMem(RT_STATE_BYTES + RT_GUEST_BYTES, MEMF_ANY | MEMF_CLEAR);
    uint8_t *stack = (uint8_t *)AllocMem(GUEST_STACK_BYTES, MEMF_ANY);
    int32_t code = -1;
    if (block && stack) {
        plat_log("SWOTL guest start");
        rt_start(block + RT_STATE_BYTES);
        code = amiga_guest_call(stack + GUEST_STACK_BYTES);
    }
    for (int32_t k = 0; k < MAX_FILES; ++k) {
        if (files[k]) {
            plat_close(k);
        }
    }
    if (stack) {
        FreeMem(stack, GUEST_STACK_BYTES);
    }
    if (block) {
        FreeMem(block, RT_STATE_BYTES + RT_GUEST_BYTES);
    }
    CloseLibrary((struct Library *)DOSBase);
    return code;
}
