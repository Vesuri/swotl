# dA JoRMaS Amiga framework

These sources come from `dA JoRMaS/Productions/DanceDiverse3/Source`, by way
of the Slicks 'N' Slide port (`~/Documents/Slicks`, commit `a09987d`, the last
revision carrying the complete set). The port uses the framework's
`AmigaHardware`, `Bitmap`, `CopperList`, and `Palette24Bit` classes for its AGA
display; `Palette`, `Sprite`, and `Util` come with them because those classes
include them.

`SASCCompat.h` and the small conditional declarations in the headers adapt
the original SAS/C interfaces to the project's `m68k-amiga-elf-g++` build.
The few C++ source edits only make SAS/C's old for-loop scoping and const
permissiveness explicit; they do not change the framework's Amiga behavior.
Slicks' later fixes carried here: the unused blitter-queue allocation leak
(`fe94b50`) and startup-only copper palette storage (`a09987d`).

`compat-include/stdint.h` is local, in the template's `compat-include/`
style: it lets the C++ sources include the runtime's C headers, taking the
fixed-width types from `SASCCompat.h`.
