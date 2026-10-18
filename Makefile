## SWOTL — repository-level targets.
## The Amiga executable is the product; the build lives in amiga/.

.PHONY: all help inspect hash check-ref prepare-reference reference-staging reference-emulator reference-run reference coverage sound-reference sound-fm sound-tfh map trace-summary ghidra gen gen-check lint test test-decode test-x86 test-m68k test-blocks test-sabotage test-guards gates g-sabotage g-host-all g-fsuae host test-host test-host-all test-amiga test-amiga-replay test-amiga-restore amiga amiga-release smoke smoke-release size clean

PYTHON ?= python3
# AmigaXDev's shared Python package (amigaxdev.dos.mz_info).
AMIGA_PYLIB ?= $(HOME)/.local/share/amiga/pylib
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
	@echo "  make sound-reference    OPL log + SPAZ probes + Nuked OPL WAVs (tmp/sound/)"
	@echo "  make sound-tfh          hybrid sample/FM WAVs (user TFH_RSC, tmp/sound/*-tfh.wav)"
	@echo "  make sound-fm           FM re-hoster Paula WAVs of the references (tmp/sound/*-paula.wav)"
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
	@echo "  make test-host-all      the same to every milestone, m1-m7, and coverage c6-c10, c12, c13"
	@echo "  make test-amiga         m1b-logo on the A1200 model (FS-UAE + GDB capture, amiga/milestone.gdb.in; AMIGA_CPU=68030)"
	@echo "  make gates              the step gates: test, sabotage, host milestones, Amiga, smoke and restoration"
	@echo "  make amiga   build amiga/out/Swotl.exe"
	@echo "  make amiga-release  build and verify separate stripped amiga/out/Swotl-release.exe"
	@echo "  make smoke-release  boot the stripped executable under FS-UAE"
	@echo "  make size    account for code, data, symbols and relocations in the executable"
	@echo "  make smoke   boot it under FS-UAE + GDB and check the takeover runs"
	@echo "  make clean   remove Amiga build output"

inspect:
	PYTHONPATH='$(AMIGA_PYLIB)' $(PYTHON) -m amigaxdev.dos.mz_info ref/SWOTL.EXE
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

build/tools/opl_render: tools/opl_render.cpp
	mkdir -p build/tools
	c++ -O2 -std=c++17 -Itools/vendor/dosbox-x/src/hardware -o $@ $< \
		tools/vendor/dosbox-x/src/hardware/nukedopl.cpp

build/tools/fm_check: tools/fm_check.cpp src/platform/amiga/fm_paula.c src/platform/amiga/fm_paula.h
	mkdir -p build/tools
	cc -O2 -std=c99 -Wall -Wextra -Werror -c -o build/tools/fm_paula.o src/platform/amiga/fm_paula.c
	c++ -O2 -std=c++17 -Isrc/platform/amiga -Itools/vendor/dosbox-x/src/hardware -o $@ $< \
		build/tools/fm_paula.o tools/vendor/dosbox-x/src/hardware/nukedopl.cpp

sound-reference: check-ref build/tools/opl_render
	$(PYTHON) tools/sound_reference.py

# FM re-hoster (docs/sound-plan.md) on the sound references: Paula WAVs
# beside the Nuked ones; t-fm gates the effect runs, the title (music) is
# rendered for listening.
FM_RUNS = c6-flight-keys c12-b17-bombing c13-me262-gunnery
FM_OPL = tmp/pc-runs/sound-$(1)/trace/opl.csv
sound-fm: build/tools/fm_check
	mkdir -p tmp/sound
	-for r in title $(FM_RUNS); do build/tools/fm_check $(call FM_OPL,$$r) tmp/sound/$$r-paula.wav; done
t-fm: build/tools/fm_check
	$(call RUN,fm-paula,mkdir -p tmp/sound && for r in $(FM_RUNS); do \
		build/tools/fm_check $(call FM_OPL,$$r) tmp/sound/$$r-paula.wav || exit 1; done)
t-fm-quality:
	$(call RUN,fm-quality,$(PYTHON) tests/test_fm_quality.py)
t-sab-fm-quality:
	$(call RUN,sabotage-fm-quality,$(PYTHON) tests/test_fm_quality.py --sabotage)
t-sab-fm: build/tools/fm_check
	$(call RUN,sabotage-fm-paula,for s in pitch level; do \
		! build/tools/fm_check $(call FM_OPL,c6-flight-keys) tmp/test/fm-sabotage.wav --sabotage $$s || exit 1; done)

TFH_RSC ?= tmp/tfh/TheirFinestHour&Missions/data/sfx.rsc
build/tools/tfh_render: tools/tfh_render.cpp src/platform/amiga/tfh_paula.c src/platform/amiga/tfh_paula.h src/platform/amiga/fm_paula.c src/platform/amiga/fm_paula.h
	mkdir -p build/tools
	cc -O2 -std=c99 -Wall -Wextra -Werror -c -o build/tools/tfh_render_fm.o src/platform/amiga/fm_paula.c
	cc -O2 -std=c99 -Wall -Wextra -Werror -c -o build/tools/tfh_paula.o src/platform/amiga/tfh_paula.c
	c++ -O2 -std=c++17 -Wall -Wextra -Werror -Isrc/platform/amiga -o $@ $< build/tools/tfh_render_fm.o build/tools/tfh_paula.o
sound-tfh: host build/tools/tfh_render
	mkdir -p tmp/sound
	for r in $(FM_RUNS); do $(PYTHON) tests/host_run.py --table reference/coverage.csv --milestone $$r --timeout 2400 --sound-log tmp/sound/$$r-tfh.csv && build/tools/tfh_render tmp/sound/$$r-tfh.csv "$(TFH_RSC)" tmp/sound/$$r-tfh.wav || exit 1; done
t-tfh:
	$(call RUN,tfh,$(PYTHON) tests/test_tfh.py)
t-sab-tfh:
	$(call RUN,sabotage-tfh,$(PYTHON) tests/test_tfh.py --sabotage)

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
	@$(MAKE) -s -k -j$(JOBS) t-sab-block-boundary t-sab-x86 t-sab-m68k t-sab-host t-sab-carry-entries t-sab-align t-sab-next-branch t-sab-amiga-input t-sab-display-queue t-sab-display-palette t-sab-file-dates t-sab-cell-cache t-sab-replay-hooks t-sab-replay-events t-sab-host-replay-visits t-sab-rep-replay t-sab-rep-lowering t-sab-profile-tools t-sab-cost-tools t-sab-align-convergence t-sab-fm t-sab-fm-quality t-sab-tfh t-sab-sound-hooks t-sab-audio t-sab-load-image t-sab-host-launch t-sab-keyboard-prefix t-sab-interrupt-frame-mask t-sab-dosbox-retf t-sab-dos-search t-sab-dos-sda t-sab-machine-vectors t-sab-oracle-boundary t-sab-oracle-exception-writes t-sab-helper-branches t-sab-block-assembly t-sab-key-release t-sab-key-chords t-sab-replay-chords t-sab-fixture-inputs t-sab-joystick

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
TESTS = t-block-boundary t-joystick t-rep-replay t-rep-lowering t-host-replay-visits t-fixture-inputs t-key-chords t-replay-chords t-key-release t-oracle-boundary t-oracle-exception-writes t-helper-branches t-block-assembly t-dos-sda t-dos-search t-machine-vectors t-interrupt-frame-mask t-keyboard-prefix t-host-launch t-load-image t-align-convergence t-replay-hooks t-replay-events t-file-dates t-mouse-irq t-display-queue t-display-palette t-amiga-input t-smc-flow t-cell-cache t-align t-next-branch t-dosbox-retf t-reglive t-compact t-byteorder-entries t-carry-entries t-hunk-size t-profile-tools t-cost-tools t-lint t-decode $(subst /,-of-,$(SHARDS:%=t-x86-%)) $(subst /,-of-,$(SHARDS:%=t-m68k-%)) \
	t-blocks t-guards t-fm t-fm-quality t-tfh t-sound-hooks t-audio $(HOST_MILESTONES:%=t-host-%)

test: host
	@$(MAKE) -s -k -j$(JOBS) $(TESTS)

t-display-palette:
	$(call RUN,display-palette,$(PYTHON) tests/test_display_palette.py)
t-sab-display-palette:
	$(call RUN,sabotage-display-palette,$(PYTHON) tests/test_display_palette.py --sabotage)

t-display-queue:
	$(call RUN,display-queue,$(PYTHON) tests/test_display_queue.py)
t-sab-display-queue:
	$(call RUN,sabotage-display-queue,$(PYTHON) tests/test_display_queue.py --sabotage)

t-interrupt-frame-mask:
	$(call RUN,interrupt-frame-mask,$(PYTHON) tests/test_interrupt_frame_mask.py)
t-sab-interrupt-frame-mask:
	$(call RUN,sabotage-interrupt-frame-mask,$(PYTHON) tests/test_interrupt_frame_mask.py --sabotage)
t-keyboard-prefix:
	$(call RUN,keyboard-prefix,$(PYTHON) tests/test_keyboard_prefix.py)
t-sab-keyboard-prefix:
	$(call RUN,sabotage-keyboard-prefix,$(PYTHON) tests/test_keyboard_prefix.py --sabotage)

t-amiga-input:
	$(call RUN,amiga-input,$(PYTHON) tests/test_amiga_input.py)
t-sab-amiga-input:
	$(call RUN,sabotage-amiga-input,$(PYTHON) tests/test_amiga_input.py --sabotage)

t-sab-carry-entries:
	$(call RUN,sabotage-carry-entries,$(PYTHON) tests/test_carry_entries.py --sabotage)

t-align:
	$(call RUN,align,$(PYTHON) tests/test_align.py)
t-sab-align:
	$(call RUN,sabotage-align,$(PYTHON) tests/test_align.py --sabotage)
t-block-boundary:
	$(call RUN,block-boundary,$(PYTHON) tests/test_block_boundary.py)
t-sab-block-boundary:
	$(call RUN,sabotage-block-boundary,$(PYTHON) tests/test_block_boundary.py --sabotage)

t-next-branch:
	$(call RUN,next-branch,$(PYTHON) tests/test_next_branch.py)
t-sab-next-branch:
	$(call RUN,sabotage-next-branch,$(PYTHON) tests/test_next_branch.py --sabotage)

t-key-chords:
	$(call RUN,key-chords,$(PYTHON) tests/test_key_chords.py)
t-sab-key-chords:
	$(call RUN,sabotage-key-chords,$(PYTHON) tests/test_key_chords.py --sabotage)
t-replay-chords:
	$(call RUN,replay-chords,$(PYTHON) tests/test_replay_chords.py)
t-sab-replay-chords:
	$(call RUN,sabotage-replay-chords,$(PYTHON) tests/test_replay_chords.py --sabotage)

t-key-release:
	$(call RUN,key-release,$(PYTHON) tests/test_key_release.py)
t-sab-key-release:
	$(call RUN,sabotage-key-release,$(PYTHON) tests/test_key_release.py --sabotage)

t-helper-branches:
	$(call RUN,helper-branches,$(PYTHON) tests/test_helper_branches.py)
t-sab-helper-branches:
	$(call RUN,sabotage-helper-branches,$(PYTHON) tests/test_helper_branches.py --sabotage)
t-block-assembly:
	$(call RUN,block-assembly,$(PYTHON) tests/test_m68k_assembly.py)
t-sab-block-assembly:
	$(call RUN,sabotage-block-assembly,$(PYTHON) tests/test_m68k_assembly.py --sabotage)
t-oracle-exception-writes:
	$(call RUN,oracle-exception-writes,$(PYTHON) tests/test_oracle_exception_writes.py)
t-sab-oracle-exception-writes:
	$(call RUN,sabotage-oracle-exception-writes,$(PYTHON) tests/test_oracle_exception_writes.py --sabotage)
t-oracle-boundary:
	$(call RUN,oracle-boundary,$(PYTHON) tests/test_oracle_boundary.py)
t-sab-oracle-boundary:
	$(call RUN,sabotage-oracle-boundary,$(PYTHON) tests/test_oracle_boundary.py --sabotage)

t-dosbox-retf:
	$(call RUN,dosbox-retf,$(PYTHON) tests/test_dosbox_retf.py)
t-sab-dosbox-retf:
	$(call RUN,sabotage-dosbox-retf,$(PYTHON) tests/test_dosbox_retf.py --sabotage)

t-compact:
	$(call RUN,compact,$(PYTHON) tests/test_compact.py)

t-byteorder-entries:
	$(call RUN,byteorder-entries,$(PYTHON) tests/test_byteorder_entries.py)

t-carry-entries:
	$(call RUN,carry-entries,$(PYTHON) tests/test_carry_entries.py)

t-hunk-size:
	$(call RUN,hunk-size,$(PYTHON) tests/test_hunk_size.py)
t-profile-tools:
	$(call RUN,profile-tools,$(PYTHON) tests/test_profile_tools.py)
t-replay-hooks:
	$(call RUN,replay-hooks,$(PYTHON) tests/test_replay_hooks.py)
t-sab-replay-hooks:
	$(call RUN,sabotage-replay-hooks,$(PYTHON) tests/test_replay_hooks.py --sabotage)
t-replay-events:
	$(call RUN,replay-events,$(PYTHON) tests/test_replay_events.py)
t-sab-replay-events:
	$(call RUN,sabotage-replay-events,$(PYTHON) tests/test_replay_events.py --sabotage)
t-dos-sda:
	$(call RUN,dos-sda,$(PYTHON) tests/test_dos_sda.py)
t-sab-dos-sda:
	$(call RUN,sabotage-dos-sda,$(PYTHON) tests/test_dos_sda.py --sabotage)
t-dos-search:
	$(call RUN,dos-search,$(PYTHON) tests/test_dos_search.py)
t-sab-dos-search:
	$(call RUN,sabotage-dos-search,$(PYTHON) tests/test_dos_search.py --sabotage)
t-machine-vectors:
	$(call RUN,machine-vectors,$(PYTHON) tests/test_machine_vectors.py)
t-sab-machine-vectors:
	$(call RUN,sabotage-machine-vectors,$(PYTHON) tests/test_machine_vectors.py --sabotage)
t-file-dates:
	$(call RUN,file-dates,$(PYTHON) tests/test_file_dates.py)
t-sab-file-dates:
	$(call RUN,sabotage-file-dates,$(PYTHON) tests/test_file_dates.py --sabotage)
t-mouse-irq:
	$(call RUN,mouse-irq,$(PYTHON) tests/test_mouse_irq.py)
t-reglive:
	$(call RUN,reglive,$(PYTHON) tests/test_reglive.py)
t-smc-flow:
	$(call RUN,smc-flow,$(PYTHON) tests/test_smc_flow.py)
t-cell-cache:
	$(call RUN,cell-cache,$(PYTHON) tests/test_cell_cache.py)
t-sab-cell-cache:
	$(call RUN,sabotage-cell-cache,$(PYTHON) tests/test_cell_cache.py --sabotage)

t-cost-tools:
	$(call RUN,cost-tools,$(PYTHON) tests/test_cost_meter.py)
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
# its x86 side is reused by the sabotage plants (tests/m68k_sabotage.py)
t-m68k-boundary.0-of-1:
	$(call RUN,m68k-boundary.0-of-1,$(PYTHON) tests/m68k_diff.py --only boundary --shard 0/1 \
		--record tmp/test/x86-side-boundary.pkl)
t-blocks:
	$(call RUN,blocks,$(PYTHON) tests/m68k_blocks.py)
t-guards:
	$(call RUN,guards,$(PYTHON) tests/test_guards.py)
t-host-%:
	$(call RUN,host-$*,$(PYTHON) tests/host_run.py --milestone $*)
t-hle-music-skip:
	$(call RUN,hle-music-skip,$(PYTHON) tests/host_run.py --milestone m2-choose-side --music-skip --timeout 2400)
t-cov-%:
	$(call RUN,host-$*,$(PYTHON) tests/host_run.py --table reference/coverage.csv --milestone $* --timeout 2400)
t-sab-x86:
	$(call RUN,sabotage-x86,$(PYTHON) tests/x86_sabotage.py)
t-sab-m68k:
	$(call RUN,sabotage-m68k,$(PYTHON) tests/m68k_sabotage.py)
t-sab-host:
	$(call RUN,sabotage-host,$(PYTHON) tests/host_run.py --sabotage --milestone m1b-logo)

# Host image: the generated program and the runtime for tests/host_run.py.
# The shared toolchain (amiga/env.sh sets both; these are its defaults).
AMIGA_TOOLCHAIN ?= $(HOME)/.local/opt
VASM     ?= $(HOME)/.local/vasmm68k_mot
CROSS    = $(AMIGA_TOOLCHAIN)/bin/m68k-amiga-elf-
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
HOST_COVERAGE = c1-historical c2-german-school c3-custom c4-tour c5-records \
	c6-flight-keys c7-demo-dispatch c8-steep-bank c9-mouse-menu c10-campaign-weeks \
	c12-b17-bombing c13-me262-gunnery c15-p51-gunnery c16-p51d-gunnery \
	c17-p38-gunnery c18-p80-gunnery c19-fw190-gunnery c21-go229-gunnery \
	c24-custom-create c27-campaign-flight c28-me163-map-return \
	c29-he162-map-return c30-do335-map-return c31-map-briefing-return c32-historical-high-view \
	c33-b17-stations c34-custom-reload c35-custom-options c36-custom-flight c37-custom-roster c38-pilot-fighter c39-weapons-scroll \
	c40-map-aircraft c41-briefing-scroll c42-flight-aircraft c43-german-campaign c44-german-map c45-german-records c46-pilot-record c47-pilot-delete \
	c48-pilot-awards c49-german-awards \
	c50-campaign-abort c51-film-delete c53-tour-mission-end c54-film-views c55-tour-summary c57-film-reload c58-tour-end-map c59-tour-end-map-detail c60-tour-fate-dismiss c61-tour-end-status c52-campaign-loss c56-german-mission-end c62-tour-completed-record-view c63-tour-record-scroll c64-roster-scroll c65-pilot-long-list c66-flight-calibration c67-map-scale c68-map-aircraft-close c69-map-target-close c70-custom-friendly-end c71-custom-friendly-bailout c72-historical-end-v1 c73-p38-ground-end-v2 c74-flight-v1-close c75-campaign-setup-cancel c76-b17-gunner-auto c77-me262-flight3 c78-other-pilot-crash c79-inflight-change-orders c80-tour-briefing c81-pilot-damage c82-gunner-damage c83-program-disk-prompt c84-pilot-wing-damage c85-joystick-calibration c11-tour-mission c14-film-save c25-film-load
AMIGA_REPLAY_MILESTONES = m2-choose-side m5-player-flight c9-mouse-menu c66-flight-calibration c85-joystick-calibration
AMIGA_MILESTONE ?= m1b-logo
AMIGA_CPU ?= 68030
AMIGA_CAPTURE = tmp/amiga-$(AMIGA_MILESTONE)

test-host: host
	@$(MAKE) -s -k -j$(JOBS) $(HOST_MILESTONES:%=t-host-%)

test-host-all: host
	@$(MAKE) -s -k -j$(JOBS) $(HOST_MILESTONES_ALL:%=t-host-%) $(HOST_COVERAGE:%=t-cov-%) t-hle-music-skip

test-amiga: amiga host
	@mkdir -p $(AMIGA_CAPTURE)
	sed -e "s|@LABEL@|$$($(PYTHON) tests/host_run.py --label --milestone $(AMIGA_MILESTONE))|" \
		-e "s|@OUT@|../$(AMIGA_CAPTURE)|" amiga/milestone.gdb.in > $(AMIGA_CAPTURE)/fixture.gdb
	. amiga/env.sh && cd amiga && AMIGA_CPU=$(AMIGA_CPU) ./debug.sh "" "../$(AMIGA_CAPTURE)/fixture.gdb" 2>&1 | \
		tee ../$(AMIGA_CAPTURE)/gdb.log | sed -n 's/^SWOTL_REGS //p' > ../$(AMIGA_CAPTURE)/regs.txt
	grep -q '^SWOTL_MILESTONE_OK$$' $(AMIGA_CAPTURE)/gdb.log
	$(PYTHON) tests/host_run.py --milestone $(AMIGA_MILESTONE) --amiga $(AMIGA_CAPTURE)

# Each replay owns its image, capture directory and strictly claimed GDB port.
test-amiga-replay: host
	@$(MAKE) -s -k -j3 $(AMIGA_REPLAY_MILESTONES:%=t-amiga-replay-%)
t-amiga-replay-%:
	$(call RUN,amiga-replay-$*,. amiga/env.sh && $(PYTHON) tests/amiga_replay.py --milestone $*)

test-amiga-restore: amiga
	bash amiga/restore_check.sh

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

# Step gates (docs/speed-plan.md §2): test first (it writes build/gen and the
# host image), then the others at once, the FS-UAE gates in turn. Each
# logs to tmp/gates/<gate>.log and prints its result and seconds.
GATE = @mkdir -p tmp/gates; s=$$(date +%s); if $(MAKE) -s $(1) > tmp/gates/$(1).log 2>&1; \
	then r=ok; else r=FAIL; fi; echo "$(1) $$r $$(( $$(date +%s) - s ))s"; [ $$r = ok ]

gates:
	$(call GATE,test)
	@$(MAKE) -s -k -j3 g-sabotage g-host-all g-fsuae

g-sabotage:
	$(call GATE,test-sabotage)
g-host-all:
	$(call GATE,test-host-all)
g-fsuae:
	$(call GATE,test-amiga)
	$(call GATE,smoke)
	$(call GATE,test-amiga-restore)
	$(call GATE,test-amiga-replay)

clean:
	$(MAKE) -C amiga clean

t-sab-profile-tools:
	$(call RUN,sabotage-profile-tools,$(PYTHON) tests/test_profile_tools.py --sabotage)

t-align-convergence:
	$(call RUN,align-convergence,$(PYTHON) tests/test_align_convergence.py)
t-sab-align-convergence:
	$(call RUN,sabotage-align-convergence,$(PYTHON) tests/test_align_convergence.py --sabotage)

t-sab-cost-tools:
	$(call RUN,sabotage-cost-tools,$(PYTHON) tests/cost_tools_sabotage.py)

t-sound-hooks:
	$(call RUN,sound-hooks,$(PYTHON) tests/test_sound_hooks.py)
t-sab-sound-hooks:
	$(call RUN,sabotage-sound-hooks,$(PYTHON) tests/test_sound_hooks.py --sabotage)

t-audio:
	$(call RUN,audio,$(PYTHON) tests/test_audio.py)
t-sab-audio:
	$(call RUN,sabotage-audio,$(PYTHON) tests/test_audio.py --sabotage)

t-load-image:
	$(call RUN,load-image,$(PYTHON) tests/test_load_image.py)
t-sab-load-image:
	$(call RUN,sabotage-load-image,$(PYTHON) tests/test_load_image.py --sabotage)

t-host-launch:
	$(call RUN,host-launch,$(PYTHON) tests/test_host_launch.py)
t-sab-host-launch:
	$(call RUN,sabotage-host-launch,$(PYTHON) tests/test_host_launch.py --sabotage)

t-fixture-inputs:
	$(call RUN,fixture-inputs,$(PYTHON) tests/test_fixture_inputs.py)
t-sab-fixture-inputs:
	$(call RUN,sabotage-fixture-inputs,$(PYTHON) tests/test_fixture_inputs.py --sabotage)

t-host-replay-visits:
	$(call RUN,host-replay-visits,$(PYTHON) tests/test_host_replay_visits.py)
t-sab-host-replay-visits:
	$(call RUN,sabotage-host-replay-visits,$(PYTHON) tests/test_host_replay_visits.py --sabotage)

t-rep-replay:
	$(call RUN,rep-replay,$(PYTHON) tests/test_rep_replay.py)
t-sab-rep-replay:
	$(call RUN,sabotage-rep-replay,$(PYTHON) tests/test_rep_replay.py --sabotage)
t-rep-lowering:
	$(call RUN,rep-lowering,$(PYTHON) tests/test_rep_lowering.py)
t-sab-rep-lowering:
	$(call RUN,sabotage-rep-lowering,$(PYTHON) tests/test_rep_lowering.py --sabotage)

# Exact original gameport recording and diagnostic-only replay.
t-joystick:
	$(call RUN,joystick-cli,$(PYTHON) tests/test_joystick_cli.py)
	$(call RUN,joystick-link,$(PYTHON) tests/test_joystick_link.py)
	$(call RUN,joystick-replay,$(PYTHON) tests/test_joystick_replay.py)
	$(call RUN,joystick-events,$(PYTHON) tests/test_joystick_events.py)
	$(call RUN,joystick-recorder,$(PYTHON) tests/test_joystick_recorder.py)
t-sab-joystick:
	$(call RUN,sabotage-joystick-cli,$(PYTHON) tests/test_joystick_cli.py --sabotage)
	$(call RUN,sabotage-joystick-link,$(PYTHON) tests/test_joystick_link.py --sabotage)
	$(call RUN,sabotage-joystick-replay,$(PYTHON) tests/test_joystick_replay.py --sabotage)
	$(call RUN,sabotage-joystick-events,$(PYTHON) tests/test_joystick_events.py --sabotage)
	$(call RUN,sabotage-joystick-recorder,$(PYTHON) tests/test_joystick_recorder.py --sabotage)
