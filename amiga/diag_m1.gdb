# Milestone m1 fixture (gate 5): the generated program reaches RTSVGA.OVL+390D
# (label VGA_0390D); dump guest RAM, the state block and the guest registers
# for tests/host_run.py --amiga. Output directory: ../tmp/amiga-m1.
# gdb types a0-a7 as pointers and rt_guest has no debug type: cast both.
break VGA_0390D
commands
  silent
  printf "SWOTL_M1_REGS ax=%04x cx=%04x dx=%04x bx=%04x sp=%04x bp=%04x si=%04x di=%04x\n", $d0 & 0xffff, $d1 & 0xffff, $d2 & 0xffff, $d3 & 0xffff, $d4 & 0xffff, $d5 & 0xffff, (unsigned)$a4 & 0xffff, (unsigned)$a5 & 0xffff
  set $g = *(unsigned char **)&rt_guest
  dump binary memory ../tmp/amiga-m1/state.bin $g-16 $g
  dump binary memory ../tmp/amiga-m1/ram.bin $g $g+0x100000
  printf "SWOTL_M1_OK\n"
  quit 0
end
break plat_exit
commands
  silent
  printf "SWOTL_M1_EXIT\n"
  quit 1
end
continue
