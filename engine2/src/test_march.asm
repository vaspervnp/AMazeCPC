; =====================================================================
;  engine2 -- test_march.asm
;
;  Harness for verifying and timing march.asm on the headless CPC 6128.
;  Everything lives in &4000-&7FFF, which is RAM in every ROM
;  configuration, so the blob can be poked and jumped to straight from
;  the emulator with no disc, no firmware and no OUT to the gate array.
;
;  Entry vectors (the emulator sets PC to one of these):
;    &4000  run march once, then spin
;    &4003  march repeatedly, counting iterations
;    &4006  march_setup only, repeatedly  (isolates the per-frame cost)
;    &4009  empty loop  (measures the harness's own overhead)
;    &400C  build_l1 only
;    &400F  fracmul only  (the seed multiply's inner loop)
; =====================================================================

    org #4000

    jp entry_once
    jp entry_bench
    jp entry_setup
    jp entry_empty
    jp entry_l1
    jp entry_frac

CPUSTK      equ #7F00

; march.asm keeps its working RAM at &2400-&32FF, which reads as the lower
; ROM until the gate array is told otherwise.  These vectors all start
; above &4000, which is RAM in every configuration, so the OUT can run
; before anything touches &3000.
romoff
    ld bc,#7F8C                 ; mode 0, both ROMs disabled
    out (c),c
    ret

entry_once
    di
    ld sp,CPUSTK
    call romoff
    call copy_maze
    call march
    ld a,#EE
    ld (done_flag),a
to_spin
    jr to_spin

entry_bench
    di
    ld sp,CPUSTK
    call romoff
    call copy_maze
tb_loop
    ld hl,(iters)
    inc hl
    ld (iters),hl
    call march
    jp tb_loop

entry_setup
    di
    ld sp,CPUSTK
    call romoff
    call copy_maze
ts_loop
    ld hl,(iters)
    inc hl
    ld (iters),hl
    call march_setup
    jp ts_loop

entry_empty
    di
    ld sp,CPUSTK
    call romoff
    call copy_maze
te_loop
    ld hl,(iters)
    inc hl
    ld (iters),hl
    jp te_loop

entry_l1
    di
    ld sp,CPUSTK
    call romoff
tl_loop
    ld hl,(iters)
    inc hl
    ld (iters),hl
    call build_l1
    jp tl_loop

entry_frac
    di
    ld sp,CPUSTK
    call romoff
tf_loop
    ld hl,(iters)
    inc hl
    ld (iters),hl
    ld de,1234
    ld c,#AB
    call fracmul
    jp tf_loop

copy_maze
    jp maze_unpack                  ; march.asm's, and MAZEDATA is packed

iters       dw 0
done_flag   db 0

    include "march.asm"
    include "gen_slopes.inc"
    include "gen_mtab.inc"    ; MARCHTB in base RAM -- see gen_march.py
    include "gen_maze.inc"
