## SWOTL — repository-level targets.
## The Amiga executable is the product; the build lives in amiga/.

.PHONY: all help inspect hash check-ref prepare-reference reference-staging reference-emulator reference-run reference coverage map trace-summary ghidra amiga smoke clean

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
	@echo "  make reference-emulator build instrumented DOSBox-X (tools/patches/ORDER)"
	@echo "  make reference-run RUN=name [RUN_ARGS=...]  headless traced run -> tmp/pc-runs/name"
	@echo "  make reference          run all milestones (reference/milestones.csv): signals, determinism, image proof"
	@echo "  make coverage           run the coverage scripts (reference/coverage.csv)"
	@echo "  make map                sweep + PLINK check + code-write audit + surface over tmp/pc-runs/ref-*"
	@echo "  make trace-summary RUN=name                 summarise that run's trace"
	@echo "  make ghidra             sweep + headless Ghidra project per module -> tmp/ghidra/*.txt"
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

reference-emulator:
	tools/build_dosbox_x.sh

RUN ?= unattended
RUN_ARGS ?= --time-limit 60

reference-run: check-ref
	$(PYTHON) tools/pc_run.py $(RUN) $(RUN_ARGS)

reference: check-ref
	$(PYTHON) tools/reference.py

coverage: check-ref
	$(PYTHON) tools/reference.py --table reference/coverage.csv

map:
	$(PYTHON) tools/sweep.py --annotations
	$(PYTHON) tools/plink_check.py
	$(PYTHON) tools/code_writes.py
	$(PYTHON) tools/surface.py > tmp/sweep/surface.md

trace-summary:
	$(PYTHON) tools/trace_summary.py tmp/pc-runs/$(RUN)/trace

ghidra:
	$(PYTHON) tools/ghidra_import.py

amiga:
	. amiga/env.sh && $(MAKE) -C amiga

smoke: amiga
	. amiga/env.sh && amiga/debug.sh "" "$(CURDIR)/amiga/diag_smoke.gdb" | grep -q '^SWOTL_SMOKE_OK'

clean:
	$(MAKE) -C amiga clean
