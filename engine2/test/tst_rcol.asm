; =====================================================================
;  engine2/test/tst_rcol.asm -- emulator harness for src/rastcol.asm.
;
;  The quad records are poked straight into QUADS by the driver, so no
;  geometry runs here at all: this verifies and measures the COLUMN
;  RENDERER and nothing else, exactly as tst_rast.asm does for the span
;  renderer.
;
;  TWO BANKS, AND THE DRIVER LOADS THEM DIFFERENTLY.  rastcol.asm reads
;  its textures out of RAM bank 5, and cpc.write_ram cannot put them
;  there: it writes the BASE 64K, banks 0-3, ignoring paging -- which is
;  also why every other harness here can write "bank 4" at &4000 without
;  ever selecting it.  emu_rcol.py writes bank 5 through cpcemu_ram_ptr
;  instead, straight into the physical bank.  raster_colframe pages bank 5
;  in and bank 4 back out around itself, so nothing here has to care.
;
;  Memory map while testing
;     #3700-#3ABF   QUADS (the same address kernel.asm uses)
;     #3FF0         stack -- BELOW the paged window, see below
;     #4000-        bank 4: the precalculated tables (LINETAB)
;                   bank 5: the textures, CTABT and RTHRESH
;     #8000-        this harness + raster.asm + rastcol.asm
;
;  Entries (the driver sets PC to one of these):
;    #8000  render (fg_nquad) quads, then spin, (done) = #FF
;    #8004  bench: counter++ ; raster_colframe
;    #8008  bench: counter++ ; (empty control)
; =====================================================================

    include "tab_equ_test.inc"

; THE STACK MUST LIVE BELOW &4000, and that is not a detail.  This
; harness's first version put it at &7FF0, where every other harness here
; puts it -- and &7FF0 is INSIDE the &4000-&7FFF window raster_colframe
; pages bank 5 into.  The render came out 99.7% right and then RET'd into
; the firmware, because the return address had been pushed into one bank
; and popped out of another.  The game has never had this problem: its
; STACKTOP is &3FF0, under the window, which is where this one is now.
STACK   equ #3FF0

; QUADS COMES FROM THE ENGINE, IT IS NOT A COPY.  See memmap.inc for what
; a second copy of it cost the last time there was one.
    include "memmap.inc"
QRECSZ  equ 8

    org #8000

    di
    jp  e_many
    di
    jp  e_bench
    di
    jp  e_empty
    ifdef PACED
    di
    jp  e_hbench
    endif

; ---------------------------------------------------------------------
romoff
    ld  bc,#7F8C                ; mode 0, both ROMs disabled
    out (c),c
    ld  bc,#7FC4                ; ...and RAM config 4, which is the state
    out (c),c                   ; main3.asm:start leaves the machine in and
    ret                         ; the state raster_colframe restores

setup
    call romoff
    call raster_init            ; needs bank 4 (LINETAB)
    ld   a,(bufh)
    call raster_setbuf
    ret

; ---------------------------------------------------------------------
e_many
    ld  sp,STACK
    call setup
    xor a
    ld  (done),a
    call raster_colframe
    ld  a,#FF
    ld  (done),a
e_spin
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
    call raster_colframe
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
    jr  ee_l

; ---------------------------------------------------------------------
counter  dw 0
done     db 0
bufh     db #C0
fg_nquad db 0                   ; kernel.asm owns this in the real build

    ifdef PACED
; =====================================================================
;  THE STUB ACCUMULATOR -- main3.asm's cost_unit, minus the game, and
;  with a COUNTDOWN in front of it.
;
;  WHY: the thing that decides the frame period is the longest stretch of
;  work between two points at which the accumulator could take a vsync --
;  i.e. between two cost_unit calls.  There is no clock to time that with,
;  so this times a PREFIX instead: cost_unit bails out to hb_abort on the
;  k'th call, the driver sweeps k, and the DIFFERENCES between consecutive
;  k are the intervals themselves.  engine2/tools/emu_atomic.py does
;  exactly this for raster_quad; this is the same trick for the column
;  renderer, and it is what a per-FRAME check cannot see -- a charge can
;  bound a whole frame and still under-charge one interval inside it, and
;  then the yield lands past the vsync edge and the frame silently takes
;  another period.
;
;  COST_THI is 0 so EVERY call takes the yield branch: that is both the
;  expensive path and the hostile one, since wait_vsync destroys A and B.
;
;  UNLIKE raster_quad, SP IS NEVER THE SCREEN AT A HOOK here -- rastcol
;  charges in rc_face and rc_column, both outside the fill -- so the abort
;  only has to put SP back where the bench loop left it.
; =====================================================================
C_CFRAME equ 2000
C_CFACE  equ 1000
C_CSKIP  equ 150
C_COLS   equ 330
C_CBAND  equ 460
C_COLR   equ 22
C_CEDGE  equ 60
COST_THI equ 0

cost_unit
    push af
    push hl
    ld   hl,hookn
    ld   a,(hl)
    or   a
    jr   z,cu_go
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
    in   a,(c)                  ; wrecks exactly what the real one wrecks
    rra
    ret                         ; ...but does not wait

cost_acc  dw 0
pace_left db 0
hookn     db 0
hookk     db 255
hookbc    dw 0

e_hbench
    ld  sp,STACK
    call setup
    ld  hl,0
    ld  (counter),hl
hb_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ld  a,(hookk)
    ld  (hookn),a
    call raster_colframe
    jr  hb_l
hb_abort
    ld  (hookbc),bc             ; the CHARGE this hook was about to take
    ld  bc,#7FC4                ; raster_colframe was mid-render, so bank
    out (c),c                   ; 5 is still paged: put bank 4 back
    ld  sp,STACK
    jr  hb_l
    endif

    include "raster.asm"        ; raster_init, raster_setbuf, VPLINE
    include "rastcol.asm"
