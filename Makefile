## SWOTL — repository-level targets.
## The Amiga executable is the product; the build lives in amiga/.

.PHONY: all help amiga smoke clean

all: help

help:
	@echo "SWOTL — DOS x86 -> Amiga 68020 static translation port"
	@echo
	@echo "  make amiga   build amiga/out/Swotl.exe"
	@echo "  make smoke   boot it under FS-UAE + GDB and check the takeover runs"
	@echo "  make clean   remove Amiga build output"

amiga:
	. amiga/env.sh && $(MAKE) -C amiga

smoke: amiga
	. amiga/env.sh && amiga/debug.sh "" "$(CURDIR)/amiga/diag_smoke.gdb" | grep -q '^SWOTL_SMOKE_OK'

clean:
	$(MAKE) -C amiga clean
