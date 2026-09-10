; =====================================================================
;  engine2/test/tst_hud.asm -- emulator harness for the HUD.
;
;  Memory map while testing
;     #4000-#7C4D   the precalculated table bank (LINETAB lives here)
;     #7FF0         stack
;     #8000-        this harness + hud2.asm
;     #C000-        front buffer, #8000 is NOT used as a buffer here (the
;                   harness code is there); the back-buffer path is tested
;                   by pointing hud_setbuf at #C0 and #80 in turn and
;                   checking only that the SAME picture lands #4000 lower.
;
;  Entries (the driver sets PC to one of these):
;    #8000  hud_init + hud_static + hud_update, then spin, (done) = #FF
;    #8004  hud_update only (the furniture is already there), (done) = #FF
;    #8008  bench: counter++ ; hud_update            -- steady state
;    #800C  bench: counter++ ; next heading ; hud_update
;    #8010  bench: counter++ ; next heading          -- control for the above
;    #8014  bench: counter++ ; hud_static            -- the startup cost
;    #8018  bench: counter++                         -- the loop overhead
;    #801C  hud_ammo with A = (ammon), (done) = #FF
;    #8020  bench: counter++ ; hud_ammo, the count FLIPPING 0 <-> AMN so
;           every call takes the repaint branch -- the worst case, which
;           is the one C_HUD has to cover
;    #8024  hud_scan with A = (scann), (done) = #FF
;    #802C  hud_radar with (ammo_blip) as poked, (done) = #FF
;    #8028  bench: counter++ ; hud_scan, the bearing FLIPPING between two
;           DIFFERENT cells, which is the two-rectangle case -- the worst
;           one, and the one C_SCAN has to cover
; =====================================================================

    include "tab_equ_test.inc"

STACK   equ #7FF0

; ---- STAND-INS FOR THE THINGS game.asm OWNS -------------------------
;  hud2.asm's radar reads the ammo scanner's output.  This harness does
;  not include game.asm -- it never has, which is why plr_a is declared
;  at the foot of this file too -- so the two names it needs are given
;  here.  MAXAMMO has to be an equ up HERE rather than a label below,
;  because hud2.asm sizes a `ds` with it.
MAXAMMO equ 6

;  ...AND TWO MORE THAT ARRIVED LATER AND KILLED THIS HARNESS.  hud2.asm
;  grew a monster table and a health bar, so it now sizes MMVARS' tail
;  with NMON and asserts PLR_HPMAX == HUD_HPN -- both owned by game.asm
;  and gen_maze.inc, neither of which this file includes.  It stopped
;  assembling and stayed that way: rasm printed three errors, emu_hud.py
;  printed "rasm failed", and nothing else noticed.  Same shape as
;  tst_rast.asm, which had not assembled since VPCOL went to 1.
NMON    equ 1           ; only sizes mm_plc here; the real build's own
                        ; assert is what keeps MMVARS inside its hole
PLR_HPMAX equ HUD_HPN   ; TAUTOLOGICAL ON PURPOSE, and it has to be said:
                        ; the assert below it exists to catch game.asm
                        ; and genhud.py disagreeing about how many hit
                        ; points there are, and with game.asm absent
                        ; there is no second opinion to compare.  The
                        ; real build makes that check; this one cannot.

    org #8000

    di
    jp  e_once
    di
    jp  e_upd
    di
    jp  e_same
    di
    jp  e_turn
    di
    jp  e_turnctl
    di
    jp  e_static
    di
    jp  e_empty
    di
    jp  e_ammo
    di
    jp  e_ammob
    di
    jp  e_scan
    di
    jp  e_scanb
    di
    jp  e_radar

romoff
    ld  bc,#7F8C                ; mode 0, both ROMs disabled
    out (c),c
    ret

setbuf
    ld  a,(bufh)
    jp  hud_setbuf

; ---------------------------------------------------------------------
e_once
    ld  sp,STACK
    call romoff
    xor a
    ld  (done),a
    call hud_init
    call setbuf
    call hud_static
    call hud_update
    ld  a,#FF
    ld  (done),a
e_spin
    jr  e_spin

e_upd
    ld  sp,STACK
    call romoff
    xor a
    ld  (done),a
    call setbuf
    call hud_update
    ld  a,#FF
    ld  (done),a
    jr  e_spin

; ---------------------------------------------------------------------
e_same
    ld  sp,STACK
    call romoff
    call setbuf
    call hud_update             ; make sure the needle is already right
    ld  hl,0
    ld  (counter),hl
es_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call hud_update
    jr  es_l

e_turn
    ld  sp,STACK
    call romoff
    call setbuf
    ld  hl,0
    ld  (counter),hl
et_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call nextang
    call hud_update
    jr  et_l

e_turnctl
    ld  sp,STACK
    call romoff
    call setbuf
    ld  hl,0
    ld  (counter),hl
ec_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call nextang
    jr  ec_l

e_static
    ld  sp,STACK
    call romoff
    call setbuf
    ld  hl,0
    ld  (counter),hl
ez_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call hud_static
    jr  ez_l

e_empty
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ee_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    jr  ee_l

e_ammo
    ld  sp,STACK
    call romoff
    xor a
    ld  (done),a
    call setbuf
    ld  a,(ammon)
    call hud_ammo
    ld  a,#FF
    ld  (done),a
    jp  e_spin          ; ...jp: e_spin is out of jr range from down here

e_ammob
    ld  sp,STACK
    call romoff
    call setbuf
    ld  hl,0
    ld  (counter),hl
ea_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ld  a,(ammon)               ; flip 0 <-> HUD_AMN so hud_ammo can never
    xor HUD_AMN                 ; take its early-out
    ld  (ammon),a
    call hud_ammo
    jr  ea_l

e_scan
    ld  sp,STACK
    call romoff
    xor a
    ld  (done),a
    call setbuf
    ld  a,(scann)
    call hud_scan
    ld  a,#FF
    ld  (done),a
    jp  e_spin

e_scanb
    ld  sp,STACK
    call romoff
    call setbuf
    ld  hl,0
    ld  (counter),hl
es_sl
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ld  a,(scann)               ; flip between bearing 0 and bearing 4, so
    xor 4                       ; the cell always MOVES: erase one, draw
    ld  (scann),a               ; the other, which is the two-rectangle
    call hud_scan               ; worst case
    jr  es_sl

e_radar
    ld  sp,STACK
    call romoff
    xor a
    ld  (done),a
    call setbuf
    call hud_radar
    ld  a,#FF
    ld  (done),a
    jp  e_spin

; one 5-degree step of turn -- what the compass actually has to follow
nextang
    ld  a,(plr_a)
    inc a
    cp  72
    jr  c,na_ok
    xor a
na_ok
    ld  (plr_a),a
    ret

; ---------------------------------------------------------------------
counter dw 0
done    db 0
bufh    db #C0
plr_a   db 0                    ; in the real build this lives in march.asm
ammon   db 0                    ; ...and this one in game.asm, as plr_ammo
scann   db #FF                  ; ...and this one, as ammo_dir
ammo_blip ds MAXAMMO            ; ...and this array, which the radar draws
                                ; from.  e_radar below pokes it.
mon_blip  db #FF                ; ...and the monster's own bearing, which
                                ; the radar draws in its own colour

; ---- AND THE MINIMAP'S, which arrived with mm_seen and are owned by
;      march.asm and game.asm.  mm_seen folds the flood's MARK array into
;      the map and mm_plr reads where the player is standing, so a HUD
;      harness now needs four things a HUD has no business owning.  That
;      is what a byte-exact checker costs when the thing it checks grows
;      a dependency; the alternative was the checker staying dead, which
;      is what it did.
plr_x   dw #0380                ; 8.8, mid-cell: march.asm's, and mm_plr
plr_y   dw #0C80                ; reads only the high byte of each
m_gen   db 1                    ; march.asm's generation stamp.  MARK is
                                ; all zero below, so no cell reads as
                                ; seen and mm_seen walks the full fold --
                                ; which is its WORST case and the right
                                ; one to measure.
    align 256
MARK    ds 256                  ; the flood's marks, one byte a cell

    include "hud2.asm"
