## SWOTL — repository-level targets.
## The Amiga executable is the product; the build lives in amiga/.

.PHONY: all help inspect hash check-ref prepare-reference reference-staging reference-emulator reference-run reference coverage map trace-summary ghidra gen gen-check lint test test-decode test-x86 test-m68k test-blocks test-sabotage test-guards host test-host test-amiga amiga smoke clean

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
	@echo "  make gen                translate the in-scope modules -> build/gen/*.ir + coverage report"
	@echo "  make gen-check          G1: headers, digests and byte-identical regeneration of build/gen"
	@echo "  make lint               G2: no guest-address names in hand-written code"
	@echo "  make test               lint, decoder, x86/68020/block differentials, guards, gen-check, host run"
	@echo "  make test-sabotage      planted IR/decoder faults must fail the x86 differential"
	@echo "  make host               link generated program + runtime for Unicorn 68020 -> build/host/swotl.elf"
	@echo "  make test-host          run it from the MZ entry to milestone m1 against the reference"
	@echo "  make test-amiga         same milestone on the A1200 model (FS-UAE + GDB capture, amiga/diag_m1.gdb)"
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

gen:
	$(PYTHON) -m translator.gen

gen-check:
	$(PYTHON) -m translator.check gen --regen

lint:
	$(PYTHON) -m translator.check lint

test-decode:
	$(PYTHON) tests/test_decode.py

test-x86:
	$(PYTHON) tests/x86_diff.py

test-sabotage:
	$(PYTHON) tests/x86_sabotage.py
	$(PYTHON) tests/m68k_sabotage.py
	$(PYTHON) tests/host_run.py --sabotage

test-m68k:
	$(PYTHON) tests/m68k_diff.py

test-blocks:
	$(PYTHON) tests/m68k_blocks.py

test-guards: gen
	$(PYTHON) tests/test_guards.py

test: lint test-decode test-x86 test-m68k test-blocks test-guards gen-check test-host

# Host image: the generated program and the runtime for tests/host_run.py.
CROSS    = $(HOME)/.local/opt/bin/m68k-amiga-elf-
VASM     = $(HOME)/.local/vasmm68k_mot
VASMELF  = $(VASM) -quiet -m68020 -Felf -x -nowarn=62
RT_CFLAGS = -m68020 -O2 -ffreestanding -nostdlib -fomit-frame-pointer \
	-fno-tree-loop-distribute-patterns -Wall -Wextra -Werror -Isrc/runtime
RUNTIME_C = $(wildcard src/runtime/*.c)
HOST_OBJ = build/host/host_s.o build/host/host.o build/host/rt_entry.o \
	$(patsubst src/runtime/%.c,build/host/%.o,$(RUNTIME_C)) build/host/program.o

build/host/program.o: build/gen/program.s $(wildcard build/gen/*.s)
	@mkdir -p $(dir $@)
	cd build/gen && $(VASMELF) -o ../host/program.o program.s

build/host/rt_entry.o: src/runtime/rt_entry.s
	@mkdir -p $(dir $@)
	$(VASMELF) -o $@ $<

build/host/host_s.o: src/platform/host/host.s
	@mkdir -p $(dir $@)
	$(VASMELF) -o $@ $<

build/host/host.o: src/platform/host/host.c src/runtime/runtime.h src/runtime/platform.h
	@mkdir -p $(dir $@)
	$(CROSS)gcc $(RT_CFLAGS) -c -o $@ $<

build/host/%.o: src/runtime/%.c src/runtime/runtime.h src/runtime/platform.h
	@mkdir -p $(dir $@)
	$(CROSS)gcc $(RT_CFLAGS) -c -o $@ $<

build/host/swotl.elf: $(HOST_OBJ)
	$(CROSS)ld -Ttext=0x10000 -e _start -o $@ $(HOST_OBJ)

host: gen-check build/host/swotl.elf

test-host: host
	$(PYTHON) tests/host_run.py

test-amiga: amiga host
	@mkdir -p tmp/amiga-m1
	. amiga/env.sh && cd amiga && ./debug.sh "" "$(CURDIR)/amiga/diag_m1.gdb" | \
		sed -n 's/^SWOTL_M1_REGS //p' > ../tmp/amiga-m1/regs.txt
	$(PYTHON) tests/host_run.py --amiga tmp/amiga-m1

amiga: gen-check
	. amiga/env.sh && $(MAKE) -C amiga

smoke: amiga
	. amiga/env.sh && amiga/debug.sh "" "$(CURDIR)/amiga/diag_smoke.gdb" | grep -q '^SWOTL_SMOKE_OK'

clean:
	$(MAKE) -C amiga clean
