#include "Swotl.h"

int main(int argc, char** argv)
{
    Swotl swotl;
    if (swotl.isRunnable()) {
        swotl.run();
    }
    return 0;
}
