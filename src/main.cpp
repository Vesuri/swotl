#include "Swotl.h"

int main(int argc, char** argv)
{
    Swotl swotl;
    if (!swotl.isRunnable()) {
        return 20; // AmigaDOS FAIL
    }
    // The guest's DOS exit code (0 from the game's own exit), 2 from a runtime
    // stop, -1 if the guest returned: anything but 0 is a failure to the Shell.
    return swotl.run() ? 20 : 0;
}
