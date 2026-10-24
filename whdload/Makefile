# Native host cross-build: no Amiga assembler or build utilities required.
WHDLOAD ?= $(HOME)/.local/share/amiga/WHDLoad
NDK ?= $(HOME)/.local/opt/m68k-amiga-elf/sys-include
VASM ?= $(HOME)/.local/vasmm68k_mot
AMIGA_SHARE ?= $(HOME)/.local/share/amiga
OUT := ../build/whdload

# all: the release slave. The others are tools/test_whdload.py scaffolding:
# --mode smoke|boot|load, the TEST slave's PASS markers, and MemFree, which
# records kickemu's free-memory low-water marks in data/memfree for sizing
# the slave's memory reservation (docs/whdload.md).
.PHONY: all test smoke boot-test load-test memfree FORCE
all: $(OUT)/Swotl.slave
test: $(OUT)/SwotlTest.slave
smoke: $(OUT)/Smoke.slave
boot-test: $(OUT)/BootTest.slave
load-test: $(OUT)/LoadTest.slave
memfree: $(OUT)/MemFree.slave
$(OUT)/SwotlTest.slave: VASMFLAGS += -DTEST=1
$(OUT)/BootTest.slave: VASMFLAGS += -DBOOTONLY=1
$(OUT)/LoadTest.slave: VASMFLAGS += -DLOADONLY=1
$(OUT)/MemFree.slave: VASMFLAGS += -DMEMFREE=\$$100

# Reassemble the small slave on every invocation: SDK includes and assembler
# options must never leave an old diagnostic slave in a release package.
$(OUT)/Swotl.slave $(OUT)/SwotlTest.slave $(OUT)/MemFree.slave $(OUT)/BootTest.slave $(OUT)/LoadTest.slave: SwotlSlave.s FORCE
	@mkdir -p $(OUT)/include/lvo
	@for lib in dos exec graphics expansion; do ln -sf "$(NDK)/lvo/$${lib}_lib.i" "$(OUT)/include/lvo/$$lib.i"; done
	$(VASM) -m68020 -pic -x -devpac -Fhunkexe -nosym $(VASMFLAGS) -I$(OUT)/include -I"$(WHDLOAD)/Include" -I"$(WHDLOAD)/Src/sources" -I"$(NDK)" -o $@ $<

# The smoke slave is AmigaXDev's shared one with this project's name (smoke_name.i).
$(OUT)/Smoke.slave: $(AMIGA_SHARE)/whdload/SmokeSlave.s smoke_name.i FORCE
	@mkdir -p $(OUT)
	$(VASM) -m68000 -pic -x -devpac -Fhunkexe -nosym -DSMOKE_DATA_LAST=1 -I. -I"$(WHDLOAD)/Include" -I"$(NDK)" -o $@ $<
