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
;      ammo_arm       full magazine, every pickup back -- "start a life"
;
;  It also OWNS (plr_ammo) and (gun_recoil), which hud2.asm and gun.asm
;  read.  Same rule as (plr_moving): the game layer decides what
;  happened, the drawing layers decide what it looks like.
;
;  THE KEYS: cursors walk and turn, SHIFT doubles both, SPACE works the
;  nearest door, CTRL or Z fires, ESC quits.
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

; ---------------------------------------------------------------------
;  AMMUNITION.  Six rounds, six pips in the HUD's top-left readout, and
;  a magazine that only refills by walking over a pickup.
;
;  THE PICKUPS ARE A LIST, NOT A MAP CODE.  gen_march.py emits AMMOTAB
;  as NAMMO cell indices (y*16+x, the same index SOLID uses) because the
;  alternative -- a fifth value in SOLID -- would put a test in the
;  march's hot loop, which reads SOLID four times a cell, for something
;  that is neither opaque nor solid.  ammo_scan walks NAMMO bytes once a
;  game frame instead -- 6 compares -- and COLLECTS as it goes: a pickup
;  at L1 zero is the one the player is standing on, so finding the
;  nearest and picking one up are the same walk.  It is off the pacer's
;  critical path inside C_TAIL.
;
;  ammo_st IS A COPY, made by game_init, so the map's table stays intact
;  and a future restart can re-arm every pickup by copying it again.  A
;  taken pickup is #FF, which no cell index can be (the map is 16x16, so
;  indices stop at 255 -- but cell 255 is the bottom-right corner and is
;  always WALL, so it can never be a pickup and never be stood on).
AMMO_MAX    equ 6

; ---- THE PLAYER'S HIT POINTS, and the bar that shows them are ONE
;  NUMBER.  genhud.py derives the health bar's width from HP_MAX and
;  hud_health draws HUD_HPSEG bytes per point, so a PLR_HPMAX that
;  disagreed with the readout would either leave a segment permanently
;  dark or run the bar past the slot that holds it.  The assert is the
;  only thing tying an .asm constant to a generated .inc one.
PLR_HPMAX   equ 5
;  The assert is at the FOOT of hud2.asm and not here: gen_hud.inc is
;  included by hud2.asm, which main3.asm includes AFTER this file, and
;  rasm evaluates an assert where it stands -- so HUD_HPN is not a
;  symbol yet at this line.  Same trap the HUD_THI_* asserts fell into.

AMMO_GONE   equ #FF
AMMO_NODIR  equ #FF         ; (ammo_dir) when the map has none left.  A
                            ; real value is (band << 4) | bearing with
                            ; band <= 2 and bearing <= 7, so #FF is a
                            ; value it can never take
AMMO_NEAR   equ 3           ; L1 cells: <= this is the near band...
AMMO_MID    equ 7           ; ...and <= this the middle one.  A room is
                            ; 4x4 and the rooms sit on a 5-cell pitch, so
                            ; near is THIS ROOM, mid is the next one over,
                            ; and far is across the map
MAXAMMO     equ 6           ; pickups the engine can hold; main3.asm asserts
                            ; MAXAMMO >= NAMMO once gen_maze.inc is in, the
                            ; same way MAXDOORS is checked against NDOORS --
                            ; gen_maze.inc is included after this file, so
                            ; NAMMO is not a name yet here
RECOIL_N    equ 2           ; game frames the weapon stays kicked up

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
    assert DOORTAB >= QUADS+NQUAD*8    ; ...and of the quad list, whose
                                      ; length is memmap.inc's now
DOOR_REACH  equ 320         ; 1.25 cells, 8.8, for the nearest-door search


; ---------------------------------------------------------------------
;  game_init -- SOLID must already hold the maze.
; ---------------------------------------------------------------------
game_init
    ld   hl,START_X*256+128         ; start in the middle of the start cell
    ld   (plr_x),hl
    ld   hl,START_Y*256+128
    ld   (plr_y),hl
    ld   a,START_A                  ; THE MAP DECIDES WHICH WAY YOU FACE,
    ld   (plr_a),a                  ; and gen_march.py derives it as the
    xor  a                          ; heading from the start cell to the
    ld   (door_n),a                 ; monster's.  It was `xor a` -- due
                                    ; east -- with the monster two cells
                                    ; WEST, i.e. behind your head, and
                                    ; once the monster walked that made
                                    ; the opening unsurvivable: it bites
                                    ; from frame 12 and a 180-degree turn
                                    ; is 36 frames.  See start_heading().

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

    call ammo_arm
    ret


; ---------------------------------------------------------------------
;  ammo_arm -- full magazine, every pickup back on the map.
;
;  Split out of game_init because it is the whole of "start a life": a
;  restart calls this and nothing else has to remember what ammo state
;  consists of.
; ---------------------------------------------------------------------
ammo_arm
    ; ---- THE MONSTER IS PART OF STARTING A LIFE, and it has to be put
    ;      back BY VALUE.  MONCELL is a byte mon_move writes every
    ;      MON_RATE frames and mon_hit sets to #FF, so by the time a
    ;      restart runs it holds wherever the thing died -- which is
    ;      nowhere.  MONSTART is the map's own equ, which nothing can
    ;      overwrite; gen_march.py emits the pair for exactly this.
    ld   a,MONSTART
    ld   (MONCELL),a
    ld   a,MON_HPMAX
    ld   (mon_hp),a
    ld   a,MON_RATE
    ld   (mon_tick),a
    ld   a,AMMO_NODIR
    ld   (mon_blip),a
    ld   a,PLR_HPMAX                   ; ...and the player back on his feet
    ld   (plr_hp),a
    ld   a,MN_G0                    ; ...and the score back to nothing.  A
    ld   (scr_g),a                  ; LIFE is what it counts, so it resets
                                    ; where the pickups and the monster do

    ld   a,AMMO_MAX
    ld   (plr_ammo),a
    ld   hl,ammo_blip               ; no blip anywhere until the first scan,
    ld   b,MAXAMMO                  ; and the slots past NAMMO stay that way
aa_bl
    ld   (hl),AMMO_NODIR
    inc  hl
    djnz aa_bl
    ld   a,AMMO_NODIR
    ld   (ammo_dir),a
    ld   hl,ammo_st                 ; ...and every slot of the live list is
    ld   b,MAXAMMO                  ; GONE before the map's own are copied
aa_st                               ; over it, so a MAXAMMO bigger than
    ld   (hl),AMMO_GONE             ; NAMMO cannot leave a stale cell index
    inc  hl                         ; in the tail
    djnz aa_st
    ld   hl,AMMOTAB
    ld   de,ammo_st
    ld   bc,NAMMO
    ldir
    ret


; ---------------------------------------------------------------------
;  fire_edge -- fire if the fire key went down THIS frame.
;
;  TWO KEYS, AND THE SECOND ONE IS THERE TO BE TESTED.  CTRL (row 2 bit
;  7) is what a CPC player reaches for, and it is the same byte the
;  SHIFT test above already read.  But engine2/tools/emu_verify3.py
;  drives the machine through the emulator's key_down(), and that maps
;  ASCII to the matrix: it can press every letter and digit and NOT a
;  single modifier -- probed, all 255 codes, and none of them pulls row
;  2 bit 7.  A fire key only reachable by CTRL would therefore be the
;  one input in this engine with no test behind it.
;
;  So Z (row 8 bit 7, the row ESC already lives in) fires as well.  It
;  is on the left of the keyboard, where the hand that is not on the
;  cursor keys is, which is where a CPC fire key belongs anyway.
;
;  THE EDGE IS WHAT MAKES ONE PRESS ONE ROUND.  Held down, the bit stays
;  low every frame and the magazine would empty in six.  The matrix is
;  ACTIVE LOW, so ANDing the two bytes gives a bit that is 0 when EITHER
;  key is down -- one test for both.
;
;  Clobbers AF HL (and whatever fire clobbers).
; ---------------------------------------------------------------------
fire_edge
    ld   a,(KEYS+2)
    ld   hl,KEYS+8
    and  (hl)
    and  #80
    ret  nz                         ; neither key is down
    ld   a,(PREVKEYS+2)
    ld   hl,PREVKEYS+8
    and  (hl)
    and  #80
    ret  z                          ; ...it was down last frame too
    ; fall through


; ---------------------------------------------------------------------
;  fire -- one round, if there is one.
;
;  IN   nothing.  OUT  A/F clobbered.
;
;  An empty magazine is a NO-OP AND NOT AN UNDERFLOW: the pips are drawn
;  from this byte and 255 of them would run the length of the HUD.
; ---------------------------------------------------------------------
fire
    ld   hl,plr_ammo
    ld   a,(hl)
    or   a
    jr   nz,fi_have
    ld   a,SFX_CLICK                ; EMPTY IS A SOUND, not silence.  A
    jp   snd_play                   ; trigger that does nothing and says
fi_have                             ; nothing reads as a dropped key
    dec  (hl)
    call fx_fire                    ; ...and work out what it hit
    ld   a,(fx_pen)                 ; ...which also picks the SOUND: the
    cp   FX_BLOOD                   ; ear and the eye should agree about
    ld   a,SFX_SHOT_STONE           ; whether that was a wall or a body
    jr   nz,fs_snd
    call mon_hit                    ; FLESH: take a hit point off it, and
fs_snd                              ; let it pick between the wet thump
                                    ; and the death cry.  The ONE caller,
                                    ; because fx_fire's compare is the one
                                    ; place the engine knows the round
                                    ; landed on the monster and not a wall
    call snd_play
    ld   a,RECOIL_N                 ; THE RECOIL IS THE FEEDBACK.  The pip
    ld   (gun_recoil),a             ; going out in the HUD is 8 pixels in
    ret                             ; the corner of the screen and the shot
                                    ; is otherwise silent, so the weapon
                                    ; kicks: gun.asm aims the bob at the
                                    ; top of its swing while this counts
                                    ; down, and eases back after.
                                    ;
                                    ; THE STATE LIVES HERE, not in gun.asm,
                                    ; the same way (plr_moving) does -- the
                                    ; game owns what happened and the gun
                                    ; owns how it looks.  It also keeps
                                    ; game.asm assemblable without gun.asm,
                                    ; which engine2/test/tst_game.asm needs.


; ---------------------------------------------------------------------
;  ammo_scan -- WHERE THE NEAREST LIVE PICKUP IS, packed for the HUD.
;
;  OUT  (ammo_dir) = (band << 4) | bearing, or AMMO_NODIR if the map has
;                    no pickup left on it.
;       bearing 0..7 is RELATIVE TO THE NOSE: 0 dead ahead, then
;       clockwise, which is the direction turn_right takes plr_a.
;       band 0 near / 1 mid / 2 far, by L1 distance in CELLS.
;  Clobbers AF BC DE HL.
;
;  WHY THIS EXISTS.  The pickups are not drawn in the 3D view -- the
;  engine has no billboard path -- so without this the player has six
;  invisible boxes in a sixteen-cell maze and no way to look for them.
;  The pad in the HUD is the sense of smell the renderer cannot give.
;
;  THE BEARING IS EIGHT SECTORS AND THAT IS ON PURPOSE.  The pad has
;  eight cells, so anything finer would be thrown away; and eight
;  sectors is the one quantisation that needs no trigonometry at all --
;  the sign of dx and dy picks the quadrant, and one comparison of
;  slopes picks which third of it.
;
;  THE SLOPE TEST IS 5:2 AND NOT 1:1.  The sector boundaries want to be
;  at 22.5 and 67.5 degrees.  Comparing |dy| against |dx| directly puts
;  them at 45, which would make the four diagonal cells cover everything
;  and the four axis cells almost nothing.  2|dy| vs |dx| is the usual
;  cheap fix and puts them at 26.57; 5|dy| vs 2|dx| puts them at 21.80
;  and 68.20, within a degree of right, and costs one extra ADD because
;  5n is (n<<2)+n.  |dx| and |dy| are at most 15 cells, so 5n is at most
;  75 and none of it can carry out of a byte.
; ---------------------------------------------------------------------
ammo_scan
    ld   a,AMMO_NODIR               ; --- the nearest live one, by L1
    ld   (as_best),a
    ld   (as_dist),a                ; ...at a distance nothing can lose to
    ld   hl,ammo_st
    ld   b,NAMMO
as_next
    ld   a,(hl)
    inc  hl
    cp   AMMO_GONE
    jr   z,as_gone
    push hl
    push bc
    ld   c,a                        ; C = the cell
    ld   a,NAMMO                    ; ...and this pickup's SLOT, taken now
    sub  b                          ; because as_l1 clobbers B -- it uses it
    ld   (as_ix),a                  ; for |dx|, and reading it back after
    ld   a,c                        ; gave a garbage index and a blip read
    call as_l1                      ; out of the wrong slot
    or   a                          ; SIGNED offsets in as_tdx / as_tdy
    jp   z,as_take                  ; ...ZERO: we are standing on it.  jp:
                                    ; as_take sits past the sector code
    ld   (as_cur),a
    ld   hl,as_dist
    cp   (hl)
    jr   nc,as_far                  ; strictly nearer wins, so the first
    ld   (hl),a                     ; of two equals keeps the readouts steady
    ld   a,c
    ld   (as_best),a
    ld   a,(as_tdx)                 ; ...and its offsets come with it
    ld   (as_dx),a
    ld   a,(as_tdy)
    ld   (as_dy),a
    ld   a,(as_ix)                  ; ...and WHICH slot it was, so the
    ld   (as_bi),a                  ; bearing can be read back off its blip
as_far
    ; ---- THE BLIP FOR THIS ONE.  Every live pickup gets a packed
    ;      (band << 4) | WORLD SECTOR, which is what the dial draws: the
    ;      radar is world-referenced, like the dial it sits in, so the
    ;      needle and the blips can be lined up by eye.  The nose-relative
    ;      bearing the pad wants is one subtraction off the winner's.
    call as_sector                  ; -> A = sector 0..7 for as_tdx/as_tdy
    ld   c,a
    ld   a,(as_cur)
    call as_band                    ; -> A = #00 / #10 / #20
    or   c
    push af                         ; ...af: as_slot clobbers A, and A is
    call as_slot                    ; the packed blip we came here to store
    pop  af
    ld   (hl),a
    pop  bc
    pop  hl
    djnz as_next
    jr   as_done
as_gone
    push hl
    push bc
    ld   a,NAMMO
    sub  b
    ld   (as_ix),a
    call as_slot
    ld   (hl),AMMO_NODIR            ; no blip in this slot
    pop  bc
    pop  hl
    djnz as_next
as_done

    ld   a,(as_best)
    cp   AMMO_NODIR
    jr   z,as_none

    ; ---- the pad's bearing is the winner's sector minus the nose's.
    ;      That is round(plr_a / 9): 72 headings over 8 sectors.  A
    ;      72-BYTE TABLE WAS THE FIRST ANSWER and it cost more of the body
    ;      than the whole scanner -- game_end went 142 bytes past BUCK0.
    ;      Nine never divides more than eight times into 75, so
    ;      subtracting it in a loop is twelve bytes and 25 us.
    ld   a,(as_bi)
    ld   c,a
    ld   b,0
    ld   hl,ammo_blip
    add  hl,bc
    ld   a,(hl)
as_pack                             ; IN A = (band << 4) | WORLD sector.
                                    ; A LABEL AND NOT A ROUTINE -- the
                                    ; path above falls straight into it,
                                    ; so the exit's bearing below reaches
                                    ; the nose-relative arithmetic for the
                                    ; price of one jp and no duplication.
    ld   e,a
    and  7                          ; E keeps the band, A the sector
    ld   c,a
    ld   a,(plr_a)
    add  a,4                        ; ...+ half a sector, so it ROUNDS
    ld   d,0
as_div
    sub  9
    jr   c,as_gotp
    inc  d
    jr   as_div
as_gotp
    ld   a,c
    sub  d
    and  7                          ; ...and it wraps, both ways
    ld   c,a
    ld   a,e
    and  #30                        ; the band came packed already
    or   c
    ld   (ammo_dir),a
    ret

; ---- NOTHING LEFT TO PICK UP MEANS THE PAD POINTS AT THE WAY OUT.
;
;  THE EXIT WOULD OTHERWISE BE UNFINDABLE, and that is not a small thing:
;  the map is 16x16, the exit is ONE cell, and it sits diagonally
;  opposite the start.  Before this the pad simply went DARK when the
;  last pickup was taken -- so the reward for clearing the maze was to
;  lose the only instrument that tells you where anything is.
;
;  It costs almost nothing because ammo_scan already does all of it: the
;  L1 walk, the eight-sector bearing, the distance band and the
;  nose-relative subtraction are the SAME code, reached at as_pack.  So
;  the exit is not a second scanner, it is the first one asked about a
;  different cell.
;
;  AND IT SEQUENCES THE GAME.  Pickups first, then the way out -- the pad
;  says which, and the player never has to be told.
as_none
    ld   a,EXIT_CELL                ; #FF = this layout has no exit, and
    inc  a                          ; gen_march.py emits that for the
    jr   z,as_dark                  ; Mode 2 map
    ld   c,EXIT_CELL
    call as_pworld
    jp   as_pack
as_dark
    ld   a,AMMO_NODIR               ; ...and only then does the pad go out
    ld   (ammo_dir),a
    ret

; --- IN C = a cell index.  OUT A = (band << 4) | WORLD SECTOR, which is
;     what the radar draws and what as_pack turns nose-relative.
;     Clobbers AF BC DE HL.
;
;     EXTRACTED FROM mon_scan, which now calls it: the monster's blip and
;     the exit's bearing are the same nine instructions, and the second
;     copy of them was the whole cost of pointing at the exit.
as_pworld
    call as_l1                      ; A = L1, as_tdx / as_tdy = the signed
    ld   (as_cur),a                 ; offsets it went through
    call as_sector
    ld   c,a
    ld   a,(as_cur)
    call as_band
    or   c
    ret

; --- COLLECTING IT IS THE SAME WALK.  A pickup at L1 zero is the one
;     the player is standing on, so ammo_pick's separate pass over the
;     same six bytes, doing the same cell compare, was doing the work
;     twice.  The readouts go dark for ONE frame and find the next one on
;     the next, which reads as the blink of having picked something up.
as_take
    pop  bc
    pop  hl
    dec  hl                         ; back to the entry just read
    ld   (hl),AMMO_GONE
    ld   hl,scr_g                   ; ...and THE SCORE, which is one INC
    inc  (hl)                       ; because it is kept as a glyph index
    ld   a,AMMO_MAX
    ld   (plr_ammo),a
    ld   a,SFX_PICKUP
    call snd_play
    call as_slot                    ; ...and its blip goes out with it, so
    ld   (hl),AMMO_NODIR            ; the dial does not show a pickup that
    ld   a,AMMO_NODIR               ; is already in the magazine
    ld   (as_best),a
    ld   (ammo_dir),a
    ret

; ---------------------------------------------------------------------
;  mon_scan -- THE MONSTER'S BLIP, by the same rule as a pickup's.
;
;  OUT  (mon_blip) = (band << 4) | WORLD SECTOR, or AMMO_NODIR when the
;       map has no monster on it.
;
;  It is a separate byte and not a seventh entry of ammo_blip because the
;  dial draws it in its own colour and remembers it separately: a pickup
;  that moves must not repaint the monster and the other way round.
;
;  Clobbers AF BC DE HL.
; ---------------------------------------------------------------------
mon_scan
    ld   a,(MONCELL)
    cp   #FF
    jr   z,ms_none
    ld   c,a
    call as_pworld                  ; the same nine instructions the exit's
ms_none                             ; bearing wants -- see there
    ld   (mon_blip),a               ; ...or A = #FF from the compare above
    ret


; ---------------------------------------------------------------------
;  mon_hit -- one round landed in the monster.  Called by fire, on the
;  frames pip.asm's fx_fire came back with FX_BLOOD.
;
;  OUT  A = the effect to play: the flesh hit, or the death.
;  Clobbers AF HL.
;
;  DEATH IS #FF IN MONCELL, and that is the whole of it.  mon_draw,
;  mon_scan and hud2.asm's radar all already test for #FF -- they had to,
;  because a map with no monster on it is a legal map -- so removing the
;  monster needs no new branch anywhere.  The one thing that does NOT
;  follow from the byte is the blip: mon_scan writes it once a frame and
;  would write it again next frame, but the radar is drawn from the LAST
;  scan, so clearing it here is what stops one frame of a dead monster's
;  mauve dot.
; ---------------------------------------------------------------------
MON_HPMAX   equ 3           ; rounds it takes.  Three of a magazine of
                            ; six, so one monster costs half the ammo a
                            ; player is carrying and a miss is felt.
                            ;
                            ; NOT `MON_HP`, WHICH IS THE OBVIOUS NAME.
                            ; rasm's labels are CASE-INSENSITIVE, so the
                            ; equ and the byte `mon_hp` below are the same
                            ; symbol and it refuses to assemble -- which
                            ; is the good outcome; the bad one would have
                            ; been silence.  AMMO_MAX / plr_ammo is the
                            ; same pairing and the same reason.

mon_hit
    ld   hl,mon_hp
    dec  (hl)
    ld   a,SFX_SHOT_FLESH
    ret  nz                         ; still standing
    ld   a,#FF
    ld   (MONCELL),a                ; off the map, for everything that
    ld   (mon_blip),a               ; reads either byte
    ld   hl,scr_g                   ; ...and it is worth the same point a
    inc  (hl)                       ; pickup is
    ld   a,SFX_MONDIE
    ret


; ---------------------------------------------------------------------
;  mon_move -- THE MONSTER WALKS AT YOU.  One cell every MON_RATE game
;  frames, greedily: step along the axis you are further away on, and if
;  that cell is solid try the other.
;
;  Clobbers AF BC DE HL.
;
;  GREEDY, AND HERE IS EXACTLY HOW INCOMPLETE THAT IS.  A rule with no
;  memory walks into walls: put the player behind a doorway that is not
;  on the straight line and the monster jams against the wall between
;  them and stays there.  engine2/tools/monmodel.py replays this routine
;  over EVERY (monster cell, player cell) pair the monster's own steps
;  could join, with the player held still -- the state is one byte and
;  the rule is deterministic, so a repeated cell is a proof of "never",
;  not a timeout:
;
;      DOORS SHUT -- the map as it loads
;        2160 of 2160 pairs = 100.00%, worst 5 steps
;      DOORS OPEN
;        13054 of 24180 = 53.99%, worst 24 steps
;
;  100% WITH THE DOORS SHUT IS NOT LUCK, it is the map: a shut door reads
;  2 in SOLID, so the monster is sealed into one 4x4 room, and inside a
;  rectangle with nothing in it greedy is complete.  That is the fight
;  this game actually has -- the monster starts in the room the player
;  starts in -- and it is why the rule is nine instructions instead of a
;  search.
;
;  THE 46% WAS SHOPPED FOR AND NOT ACCEPTED BLIND.  Three richer rules
;  were modelled over the same space (see monmodel.py's note): carry on
;  in the last direction when both axes block, 57.24%; that plus a turn
;  through the four neighbours, 61.75%; slide along the blocking wall,
;  62.24%.  The best of them buys eight points, costs a byte of state and
;  a dozen instructions, and still leaves the monster stuck more than a
;  third of the time.  A rule that is wrong 38% of the time is not
;  better than one that is wrong 46% of the time in a way that is easy to
;  describe.  What would actually fix it is aiming at the DOORWAY rather
;  than at the player, and that is a search.
;
;  IT NEVER ENTERS THE PLAYER'S CELL, and that is not politeness.  At L1
;  zero the box's centre is at the near plane and pip.asm's box_draw
;  rejects it, so a monster standing on the player would be invisible AND
;  unshootable.  It stops at L1 1, in your face and fully drawn.
; ---------------------------------------------------------------------
MON_RATE    equ 6           ; game frames per cell.  THE PLAYER'S OWN
                            ; SPEED IS THE SCALE: a walk is STEP/256 =
                            ; 0.094 cells a frame and SHIFT doubles it to
                            ; 0.188, so 1/6 = 0.167 is faster than
                            ; walking and slower than running.  You
                            ; cannot stroll away from it and you can run.
                            ; At PACE_FRAMES 10 that is 1.2 s a cell, and
                            ; the worst in-room chase above is 5 steps =
                            ; 6.0 s to cross the room and reach you.

mon_move
    ld   a,(MONCELL)
    inc  a
    ret  z                          ; #FF: dead, or a map with none on it
    ld   hl,mon_tick
    dec  (hl)
    ret  nz                         ; not its frame
    ld   (hl),MON_RATE

    ld   a,(MONCELL)
    ld   c,a                        ; as_l1 wants the cell in C and leaves
    call as_l1                      ; it there; (as_tdx)/(as_tdy) come out
    cp   2                          ; signed, cell MINUS player
    jr   c,mon_bite                 ; L1 0 or 1: it is on you.  See the note

    ld   a,(as_tdx)                 ; ---- the two candidate steps, each as
    call mm_dir                     ;      a CELL OFFSET and a magnitude
    ld   (mm_mx),a
    ld   a,b
    ld   (mm_ox),a
    ld   a,(as_tdy)
    call mm_dir
    ld   (mm_my),a
    ld   a,b                        ; a step in y is sixteen cells, and
    add  a,a                        ; +-1 shifted left four times is +-16
    add  a,a                        ; in eight bits, sign and all
    add  a,a
    add  a,a
    ld   (mm_oy),a

    ld   a,(mm_mx)                  ; ---- and the dominant axis goes first
    ld   hl,mm_my
    cp   (hl)
    jr   c,mm_yfirst                ; TIES GO TO X, because >= is the free
    ld   a,(mm_ox)                  ; branch after a CP
    call mm_try
    ret  nc
    ld   a,(mm_oy)
    jp   mm_try
mm_yfirst
    ld   a,(mm_oy)
    call mm_try
    ret  nc
    ld   a,(mm_ox)
    jp   mm_try

; --- THE MONSTER'S TURN IS A STEP OR A BITE, NEVER BOTH.
;
;     It is reached from mon_move's own MON_RATE tick, which is what
;     makes the rate one number instead of two: the thing moves one cell
;     every six frames, and when there is no cell left to move into
;     because the player is standing in the next one, it takes a hit
;     point instead.  One bite every 1.2 s at PACE_FRAMES 10, so PLR_HPMAX
;     5 is six seconds of contact -- long enough to back away and shoot,
;     short enough that standing in front of it is a decision.
;
;     A SEPARATE ATTACK COOLDOWN WOULD BE A SECOND CONSTANT SAYING THE
;     SAME THING, and the two would drift.  This way "how fast is the
;     monster" has one answer.
;
;     Clobbers AF HL.
mon_bite
    ld   hl,plr_hp
    ld   a,(hl)
    or   a
    ret  z                          ; already dead: main_loop is about to
    dec  (hl)                       ; notice, and a second bite would
    ld   a,SFX_HURT                 ; underflow the bar to 255 segments
    jp   snd_play


; --- IN A = a signed offset.  OUT A = |offset|, B = the step TOWARD zero
;     as -1, 0 or +1.  The sign is inverted because as_tdx is cell minus
;     player: a monster east of the player has dx > 0 and must step west.
mm_dir
    ld   b,0
    or   a
    ret  z
    jp   m,md_neg
    ld   b,-1
    ret
md_neg
    neg
    ld   b,1
    ret

; --- IN A = a cell offset, C = the monster's cell.  Takes the step if
;     the cell is open.  OUT carry SET = did not move, clear = moved.
;
;     SOLID AND NOT "not a wall": 0 is open, 1 a wall, 2 a shut door.  A
;     shut door stops the monster exactly as it stops the player, which
;     is what seals it into its room until the player opens one.
;
;     THE ADD CANNOT WALK OFF THE MAP.  A step of -1 from x = 0 would
;     wrap into the previous row -- but row 0, row 15 and columns 0 and
;     15 are wall in every map world.py will emit (it asserts a closed
;     border), so the candidate always reads solid and is rejected
;     before the wrap can be acted on.
mm_try
    or   a
    scf
    ret  z                          ; no offset on this axis at all
    add  a,c
    ld   l,a
    ld   h,SOLID/256
    ld   a,(hl)
    or   a                          ; ...which also clears the carry
    jr   z,mt_go
    scf
    ret                             ; wall or shut door
mt_go
    ld   a,l                        ; carry is still clear from the `or a`
    ld   (MONCELL),a                ; -- and neither of these touches it
    ret


; --- HL -> ammo_blip[as_ix].  Clobbers AF BC HL.
as_slot
    ld   a,(as_ix)
    ld   c,a
    ld   b,0
    ld   hl,ammo_blip
    add  hl,bc
    ret

; --- A = the distance in L1 cells -> A = the band, already shifted into
;     the high nibble.  Clobbers AF.
as_band
    cp   AMMO_NEAR+1
    ld   a,#00
    ret  c
    ld   a,(as_cur)
    cp   AMMO_MID+1
    ld   a,#10
    ret  c
    ld   a,#20
    ret

; --- WHICH OF EIGHT SECTORS as_tdx / as_tdy POINT INTO.
;
;     Sectors run +x = 0 and CLOCKWISE on a map drawn with +y downward,
;     which is the way turn_right takes plr_a.
;
;     THE SLOPE TEST IS 5:2 AND NOT 1:1.  The boundaries want to be at
;     22.5 and 67.5 degrees.  Comparing |dy| against |dx| puts them at
;     45, which would give the four diagonal sectors everything and the
;     four axis sectors almost nothing.  5|dy| vs 2|dx| puts them at
;     21.80 and 68.20 and costs one ADD, because 5n is (n<<2)+n.  Both
;     are at most 15 cells, so 5n cannot carry out of a byte.
;
;     OUT A = 0..7.  Clobbers AF BC DE HL.
as_sector
    ld   a,(as_tdx)                 ; --- |dx| in B, |dy| in C
    or   a
    jp   p,as_axp
    neg
as_axp
    ld   b,a
    ld   a,(as_tdy)
    or   a
    jp   p,as_ayp
    neg
as_ayp
    ld   c,a

    ld   d,1                        ; --- D = the shape: 0 flat, 1
    ld   a,b                        ;     diagonal, 2 upright
    add  a,a
    add  a,a
    add  a,b                        ; 5|dx|
    ld   e,a
    ld   a,c
    add  a,a                        ; 2|dy|
    cp   e
    jr   c,as_notup
    ld   d,2                        ; 2|dy| >= 5|dx|: upright
    jr   as_shape
as_notup
    ld   a,c
    add  a,a
    add  a,a
    add  a,c                        ; 5|dy|
    ld   e,a
    ld   a,b
    add  a,a                        ; 2|dx|
    cp   e
    jr   c,as_shape
    ld   d,0                        ; 2|dx| >= 5|dy|: flat
as_shape

    ld   a,(as_tdy)                 ; --- THE QUADRANT IS JUST THE TWO SIGN
    rlca                            ;     BITS.  rlca drops bit 7 into bit
    and  1                          ;     0, so this is the sign of dy in
    add  a,a                        ;     one instruction and no branch;
    ld   e,a                        ;     OCTAB is laid out in (sy, sx)
    ld   a,(as_tdx)                 ;     order to suit.
    rlca
    and  1
    add  a,e                        ; i = sy*2 + sx
    ld   e,a
    add  a,a                        ; --- the sector: OCTAB[i*3 + s]
    add  a,e                        ; ... 3i, as 2i + i
    add  a,d                        ; ... + the shape
    ld   e,a
    ld   d,0
    ld   hl,OCTAB
    add  hl,de
    ld   a,(hl)
    ret


; --- IN C = a cell index.  OUT A = |dx| + |dy| from the player, cells.
;     Clobbers AF B E.  C is left alone: the caller still wants it.
as_l1
    ld   a,c
    and  #0F
    ld   e,a
    ld   a,(plr_x+1)                ; plr_x is 8.8: the high byte IS the
    ld   b,a                        ; cell
    ld   a,e
    sub  b                          ; dx = cx - px, SIGNED
    ld   (as_tdx),a
    jr   nc,al_xp                   ; both are 0..15, so the borrow IS
    neg                             ; the sign, and the store above does
al_xp                               ; not touch it
    ld   b,a
    ld   a,c
    rrca
    rrca
    rrca
    rrca
    and  #0F
    ld   e,a
    ld   a,(plr_y+1)
    ld   d,a
    ld   a,e
    sub  d                          ; dy = cy - py
    ld   (as_tdy),a
    jr   nc,al_yp
    neg
al_yp
    add  a,b
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
    ; ---- SHIFT RUNS, AND IT DOES EACH THING TWICE RATHER THAN TWICE AS
    ;      FAR.  Two 24/256 steps cover the same ground as one 48/256
    ;      step but test the collision box at the half way point as well,
    ;      so a running player cannot cross a wall a walking one would
    ;      have been stopped by -- and PRAD is 64/256, so a single 48/256
    ;      step was already most of the box.
    ;
    ;      It also leaves (mv_dx)/(mv_dy) ALONE.  door_act probes 0.75
    ;      cells ahead by taking 8 * the step vector, so doubling the
    ;      vector would have quietly doubled the reach of SPACE too.
    ;
    ;      Row 2 bit 5 is SHIFT, and the matrix is ACTIVE LOW.
    ld   a,(KEYS+2)
    cpl
    and  #20
    ld   (mv_fast),a

    ld   hl,KEYS                    ; --- turn: 1 step = 5 degrees, or 10
    bit  1,(hl)                     ;     with SHIFT
    jr   nz,gs_nright
    call turn_right                 ; leaves HL alone, so KEYS+1 is INC HL
    ld   a,(mv_fast)
    or   a
    call nz,turn_right
gs_nright
    inc  hl
    bit  0,(hl)
    jr   nz,gs_nleft
    call turn_left
    ld   a,(mv_fast)
    or   a
    call nz,turn_left
gs_nleft

    call step_vector                ; STEPTAB[plr_a] -> (mv_dx)(mv_dy)

    ld   hl,KEYS                    ; --- walk
    bit  0,(hl)
    jr   nz,gs_noup
    call move_apply
    ld   a,(mv_fast)
    or   a
    call nz,move_apply
    jr   gs_moving
gs_noup                             ; HL is still KEYS
    bit  2,(hl)
    jr   nz,gs_still
    call neg_step                   ; back = the same vector, negated
    call move_apply
    ld   a,(mv_fast)
    or   a
    call nz,move_apply
    call neg_step
gs_moving                           ; (plr_moving) is what drives the
    ld   a,1                        ; weapon's bob -- see gun.asm.  It is
    jr   gs_setmv                   ; the walk KEY, not the outcome of the
gs_still                            ; collision test: a player pressed into
    xor  a                          ; a wall is still walking on the spot,
gs_setmv                            ; and freezing the sway there reads as
    ld   (plr_moving),a             ; the game having stopped responding.
gs_walked

    call ammo_scan                  ; --- collect the pickup we are on,
                                    ;     else say where the nearest is
    call mon_move                   ; --- the monster takes its step...
    call mon_scan                   ; --- ...and THEN says where it is.
                                    ;     This order, because the radar is
                                    ;     drawn from the last scan: scan
                                    ;     first and the blip would be one
                                    ;     cell and one frame behind the
                                    ;     thing the renderer draws

    call fire_edge                  ; --- CTRL or Z, on the press edge

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

    ; ---- THE WAY OUT.  EXIT_CELL is an equ gen_march.py emits from the
    ;      map's 'X', and as_l1 already answers "how far is the player
    ;      from that cell" for the pickups and the monster -- so the whole
    ;      of the win condition is a cell index and a zero test.  Six
    ;      instructions, and NOT a fifth code in SOLID: the march reads
    ;      SOLID four times a cell in its hot loop and its alphabet is
    ;      full.  A map with no exit emits #FF = (15,15), outer wall,
    ;      unstandable, so the test is simply never true.
    ld   a,(plr_x+1)                ; plr_x is 8.8: the high byte IS the
    cp   EXIT_X                     ; cell, the same read as_l1 makes
    jr   nz,gs_noexit
    ld   a,(plr_y+1)
    cp   EXIT_Y
    jr   nz,gs_noexit
    ld   a,2                        ; ...and 2 is WON.  1 is ESC, 0 is
    ret                             ; keep playing -- see the ret below
gs_noexit

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
    ; ---- ONE QUADRANT OF TABLE, FOLDED FOUR WAYS.
    ;      STEPTAB was all 72 headings, 144 bytes, in a body segment
    ;      whose `assert game_end <= BUCK0` has fired ten times.  The
    ;      first quadrant is enough because the other three are exact
    ;      sign flips of it -- cos(90+t) = -sin t and sin(90+t) = cos t,
    ;      and the ROUNDING survives that: checked in Python over all 72
    ;      headings, 0 of them disagree with the folded value.  36 bytes
    ;      of table and about 40 of code, against 144.
    ld   a,(plr_a)
    ld   b,0                        ; B = the quadrant, A = the heading
sv_quad                             ; within it (0..17)
    cp   18
    jr   c,sv_got
    sub  18
    inc  b
    jr   sv_quad
sv_got
    add  a,a
    ld   l,a
    ld   h,0
    ld   de,STEPTAB
    add  hl,de
    ld   e,(hl)                     ; E = cos, D = sin, both signed bytes
    inc  hl
    ld   d,(hl)
    ; quadrant 0 (c, s)   1 (-s, c)   2 (-c, -s)   3 (s, -c)
    ld   a,b
    or   a
    jr   z,sv_store
    dec  a
    jr   nz,sv_q23
    ; ---- q1: (x, y) = (-s, c).  AND IT USED TO COME OUT (-c, s).
    ;
    ;      What stood here swapped E and D, negated one, and then did
    ;      `ex de,hl` / three loads / `ex de,hl` to "put E back as x" --
    ;      which swapped them a SECOND time and undid the first.  The
    ;      result was (-cos t, sin t): quadrant 1 mirrored about 135
    ;      degrees.  sv_store reads nothing but D and E, so the whole HL
    ;      dance was moving a value that was already where it belonged.
    ;
    ;      MEASURED on the booted disc, poking (plr_a) and reading
    ;      (mv_dx)(mv_dy) at every 6th heading:
    ;
    ;          a=18  wanted  90.0 deg   got 180.0
    ;          a=24  wanted 120.0 deg   got 150.3
    ;          a=30  wanted 150.0 deg   got 119.7
    ;
    ;      and quadrants 0, 2 and 3 all exact.  THE RENDERER WAS RIGHT
    ;      THE WHOLE TIME: gen_march.py writes MARCHTB for all 72
    ;      headings out of Python's own cos/sin, and MARCHTB[18]'s fwd is
    ;      (0, 1024) = due south.  So on eighteen of the seventy-two
    ;      headings the player LOOKED SOUTH AND WALKED WEST.
    ;
    ;      Nothing caught it because nothing tested quadrant 1:
    ;      emu_verify3 checked heading 0 (east) and heading 63 (315 deg),
    ;      the walk test walks east, and emu_pace's corridors() asked for
    ;      heading 18 believing it was south -- which is how this
    ;      surfaced at all, as a corridor that walked 0.000 cells along
    ;      its own axis.  emu_verify3 now sweeps ALL 72.
    ;
    ;      This is the same shape as sv_q3 below: swap, then negate the
    ;      one that needs it.
    ld   a,d                        ; A = sin
    neg                             ; ...= -sin
    ld   d,e                        ; D = cos
    ld   e,a                        ; E = -sin
    jr   sv_store
sv_q23
    dec  a
    jr   nz,sv_q3
    ld   a,e                        ; q2: (-c, -s)
    neg
    ld   e,a
    ld   a,d
    neg
    ld   d,a
    jr   sv_store
sv_q3
    ld   a,d                        ; q3: (s, -c)
    ld   d,e
    ld   e,a
    ld   a,d
    neg
    ld   d,a
sv_store
    ld   a,e                        ; x, sign extended
    ld   c,a
    add  a,a
    sbc  a,a
    ld   b,a
    ld   a,c
    ld   c,a
    ld   (mv_dx),bc
    ld   a,d                        ; ...and y
    ld   c,a
    add  a,a
    sbc  a,a
    ld   b,a
    ld   (mv_dy),bc
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
    ;      door_lift turns it into how far the door has RISEN, and
    ;      ds_apply below turns it into DOORMOV so the march sees
    ;      through the doorway; DOOR_SHUT and DOOR_OPEN are the two
    ;      resting states and neither of them animates anything.
    cp   DOOR_SHUT
    jr   z,ds_noanim
    cp   DOOR_OPEN
    jr   z,ds_noanim
    ld   (door_anim),a
ds_noanim
    ld   hl,door_idx
    add  hl,de
    ld   l,(hl)
    ld   h,SOLID/256
    ; ---- WHAT THE KERNEL IS TOLD ABOUT THIS CELL.  Three states, and
    ;      the middle one is what lets the run be SEEN:
    ;        DOOR_OPEN        -> 0        gone: walk through it
    ;        DOOR_SHUT        -> 2        shut: opaque and solid
    ;        anything between -> DOORMOV, which march.asm floods THROUGH
    ;      -- so the room beyond is marched and DRAWN behind the rising
    ;      door -- while coll_free still sees a non-zero cell and keeps
    ;      the player out of it.  Opacity and solidity are different
    ;      questions, and this is where they stop being the same byte.
    cp   DOOR_OPEN
    jr   z,ds_wopen
    cp   DOOR_SHUT
    ld   a,DOOR_SHUT
    jr   z,ds_w
    ld   a,DOORMOV
    jr   ds_w
ds_wopen
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
    ld   a,SFX_DOOR                 ; the run takes six frames, and the
    jp   snd_play                   ; sound is a second of it rising
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
    ld   a,SFX_DOOR                 ; shutting is the same machinery and
    jp   snd_play                   ; the same second of movement
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
    repeat N_ANGLES/4,IA
    db int(1.0*STEP*cos((IA-1)*360.0/N_ANGLES))
    db int(1.0*STEP*sin((IA-1)*360.0/N_ANGLES))
    rend
    assert N_ANGLES == 72           ; step_vector folds by quadrants of 18


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
mv_fast     db 0                ; non-zero while SHIFT is held

plr_ammo    db AMMO_MAX         ; rounds left, 0..AMMO_MAX.  hud2.asm reads
                                ; it; ammo_arm sets it
plr_hp      db PLR_HPMAX           ; hit points left.  0 ends the game --
                                ; main3.asm tests it beside the ESC key,
                                ; because both are "stop playing"
gun_recoil  db 0                ; frames of kick left.  gun.asm's consumer
ammo_st     ds MAXAMMO          ; the live pickups: a cell index each, or
                                ; AMMO_GONE once collected
ammo_blip   ds MAXAMMO          ; ONE PACKED (band << 4) | WORLD SECTOR
                                ; per pickup, or AMMO_NODIR where there
                                ; is none left.  hud2.asm's radar draws
                                ; straight off this; ammo_dir below is
                                ; the same thing for the WINNER, turned
                                ; nose-relative for the direction pad.
as_cur      db 0                ; the distance of the pickup being looked at
as_ix       db 0                ; ...and its slot in ammo_blip
mon_hp      db MON_HPMAX         ; rounds it can still take.  0 is death,
                                ; and death is #FF in MONCELL -- see
                                ; mon_hit
mon_tick    db MON_RATE         ; game frames until its next cell.  Counts
                                ; DOWN, reloaded by mon_move
mm_ox       db 0                ; mon_move's two candidate steps, each a
mm_oy       db 0                ; signed CELL offset (+-1, +-16)...
mm_mx       db 0                ; ...and how far away the player is on
mm_my       db 0                ; that axis, which picks the order
mon_blip    db AMMO_NODIR       ; the monster's packed bearing, for the
                                ; dial.  Its own byte -- see mon_scan
as_bi       db 0                ; ...and which slot the winner was in
ammo_dir    db AMMO_NODIR       ; the scanner's packed bearing.  hud2.asm
                                ; reads it; ammo_scan writes it
as_best     db AMMO_NODIR       ; ammo_scan's working set: the nearest
as_dist     db #FF              ; live cell so far and its L1 distance...
as_dx       db 0                ; ...and, once found, its signed offset
as_dy       db 0                ; from the player in cells
as_tdx      equ PIPVARS+5       ; as_l1's scratch: the offsets of whatever
as_tdy      equ PIPVARS+6       ; cell it was last asked about.  In the
                                ; gap above the door tables with pip.asm's
                                ; -- see there for why, and for the assert
                                ; that keeps them clear of RC_COVER

; WHICH OF EIGHT SECTORS A DIRECTION IS IN, by the SIGNS of its offset
; and its shape.  Sectors run +x = 0 and clockwise on a map drawn with +y
; downward, which is the way turn_right takes plr_a.
;
;   row  i = (dy<0)*2 + (dx<0)      shape  0 flat (mostly x)
;        0  right and below                1 diagonal
;        1  left  and below                2 upright (mostly y)
;        2  right and above
;        3  left  and above
;
; A TABLE AND NOT A BRANCH TREE.  The twelve cases are four lines here
; against about forty of jumps, and the thing that is easy to get wrong
; -- which way the sector numbers run round the quadrants -- is visible
; all at once instead of spread over a page.  The row order is the order
; the two sign bits fall out in, so there is no quadrant to decode at all.
OCTAB       db 0,1,2            ; dx>=0 dy>=0:  E  SE S
            db 4,3,2            ; dx<0  dy>=0:  W  SW S
            db 0,7,6            ; dx>=0 dy<0:   E  NE N
            db 4,5,6            ; dx<0  dy<0:   W  NW N
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
