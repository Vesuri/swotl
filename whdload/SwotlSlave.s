; WHDLoad/Kickstart 3.1 launcher for the Amiga port. Cross-assembled with vasm.
; The executable uses Exec/graphics/DOS; kickfs supplies ordinary file access.
; Custom1 selects Their Finest Hour sound: the slave passes the game's own TFH
; argument (docs/sound-plan.md) through RunCommand, as a Shell does, so the
; same executable runs from a Shell.

        INCLUDE whdload.i
        INCLUDE whdmacros.i

; Code, guest RAM and the EMS store need Fast RAM (D15); memory evidence:
; docs/whdload.md, Memory.
CHIPMEMSIZE = $200000
FASTMEMSIZE = $600000
NUMDRIVES = 0
WPDRIVES = 0
BLACKSCREEN
INITAGA
BOOTDOS
CACHE                           ; _bootdos falls back to CACHECHIP without MMU
HDINIT
SEGTRACKER
NO68020                         ; portable kickemu patches; game still needs 020
; Do not use kick31.s STACKSIZE: its A600 patch at $2305c overwrites
; the MOVE.L opcode (the immediate starts at $2305e).
        IFD TEST
BOOTEARLY
DEBUG
        ENDC

slv_Version = 17
slv_Flags = WHDLF_NoError|WHDLF_ReqAGA|WHDLF_Req68020
slv_keyexit = $5f                 ; Help: the game's key table has no Help key
        INCLUDE whdload/kick31.s

slv_CurrentDir dc.b "data",0
slv_name dc.b "Secret Weapons of the Luftwaffe",0
slv_copy dc.b "1991 Lucasfilm Games",0
slv_info dc.b "Amiga port by Vesuri",10
        dc.b "Version 0.90 (28.10.2026)",10
        dc.b "Help quits",0
slv_config dc.b "C1:B:Their Finest Hour sound effects;",0
        dc.b "$VER: SWotL.slave 0.90 (28.10.2026)",0
_program dc.b "SWotL",0
; Test only, keys of pc-reference-loop.md scripts: CAMPAIGN creates campaign
; file A.CBA (c10); TOUR creates pilot A, then rewrites it with O_TRUNC (c11).
        IFD CAMPAIGN
_args_fm dc.b "KEYS=300:enter,p300:enter,p200:u,p200:b,p200:s,p600:1,p600:2,p600:a,p100:enter",10,0
        ELSE
        IFD TOUR
_args_fm dc.b "KEYS=300:enter,p300:enter,p200:u,p200:t,p200:s,p600:2,p600:c,p600:a,p100:enter,p600:s,p600:1,p600:m",10,0
        ELSE
_args_fm dc.b 10,0
        ENDC
        ENDC
_args_fm_end
_args_tfh dc.b "TFH",10,0
_args_tfh_end
        EVEN

_bootdos
        move.l (_resload,pc),a2
        ; CACHE marks BaseMem noncacheable, which needs WHDLoad's MMU (68040/060,
        ; 68030 with the MMU option); without it WHDLoad switches every cache off
        ; (CACR 0). Then keep CACHECHIP's instruction cache (docs/whdload.md).
        move.l 4.w,a6
        lea (_getcacr,pc),a5
        jsr (_LVOSupervisor,a6)
        and.w #$8001,d0           ; IC (68040/060) or EI (68020/030)
        bne .cached
        move.l #WCPUF_Base_WT|WCPUF_Exp_CB|WCPUF_Slave_CB|WCPUF_IC|WCPUF_BC|WCPUF_SS|WCPUF_SB,d0
        move.l #WCPUF_All,d1
        jsr (resload_SetCPU,a2)
.cached
        lea (_config_tags,pc),a0
        jsr (resload_Control,a2)
        IFD BOOTONLY
        pea TDREASON_OK
        jmp (resload_Abort,a2)
        ENDC
        IFD TEST
        lea (_bootmark,pc),a0
        bsr _mark
        ENDC
        ; The argument line and its length without the terminating zero.
        lea (_args_fm,pc),a0
        move.l #_args_fm_end-_args_fm-1,d0
        tst.l (_tfh,pc)
        beq .args
        lea (_args_tfh,pc),a0
        move.l #_args_tfh_end-_args_tfh-1,d0
.args   lea (_args,pc),a1
        move.l a0,(a1)+
        move.l d0,(a1)
        IFD TEST
        move.l (_args,pc),a1
        lea (_argsmark,pc),a0
        jsr (resload_SaveFile,a2)
        ENDC
        lea (_dosname,pc),a1
        move.l 4.w,a6
        jsr (_LVOOldOpenLibrary,a6)
        move.l d0,a6
        tst.l d0
        beq .oserror
        lea (_program,pc),a0
        move.l a0,d1
        jsr (_LVOLoadSeg,a6)
        move.l d0,d7
        beq .readerror
        IFD TEST
        lea (_loadmark,pc),a0
        bsr _mark
        ENDC
        jsr (resload_FlushCache,a2)
        ; Establish PROGDIR as a Shell would. Calling a LoadSeg entry alone
        ; does not set pr_HomeDir.
        lea (_current,pc),a0
        move.l a0,d1
        moveq #-2,d2              ; ACCESS_READ, lock the actual current drawer
        jsr (_LVOLock,a6)
        tst.l d0
        beq .readerror
        move.l d0,d1
        jsr (_LVOSetProgramDir,a6)
        lea (_oldhome,pc),a0
        move.l d0,(a0)
        IFD LOADONLY
        pea TDREASON_OK
        jmp (resload_Abort,a2)
        ENDC
        ; RunCommand allocates and swaps in the stack and also places the line
        ; in Input()'s buffer, where ReadArgs reads it (dos.doc RunCommand);
        ; -1 when it could not run the program.
        move.l d7,d1
        move.l #16384,d2
        move.l (_args,pc),d3
        move.l (_argslen,pc),d4
        jsr (_LVORunCommand,a6)
        move.l d0,d6
        move.l (_oldhome,pc),d1
        jsr (_LVOSetProgramDir,a6)
        move.l d0,d1
        jsr (_LVOUnLock,a6)
        move.l d7,d1
        jsr (_LVOUnLoadSeg,a6)
        move.l a6,a1
        move.l 4.w,a6
        jsr (_LVOCloseLibrary,a6)
        tst.l d6
        bne .gameerror
        IFD TEST
        lea (_exitmark,pc),a0
        bsr _mark
        ENDC
        IFD MEMFREE
        ; Diagnostic only: kickemu's lowest largest free Chip/Fast chunks.
        lea (_memfreename,pc),a0
        lea MEMFREE,a1
        moveq #8,d0
        move.l (_resload,pc),a2
        jsr (resload_SaveFile,a2)
        ENDC
        pea TDREASON_OK
        bra .abort
.readerror
        jsr (_LVOIoErr,a6)
        pea (_program,pc)
        move.l d0,-(sp)
        pea TDREASON_DOSREAD
        bra .abort
.oserror
        clr.l -(sp)
        clr.l -(sp)
        pea TDREASON_OSEMUFAIL
        bra .abort
.gameerror
        pea (_failed,pc)
        pea TDREASON_FAILMSG
.abort
        move.l (_resload,pc),a2
        jmp (resload_Abort,a2)
_getcacr
        movec cacr,d0
        rte
_failed dc.b "Secret Weapons of the Luftwaffe could not start. Check the installed original data files.",0
        IFD MEMFREE
_memfreename dc.b "memfree",0
        ENDC
_current dc.b 0
        EVEN
_config_tags dc.l WHDLTAG_CUSTOM1_GET
_tfh    dc.l 0
        dc.l 0
_args   dc.l 0
_argslen dc.l 0
_oldhome dc.l 0
        IFD TEST
_bootearly
        move.l (_resload,pc),a2
        lea (_earlymark,pc),a0
        bra _mark
_mark
        movem.l d0-d1/a0-a1,-(sp)
        lea (_marker,pc),a1
        moveq #4,d0
        jsr (resload_SaveFile,a2)
        movem.l (sp)+,d0-d1/a0-a1
        rts
_marker dc.b "PASS"
_earlymark dc.b "test-early",0
_bootmark dc.b "test-bootdos",0
_argsmark dc.b "test-args",0
_loadmark dc.b "test-loaded",0
_exitmark dc.b "test-returned",0
        EVEN
        ENDC
