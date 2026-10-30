# dA JoRMaS Amiga framework

These sources come from `dA JoRMaS/Productions/DanceDiverse3/Source`, by way
of the Slicks 'N' Slide port (the Slicks repo, commit `a09987d`, the last
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
From the canonical tree (below): every custom-chip and CIA register pointer is `volatile`.
Without it GCC read `$BFE001` with `bfextu`, merged the two INTREQ writes of
`clearInterruptRequests` and deleted the VHPOSR wait of a Paula restart (0.91: retriggers
missed on a 68040); `amiga/Makefile` audits that wait in every link.

`compat-include/stdint.h` is local, in the template's `compat-include/`
style: it lets the C++ sources include the runtime's C headers, taking the
fixed-width types from `SASCCompat.h`.

Framework base: AmigaXDev commit 2e02af5, the canonical tree in `$AMIGA_FRAMEWORK` (the C++
lineage this copy shares with Slicks byte for byte). Compare with it and take fixes from it with
`python3 -m amigaxdev.framework diff "Secret Weapons of Luftwaffe"` (run from the directory above
this repository).
