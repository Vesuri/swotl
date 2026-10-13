-- Emulator events enter CIA/JOY0DAT; no writes to game RAM or calls to Input.
local field = 0
local function event(s)
    uae_log("SWOTL_INPUT " .. s .. "\n")
    uae_write_config(s)
end
function on_uae_vsync()
    field = field + 1
    if field == 10 then uae_log("SWOTL_HARDWARE_LUA_STARTED") end
    if field == 2000 then event("KEY_RETURN 1") end
    if field == 2010 then event("KEY_RETURN 0") end
    if field == 2020 then
        event("MOUSE1_HORIZ 1")
        event("MOUSE1_VERT -1")
    end
    if field == 2040 then
        event("MOUSE1_HORIZ 0")
        event("MOUSE1_VERT 0")
    end
    if field == 2050 then event("JOY1_FIRE_BUTTON 1") end
    if field == 2060 then
        event("JOY1_FIRE_BUTTON 0")
        event("JOY1_2ND_BUTTON 1")
    end
    if field == 2070 then
        event("JOY1_2ND_BUTTON 0")
        event("JOY1_3RD_BUTTON 1")
    end
    if field == 2080 then event("JOY1_3RD_BUTTON 0") end
end
