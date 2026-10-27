#include "Swotl.h"

int main(int argc, char** argv)
{
    Swotl swotl;
    if (!swotl.isRunnable()) {
        return 20; // AmigaDOS FAIL
    }
    swotl.run();
    return 0;
}
