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
; =====================================================================

    include "tab_equ_test.inc"

STACK   equ #7FF0

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

    include "hud2.asm"
