; =====================================================================
;  engine2/test/tst_rast.asm -- emulator harness for src/raster.asm.
;
;  The quad record(s) are poked straight into QUADS by the driver, so no
;  geometry runs here at all: this measures and verifies the RASTERISER
;  and nothing else.
;
;  Memory map while testing
;     #3600-#39BF   QUADS (the same address kernel.asm uses)
;     #4000-#7C4D   the precalculated table bank (LINETAB, RAMP)
;     #8000-        this harness + raster.asm
;     #7FF0         stack
;
;  Entries (the driver sets PC to one of these):
;    #8000  rasterise ONE quad at QUADS, then spin, (done) = #FF
;    #8004  bench: counter++ ; raster_quad(QUADS)
;    #8008  bench: counter++ ; (empty control)
;    #800C  rasterise (fg_nquad) quads, then spin, (done) = #FF
;    #8010  bench: counter++ ; raster_frame
;
;  BUILT TWICE.  `rasm -DPACED=1` compiles raster.asm's MID-QUAD YIELD --
;  the hooks that let main3.asm's accumulator take its vsync every RQ_BCH
;  body scanlines and every RQ_WCH wedge pairs -- and the stub accumulator
;  at the foot of this file stands in for main3.asm's.  emu_rast.py
;  verifies BOTH builds against the same model, because the whole claim
;  the hooks have to earn is that they change the TIMING and not one
;  pixel: SP is the screen pointer inside a fill, so a hook that borrows a
;  real stack for its CALL and hands the screen back wrongly corrupts the
;  picture, not the schedule.  The stub therefore YIELDS ON EVERY CALL --
;  the maximally hostile case -- and its yield clobbers exactly what
;  main3.asm's wait_vsync clobbers, which is A and B and nothing else.
; =====================================================================

    include "tab_equ_test.inc"

STACK   equ #7FF0

; QUADS COMES FROM THE ENGINE, IT IS NOT A COPY.  This file used to carry
; its own `QUADS equ #3600`; see memmap.inc for what that cost.
    include "memmap.inc"
QRECSZ  equ 8

    org #8000

    di
    jp  e_once
    di
    jp  e_bench
    di
    jp  e_empty
    di
    jp  e_many
    di
    jp  e_fbench
    ifdef PACED
    di
    jp  e_hbench
    endif

; ---------------------------------------------------------------------
romoff
    ld  bc,#7F8C                ; mode 0, both ROMs disabled
    out (c),c
    ret

setup
    call romoff
    call raster_init            ; needs bank 4 (LINETAB)
    ld   a,(bufh)
    call raster_setbuf
    ret

; ---------------------------------------------------------------------
e_once
    ld  sp,STACK
    call setup
    xor a
    ld  (done),a
    ld  hl,QUADS
    call raster_quad
    ld  a,#FF
    ld  (done),a
e_spin
    jr  e_spin

e_many
    ld  sp,STACK
    call setup
    xor a
    ld  (done),a
    call raster_frame
    ld  a,#FF
    ld  (done),a
    jr  e_spin

; ---------------------------------------------------------------------
e_bench
    ld  sp,STACK
    call setup
    ld  hl,0
    ld  (counter),hl
eb_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ifdef PACED
    xor a                       ; DISARM the hook trap: it is a countdown
    ld  (hookn),a               ; in RAM and e_hbench leaves it part-way
    endif                       ; down.  e_empty pays the same 2 us.
    ld  hl,QUADS
    call raster_quad
    jr  eb_l

e_empty
    ld  sp,STACK
    call setup
    ld  hl,0
    ld  (counter),hl
ee_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ifdef PACED
    xor a
    ld  (hookn),a
    endif
    jr  ee_l

e_fbench
    ld  sp,STACK
    call setup
    ld  hl,0
    ld  (counter),hl
ef_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ifdef PACED
    xor a
    ld  (hookn),a
    endif
    call raster_frame
    jr  ef_l

; ---------------------------------------------------------------------
counter  dw 0
done     db 0
bufh     db #C0
fg_nquad db 0                   ; kernel.asm owns this in the real build

    ifdef PACED
; ---------------------------------------------------------------------
;  THE STUB ACCUMULATOR -- main3.asm's cost_unit, minus the game.
;
;  The C_* are main3.asm's own values; they only decide what number goes
;  into an accumulator nobody reads here, but keeping them identical
;  means this harness assembles the SAME hook code the disc runs.
;
;  IT IS main3.asm's cost_unit AND pace_wait, INSTRUCTION FOR
;  INSTRUCTION, with two deliberate differences:
;
;    * COST_THI is 0, so `CP COST_THI` never sets carry and EVERY call
;      takes the YIELD branch.  That is both the expensive path (so what
;      this harness times is the worst hook, not the average one) and the
;      hostile one (wait_vsync's `LD B,#F5 / IN A,(C) / RRA` destroys A
;      and B, so a hook that forgot to save the moving edge in C or the
;      fill word in DE paints the wrong pixels and emu_rast.py sees it).
;    * wait_vsync is a RET.  This is measuring WORK, not schedule, which
;      is the same stub engine2/tools/emu_pacefit.py pokes into the
;      running game before it benches anything.
;
;  Plus an 8 us prologue -- LD HL,hookn / DEC (HL) / JR Z -- that e_hbench
;  needs and the disc does not have.  It is in every interval this harness
;  reports, once, and the driver subtracts it.
; ---------------------------------------------------------------------
C_QSET   equ 880
C_BLINE  equ 20
C_WPAIR  equ 122
C_CHUNK  equ 300
C_PMUL   equ 90
COST_THI equ 0                  ; -> every call yields; see above

cost_unit
    push af
    push hl
    ld   hl,hookn               ; the e_hbench prologue: hookn counts DOWN
    ld   a,(hl)                 ; from whatever the driver set, and zero
    or   a                      ; is where this run stops.  0 disables it,
    jr   z,cu_go                ; which is how every other entry runs.
    dec  (hl)
    jr   z,hb_abort
cu_go
    ld   hl,(cost_acc)
    add  hl,bc
    ld   a,h
    cp   COST_THI
    jr   nc,cu_yield
    ld   (cost_acc),hl
cu_ret
    pop  hl
    pop  af
    ret
cu_yield
    ld   (cost_acc),bc
    call pace_wait
    jr   cu_ret

pace_wait
    ld   a,(pace_left)
    or   a
    jr   z,pw_go
    dec  a
    ld   (pace_left),a
pw_go
    ld   b,#F5                  ; wait_vsync's own opening, so the yield
    in   a,(c)                  ; wrecks exactly the registers the real
    rra                         ; one wrecks...
    ret                         ; ...but does not wait

cost_acc  dw 0
pace_left db 0
hookn     db 0                  ; hooks left before e_hbench gives up

; ---------------------------------------------------------------------
;  e_hbench -- THE ATOMIC UNIT, MEASURED RATHER THAN MODELLED.
;
;  The thing the mid-quad yield exists to shrink is the longest stretch of
;  work between two points at which main3.asm's accumulator could take a
;  vsync -- i.e. between two cost_unit calls.  There is no clock on the
;  machine to time that with, so this times a PREFIX instead: cost_unit
;  above bails out to hb_abort on the k'th call, so the bench loop
;  measures "raster_quad up to hook k".  The driver sweeps k, and the
;  DIFFERENCES between consecutive k are the intervals themselves; a k
;  bigger than the quad has hooks runs the whole quad.
;
;  The abort throws away whatever cost_unit had pushed, which is why it
;  reloads SP -- and SP may be anywhere in the screen when a hook fires,
;  so it has to be reloaded in any case.
; ---------------------------------------------------------------------
e_hbench
    ld  sp,STACK
    call setup
    ld  hl,0
    ld  (counter),hl
hb_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ld  a,(hookk)               ; the driver sets k; hookn counts it down
    ld  (hookn),a
    ld  hl,QUADS
    call raster_quad
    jr  hb_l
hb_abort
    ld  (hookbc),bc             ; the CHARGE this hook was about to take,
    ld  sp,STACK                ; so the driver can check it against
    jr  hb_l                    ; pacemodel.py's twin of the same sum
hookk    db 255                 ; how many hooks to let through; 255 = all
hookbc   dw 0
    endif

    include "raster.asm"
