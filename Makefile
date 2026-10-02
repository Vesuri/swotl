## SWOTL — repository-level targets.
## The Amiga executable is the product; the build lives in amiga/.

.PHONY: all help inspect hash check-ref prepare-reference reference-staging amiga smoke clean

PYTHON ?= python3
REFERENCE_ROOT ?= tmp/pc-root
REF_HASHES ?= tmp/ref.sha256

all: help

help:
	@echo "SWOTL — DOS x86 -> Amiga 68020 static translation port"
	@echo
	@echo "  make inspect            MZ header and .OVL summary of ref/"
	@echo "  make hash               record SHA-256 of ref/ in $(REF_HASHES)"
	@echo "  make check-ref          verify ref/ against $(REF_HASHES)"
	@echo "  make prepare-reference  copy ref/ to disposable $(REFERENCE_ROOT)"
	@echo "  make reference-staging  play the disposable copy in DOSBox Staging"
	@echo "  make amiga   build amiga/out/Swotl.exe"
	@echo "  make smoke   boot it under FS-UAE + GDB and check the takeover runs"
	@echo "  make clean   remove Amiga build output"

inspect:
	$(PYTHON) tools/mz_info.py ref/SWOTL.EXE
	$(PYTHON) tools/ovl_info.py ref/*.OVL

hash:
	@mkdir -p $(dir $(REF_HASHES))
	cd ref && find . -type f ! -name .DS_Store -print0 | LC_ALL=C sort -z | \
		xargs -0 shasum -a 256 > "$(abspath $(REF_HASHES))"

check-ref:
	cd ref && shasum -a 256 -c --quiet "$(abspath $(REF_HASHES))"

prepare-reference: check-ref
	@mkdir -p $(REFERENCE_ROOT)
	rsync -a --delete --exclude '*.pdf' ref/ $(REFERENCE_ROOT)/

reference-staging: prepare-reference
	dosbox-staging --noprimaryconf --nolocalconf -conf reference/dosbox-staging.conf
	$(MAKE) check-ref

amiga:
	. amiga/env.sh && $(MAKE) -C amiga

smoke: amiga
	. amiga/env.sh && amiga/debug.sh "" "$(CURDIR)/amiga/diag_smoke.gdb" | grep -q '^SWOTL_SMOKE_OK'

clean:
	$(MAKE) -C amiga clean
