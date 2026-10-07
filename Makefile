## SWOTL — repository-level targets.
## The Amiga executable is the product; the build lives in amiga/.

.PHONY: all help inspect hash check-ref prepare-reference reference-staging reference-emulator reference-run reference coverage map trace-summary ghidra gen gen-check lint test test-decode test-x86 test-m68k test-blocks test-sabotage test-guards host test-host test-host-all test-amiga amiga amiga-release smoke smoke-release size clean

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
	@echo "  make test-sabotage      planted IR/decoder/runtime faults must fail the differentials and host run"
	@echo "  make host               link generated program + runtime for Unicorn 68020 -> build/host/swotl.elf"
	@echo "  make test-host          run it from the MZ entry to milestones m1-m3 against the reference"
	@echo "  make test-host-all      the same to every milestone, m1-m7, and c6-flight-keys (~6 min)"
	@echo "  make test-amiga         m1b-logo on the A1200 model (FS-UAE + GDB capture, amiga/milestone.gdb.in; AMIGA_CPU=68030)"
	@echo "  make amiga   build amiga/out/Swotl.exe"
	@echo "  make amiga-release  build and verify separate stripped amiga/out/Swotl-release.exe"
	@echo "  make smoke-release  boot the stripped executable under FS-UAE"
	@echo "  make size    account for code, data, symbols and relocations in the executable"
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

reference: check-ref gen
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

test-sabotage: host
	@$(MAKE) -s -k -j$(JOBS) t-sab-x86 t-sab-m68k t-sab-host t-sab-carry-entries

test-m68k:
	$(PYTHON) tests/m68k_diff.py

test-blocks:
	$(PYTHON) tests/m68k_blocks.py

test-guards: gen
	$(PYTHON) tests/test_guards.py

# Checks run in parallel after the one writer of build/gen (gen-check) and the
# host image; each logs to tmp/test/<name>.log and prints one status line.
JOBS ?= $(shell sysctl -n hw.ncpu 2>/dev/null || nproc)
RUN = @mkdir -p tmp/test; if $(2) > tmp/test/$(1).log 2>&1; then echo "ok    $(1)"; \
	else echo "FAIL  $(1) (tmp/test/$(1).log)"; tail -n 15 tmp/test/$(1).log; exit 1; fi
SHARDS = forms.0/4 forms.1/4 forms.2/4 forms.3/4 space.0/1 boundary.0/1 blocks.0/1
TESTS = t-carry-entries t-hunk-size t-profile-tools t-lint t-decode $(subst /,-of-,$(SHARDS:%=t-x86-%)) $(subst /,-of-,$(SHARDS:%=t-m68k-%)) \
	t-blocks t-guards $(HOST_MILESTONES:%=t-host-%)

test: host
	@$(MAKE) -s -k -j$(JOBS) $(TESTS)

t-sab-carry-entries:
	$(call RUN,sabotage-carry-entries,$(PYTHON) tests/test_carry_entries.py --sabotage)

t-carry-entries:
	$(call RUN,carry-entries,$(PYTHON) tests/test_carry_entries.py)

t-hunk-size:
	$(call RUN,hunk-size,$(PYTHON) tests/test_hunk_size.py)
t-profile-tools:
	$(call RUN,profile-tools,$(PYTHON) tests/test_profile_tools.py)
t-lint:
	$(call RUN,lint,$(PYTHON) -m translator.check lint)
t-decode:
	$(call RUN,decode,$(PYTHON) tests/test_decode.py)
# t-x86-<corpus>.<k>-of-<n>: one shard of a differential corpus
CORPUS = $(word 1,$(subst ., ,$*))
SHARD = $(subst -of-,/,$(word 2,$(subst ., ,$*)))
t-x86-%:
	$(call RUN,x86-$*,$(PYTHON) tests/x86_diff.py --only $(CORPUS) --shard $(SHARD))
t-m68k-%:
	$(call RUN,m68k-$*,$(PYTHON) tests/m68k_diff.py --only $(CORPUS) --shard $(SHARD))
t-blocks:
	$(call RUN,blocks,$(PYTHON) tests/m68k_blocks.py)
t-guards:
	$(call RUN,guards,$(PYTHON) tests/test_guards.py)
t-host-%:
	$(call RUN,host-$*,$(PYTHON) tests/host_run.py --milestone $*)
t-cov-%:
	$(call RUN,host-$*,$(PYTHON) tests/host_run.py --table reference/coverage.csv --milestone $* --timeout 2400)
t-sab-x86:
	$(call RUN,sabotage-x86,$(PYTHON) tests/x86_sabotage.py)
t-sab-m68k:
	$(call RUN,sabotage-m68k,$(PYTHON) tests/m68k_sabotage.py)
t-sab-host:
	$(call RUN,sabotage-host,$(PYTHON) tests/host_run.py --sabotage --milestone m1b-logo)

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

HOST_MILESTONES = m1-mode13h m1b-logo m2-choose-side m3-demo-flight
HOST_MILESTONES_ALL = $(HOST_MILESTONES) m4-demo-frames m5-player-flight m6-film-room m7-campaign
HOST_COVERAGE = c6-flight-keys
AMIGA_MILESTONE ?= m1b-logo
AMIGA_CPU ?= 68030
AMIGA_CAPTURE = tmp/amiga-$(AMIGA_MILESTONE)

test-host: host
	@$(MAKE) -s -k -j$(JOBS) $(HOST_MILESTONES:%=t-host-%)

test-host-all: host
	@$(MAKE) -s -k -j$(JOBS) $(HOST_MILESTONES_ALL:%=t-host-%) $(HOST_COVERAGE:%=t-cov-%)

test-amiga: amiga host
	@mkdir -p $(AMIGA_CAPTURE)
	sed -e "s|@LABEL@|$$($(PYTHON) tests/host_run.py --label --milestone $(AMIGA_MILESTONE))|" \
		-e "s|@OUT@|../$(AMIGA_CAPTURE)|" amiga/milestone.gdb.in > $(AMIGA_CAPTURE)/fixture.gdb
	. amiga/env.sh && cd amiga && AMIGA_CPU=$(AMIGA_CPU) ./debug.sh "" "../$(AMIGA_CAPTURE)/fixture.gdb" 2>&1 | \
		tee ../$(AMIGA_CAPTURE)/gdb.log | sed -n 's/^SWOTL_REGS //p' > ../$(AMIGA_CAPTURE)/regs.txt
	$(PYTHON) tests/host_run.py --milestone $(AMIGA_MILESTONE) --amiga $(AMIGA_CAPTURE)

amiga: gen-check
	. amiga/env.sh && $(MAKE) -C amiga

amiga-release: amiga
	. amiga/env.sh && elf2hunk amiga/out/Swotl.elf amiga/out/Swotl-release.exe -s
	$(PYTHON) tools/hunk_size.py --release-of amiga/out/Swotl.exe amiga/out/Swotl-release.exe

smoke-release: amiga-release
	. amiga/env.sh && amiga/debug.sh "" "$(CURDIR)/amiga/diag_smoke.gdb" "$(CURDIR)/amiga/out/Swotl-release.exe" | grep -q '^SWOTL_SMOKE_OK'

size: amiga
	$(PYTHON) tools/hunk_size.py amiga/out/Swotl.exe

smoke: amiga
	. amiga/env.sh && amiga/debug.sh "" "$(CURDIR)/amiga/diag_smoke.gdb" | grep -q '^SWOTL_SMOKE_OK'

clean:
	$(MAKE) -C amiga clean
