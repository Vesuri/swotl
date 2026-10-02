// Runtime shims for building SWOTL with m68k-amiga-elf-gcc (-nostdlib).
// Derived from the dA JoRMaS template's GCCRuntime.cpp (via Pokeri and Slicks):
// no ProductionRunner and no level-3 autovector; the VBI hangs off exec.

#include <proto/exec.h>
#include <exec/execbase.h>
#include <exec/memory.h>

// Initialised before main() by an init-array ctor (the gcc8 crt runs
// __init_array_start.. before calling main()).
struct ExecBase* SysBase = 0;
// Read through asm: GCC 12+ rejects a dereference of a constant low address.
__attribute__((constructor)) static void initSysBase()
{
    __asm__ volatile("move.l 4.w,%0" : "=r"(SysBase));
}

// Used by the proto/graphics.h inline calls; opened by Swotl's ctor.
struct GfxBase* GfxBase = 0;

void* operator new(unsigned long n)
{
    unsigned long* p = (unsigned long*)AllocMem(n + sizeof(unsigned long), MEMF_ANY | MEMF_CLEAR);
    if (!p) {
        return 0;
    }
    *p = n + sizeof(unsigned long);
    return p + 1;
}

void* operator new[](unsigned long n) { return operator new(n); }

void operator delete(void* p)
{
    if (!p) {
        return;
    }
    unsigned long* q = (unsigned long*)p - 1;
    FreeMem(q, *q);
}

void operator delete[](void* p) { operator delete(p); }
void operator delete(void* p, unsigned long) { operator delete(p); }
void operator delete[](void* p, unsigned long) { operator delete(p); }

extern "C" void __cxa_pure_virtual() { for (;;) ; }
