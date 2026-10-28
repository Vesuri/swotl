# Run from anywhere: make -C tools/install-data [amiga|test]
# Source amiga/env.sh before building the Amiga binary.
# io*, sha256*, start.s: AmigaXDev install-data; blast*: zlib contrib/blast 1.3.
# Both are vendored unchanged and pinned in vendored.sha256.
ROOT := ../..
BUILD ?= $(ROOT)/build/install-data
CC ?= cc
CFLAGS ?= -O2 -g
WARN = -std=c99 -Wall -Wextra -Werror
SOURCES = install.c sha256.c blast.c
HEADERS = io.h sha256.h blast.h install_config.h
AMIGA_CC = m68k-amiga-elf-gcc
AMIGA_NM = $(dir $(shell command -v $(AMIGA_CC)))../m68k-amiga-elf/bin/nm
# 68020 like the game: 32-bit divide in the FAT12 reader, no libgcc.
AMIGA_FLAGS = -std=c99 -O2 -g -m68020 -msoft-float -nostdlib -fno-builtin -fno-tree-loop-distribute-patterns -fstack-usage -Wall -Wextra -Wno-volatile-register-var -DINSTALL_AMIGA -Iamiga
.PHONY: all amiga test pinned
all: pinned $(BUILD)/SWotLInstallData
pinned:
	@shasum -a 256 -c --quiet vendored.sha256
$(BUILD):
	mkdir -p $@
$(BUILD)/SWotLInstallData: $(SOURCES) io_unix.c $(HEADERS) | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) $(SOURCES) io_unix.c -o $@
amiga: pinned $(BUILD)/SWotLInstallData.exe
$(BUILD)/install.o: install.c $(HEADERS) Makefile | $(BUILD)
	$(AMIGA_CC) $(AMIGA_FLAGS) -c $< -o $@
$(BUILD)/blast.o: blast.c blast.h amiga/setjmp.h Makefile | $(BUILD)
	$(AMIGA_CC) $(AMIGA_FLAGS) -c $< -o $@
$(BUILD)/sha256.o: sha256.c sha256.h io.h Makefile | $(BUILD)
	$(AMIGA_CC) $(AMIGA_FLAGS) -c $< -o $@
$(BUILD)/io_amiga.o: io_amiga.c io.h install_config.h Makefile | $(BUILD)
	$(AMIGA_CC) $(AMIGA_FLAGS) -c $< -o $@
$(BUILD)/start.o: start.s | $(BUILD)
	$(AMIGA_CC) -m68020 -c $< -o $@
$(BUILD)/setjmp.o: amiga/setjmp.s | $(BUILD)
	$(AMIGA_CC) -m68020 -c $< -o $@
$(BUILD)/SWotLInstallData.elf: $(BUILD)/start.o $(BUILD)/install.o $(BUILD)/blast.o $(BUILD)/sha256.o $(BUILD)/io_amiga.o $(BUILD)/setjmp.o
	$(AMIGA_CC) -nostdlib -m68020 -Wl,--emit-relocs,-Ttext=0,-e,_start,-Map=$(BUILD)/SWotLInstallData.map $^ -o $@
	$(AMIGA_NM) -u $@ > $(BUILD)/undefined.txt
	@test ! -s $(BUILD)/undefined.txt
$(BUILD)/SWotLInstallData.exe: $(BUILD)/SWotLInstallData.elf
	elf2hunk $< $@ -s
test: all
	python3 test_install.py $(BUILD)/SWotLInstallData
