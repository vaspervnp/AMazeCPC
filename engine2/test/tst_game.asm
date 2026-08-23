; =====================================================================
;  engine2/test/tst_game.asm -- emulator harness for src/game.asm.
;
;  The renderer is NOT here: this harness exists to drive the game layer
;  one frame at a time with a synthetic key matrix and read the player
;  state back out, which is how the collision rule is unit tested
;  (engine2/tools/emu_game.py).
;
;  Entries (the driver sets PC to one of these):
;    #8000  SOLID <- MAZEDATA, game_init, then spin;  (done) = #FF
;    #8004  ONE game_run -- i.e. game_step with the matrix read skipped,
;           so the driver can poke KEYS itself.  (esc) = its return.
; =====================================================================

    include "tab_equ_test.inc"

STACK   equ #7FF0

    org #8000

    di
    jp  e_init
    di
    jp  e_step

romoff
    ld  bc,#7F8C
    out (c),c
    ret

e_init
    ld  sp,STACK
    call romoff
    ld  hl,MAZEDATA
    ld  de,SOLID
    ld  bc,256
    ldir
    call game_init
    ld  a,#FF
    ld  (done),a
e_spin
    jr  e_spin

e_step
    ld  sp,STACK
    call romoff
    xor a
    ld  (done),a
    call game_run
    ld  (esc),a
    ld  a,#FF
    ld  (done),a
    jr  e_spin

done    db 0
esc     db 0

    include "march.asm"
    include "game.asm"
    include "gen_slopes.inc"
    include "gen_maze.inc"
