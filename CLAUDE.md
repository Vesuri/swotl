# Secret Weapons of the Luftwaffe — DOS to Amiga port

Port Totally Games / Lucasfilm Games' 1991 VGA DOS flight simulator Secret
Weapons of the Luftwaffe (version 2.2) to the Amiga. Fidelity comes before
improvement, and the original game running under a PC emulator is the ground
truth. The porting approach is still to be decided and deliberately differs
from Slicks 'N' Slide's; do not assume that project's pipeline.

## Standing rules

- Commit each coherent, verified piece of work before moving to the next.
  Use the repository's Vesuri identity, disable hooks/signing, and omit
  co-author trailers.
- This file carries rules and pointers, never dated progress notes. Put
  measured findings and history in `docs/`.
- The original game files, the manual, archives, dumps, traces, screenshots
  and other byte-derived game material live in the ignored `ref/` and `tmp/`
  directories and must never be committed.
- Ground-truth comparisons use the original game under the PC reference
  loop, never a host approximation or the Amiga port compared with itself.
- Reuse the established Amiga build, FS-UAE/GDB, measurement and documentation
  practices from `~/Documents/Slicks`, `~/Documents/Rescue on Fractalus`,
  `~/Documents/Revs`, `~/Documents/Vette` and `~/Documents/Pokeri`, and the
  dA JoRMaS framework from `~/Documents/dA JoRMaS/Template/C++`; do not
  re-derive target-side lessons without evidence.

## Local layout

- `ref/`: the installed original game (v2.2, code wheel removed) and the
  manual PDF. Run it with `dosbox-staging -conf reference/dosbox-staging.conf`.
- `tmp/`: the source archives and scratch.
- `amiga/env.sh`: puts the shared `~/.local` toolchain and FS-UAE on PATH.
- `tools/ghidra`: symlink to the shared Ghidra install.
