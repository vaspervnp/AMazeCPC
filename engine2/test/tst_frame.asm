; =====================================================================
;  engine2/test/tst_frame.asm -- emulator harness for a COMPLETE FRAME.
;
;      frame = bg_fill  ->  frame_geom (march + project)  ->  raster_frame
;
;  This is the first harness that runs the whole pipeline end to end, so
;  it is the one that answers "does a frame fit in 80 ms".  Nothing is
;  modelled here: every entry point below is a real call into the real
;  code, measured with the 16-bit counter.
;
;  Memory map while testing
;     #2700-#35FF   march working RAM (FTAB SOLID MARK MSTACK BUCKETS)
;     #3600-#39BF   QUADS, the kernel's output
;     #4000-#7C4D   the precalculated table bank
;     #7FF0         stack
;     #8000-        this harness + kernel + march + project + raster + bg
;     #C000-        the buffer being painted
;
;  #2700 is under the lower ROM in the default configuration, so every
;  entry disables both ROMs first.
;
;  Entries (the driver sets PC to one of these):
;    #8000  render ONE whole frame, then spin, (done) = #FF
;    #8004  bench: counter++ ; whole frame
;    #8008  bench: counter++ ; (empty control -- the loop overhead)
;    #800C  bench: counter++ ; frame_geom only
;    #8010  bench: counter++ ; bg_fill only
;    #8014  bench: counter++ ; raster_frame only (quad list pre-built)
;    #8018  bench: counter++ ; bg_fill + frame_geom  (no fill of walls)
; =====================================================================

    include "tab_equ_test.inc"

STACK   equ #7FF0

    org #8000

; 4-byte vectors: the DI must be the very first instruction executed, or a
; pending BASIC interrupt derails us into the firmware before we get there.
    di
    jp  e_once
    di
    jp  e_frame
    di
    jp  e_empty
    di
    jp  e_geom
    di
    jp  e_bg
    di
    jp  e_rast
    di
    jp  e_bgeom
    di
    jp  e_march
    di
    jp  e_proj

; ---------------------------------------------------------------------
romoff
    ld  bc,#7F8C                ; mode 0, both ROMs disabled
    out (c),c
    ret

; NB: the caller must set SP before calling this.
boot
    call romoff
    ld  hl,MAZEDATA
    ld  de,SOLID
    ld  bc,256
    ldir
    call frame_init             ; wants bank 4, which is already at #4000
    ld   a,(bufh)
    call frame_setbuf
    ret

; The frame itself is src/frame.asm:frame_draw -- this harness does not
; own a copy of the order the three pieces run in.
frame_all   equ frame_draw

; ---------------------------------------------------------------------
e_once
    ld  sp,STACK
    call boot
    xor a
    ld  (done),a
    call frame_all
    ld  a,#FF
    ld  (done),a
e_spin
    jr  e_spin

; ---------------------------------------------------------------------
e_frame
    ld  sp,STACK
    call boot
    ld  hl,0
    ld  (counter),hl
ef_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call frame_all
    jr  ef_l

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

e_geom
    ld  sp,STACK
    call boot
    ld  hl,0
    ld  (counter),hl
eg_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call frame_geom
    jr  eg_l

e_bg
    ld  sp,STACK
    call boot
    ld  hl,0
    ld  (counter),hl
eb_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call bg_fill
    jr  eb_l

; raster only: build the quad list ONCE, then paint it over and over.
e_rast
    ld  sp,STACK
    call boot
    call frame_geom
    ld  hl,0
    ld  (counter),hl
er_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call raster_frame
    jr  er_l

e_bgeom
    ld  sp,STACK
    call boot
    ld  hl,0
    ld  (counter),hl
eq_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call bg_fill
    call frame_geom
    jr  eq_l

; The two halves of frame_geom on their own.  main3.asm's deliberate pad
; puts a vsync wait between them, so what matters is not their sum but
; whether EITHER of them can exceed one 20 ms vsync period.
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

; project only: march ONCE to fill the buckets, then project them over and
; over.  project_all reads the buckets and does not consume them.
e_proj
    ld  sp,STACK
    call boot
    call march
    ld  hl,0
    ld  (counter),hl
ep_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call project_all
    jr  ep_l

; ---------------------------------------------------------------------
counter dw 0
done    db 0
bufh    db #C0

    include "frame.asm"
    include "kernel.asm"
    include "march.asm"
    include "project.asm"
    include "raster.asm"
    include "bg.asm"
    include "gen_slopes.inc"
    include "gen_maze.inc"
