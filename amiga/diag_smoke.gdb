# Smoke fixture: AGA takeover is live once the VERTB vector has counted 100 frames.
# gdb aborts the whole file at the first unknown symbol: keep in step with the source.
break Swotl::verticalBlank if Swotl::vbiCount >= 100
commands
  silent
  printf "SWOTL_SMOKE_OK vbiCount=%u\n", Swotl::vbiCount
  quit 0
end
break Swotl::~Swotl
commands
  silent
  printf "SWOTL_SMOKE_EARLY_EXIT\n"
  quit 1
end
continue
