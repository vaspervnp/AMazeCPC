; =====================================================================
;  engine2/src/game.asm -- THE GAME LAYER.
;
;  Everything between "a key is down" and "(plr_x)(plr_y)(plr_a) and
;  SOLID are what the renderer should draw".  It owns no pixels: the
;  frame is src/frame.asm, and the top level that wires the two together
;  is src/main3.asm.
;
;      game_init      once, after SOLID has been loaded from MAZEDATA
;      game_step      once per game frame, BEFORE frame_draw
;                     returns A = 0 normally, A = 1 if ESC was pressed
;
;  ------------------------------------------------------------------
;  FREE MOVEMENT.  plr_x / plr_y are unsigned 16-bit 8.8 cell
;  coordinates, exactly as march.asm wants them; plr_a is 0..71 in
;  5-degree steps.  Forward and back move along the heading vector by a
;  fixed step read out of STEPTAB, which is
;
;      STEPTAB[a] = (round(STEP*cos(5a)), round(STEP*sin(5a)))
;
;  i.e. the same (cos, sin) convention as the BASIS table gentab.py
;  builds for the march (fwd = (cos a, sin a), +y is south, and heading
;  INCREASING turns right).  It is a separate 144-byte table rather than
;  a multiply against BASIS because the whole movement update is then
;  two table reads and two 16-bit adds, and because it lets the step be
;  chosen here in one constant.
;
;  STEP = 24/256 of a cell per game frame.  256/24 = 10.667 frames per
;  cell, and the frame period is LOCKED at 5 vsyncs = 99.84 ms, so that
;  is 1.0651 s per cell and 50.1 deg/s of turn, IN EVERY VIEW.
;
;  THE PERIOD IS THE WHOLE POINT, because walking speed is distance per
;  frame over seconds per frame and this file fixes only the numerator.
;  The main loop used to flip on the first vsync after the render, which
;  makes a frame a whole number of 20 ms periods but not the SAME whole
;  number:
;
;    cadence    fps    share   cell crossing   turn rate (1 step = 5 deg)
;     40 ms    25.0    57.0%      0.43 s              125 deg/s
;     60 ms    16.7    37.0%      0.64 s               83 deg/s
;     80 ms    12.5     6.0%      0.85 s               62 deg/s
;
;  -- a corridor walked twice as fast as a junction.  A four-chunk pad
;  cut that to 80 ms 79% / 100 ms 20% / 120 ms 1% / 140 ms 0.5%, i.e. a
;  1.75x spread, which is still the player feeling the view cost in his
;  feet.
;
;  IT IS NOW CONSTANT, and not by measuring the elapsed time, which this
;  machine genuinely cannot do: interrupts are off because SP is the
;  screen pointer inside the fills and the flood stack inside the march,
;  so the 300 Hz tick cannot be counted; there is no other timer; and the
;  vsync pulse is ~1 ms wide, so polling it at stage boundaries misses
;  pulses.  What the engine does instead is carry a COST ACCUMULATOR --
;  it adds a measured constant as each cell is marched, each face
;  projected and each quad rasterised, and yields a vsync wait when the
;  running total approaches 20 ms.  See the PACING note at the top of
;  engine2/src/main3.asm.  MEASURED on the built disc, engine2/tools/
;  emu_pace.py, sampling (frame_ctr) five times per vsync over 1400
;  reachable states: 100% of frames at 5 vsyncs = 99.84 ms = 10.0 fps.
;
;  10 fps is slower than the 12.5 the old pad hit most of the time, and
;  it is the right trade: a constant 10 is worth more than a mean 11.8
;  that swings between 12.5 and 7.1 with the view.
;
;  ------------------------------------------------------------------
;  COLLISION.  The player is a square of half-width PRAD = 64/256 =
;  0.25 cells.  A candidate position is FREE iff none of the four cells
;  containing the corners of that square is solid -- four SOLID reads,
;  no multiply (the box is half a cell across, so it can never span more
;  than two cells on an axis).
;
;  The two axes are tested INDEPENDENTLY and applied independently, so
;  walking into a wall at an angle keeps the component along the wall:
;  that is the whole reason free movement feels right, and it is what
;  makes a corner impossible to squeeze through.
;
;  0.25 IS ALSO A RENDERING REQUIREMENT, not just a feel one.
;  project.asm rejects a face nearer than ZNEAR = 0.125 cells, so a
;  player allowed within 0.125 of a wall plane sees straight through the
;  wall.  PRAD = 0.25 keeps the player's centre at least 0.25 from every
;  solid cell on both axes, hence at least 0.25 from any wall PLANE,
;  which is 2x ZNEAR.  Do not lower PRAD below 32 without re-reading
;  project.asm.
;
;  ------------------------------------------------------------------
;  DOORS run 2 = shut .. 8 = open in the door list below, one step per
;  game frame, so a door takes SIX frames.  SOLID gets 2 while the door
;  is anything but fully open and 0 when it is open, because SOLID is the
;  kernel's input and the kernel's alphabet is exactly 0 open / 1 wall /
;  2 door.  A door is therefore SOLID to the player for the whole run and
;  becomes passable on the frame it finishes.
;
;  AND THE RUN IS DRAWN.  The quad carries only (kind, k), so the shape
;  of a half-open door cannot be expressed in the quad -- but it does not
;  have to be: door_lift hands the renderer ONE byte, how far up the door
;  has gone, and rc_column raises the bottom edge of every door face by
;  that fraction of its distance from the horizon.  The door lifts out of
;  the way.  It is clamped at the horizon, and rc_lift in rastcol.asm
;  says why that clamp is a correctness requirement and not a taste.
;
;  SPACE acts on the door 0.75 cells IN FRONT of the player if there is
;  one, and otherwise on the nearest door whose centre is within 1.25
;  cells (L-infinity), nearest by L1.  It will not shut a door whose cell
;  the player's PRAD COLLISION BOX overlaps -- the same box move_apply
;  tests, so it refuses while the player merely straddles the threshold,
;  not only while the player's centre is in the doorway.
;
;  Clobbers AF BC DE HL.  Interrupts must be off (the matrix read drives
;  the PPI directly).
; =====================================================================

; Needs from march.asm:   SOLID plr_x plr_y plr_a
; Needs from gen_maze.inc: START_X START_Y
; Needs from tab_equ.inc:  N_ANGLES

STEP        equ 24          ; 8.8 cell units per game frame
PRAD        equ 64          ; collision half-width, 8.8 (= 0.25 cell)
; ---------------------------------------------------------------------
;  A DOOR RUNS ONE STEP A GAME FRAME, from DOOR_SHUT to DOOR_OPEN and
;  back, so the number of frames it takes IS the difference between them
;  -- six here, and doors_step is what walks it.  It was four.
;
;  SOLID CLEARS ONLY AT DOOR_OPEN (doors_step, ds_apply), so the door
;  blocks the player for the whole run and becomes passable on the frame
;  it finishes.  That is deliberate: SOLID is read by the march for
;  OPACITY and by coll_free for COLLISION, and a door that cleared early
;  would be walk-through-able while it still looks shut.
;
;  THE RUN IS VISIBLE: door_lift below turns door_st into the fraction
;  rc_column raises each door face's bottom edge by, so the door rises
;  over these six frames instead of vanishing at the end of them.  What
;  is behind it is still not drawn -- SOLID is read by the march for
;  OPACITY as well as by coll_free for COLLISION, so the cell stays
;  opaque for the whole run -- which is why the door lifts to reveal the
;  FLOOR rather than the room beyond.
; ---------------------------------------------------------------------
DOOR_SHUT   equ 2
DOOR_OPEN   equ 8           ; 8 - 2 = SIX frames to run, one step each

; HOW MANY DOORS THE ENGINE CAN HOLD, and it must be >= the map's.
;
; game_init scans SOLID and registers doors until it has MAXDOORS of
; them, then SILENTLY SKIPS THE REST (gi_scan: `cp MAXDOORS / jr
; nc,gi_next`).  A door that is never registered is never in door_idx,
; so door_act can never find it and doors_step never runs it: it is shut
; for ever, and it still reads 2 in SOLID so it still blocks the player.
;
; THIS WAS 8 WHILE THE MAP HAD 12 DOORS.  The four it dropped were the
; last four in scan order -- (7,10), (12,10), (5,13), (10,13) -- and the
; player starts at (3,12), whose room's east door is (5,13).  So the
; first door a new player walks into was one of the dead ones, and the
; bug read as "the doors do not open at all".  The single-door test
; passed throughout, because it picked the first door in the map and
; that one was inside the cap.
;
; It only sizes the three arrays below (3 bytes a door); the per-frame
; cost follows door_n, the number actually found.  gen_march.py emits
; NDOORS from the map and main3.asm asserts MAXDOORS >= NDOORS, so a map
; that outgrows this fails the BUILD instead of losing doors in silence.
MAXDOORS    equ 16

; ---------------------------------------------------------------------
;  THE DOOR TABLES LIVE IN THE FREE RAM ABOVE QUADS, not in the code
;  segment.  Three arrays of MAXDOORS bytes is 48, the body had 162 to
;  spare under BUCK0, and `assert game_end <= BUCK0` fired the moment
;  MAXDOORS grew and door_shrink arrived.  march.asm places SOLID and
;  MARK the same way, and for the same reason.
;
;  QUADS is #3A00-#3DBF (memmap.inc) and the CPU stack tops out at
;  #3FF0, so #3DC0 upwards is free.  addrs.py parses these out of this
;  file for the harnesses, because rasm does NOT put `equ` symbols in
;  the .sym file -- only labels -- so nothing can read them from there.
; ---------------------------------------------------------------------
;  THEY ARE LITERALS WITH ASSERTS, not expressions, and that is for the
;  Python side: addrs.py parses `name equ <number>` and cannot evaluate
;  `DOORTAB+MAXDOORS`.  The asserts below are what keep the literals
;  honest, so the two can never drift apart in silence.
DOORTAB     equ #3DC0
door_idx    equ #3DC0                   ; MAXDOORS: each door's cell index
door_st     equ #3DD0                   ; ...its current state
door_tg     equ #3DE0                   ; ...and the state it is running to
    assert door_idx == DOORTAB
    assert door_st  == DOORTAB+MAXDOORS
    assert door_tg  == DOORTAB+MAXDOORS*2
    assert DOORTAB+MAXDOORS*3 <= #3FF0  ; clear of the CPU stack
    assert DOORTAB >= QUADS+120*8       ; ...and of the quad list
DOOR_REACH  equ 320         ; 1.25 cells, 8.8, for the nearest-door search


; ---------------------------------------------------------------------
;  game_init -- SOLID must already hold the maze.
; ---------------------------------------------------------------------
game_init
    ld   hl,START_X*256+128         ; start in the middle of the start cell
    ld   (plr_x),hl
    ld   hl,START_Y*256+128
    ld   (plr_y),hl
    xor  a
    ld   (plr_a),a                  ; heading 0 = +x = east
    ld   (door_n),a

    ld   hl,PREVKEYS                ; nothing held, and bits are active low
    ld   b,10
gi_pk
    ld   (hl),#FF
    inc  hl
    djnz gi_pk

    ld   hl,SOLID                   ; every cell that reads 2 is a door
    ld   c,0
gi_scan
    ld   a,(hl)
    cp   DOOR_SHUT
    jr   nz,gi_next
    ld   a,(door_n)
    cp   MAXDOORS
    jr   nc,gi_next
    push hl
    ld   e,a
    ld   d,0
    inc  a
    ld   (door_n),a
    ld   hl,door_idx
    add  hl,de
    ld   (hl),c
    ld   hl,door_st
    add  hl,de
    ld   (hl),DOOR_SHUT
    ld   hl,door_tg
    add  hl,de
    ld   (hl),DOOR_SHUT
    pop  hl
gi_next
    inc  hl
    inc  c
    jr   nz,gi_scan
    ret


; ---------------------------------------------------------------------
;  game_step -- one game frame of input, movement and doors.
;  OUT  A = 0 keep playing, A = 1 the player pressed ESC.
;
;  game_run is the same thing with the matrix read skipped, so a test
;  harness can poke KEYS directly (engine2/test/tst_game.asm).
; ---------------------------------------------------------------------
game_step
    call scan_keys
game_run
    ld   hl,KEYS                    ; --- turn: 1 step = 5 degrees
    bit  1,(hl)
    call z,turn_right               ; leaves HL alone, so KEYS+1 is INC HL
    inc  hl
    bit  0,(hl)
    call z,turn_left

    call step_vector                ; STEPTAB[plr_a] -> (mv_dx)(mv_dy)

    ld   hl,KEYS                    ; --- walk
    bit  0,(hl)
    jr   nz,gs_noup
    call move_apply
    jr   gs_moving
gs_noup                             ; HL is still KEYS
    bit  2,(hl)
    jr   nz,gs_still
    call neg_step                   ; back = the same vector, negated
    call move_apply
    call neg_step
gs_moving                           ; (plr_moving) is what drives the
    ld   a,1                        ; weapon's bob -- see gun.asm.  It is
    jr   gs_setmv                   ; the walk KEY, not the outcome of the
gs_still                            ; collision test: a player pressed into
    xor  a                          ; a wall is still walking on the spot,
gs_setmv                            ; and freezing the sway there reads as
    ld   (plr_moving),a             ; the game having stopped responding.
gs_walked

    ld   hl,KEYS+5                  ; --- SPACE, on the press edge only
    bit  7,(hl)
    jr   nz,gs_nospace
    ld   hl,PREVKEYS+5
    bit  7,(hl)
    jr   z,gs_nospace
    call door_act
    ifdef PACED
    ; AND CHARGE IT.  door_act is the one branch of the tail that is not
    ; in C_TAIL: MEASURED 689.7 us worst (engine2/tools/emu_holes.py),
    ; taken only on the frames a player taps SPACE.  cost_add charges
    ; without testing and without waiting -- see main3.asm, and see
    ; C_DOORACT for why a wait here would be wrong.
    ld   bc,C_DOORACT
    call cost_add
    endif
gs_nospace

    call doors_step

    ld   hl,KEYS                    ; snapshot for the next frame's edges
    ld   de,PREVKEYS
    ld   bc,10
    ldir

    dec  hl                         ; --- ESC; LDIR left HL at KEYS+10
    dec  hl
    bit  2,(hl)
    ld   a,0
    ret  nz
    inc  a
    ret


; ---------------------------------------------------------------------
;  turn_right / turn_left -- plr_a +- 1 modulo N_ANGLES.
; ---------------------------------------------------------------------
turn_right
    ld   a,(plr_a)
    inc  a
    cp   N_ANGLES
    jr   c,tr_ok
    xor  a
tr_ok
    ld   (plr_a),a
    ret

turn_left
    ld   a,(plr_a)
    or   a
    jr   nz,tl_ok
    ld   a,N_ANGLES
tl_ok
    dec  a
    ld   (plr_a),a
    ret


; ---------------------------------------------------------------------
;  step_vector -- (mv_dx)(mv_dy) = STEPTAB[plr_a], sign extended.
; ---------------------------------------------------------------------
step_vector
    ld   a,(plr_a)
    add  a,a
    ld   l,a
    ld   h,0
    ld   de,STEPTAB
    add  hl,de
    ld   a,(hl)
    ld   e,a
    add  a,a                        ; carry = sign
    sbc  a,a                        ; A = 0 or #FF
    ld   d,a
    ld   (mv_dx),de
    inc  hl
    ld   a,(hl)
    ld   e,a
    add  a,a
    sbc  a,a
    ld   d,a
    ld   (mv_dy),de
    ret

neg_step
    ld   hl,0
    ld   de,(mv_dx)
    or   a
    sbc  hl,de
    ld   (mv_dx),hl
    ld   hl,0
    ld   de,(mv_dy)
    or   a
    sbc  hl,de
    ld   (mv_dy),hl
    ret


; ---------------------------------------------------------------------
;  move_apply -- try (mv_dx) on x, then (mv_dy) on y, each on its own.
;  Applying them separately is what lets the player SLIDE along a wall
;  instead of sticking to it.
; ---------------------------------------------------------------------
move_apply
    ld   hl,(plr_y)                 ; --- x, at the current y
    ld   (ct_y),hl
    ld   hl,(plr_x)
    ld   de,(mv_dx)
    add  hl,de
    ld   (ct_x),hl
    call coll_free
    jr   nz,ma_nox
    ld   hl,(ct_x)
    ld   (plr_x),hl
ma_nox
    ld   hl,(plr_x)                 ; --- y, at the x we ended up with
    ld   (ct_x),hl
    ld   hl,(plr_y)
    ld   de,(mv_dy)
    add  hl,de
    ld   (ct_y),hl
    call coll_free
    ret  nz
    ld   hl,(ct_y)
    ld   (plr_y),hl
    ret


; ---------------------------------------------------------------------
;  box_cells -- the 2x2 cell block the PRAD box around (ct_x, ct_y)
;  touches.  The box is 0.5 cells across, so it can never span more than
;  two cells on an axis and the block is always exactly 2x2 (with
;  duplicates when the box lies inside one cell).
;
;  OUT  B = 16*cy0   C = 16*cy1   D = cx0   E = cx1
;       so the four cell indices are B|D, B|E, C|D, C|E.
;  This is factored out of coll_free because door_act has to test THE
;  SAME BOX: a door that only looked at the player's centre cell could be
;  shut on a player straddling the threshold, which wedges the player
;  inside SOLID (no heading moves) and puts the centre inside project.asm's
;  ZNEAR so the shut door is see-through.
; ---------------------------------------------------------------------
box_cells
    ld   de,PRAD
    ld   hl,(ct_x)
    or   a
    sbc  hl,de
    ld   a,h
    and  15
    ld   (cf_x0),a
    ld   hl,(ct_x)
    add  hl,de
    ld   a,h
    and  15
    ld   (cf_x1),a
    ld   hl,(ct_y)
    or   a
    sbc  hl,de
    ld   a,h
    and  15
    rlca
    rlca
    rlca
    rlca
    ld   b,a                        ; B = 16*cy0
    ld   hl,(ct_y)
    add  hl,de
    ld   a,h
    and  15
    rlca
    rlca
    rlca
    rlca
    ld   c,a                        ; C = 16*cy1
    ld   a,(cf_x0)
    ld   d,a
    ld   a,(cf_x1)
    ld   e,a
    ret


; ---------------------------------------------------------------------
;  coll_free -- is the PRAD box around (ct_x, ct_y) clear of SOLID?
;  OUT  A = 0 and Z  free;  A != 0 and NZ  blocked.
; ---------------------------------------------------------------------
coll_free
    call box_cells
    ld   h,SOLID/256
    ld   a,b
    or   d
    ld   l,a
    ld   a,(hl)
    or   a
    ret  nz
    ld   a,b
    or   e
    ld   l,a
    ld   a,(hl)
    or   a
    ret  nz
    ld   a,c
    or   d
    ld   l,a
    ld   a,(hl)
    or   a
    ret  nz
    ld   a,c
    or   e
    ld   l,a
    ld   a,(hl)
    or   a
    ret


; ---------------------------------------------------------------------
;  door_lift -- MAKE THE DOOR'S RUN VISIBLE, and make it go UP.
;
;  A door runs DOOR_SHUT..DOOR_OPEN one step a game frame, and that run
;  used to be invisible: the quad record carries only (kind, k), so a
;  door part way open was drawn as a whole door face and then VANISHED
;  on the frame SOLID cleared.
;
;  This hands rastcol.asm one number -- how far up the door has gone, as
;  a fraction of 256 -- and rc_column raises the BOTTOM edge of every
;  door face by that much of its distance from the horizon.  So the door
;  lifts out of the way instead of shrinking towards eye level, which is
;  what scaling the face's half height did and what it looked like.
;
;  IT IS ONE BYTE AND NOT A PASS OVER THE QUAD LIST.  The first version
;  walked QUADS after project_all and scaled the half heights of the door
;  faces, two multiplies a quad; this writes a byte and the renderer does
;  the rest where it already has the row range in hand.
;
;  ONE FRACTION FOR ALL DOOR FACES, deliberately: the quad does not carry
;  which door it came from, and door_act starts one door at a time, so in
;  play there is exactly one door mid-run.
; ---------------------------------------------------------------------
door_lift
    ld   a,(door_anim)
    sub  DOOR_SHUT+1
    jr   c,dl_none                  ; at rest: the door is whole
    cp   DOOR_OPEN-DOOR_SHUT-1
    jr   nc,dl_none                 ; open: not drawn at all
    ld   e,a
    ld   d,0
    ld   hl,DLIFT
    add  hl,de
    ld   a,(hl)
    ld   (rc_dlift),a
    ret
dl_none
    xor  a
    ld   (rc_dlift),a
    ret


; ---------------------------------------------------------------------
;  doors_step -- one animation step per door per frame, and SOLID.
; ---------------------------------------------------------------------
doors_step
    ld   a,DOOR_SHUT                ; ...and nothing is animating unless a
    ld   (door_anim),a              ; door below turns out to be mid-run
    ld   a,(door_n)
    or   a
    ret  z
    ld   b,a
    ld   c,0
ds_l
    push bc
    ld   e,c
    ld   d,0
    ld   hl,door_st
    add  hl,de
    ld   a,(hl)
    push hl
    ld   hl,door_tg
    add  hl,de
    cp   (hl)
    jr   z,ds_same
    jr   c,ds_inc
    dec  a
    jr   ds_set
ds_inc
    inc  a
ds_set
    pop  hl
    ld   (hl),a
    jr   ds_apply
ds_same
    pop  hl
ds_apply
    ; ---- IS THIS DOOR PART WAY THROUGH ITS RUN?  A is its new state.
    ;      door_shrink scales the door faces by it, which is what makes
    ;      the run visible; DOOR_SHUT and DOOR_OPEN are the two resting
    ;      states and neither of them animates anything.
    cp   DOOR_SHUT
    jr   z,ds_noanim
    cp   DOOR_OPEN
    jr   z,ds_noanim
    ld   (door_anim),a
ds_noanim
    ld   hl,door_idx                ; SOLID = 0 only when fully open
    add  hl,de
    ld   l,(hl)
    ld   h,SOLID/256
    cp   DOOR_OPEN
    ld   a,DOOR_SHUT
    jr   nz,ds_w
    xor  a
ds_w
    ld   (hl),a
    pop  bc
    inc  c
    djnz ds_l
    ret


; ---------------------------------------------------------------------
;  door_act -- SPACE.  The door in front wins; otherwise the nearest one
;  within DOOR_REACH.  Nothing happens if there is neither.
; ---------------------------------------------------------------------
door_act
    ld   hl,(mv_dx)                 ; probe 0.75 cells ahead: 8 * STEP
    add  hl,hl
    add  hl,hl
    add  hl,hl
    ld   de,(plr_x)
    add  hl,de
    ld   a,h
    and  15
    ld   c,a
    ld   hl,(mv_dy)
    add  hl,hl
    add  hl,hl
    add  hl,hl
    ld   de,(plr_y)
    add  hl,de
    ld   a,h
    and  15
    rlca
    rlca
    rlca
    rlca
    or   c
    call door_find
    jr   nc,da_have

    ; ---- nothing in front: nearest door centre within DOOR_REACH
    ld   a,(door_n)
    or   a
    ret  z
    ld   b,a
    ld   c,0
    ld   hl,#7FFF
    ld   (da_best),hl
    ld   a,#FF
    ld   (da_slot),a
da_l
    push bc
    ld   e,c
    ld   d,0
    ld   hl,door_idx
    add  hl,de
    ld   a,(hl)
    ld   (da_idx),a
    and  15                         ; cell centre x, 8.8
    ld   h,a
    ld   l,128
    ld   (da_t),hl
    ld   hl,(plr_x)
    call da_absdiff
    jr   nc,da_next
    push hl
    ld   a,(da_idx)
    rrca                            ; cell centre y, 8.8
    rrca
    rrca
    rrca
    and  15
    ld   h,a
    ld   l,128
    ld   (da_t),hl
    ld   hl,(plr_y)
    call da_absdiff
    pop  de
    jr   nc,da_next
    add  hl,de                      ; L1 distance
    ex   de,hl
    ld   hl,(da_best)
    or   a
    sbc  hl,de
    jr   c,da_next
    jr   z,da_next
    ld   (da_best),de
    ld   a,c
    ld   (da_slot),a
da_next
    pop  bc
    inc  c
    djnz da_l
    ld   a,(da_slot)
    inc  a
    ret  z                          ; #FF: no door in reach
    dec  a

    ; ---- A = the door's slot in the list ----------------------------
da_have
    ld   e,a
    ld   d,0
    ld   hl,door_tg
    add  hl,de
    ld   a,(hl)
    cp   DOOR_OPEN
    jr   z,da_shut
    ld   (hl),DOOR_OPEN
    ret
;  A door refuses to shut while the player's COLLISION BOX overlaps its
;  cell -- not merely while the player's CENTRE is in it.  This is the
;  same 2x2 block that move_apply/coll_free test, so a position a door
;  will shut at is always a position the player can still move out of.
;  Testing only the centre let a player straddling the threshold shut the
;  door around itself: the box was then inside SOLID, every heading was
;  blocked on both axes, and the centre sat within ZNEAR of the wall
;  plane so project.asm dropped the face and the shut door was
;  see-through.  Only pressing SPACE again escaped.
;  The 2x2 block is (cx0|cx1) x (cy0|cy1), so it contains the door cell
;  iff its column is cx0 or cx1 AND its row is cy0 or cy1 -- two byte
;  compares per axis rather than four full cell indices.
da_shut
    push hl                         ; HL = the door's door_tg entry
    ld   hl,door_idx
    add  hl,de
    push hl                         ; -> the door's cell index
    ld   hl,(plr_x)
    ld   (ct_x),hl
    ld   hl,(plr_y)
    ld   (ct_y),hl
    call box_cells                  ; B,C = 16*cy0/cy1;  D,E = cx0/cx1
    pop  hl
    ld   a,(hl)
    and  15                         ; the door's column
    cp   d
    jr   z,ds_col
    cp   e
    jr   nz,ds_go
ds_col
    ld   a,(hl)
    and  #F0                        ; the door's row, already x16
    cp   b
    jr   z,ds_wedge
    cp   c
    jr   z,ds_wedge
ds_go
    pop  hl                         ; the box is clear of the door cell
    ld   (hl),DOOR_SHUT
    ret
ds_wedge
    pop  hl                         ; it overlaps: refuse, or we wedge
    ret

; HL = player coordinate, (da_t) = target coordinate.
; OUT  HL = |target - player|, CARRY SET if that is within DOOR_REACH.
da_absdiff
    ex   de,hl
    ld   hl,(da_t)
    or   a
    sbc  hl,de
    bit  7,h
    jr   z,da_ad1
    ex   de,hl
    ld   hl,0
    or   a
    sbc  hl,de
da_ad1
    ld   de,DOOR_REACH
    push hl
    or   a
    sbc  hl,de
    pop  hl
    ret

; A = cell index.  OUT  carry CLEAR and A = slot if that cell is a door.
door_find
    ld   c,a
    ld   a,(door_n)
    or   a
    scf
    ret  z
    ld   b,a
    ld   hl,door_idx
    ld   e,0
df_l
    ld   a,(hl)
    cp   c
    jr   z,df_hit
    inc  hl
    inc  e
    djnz df_l
    scf
    ret
df_hit
    ld   a,e
    or   a                          ; clears carry
    ret


; ---------------------------------------------------------------------
;  scan_keys -- the matrix, no firmware.  AY register 14 is wired to the
;  key rows, reached through PPI port C (row select) and port A (data);
;  bits are ACTIVE LOW.  Lifted unchanged from src/input.asm, which is
;  the version that works on the two shipped discs.
;
;    row 0  bit 0 cursor up   bit 1 cursor right   bit 2 cursor down
;    row 1  bit 0 cursor left
;    row 5  bit 7 space
;    row 8  bit 2 escape
; ---------------------------------------------------------------------
scan_keys
    ld hl,KEYS
    ld bc,#F782
    out (c),c                   ; PPI: ports A and C to output
    ld bc,#F40E
    out (c),c                   ; address AY register 14
    ld bc,#F6C0
    out (c),c                   ; AY: latch the register number
    ld c,0
    out (c),c                   ; AY: back to inactive
    ld bc,#F792
    out (c),c                   ; PPI: port A to input
    ld bc,#F640                 ; port C = &40 | row
sk_row
    out (c),c
    ld b,#F4
    in a,(c)
    ld (hl),a
    inc hl
    ld b,#F6
    inc c
    ld a,c
    cp #4A                      ; ten rows, &40..&49
    jr c,sk_row
    ld bc,#F782
    out (c),c
    ret


; ------------------------------------------------------------ tables ---
;  STEPTAB[a] = (round(STEP*cos(5a)), round(STEP*sin(5a))), signed bytes.
;  rasm's int() ROUNDS, and its cos/sin take DEGREES, not radians -- both
;  checked against Python before this table was trusted.
STEPTAB
    repeat N_ANGLES,IA
    db int(1.0*STEP*cos((IA-1)*360.0/N_ANGLES))
    db int(1.0*STEP*sin((IA-1)*360.0/N_ANGLES))
    rend


; --------------------------------------------------------- variables ---
KEYS        ds 10
PREVKEYS    ds 10

plr_moving  db 0                ; 1 while a walk key is down.  The only
                                ; consumer is gun.asm's bob; nothing in
                                ; the movement rule reads it.
mv_dx       dw 0
mv_dy       dw 0
ct_x        dw 0
ct_y        dw 0
cf_x0       db 0
cf_x1       db 0

door_n      db 0
door_anim   db DOOR_SHUT        ; the state of whichever door is mid-run

; HOW FAR UP, as a fraction of 256 of the door's own height below the
; horizon: (st - DOOR_SHUT) * 256 / (DOOR_OPEN - DOOR_SHUT), for
; st = DOOR_SHUT+1 up.  DOOR_SHUT itself is whole and never reaches
; here; DOOR_OPEN is not drawn at all.
DLIFT       db 42,85,128,170,213
    assert DOOR_OPEN - DOOR_SHUT - 1 == 5   ; ...one entry per running step
da_best     dw 0
da_t        dw 0
da_slot     db 0
da_idx      db 0
