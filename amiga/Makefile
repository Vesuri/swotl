# SWOTL — Amiga cross-build (m68k-amiga-elf-gcc), A1200 68020/AGA.
#
#   . ./env.sh && make   — build out/Swotl.exe
#   make clean           — remove obj/ and out/
#   ./run.sh             — boot in FS-UAE (A1200, Kickstart 3.1)
#   ./debug.sh [ROM] [fixture.gdb] — source-level debug via the FS-UAE GDB stub
#
# Code lives under $(REPO)/src; this directory holds only build infrastructure.

OUT      = out/Swotl
CC       = m68k-amiga-elf-gcc
AS       = m68k-amiga-elf-as
VASM     = vasmm68k_mot
OBJDUMP  = m68k-amiga-elf-objdump
PYTHON   = python3
SDKDIR   = $(abspath $(dir $(shell which $(CC)))../m68k-amiga-elf/sys-include)
SUPPORT  = $(abspath $(dir $(shell which $(CC)))../../support)
REPO      = ..
AMIGA_PYLIB ?= $(HOME)/.local/share/amiga/pylib
AMIGA_SRC = $(REPO)/src/platform/amiga
FRAMEWORK = $(AMIGA_SRC)/framework
RUNTIME   = $(REPO)/src/runtime
GEN       = $(REPO)/build/gen

CCFLAGS  = -g -MP -MMD -m68020 -msoft-float -O2 -nostdlib \
	-fomit-frame-pointer -fno-tree-loop-distribution \
	-ffunction-sections -fdata-sections -Wall -Wextra -Werror \
	-Wno-volatile-register-var
CPPFLAGS = $(CCFLAGS) -fno-rtti -fno-exceptions -fno-use-cxa-atexit -fcheck-new \
	-std=gnu++17 -fpermissive -Wno-write-strings -Wno-pointer-arith \
	-Wno-ignored-qualifiers -Wno-sign-compare \
	-Wno-parentheses -Wno-unused-parameter \
	-include "$(FRAMEWORK)/SASCCompat.h" \
	-I"$(FRAMEWORK)" -I"$(FRAMEWORK)/compat-include" -I"$(AMIGA_SRC)" -I"$(RUNTIME)"
ASFLAGS  = -mcpu=68020 -g --register-prefix-optional -I"$(SDKDIR)"
VASMFLAGS = -m68020 -Felf -quiet -x -no-opt -nowarn=62 -I"$(SDKDIR)" -Iobj
# Generated code: vasm picks branch sizes (translator/emit.py output, never edited).
VASMGEN  = -m68020 -Felf -quiet -x -nowarn=62
LDFLAGS  = -Wl,--emit-relocs,--gc-sections,-Ttext=0,-Map=$(OUT).map

OBJECTS = obj/main.o obj/Swotl.o obj/Input.o obj/Audio.o obj/GCCRuntime.o \
	obj/framework_amiga_hardware.o obj/framework_bitmap.o \
	obj/framework_copper_list.o obj/framework_palette24.o \
	obj/gcc8_c_support.o obj/gcc8_a_support.o obj/memory.o obj/version.o \
	obj/amiga_platform.o obj/tfh_paula.o obj/fm_paula.o obj/amiga_run.o obj/c2p1x1_8_c5_bm.o obj/rt_entry.o \
	$(patsubst $(RUNTIME)/%.c,obj/rt_%.o,$(wildcard $(RUNTIME)/*.c)) obj/program.o obj/compute_projection.o obj/compute_normalise.o obj/compute_scenery.o obj/compute_native.o

# Sync image (docs/irq-plan.md I8): the generated sync-point checks and the
# runtime's sync mode (no tick at the CIA interrupt, keys as IRQ1), for the bench
# (make amiga-sync) and every replay image. Production has neither.
ifneq ($(SYNC)$(REPLAY),)
CCFLAGS += -DSWOTL_SYNC
VASMGEN += -DSWOTL_SYNC=1
endif

# Diagnostic image is built in a separate working directory by the replay test.
ifneq ($(REPLAY),)
CCFLAGS += -DSWOTL_REPLAY -I"$(REPLAY)"
VASMFLAGS += -DSWOTL_REPLAY=1
OBJECTS += obj/replay_c.o obj/replay_s.o
ifneq ($(wildcard $(REPLAY)/joystick_data.h),)
OBJECTS += obj/joystick_replay.o
LDFLAGS += -Wl,--wrap=rt_port_in,--wrap=rt_port_out
obj/joystick_replay.o: $(REPO)/tests/joystick_replay.c $(REPLAY)/joystick_data.h | obj
	$(CC) $(CCFLAGS) -ffreestanding -I"$(RUNTIME)" -c -o $@ $<
endif
obj/replay_c.o: $(REPO)/tests/amiga_replay.c $(REPLAY)/replay_data.h | obj
	$(CC) $(CCFLAGS) -ffreestanding -I"$(RUNTIME)" -c -o $@ $<
obj/replay_s.o: $(REPO)/tests/amiga_replay.s | obj
	$(VASM) $(VASMFLAGS) -o $@ $<
endif

.DEFAULT_GOAL := all
.PHONY: all clean verify-runtime
# Never leave a truncated executable that looks up to date after elf2hunk fails.
.DELETE_ON_ERROR:

all: $(OUT).exe

obj out:
	mkdir -p $@

verify-runtime: obj/gcc8_c_support.o
	PYTHONPATH='$(AMIGA_PYLIB)' $(PYTHON) -m amigaxdev.dos.verify_amiga_runtime $(OBJDUMP) $<

obj/main.o: $(REPO)/src/main.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/Swotl.o: $(AMIGA_SRC)/Swotl.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/Audio.o: $(AMIGA_SRC)/Audio.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/Input.o: $(AMIGA_SRC)/Input.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/GCCRuntime.o: $(AMIGA_SRC)/GCCRuntime.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/framework_amiga_hardware.o: $(FRAMEWORK)/AmigaHardware.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/framework_bitmap.o: $(FRAMEWORK)/Bitmap.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/framework_copper_list.o: $(FRAMEWORK)/CopperList.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/framework_palette24.o: $(FRAMEWORK)/Palette24Bit.cpp | obj
	$(CC) $(CPPFLAGS) -c -o $@ $<

obj/gcc8_c_support.o: $(SUPPORT)/gcc8_c_support.c Makefile | obj
	# Runtime implementations must not be folded into calls to themselves.
	$(CC) $(CCFLAGS) -fno-builtin -Dmemcpy=swotl_support_memcpy -Dmemset=swotl_support_memset -c -o $@ $<

obj/gcc8_a_support.o: $(SUPPORT)/gcc8_a_support.s | obj
	$(AS) $(ASFLAGS) -o $@ $<

obj/memory.o: $(AMIGA_SRC)/memory.s | obj
	$(VASM) $(VASMFLAGS) -o $@ $<

obj/amiga_platform.o: $(AMIGA_SRC)/amiga_platform.c | obj
	$(CC) $(CCFLAGS) -ffreestanding -I"$(RUNTIME)" -I"$(AMIGA_SRC)" -c -o $@ $<

obj/tfh_paula.o: $(AMIGA_SRC)/tfh_paula.c | obj
	$(CC) $(CCFLAGS) -ffreestanding -c -o $@ $<

obj/fm_paula.o: $(AMIGA_SRC)/fm_paula.c | obj
	$(CC) $(CCFLAGS) -ffreestanding -c -o $@ $<

obj/amiga_run.o: $(AMIGA_SRC)/amiga_run.s | obj
	$(VASM) $(VASMFLAGS) -o $@ $<

obj/c2p1x1_8_c5_bm.o: $(AMIGA_SRC)/c2p1x1_8_c5_bm.s | obj
	$(VASM) $(VASMFLAGS) -o $@ $<

obj/rt_%.o: $(RUNTIME)/%.c | obj
	$(CC) $(CCFLAGS) -ffreestanding -I"$(RUNTIME)" -c -o $@ $<

obj/rt_entry.o: $(RUNTIME)/rt_entry.s $(RUNTIME)/compute_transform.s | obj
	$(VASM) $(VASMFLAGS) -I"$(RUNTIME)" -o $@ $<

obj/compute_scenery.o: $(RUNTIME)/compute_scenery.s | obj
	$(VASM) $(VASMFLAGS) -I"$(RUNTIME)" -o $@ $<

obj/compute_normalise.o: $(RUNTIME)/compute_normalise.s | obj
	$(VASM) $(VASMFLAGS) -I"$(RUNTIME)" -o $@ $<

obj/compute_projection.o: $(RUNTIME)/compute_projection.s | obj
	$(VASM) $(VASMFLAGS) -I"$(RUNTIME)" -o $@ $<

obj/program.o: $(GEN)/program.s $(wildcard $(GEN)/*.s) | obj
	$(VASM) $(VASMGEN) -I"$(GEN)" -o $@ $<

obj/version.o: $(AMIGA_SRC)/version.s | obj
	$(AS) $(ASFLAGS) -o $@ $<

$(OUT).elf: $(OBJECTS) | out verify-runtime
	$(CC) $(CCFLAGS) $(LDFLAGS) $(OBJECTS) -o $@
	$(OBJDUMP) --disassemble --no-show-raw-ins -S $@ > $(OUT).s 2>/dev/null || true

$(OUT).exe: $(OUT).elf
	elf2hunk $< $@

clean:
	$(RM) -r obj out

-include obj/*.d

obj/compute_native.o: $(RUNTIME)/compute_native.s $(RUNTIME)/compute_sprite.s $(RUNTIME)/compute_line.s $(RUNTIME)/compute_raster.s $(RUNTIME)/compute_opl.s $(GEN)/native_polls.i | obj
	$(VASM) $(VASMFLAGS) -I"$(RUNTIME)" -I"$(GEN)" -o $@ $<
