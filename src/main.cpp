#include "Swotl.h"
#include "amiga_platform.h"

int main(int argc, char** argv)
{
    // The translated game runs on the OS first (phase 5 slice: until the runtime
    // stops); the display test card follows.
    amiga_run_guest();
    Swotl swotl;
    if (swotl.isRunnable()) {
        swotl.run();
    }
    return 0;
}
