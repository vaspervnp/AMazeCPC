; =====================================================================
;  engine2/test/tst_bg.asm -- emulator harness for the background fill.
;
;  Memory map while testing
;     #4000-#7C2C   the precalculated table bank (BANDPEN lives here)
;     #8000-        this harness + bg.asm
;     #7FF0         stack
;     #C000-        the buffer being painted
;
;  Entries (the driver sets PC to one of these, and pokes (bg_list) to
;  choose the 2-band or the 4-band background first):
;    #8000  paint once, then spin, (done) = #FF
;    #8004  bench: counter++ ; bg_fill
;    #8008  bench: counter++            (the empty control)
; =====================================================================

    include "tab_equ_test.inc"

STACK   equ #7FF0

    org #8000

    di
    jp  e_once
    di
    jp  e_bg
    di
    jp  e_empty

romoff
    ld  bc,#7F8C                ; mode 0, both ROMs disabled
    out (c),c
    ret

; ---------------------------------------------------------------------
e_once
    ld  sp,STACK
    call romoff
    call bg_init
    xor a
    ld  (done),a
    call bg_fill
    ld  a,#FF
    ld  (done),a
e_spin
    jr  e_spin

e_bg
    ld  sp,STACK
    call romoff
    call bg_init
    ld  hl,0
    ld  (counter),hl
eb_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call bg_fill
    jr  eb_l

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

; ---------------------------------------------------------------------
counter dw 0
done    db 0

    include "bg.asm"
