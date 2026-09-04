; =====================================================================
;  engine2/test/tst_kern.asm
;
;  Emulator harness for the whole per-frame geometry kernel
;  (march -> proj_setup -> proj_face -> quad list).
;
;  Memory map while testing
;     #2700-#35FF   march working RAM (FTAB SOLID MARK MSTACK BUCKETS)
;     #3600-#39BF   QUADS, the kernel's output
;     #4000-#6C31   the precalculated table bank
;     #8000-        this harness + kernel + march + project + math tables
;     #7FF0         stack
;
;  #2700 is under the lower ROM in the default configuration, so every
;  entry point disables both ROMs first (the entry vectors themselves
;  live at #8000, which is RAM whatever the gate array is doing).
;
;  Entries (the driver sets PC to one of these):
;    #8000  run the kernel once, then spin, (done)=#FF
;    #8004  bench:  counter++ ; frame_geom
;    #8008  bench:  counter++ ; (empty control)
;    #800C  bench:  counter++ ; march
;    #8010  bench:  counter++ ; proj_setup + project_all  (march pre-run)
;    #8014  bench:  counter++ ; proj_setup
;    #8018  bench:  counter++ ; march_setup   (the per-frame march floor)
; =====================================================================

    include "tab_equ_test.inc"

STACK   equ #7FF0

    org #8000

; 4-byte vectors: the DI must be the very first instruction executed, or a
; pending BASIC interrupt derails us into the firmware before we get there.
    di
    jp  e_once
    di
    jp  e_all
    di
    jp  e_empty
    di
    jp  e_march
    di
    jp  e_proj
    di
    jp  e_setup
    di
    jp  e_msetup

; ---------------------------------------------------------------------
romoff
    ld  bc,#7F8C                ; mode 0, both ROMs disabled
    out (c),c
    ret

; NB: the caller must set SP before calling this -- doing it here would
; throw away boot's own return address.
boot
    call romoff
    ld  hl,MAZEDATA
    ld  de,SOLID
    ld  bc,256
    ldir
    ret

; ---------------------------------------------------------------------
e_once
    ld  sp,STACK
    call boot
    xor a
    ld  (done),a
    call frame_geom
    ld  a,#FF
    ld  (done),a
e_spin
    jr  e_spin

; ---------------------------------------------------------------------
e_all
    ld  sp,STACK
    call boot
    ld  hl,0
    ld  (counter),hl
ea_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call frame_geom
    jr  ea_l

e_empty
    ld  sp,STACK
    call boot
    ld  hl,0
    ld  (counter),hl
ee_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    jr  ee_l

e_march
    ld  sp,STACK
    call boot
    ld  hl,0
    ld  (counter),hl
em_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call march
    jr  em_l

e_proj
    ld  sp,STACK
    call boot
    call frame_geom             ; leave a real bucket list in place
    ld  hl,0
    ld  (counter),hl
ep_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call proj_setup
    call project_all
    jr  ep_l

e_setup
    ld  sp,STACK
    call boot
    call frame_geom
    ld  hl,0
    ld  (counter),hl
es_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call proj_setup
    jr  es_l

e_msetup
    ld  sp,STACK
    call boot
    ld  hl,0
    ld  (counter),hl
ems_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call march_setup
    jr  ems_l

; ---------------------------------------------------------------------
counter dw 0
done    db 0

    include "kernel.asm"
    include "march.asm"
    include "project.asm"
    include "gen_slopes.inc"
    include "gen_maze.inc"
    ; ---- MARCHTB IN BASE RAM.  march.asm reads it out of bank 5 when
    ;      MTBANK is defined and out of here when it is not, and this
    ;      harness runs AT &4000 -- paging there would swap the window
    ;      out from under its own program counter.  The include went
    ;      missing when the table moved to the bank; nothing noticed,
    ;      because engine2/tools/emu_room.py is the only caller and it is
    ;      in no make target.
    include "gen_mtab.inc"

; ---- AND ITS OWN MAP.  gen_maze.inc used to emit MAZEDATA as 64 packed
;      bytes here; they live in RAM bank 6 on the disc now, which this
;      harness has no way to reach.  It does not want them either:
;      emu_room.py POKES a synthetic 256-byte SOLID in and `boot` above
;      LDIRs it straight across, so what is needed is a writable buffer
;      of that size and not a packed map.
MAZEDATA
    ds 256
