; =====================================================================
;  engine2/src/main3.asm -- amaze.dsk, the top level.
;
;  A free-movement, 5-degree-turn first-person maze for the CPC 6128,
;  drawn by the engine2 pipeline (bg_fill -> frame_geom -> raster_frame)
;  and driven by src/game.asm.
;
;  MEMORY MAP while playing (ROMs off, interrupts off, firmware gone)
;    #0040-#2542  this program: top level + game + engine + HUD + gun
;    #2543-#27FF  free.  `assert game_end <= BUCKETS` at the foot of this
;                 file is the only thing standing between the next
;                 routine and the march's face buckets; if it fires,
;                 move BUCKETS and the four addresses under it up, or
;                 take the HUD's furniture table out of the code and
;                 into bank 4.
;                 (project.asm ORGs its LAT table at #E00, so growth in
;                 the FIRST half of the file is absorbed there instead --
;                 and only 11 bytes of THAT are left too.  New code
;                 belongs after the includes, where this file puts
;                 raster_paced.)
;                 THAT ASSERT HAS FIRED THREE TIMES.  Once when
;                 raster.asm grew raster_joint: the march's whole working
;                 RAM moved up three pages into the dead #3300-#35FF hole
;                 below QUADS.  Once when gun.asm arrived -- 255 bytes
;                 against 221 free -- which was paid for by making
;                 raster_joint assemble only when COURSES asks for it.
;                 And once when COURSES was turned back ON for the blue
;                 block walls: 500 bytes against 445 free, so the block
;                 moved up ONE MORE page, QUADS with it, into the slack
;                 above QUADS.  The harnesses had TWELVE hardcoded copies
;                 of these addresses and every one of them then read the
;                 page below -- see engine2/tools/addrs.py, which now
;                 parses them out of the source so that cannot recur.
;    #2800-#2EFF  march face buckets, one page per L1 distance 1..7
;    #2F00-#33FF  march flood stack
;    #3400-#36FF  FTAB / SOLID / MARK
;    #3700-#3ABF  QUADS, the geometry kernel's output (120 x 8 bytes; it
;                 was 120 x 14 before the record shrank to (blo, bhi,
;                 hlo, hhi, kind, k) -- see kernel.asm)
;    #3AC0-#3FEF  free;  #3FF0 is the top of our stack
;    #4000-#7C48  RAM bank 4: the precalculated tables, permanently paged
;    #8000-#BFFF  back buffer
;    #C000-#FFFF  front buffer
;
;  WHY THE PROGRAM IS RELOCATED.  The engine's working RAM starts at
;  #2700, so the code has to live BELOW it -- but a BASIC loader cannot
;  LOAD a file over #0170, because that is where the BASIC program doing
;  the loading is sitting.  So the file is built to load at #8000 (which
;  is only the back buffer, and nothing is drawn yet), and its first
;  instructions page the machine and copy the body down to #0040 before
;  jumping into it.  rasm's two-address ORG does the whole trick: the
;  body is ASSEMBLED for #0040 and EMITTED after the stub.
;
;  PACING -- A COST ACCUMULATOR, AND A GENUINELY CONSTANT PERIOD.
;
;  Walking speed is distance-per-frame over seconds-per-frame, so it is
;  constant only if the frame period is.  Flipping on the first vsync
;  after the render does not give that.  It gives a whole number of 20 ms
;  periods -- the loop never straddles a boundary -- but WHICH number
;  depends on the view, and MEASURED over 200 states drawn from the
;  reachable space (engine2/tools/emu_fps.py) it was
;
;      40 ms 57%   60 ms 37%   80 ms 6%          (PACE_FRAMES = 0)
;
;  i.e. a corridor walks twice as fast as a junction.
;
;  A FIXED PAD IS NOT ENOUGH.  This file used to cut the render into four
;  chunks with a vsync wait after each, which is exactly right when every
;  chunk is under one 20 ms period and wrong the moment one is not: a
;  chunk that overruns rounds UP to two periods.  MEASURED on the built
;  disc, 1308 states, exact per-vsync sampling:
;
;      80 ms 79.0%   100 ms 19.6%   120 ms 0.9%   140 ms 0.5%
;
;  -- mean 84.6 ms, and six or more reachable states sat at a steady
;  140 ms, because chunk 1 (bg 9.3 + march 11.7 = 21.0 ms) and chunk 2
;  (project_all 27.7 ms) each exceed a period on their own.  Walking
;  speed therefore varied by up to 1.75x with the view.
;
;  THE FIX IS COST-DRIVEN YIELDING.  The machine cannot read a clock --
;  interrupts are off (SP is the screen pointer inside the fills and the
;  flood stack inside the march), so the 300 Hz tick cannot be counted,
;  there is no other timer, and the vsync pulse is about 1 ms wide, so
;  polling it at stage boundaries misses pulses.  But the engine does not
;  need to READ the time; it knows what its own work COSTS, because every
;  unit of it has been measured:
;
;      unit                          MEASURED          charged (C_*)
;      bg_fill, whole              8501.3 us, fixed      8600
;      march_setup                1372.8-1445.1 us       1550  *
;      one popped flood cell        680.1 us              740
;      a face that becomes a quad  1298 us               1380
;      a face that does not         420 us                480
;      each clip lerp               845 us                930
;      hud_update, needle moved    1422.5 us worst       1550  *
;      gun_step + gun_draw + hook  4375.2 us worst       4500  (C_GUN) *
;      flip + game_step + head     1305.9 us             1450  (C_TAIL) *
;      door_act, SPACE edge only    756.6 us              900  (C_DOORACT) *
;      one quad                     781 + 38.60*jlo       740 + 46*jlo
;                                     + 135.7*wl2             + 138*wl2
;                                     + 2.028*bw*(jlo+jhi)    + 2*bw*(...)
;
;  A QUAD IS STILL ONE UNIT, AND THAT IS THE BIGGEST ONE THERE IS.
;  pace_quad predicts a whole quad before a pixel of it is drawn, so the
;  worst quad this viewport can produce -- 12486 us MEASURED, 63% of a
;  vsync period -- is the largest ATOMIC unit in the frame, and the
;  atomic unit is what decides how few periods a frame can pack into.
;  raster.asm can yield INSIDE raster_quad instead (RQ_SPLIT, and
;  engine2/tools/emu_atomic.py measures both): that takes the atomic unit
;  to 3415 us, byte for byte the same picture, but it costs ~200 us a
;  hook and 42 hooks a frame, the worst frame's work goes 93.00 -> 101.50
;  ms and its CHARGE 95 -> 116.3 against a 116.74 ms budget -- so the
;  greedy rule asks for a sixth wait and three states in 1400 take SEVEN
;  periods.  RQ_SPLIT is therefore 0.  See the note on it in raster.asm.
;
;  (re-measured at 40x96 with the trimmed hooks; the margins are thin by
;   design -- emu_pacefit.py reports the smallest per-phase over-estimate
;   over 40 states as +19 us on the march, +20 on the projector and -69 on
;   the rasteriser, so there is nothing left to tighten here.)
;
;  * THE FOUR STARRED ROWS WERE WRONG, and are the reason
;  engine2/tools/emu_holes.py exists.  emu_pacefit.py cannot bench them in
;  the shape the frame runs them -- its loop cannot hold a key without the
;  player walking off the state being measured, it never sees the frame
;  the flood-mark generation wraps, and it sampled march_setup and
;  hud_update at ONE state each.  Measured properly, on the booted disc,
;  pinned, with real keys held, swept over the movement lattice:
;
;    march_setup   was 1884.1 us on the one frame in 255 that the MARK
;                  wipe fell due, against a flat 1450.  march.asm now
;                  amortises the wipe, four bytes a frame; and the routine
;                  itself spans 1372.8-1445.1 us across states, so the old
;                  1450 cleared its own worst case by 4.9 us.
;    C_TAIL        was fitted to a game_step with NO KEYS HELD (656 us).
;                  Turning and walking costs 1120.4, so the tail was
;                  1305.9 against 1050.
;    C_DOORACT     did not exist: the SPACE press edge ran door_act for up
;                  to 756.6 us and charged it to nobody.
;    C_HUD         was 1420 against a measured worst of 1422.5 -- already
;                  under the truth, at heading 54, because the compass
;                  needle's blocks do not cross the same number of
;                  character rows at every angle.
;
;  None of the four had been SEEN to spill.  That is not the test.  The
;  test is that every constant bounds its unit over the whole state space,
;  and `make pace` now runs emu_holes.py to check exactly that.
;
;  MEASURED ON THIS DISC, not in a harness -- the hooks are part of the
;  cost they charge for, so they have to be inside the thing being timed.
;  engine2/tools/emu_pacefit.py drops a counter loop into the free RAM at
;  #3A00 of the RUNNING game and calls each entry point from there, 100-NOP
;  calibration 99.99 us, empty loop subtracted; 40 reachable states, least
;  squares against the counters the Z80 ITSELF charges from (m_visited,
;  pf_ok, pf_nclip, the quad records).  R^2 0.97 / 0.999 / 0.998.
;
;  The charged column is the measured one rounded UP -- every fit above is
;  checked to over-predict on all 40 states -- so AN ESTIMATE IS NEVER
;  UNDER THE TRUTH.  That one-sided property is the whole safety argument,
;  and it is why the numbers are not simply the fitted ones.
;
;  So (cost_acc) carries a running microsecond total and the accumulator
;  YIELDS -- one wait_vsync, one wait off the frame's budget, and a reset
;  -- whenever the interval is full.  "Full" is decided two ways, because
;  the two kinds of work know their cost at different times:
;
;    cost_unit   ROOM THEN CHARGE, against COST_THI = 19456.  For work
;                whose cost is known before it runs -- bg_fill, the march
;                setup, one flood cell, one quad, hud_update.
;    cost_face   CHARGE THEN TEST, against FACE_THI = 15360.  A face's
;                cost is not known until proj_face has run, so it is
;                charged afterwards against a threshold set one whole
;                C_FACE_MAX lower -- which bounds the interval just as
;                hard (15360 + 4170 = 19530) and, unlike rooming, wastes
;                nothing when the face turns out to be cheap.
;
;  ...and cost_gate, which charges nothing and is called ONCE, on the way
;  into the bucket walk.  Charge-then-test is only safe while the interval
;  is under FACE_THI when the face STARTS; cost_face keeps that true for
;  every face after the first, and the gate makes it true for the first.
;  Without it a face is charged on top of whatever the march left, which
;  can be anything under COST_THI: MEASURED, (0E10,0968) h13 came out of
;  the march at 18990 us and the first face put 2310 more on it, and
;  21300 us between two waits is a period and a bit -- so that frame took
;  SEVEN periods.  Three states in 1595 did it.
;
;  Every interval between two waits therefore holds under 19530 us of
;  ESTIMATE and so under 19530 us of real time, inside a 19968 us period,
;  WITHOUT A TIMER.
;
;  PAIRED WITH AN EXACT BUDGET.  (pace_left) starts each frame at
;  PACE_FRAMES; every yield spends one, and pace_drain spends whatever is
;  left before the flip.  The frame therefore takes EXACTLY PACE_FRAMES
;  waits however cheap or expensive the view is -- yield early when the
;  cost says so, drain the rest at the end.  The accumulator is NOT
;  cleared at the frame boundary: work done after the last wait (the flip,
;  game_step, and the head of the next frame) belongs to the next
;  interval, and carrying it is what keeps that interval honest too.
;
;  AND IT NEVER FREE-RUNS.  pace_wait used to `ret z` when the budget was
;  gone, and pace_drain with it, so an expensive frame simply stopped
;  waiting and ran the rest of the render unpaced.  The flip then landed
;  at a variable offset from the last vsync edge and the period stopped
;  being a whole number of vsyncs at all: MEASURED on the disc this file
;  used to build, (0160,0DE0) h69 and h67 sat at a steady 109.2-110.5 ms
;  = 5.47 periods, and a 24/256-lattice sweep found 1.3% of frames off the
;  grid.  Both routines now wait anyway -- see pace_wait -- so the budget
;  bounds the period from below, never from above, and the period is a
;  whole number of periods whatever happens.
;
;  WHY PACE_FRAMES IS 6 AND NOT 5.  Not for want of trying.  5 has been
;  the target three times and it does not fit, and there are now two
;  INDEPENDENT reasons, either of which settles it on its own.
;
;  (1) IT DOES NOT FIT ARITHMETICALLY.  Five periods is 99.84 ms and the
;      threshold-times-budget the accumulator actually packs into is
;      5 x 19456 = 97.28 ms.  The worst CHARGED frame at 44x96, over all
;      4055040 reachable states (engine2/tools/pacescan.py), is 105274 us.
;      That is over 97.28 ms before any question of packing arises, so no
;      chunking, threshold or hook cost can rescue it.  At 40x96 the same
;      exhaustive number is 101618 us -- also over.
;
;  (2) THE WORK ITSELF LEAVES TOO LITTLE SLACK EVEN IF IT DID FIT.  The
;      worst whole game frame MEASURED at 44x96 is 99.50 ms -- each part
;      benched on the booted disc with emu_pacefit.py's protocol, at the
;      40 most expensive states pacescan.py's exhaustive pass names, with
;      the tail charged at C_TAIL, and with the WEAPON at the bob offset
;      that draws the most rows.  Against FIVE periods (99.84 ms) that is
;      0.34 ms of slack; against six it is 20.31 ms.  It was 98.28 before
;      the sprite grew to 28x46 and the anchor moved below the bottom
;      edge: the weapon went 3.16 -> 4.38 ms and the worst frame with it.
;
;      AND THE STATE LIST IS WHY THAT NUMBER IS RIGHT.  Benched instead at
;      the 40 heaviest states a SAMPLED replay could find, the same disc
;      reads 90.63 ms -- the sample understates the worst frame by 7.6 ms,
;      because the worst frame in a 4-million-state space is not in a
;      20000-state sample of it.
;
;  AND IT WAS MEASURED ON THE DISC ANYWAY, because arithmetic that says
;  "no" is still worth checking against the machine.  PACE_FRAMES 5 built
;  and swept at 44x96, 413 states, 3304 game frames, period read at 250 us
;  and NOT rounded:
;
;      5 vsyncs  99.84 ms  86.68%      6 vsyncs  119.81 ms  13.32%
;
;  -- 55 states of 413 sat at a rock-steady 119.81 ms in a 99.84 ms world.
;  At 40x96 the same experiment gave 24 states of 533 and 4.32% of frames.
;  That is the walking-speed defect this file exists to remove, arrived at
;  from the cheap direction.
;
;  AND NOTE WHICH STATES FOUND IT.  In that PACE_FRAMES 5 sweep the 300
;  UNIFORMLY SAMPLED states were 100% on pace; every one of the 55
;  failures came from the 60 states engine2/tools/emu_pace3.py had asked
;  the offline replay to name as the worst packers.  A uniform sample of
;  the lattice would have reported a clean lock on a disc where one frame
;  in eight is a period late.  That is why the sweep is now seeded from
;  the model's worst states and why pacescan.py counts the whole space
;  instead of sampling it.
;
;  SIX HOLDS EVERYTHING, AND THAT IS AN EXHAUSTIVE STATEMENT NOW.
;  pacescan.py replays this exact rule -- same constants, same order, same
;  greedy -- for all 4055040 states a player can stand in (56320 positions
;  on the 24/256 movement lattice passing game.asm's own collision box,
;  times 72 headings), with C_DOORACT charged on EVERY frame, which is the
;  pessimistic direction:
;
;      1 wait  0.61%   2  62.14%   3  26.04%   4  10.85%   5  0.35%
;      6 waits: 0 states of 4055040
;
;  Five waits plus the drain is six periods, so the budget is exactly
;  enough and nothing reaches past it.  The worst charged frame is
;  104024 us of 116736.
;
;  THE OLD ANSWER CAME FROM A SAMPLE, AND THAT IS THE POINT.  This note
;  used to quote "12 states in 20000 ask for five" from a random replay.
;  A defect that lives on three states in a million -- which is what
;  raising C_QUAD from 740 to 920 produced, MEASURED on the disc at a
;  rock-steady 139.8 ms -- is invisible to a 20000-state sample and to a
;  1400-state disc sweep alike.  The space is 4 million states and the
;  replay is a minute on sixteen cores, so there is no reason to sample
;  it at all.
;
;  AND THAT IS WHAT THE DISC DOES.  The sweep also has to be run on the
;  RIGHT LATTICE, which is the trap an earlier one fell into: it sampled
;  sub-cell offsets at multiples of 32/256, but the movement step is
;  24/256 of a cell per game frame, so a walking player lands on offsets
;  that sweep could never reach.  On the 24/256 lattice, plus the offline
;  replay's worst packers, plus states reached by actually HOLDING KEYS,
;  plus every known bad state by name, at 250 us resolution and NOT
;  rounded to vsyncs:
;
;      PACE_FRAMES = 6   119.81 ms, 8.35 fps, for EVERY view, 100.00%
;
;  MEASURED with the weapon drawn and charged.  And walking speed follows:
;  three corridors of quite different draw cost all walk the same
;  cells/s, spread 1.0000x.
;
;  A constant 8.35 fps is worth more than a nominal 10 fps that is really
;  100 ms here, 109.2 there and 119.8 somewhere else, because the swing is
;  what the player feels as the walking speed changing -- and an
;  aperiodic swing is worse than a periodic one.  PACE_FRAMES = 0 restores
;  the unpadded behaviour for comparison.
;
;  (frame_ctr) counts game frames; it exists so the cadence above can be
;  measured on the real disc rather than modelled.
;
;  KEYS   cursor up/down  walk forward / back along the heading
;         cursor left/right  turn 5 degrees per frame
;         space           open or shut the nearest door
;         escape          back to BASIC
; =====================================================================

    include "tab_equ.inc"           ; which itself includes vpcfg.inc

GAME_ORG    equ #0040               ; where the body really runs
STACKTOP    equ #3FF0
SCR_FRONT   equ #C000
SCR_BACK    equ #8000

; ---------------------------------------------------------------------
;  THE PACING CONSTANTS.  See the PACING note above for where each of
;  them was measured; engine2/tools/pacemodel.py is the Python twin of
;  this block and MUST be kept in step with it, because that is what
;  proves six waits are enough over the whole reachable space.
;
;      6   every game frame takes exactly six vsync periods (119.81 ms)
;      5   100 ms -- what this used to be, and what three states in
;          twenty thousand cannot fit into: see the PACING note
;      0   no pad: flip on the first vsync after the render, so the
;          cadence is 2, 3 or 4 periods depending on the view
; ---------------------------------------------------------------------
;  AND IT MOVES WITH vpcfg.inc's VPCOL.  The two are coupled and there is
;  no way round it:
;
;      VPCOL 0   flat spans     PACE_FRAMES 6   119.81 ms   8.35 fps
;      VPCOL 1   textured cols  PACE_FRAMES 9   179.71 ms   5.56 fps
;
;  EXHAUSTIVE over all 6967296 reachable states (pacescan.py) with the
;  column renderer's own measured charges -- the ONE-SIDED ones, taken
;  one upper-bound hook per column pair, see engine2/src/costcol.inc --
;  the worst charged frame is 156501 us against the span renderer's
;  104024, and the distribution of waits the greedy rule asks for is
;
;      5 waits 0.096%   6  47.12%   7  51.48%   8  1.310%
;
;  -- so eight waits is what the budget has to be, and nine periods is
;  what the frame takes.  Set VPCOL back to 0 and put this back to 6.
;
;  IT WAS 10, AND THE PERIOD IT BOUGHT WAS PAYING FOR A BROKEN CHARGE
;  RATHER THAN FOR WORK.  rastcol.asm took its per-pair hook AFTER the
;  pair's own setup, so room-then-charge billed that setup to the
;  PREVIOUS hook -- often a 60 us edge run -- and the disc read
;  [10, 11, 13] vsyncs against a budget of 10 while an offline replay of
;  the same charge reported it fitting.  One hook per pair, taken first
;  and charging an upper bound, is what closed it; nothing in the
;  renderer got faster.
; ---------------------------------------------------------------------
PACE_FRAMES equ 9

;  IT IS ONE UNCONDITIONAL LINE AND THE ASSERT IS WHY.  Writing it as
;  `if VPCOL / 8 / else / 6 / endif` assembles perfectly and breaks the
;  PYTHON side silently: pacemodel.py and emu_pace.py both find
;  PACE_FRAMES by scanning main3.asm for the first line whose first token
;  is the name, so they would read 8 in a VPCOL 0 build and model a disc
;  that does not exist.  That is the same class of failure as the twelve
;  hardcoded addresses engine2/tools/addrs.py exists to remove.  So there
;  is one line, and an assert that fires the moment it disagrees with the
;  renderer it is paired with.
    assert (VPCOL == 0 && PACE_FRAMES == 6) || (VPCOL == 1 && PACE_FRAMES == 9)

; ---------------------------------------------------------------------
;  GUN -- draw the first-person weapon (engine2/src/gun.asm).  0 builds
;  the same disc without it.
;
;  The weapon is 3.16 ms of work and for one build it was charged to
;  NOBODY, so on a state whose last interval was already close to
;  COST_THI it spilled past the vsync edge and the frame took a seventh
;  period.  It is now C_GUN, one more ROOM-THEN-CHARGE unit exactly like
;  bg_fill or hud_update, taken through gun_paced at the foot of this
;  file -- the yield falls in FRONT of the weapon on a frame the view has
;  already filled and behind it on one it has not.  GUN_CHARGED below
;  keeps the before-and-after measurable.
; ---------------------------------------------------------------------
GUN         equ 1

; ---------------------------------------------------------------------
;  GUN_CHARGED -- 1 charges C_GUN through cost_unit before the weapon is
;  drawn; 0 draws exactly the same weapon and tells the accumulator
;  nothing, which is the disc the row above was measured on.
;
;  IT EXISTS SO THE FIX IS A CONTROLLED COMPARISON AND NOT A CLAIM.  Two
;  builds, the same 300 states of the 24/256 lattice out of the same
;  seed, the same 2400 game frames, the period sampled at 250 us and not
;  rounded (engine2/tools/emu_pace.py 300):
;
;      GUN_CHARGED 0    6 vsyncs 99.33%,  7 vsyncs 0.67% (2 states)
;      GUN_CHARGED 1    6 vsyncs 100.00%                     LOCKED
;
;  -- so the sampler still sees the defect when the charge is taken away,
;  which is the only thing that makes 100.00% mean anything.  The two
;  states are (0652,0262) h6 and (0378,0740) h39; both sat at a
;  ROCK-STEADY 139.78 ms, which is the shape an uncharged unit always
;  makes, and both are named in emu_pace.py:SPILL so every future run
;  measures them.  Leave this at 1; it is here to be flipped for an
;  afternoon, not to ship.
; ---------------------------------------------------------------------
GUN_CHARGED equ 1

COST_THI    equ #4C         ; the yield threshold, high byte: 19456 us.
                            ; A whole page keeps the test to CP H, and
                            ; 19968 - 19456 = 512 us is what is left over
                            ; if an estimate is ever under the truth --
                            ; which, per unit, it is not: see below.
FACE_THI    equ #3C         ; 15360 us -- the CHARGE-THEN-TEST threshold
                            ; the projector's faces use.  A face's cost is
                            ; not known until it has run, so the old code
                            ; ROOMED C_FACE_MAX (4170 us) before every one
                            ; of them and yielded when that did not fit --
                            ; which threw away up to 4170 us of a 19456 us
                            ; interval whether the face needed it or not,
                            ; and it was MEASURED as the single largest
                            ; source of packing waste (3946 / 4156 / 4136
                            ; us in the traces of the worst states).
                            ; cost_face now CHARGES what the face really
                            ; cost and tests afterwards, so the interval
                            ; runs to between FACE_THI and FACE_THI +
                            ; C_FACE_MAX = 19530 us -- still inside a
                            ; 19968 us period, with 438 us to spare, and
                            ; with the waste gone.
C_TAIL      equ 1450        ; THE TAIL: everything between pace_drain and
                            ; the next frame's first cost_unit -- flip,
                            ; game_step, and the head of main_loop.  It is
                            ; added to (cost_acc) at the TOP of the frame,
                            ; because that is where the work it charges
                            ; for has just been done.
                            ;
                            ; 1050 WAS UNDER THE TRUTH.  It was fitted to
                            ; a game_step benched with NO KEYS HELD (656
                            ; us), and a game_step that turns and walks
                            ; costs half as much again: MEASURED on the
                            ; booted disc, engine2/tools/emu_holes.py,
                            ; pinning the player so the bench cannot walk
                            ; off the state it is measuring and holding
                            ; real keys so scan_keys sees them --
                            ;
                            ;   flip                          62.5 us
                            ;   main_loop head (3 setbufs,
                            ;     frame_ctr, the accumulator) 123.0 us
                            ;   game_step, still             661.3 us
                            ;   game_step, walking + turning  worst
                            ;     over the sampled lattice   1120.4 us
                            ;
                            ; -- a tail of 1305.9 us against a constant of
                            ; 1050.  Never seen to spill, but the whole
                            ; pacing argument is that every constant is a
                            ; one-sided upper bound, so it is one now.
                            ; The SPACE branch is NOT in here: see
                            ; C_DOORACT.
C_DOORACT   equ 900         ; door_act, charged by game.asm on the SPACE
                            ; PRESS EDGE only, through cost_add -- charge,
                            ; no test, no wait.
                            ;
                            ; SEPARATE FROM C_TAIL ON PURPOSE.  MEASURED
                            ; 756.6 us worst, benched on its own over the
                            ; movement lattice (emu_holes.py), and it runs
                            ; on the frames a player taps SPACE and no
                            ; others.  Folding it into C_TAIL would charge
                            ; it to every frame forever and throw 690 us a
                            ; frame of packing headroom away; charging it
                            ; where it happens costs nothing on the frames
                            ; it does not.
                            ;
                            ; NO TEST, BECAUSE THERE IS NO BUDGET LEFT.
                            ; game_step runs after pace_drain, with
                            ; (pace_left) at zero, so a cost_unit here
                            ; would take a wait that nobody had budgeted
                            ; and turn the frame into PACE_FRAMES+1.
                            ; cost_add just leaves the microseconds in
                            ; (cost_acc), which the next frame carries in
                            ; alongside C_TAIL and pays for out of its own
                            ; first interval -- which is exactly where the
                            ; time was spent.
C_BG        equ 9320        ; bg_fill, and THE ONE CONSTANT THAT MOVES WITH
                            ; THE VIEWPORT WIDTH.  It is a straight-line
                            ; fill of a rectangle, so it reads the same
                            ; number on every state -- but a different one
                            ; at every width.  MEASURED, emu_pacefit.py's
                            ; protocol on the booted disc:
                            ;
                            ;      40 x 96    8501.3 us   ->  8600
                            ;      44 x 96    9215.8 us   ->  9320
                            ;
                            ; 178.6 us a byte, which is what four more
                            ; bytes of a 96-line fill costs.  8600 was
                            ; STILL IN THIS FILE when the viewport was
                            ; first widened to 44, i.e. 616 us UNDER the
                            ; truth, and the only reason nothing spilled is
                            ; that the other constants over-covered it.
                            ; pacemodel.py now reads this value out of this
                            ; file (see its _equ list) instead of keeping a
                            ; second copy, so the model and the disc cannot
                            ; disagree about it again.
C_MSETUP    equ 1550        ; march_setup.  This is the ROUTINE, benched
                            ; on its own -- not the 921 us intercept of
                            ; the march's cells regression, which is a fit
                            ; and not a cost.
                            ;
                            ; IT IS FLAT AGAIN.  It used to have a 534.9
                            ; us step in it -- the 256-byte MARK wipe,
                            ; taken whole on the one frame in 255 that the
                            ; generation counter wrapped.  march.asm now
                            ; spreads that over 64 frames at four bytes
                            ; each, so the wrap frame and every other
                            ; frame measure the SAME march_setup.
                            ;
                            ; AND IT IS SWEPT, which it had never been.
                            ; 1450 came from a single bench of 1350.2 us,
                            ; but march_setup's four seed multiplies and
                            ; its L1 build depend on where the player is
                            ; standing and which way he faces: MEASURED
                            ; over the movement lattice (emu_holes.py) the
                            ; spread is 1372.8 - 1445.1 us, so the old
                            ; constant cleared its own worst case by 4.9
                            ; us. That is not a bound, it is a coincidence.
                            ; 1550 clears it by 104.9.
C_CELL      equ 740         ; one popped flood cell (m_visited), incl.
                            ; the faces it files and the hook itself
C_FACE      equ 1380        ; a candidate face that becomes a quad
C_REJ       equ 480         ; ...one that is rejected
C_CLIP      equ 930         ; each clip lerp: near plane, left, right
C_FACE_MAX  equ C_FACE+3*C_CLIP     ; the room every face must be given
C_HUD       equ 1550        ; hud_update with the compass needle moved.
                            ; 1420 WAS UNDER THE TRUTH, by the same fault
                            ; C_MSETUP had: it came from emu_hud.py's
                            ; single 1360.2 us measurement of a single
                            ; heading transition.  Swept over all 72
                            ; headings with (hud_cur) forced so every call
                            ; takes the erase-and-redraw branch
                            ; (emu_holes.py), the worst is 1422.5 us at
                            ; heading 54 -- the needle's eight blocks do
                            ; not cross the same number of character rows
                            ; at every angle.  1550 clears it by 127.5.
C_GUN       equ 3400        ; THE WEAPON, gun_step + gun_draw + this hook.
                            ; MEASURED on the booted disc, emu_gun.py:
                            ; gun_draw 2404.4-3088.2 us over all 45 bob
                            ; offsets and gun_step 164.8 us walking (42.0
                            ; standing); emu_pacefit.py benches the whole
                            ; charged block, gun_step stubbed to RET so the
                            ; bob cannot walk during the loop, and reads
                            ; 3307.7 us WORST at dy = +4.  92.3 us of
                            ; margin, one-sided like every other constant
                            ; here.
                            ;
                            ; THE CHARGE FOLLOWS THE ART, IN BOTH
                            ; DIRECTIONS.  It was 3250 when the sprite was
                            ; 28x38 and bobbed upward only; it went to 4500
                            ; when the sprite was 28x46 and anchored below
                            ; the bottom edge; the art is 28x38 again and
                            ; the bench says 3307.7, so it is 3400.  The
                            ; number of rows the blitter draws is not a
                            ; constant -- it is GUN_ROWS0 = 30 at the
                            ; bottom of the swing and GUN_H = 38 at the
                            ; top, a 684 us spread -- and a cost constant
                            ; in this file bounds the WORST of a unit and
                            ; never its mean.
                            ;
                            ; THE BENCH HAD TO CHANGE WITH IT, and this is
                            ; the part worth remembering: gun_paced calls
                            ; gun_step, gun_step walks the bob, and a bench
                            ; loop runs hundreds of iterations -- so
                            ; benching the whole block reports the MEAN
                            ; over the bob cycle whatever offset was poked
                            ; in.  emu_pacefit.py stubs gun_step to RET so
                            ; the offset stays put, sweeps dy, and adds
                            ; gun_step's own walking cost back.
                            ;
                            ; AND AT 3400 IT PACKS -- WHICH IS WHAT CLOSED
                            ; THE OPEN ITEM.  pacescan.py, exhaustive over
                            ; all 4055040 states, at C_QUAD 820:
                            ;
                            ;   C_GUN 3250   0 states need a 6th wait
                            ;   C_GUN 3400   2
                            ;   C_GUN 4500  28   (the 28x46 sprite's truth)
                            ;
                            ; The 46-row sprite did NOT pack at its honest
                            ; charge, and the fix was never to lower C_GUN
                            ; -- that is the defect GUN_CHARGED exists to
                            ; document.  The fix is that C_QUAD is SEARCHED
                            ; against whatever C_GUN honestly is, and at
                            ; C_GUN 3400 the sweep puts it at 780/22 with
                            ; ZERO over-budget states.  See C_QUAD below.
                            ;
                            ; ONE UNIT, NOT SPLIT.  3.25 ms is a sixth of
                            ; a 19456 us interval, so rooming it whole can
                            ; never fail to fit somewhere in six of them;
                            ; splitting only pays when a unit approaches a
                            ; whole bin, which is raster_quad's problem
                            ; (10.5 ms) and not this one.  And it MUST be
                            ; one unit anyway: gun_draw's DE walks the
                            ; screen across the whole sprite, so there is
                            ; no place inside it a wait could be taken.
                            ;
                            ; It is charged BEFORE the blit runs, which is
                            ; the point -- room-then-charge puts the yield
                            ; in front of the weapon on a frame the view
                            ; already filled, and behind it on one it did
                            ; not.  Charging afterwards would let the two
                            ; land in the same interval and overrun it,
                            ; which is exactly the defect being fixed.
; ---------------------------------------------------------------------
;  THE RASTERISER, CHARGED BY THE SCANLINE.
;
;  raster.asm used to be charged one whole quad at a time, by pace_quad,
;  which read the record and predicted the lot before a pixel was drawn.
;  That made ONE QUAD the smallest thing between two possible vsync
;  yields -- 12486 us MEASURED on the worst shape the viewport can
;  produce -- and the frame rate is set by the largest atomic unit, not
;  by the total slack.  raster_quad now yields inside itself, every
;  RQ_BCH body scanlines and every RQ_WCH wedge pairs (raster.asm), and
;  charges WHAT IT HAS ALREADY DRAWN.
;
;  MEASURED on the built rasteriser, emu_rast.py's protocol with the
;  Bresenham steps separated out as their own regressor:
;
;      per quad, nothing drawn        426.0 us
;      body scanline                   18.78 us + 1.976 us/byte
;      wedge scanline                  59.05 us + 1.760 us/byte
;      wedge edge step                 19.27 us,  D of them per wedge
;
;  and every constant below is that rounded UP, as usual.
; ---------------------------------------------------------------------
C_QSET      equ 880         ; raster_quad's own setup, plus the raster_frame
                            ; loop and the head of the first chunk hook.
                            ; It is roomed at the TOP of raster_quad, on
                            ; the CPU stack, before the record is read.
                            ; MEASURED worst 696 us over 53 quad shapes
                            ; (engine2/tools/emu_atomic.py); 800 clears it
                            ; by 104.
C_BLINE     equ 20          ; one body scanline, fixed part; the run's bytes
                            ; are charged at 2 us each on top of it
C_WPAIR     equ 122         ; one wedge scanline PAIR, fixed part (2 x 59.05)
C_CHUNK     equ 300         ; ONE chunk hook -- the SP swap, three pushes,
                            ; cost_unit at its YIELDING worst, and the loop
                            ; re-entry.  It is added to every chunk's charge,
                            ; which pays for the hook that FOLLOWS that
                            ; chunk; there is exactly one of those per chunk,
                            ; and the charge has to cover it because the
                            ; hook runs BEFORE the charge it takes.
                            ; MEASURED worst 257 us (emu_atomic.py).
; ---------------------------------------------------------------------
;  C_JOINT -- the two course boundaries of ONE wall face, drawn on top of
;  it by raster.asm:raster_joint when vpcfg.inc's COURSES is 1.
;
;  It is a FLAT charge, not a formula like the quad's, and deliberately:
;  the joint is a thin band, so its cost is bounded by the face WIDTH and
;  the row count, both of which the quad's own charge has already paid a
;  multiply for.  A second multiply to save a few hundred microseconds on
;  the narrow faces is not worth the hook, and the LOD cut (JOINT_KMAX)
;  means only the near faces reach here at all.
; ---------------------------------------------------------------------
C_JOINT     equ 7400

; ---------------------------------------------------------------------
;  THE COLUMN RENDERER, CHARGED ONE UPPER-BOUND HOOK PER PAIR.
;
;  vpcfg.inc's VPCOL picks engine2/src/rastcol.asm over raster.asm.  Its
;  charge constants live in engine2/src/costcol.inc -- ONE file, because
;  engine2/test/tst_rcol.asm's atomic harness takes the same hooks and
;  pacemodel.py parses the same numbers, and a second copy is how C_BG
;  spent a viewport change 616 us under the truth in two places at once.
;  The shape of the charge, and the measured under-charges that forced
;  it, are documented there.
; ---------------------------------------------------------------------
    include "costcol.inc"

C_QUAD      equ 780         ; THE WHOLE-QUAD CHARGE, used when raster.asm's
C_QS        equ 22          ; RQ_SPLIT is 0 -- see pace_quad at the foot of
C_QW        equ 128         ; this file, and the note on RQ_SPLIT in
                            ; raster.asm for the measurement that put it
                            ; back in charge of the disc.
                            ;
                            ; C_QUAD IS THE LARGEST CHARGE THAT STILL LOCKS,
                            ; and it is picked that way because the two
                            ; things wanted of it pull opposite ways.
                            ; BIGGER IS SAFER: pace_quad's charge is a
                            ; regression over whole frames, its byte term is
                            ; 2 us against a real 1.976, and the viewport
                            ; width multiplies that term while C_QUAD does
                            ; not -- so widening the viewport eats the
                            ; margin.  BIGGER PACKS WORSE: the greedy rule
                            ; then asks for a sixth wait on a few states out
                            ; of four million, and those sit a whole period
                            ; late for ever.
                            ;
                            ; So it is not fitted, it is SEARCHED, over the
                            ; whole reachable space rather than a sample.
                            ; engine2/tools/pacescan.py replays the rule for
                            ; every one of the 4055040 states a player can
                            ; stand in (56320 lattice positions x 72
                            ; headings, game.asm's own box rule) at each
                            ; candidate; `pacescan.py sweep` at 44x96, with
                            ; the weapon at its own honest C_GUN of 3400:
                            ;
                            ;    C_QUAD/C_QS   states needing a 6th wait
                            ;      740 / 22          0     locked
                            ;      780 / 22          0     locked  <-- here
                            ;      740 / 23          1
                            ;      780 / 23          8
                            ;      820 / 22          2
                            ;      860 / 22          7
                            ;      960 / 23         54
                            ;
                            ; IT MOVED WITH C_GUN, WHICH IS THE POINT.  820
                            ; locked while the weapon was charged 3250 and
                            ; kept locking at the 28x46 sprite's dishonest
                            ; 3250; at the 46-row sprite's true 4500 it put
                            ; 28 states of 4055040 a whole period late, and
                            ; at the 38-row sprite's true 3400 it still puts
                            ; 2 there.  The lever is never C_GUN -- see the
                            ; note on it above -- it is this search, re-run
                            ; whenever any other charge changes.
                            ;
                            ; MEASURED on the booted disc, 60 states, with
                            ; raster_paced benched to n >= 400 iterations
                            ; (see emu_pacefit.Rig.bench -- at the old fixed
                            ; 600 ms window a 35 ms unit gets 17 iterations
                            ; and the reading is +-6%, which is what made
                            ; this look 1227 us UNDER at one state and 3681
                            ; OVER at another): the tightest whole-frame
                            ; margin at 740/22 was +155 us over 15 quads,
                            ; i.e. +10 us a quad on a reading good to +-5.
                            ; That is not a bound, it is a coin toss.  780
                            ; puts +67 us a quad under it, and it is the
                            ; largest value the exhaustive sweep still
                            ; locks at.
C_PMUL      equ 90          ; ...and what a SHORT chunk costs on top: the
                            ; five-bit multiply rq_pmul, plus the end-of-body
                            ; or end-of-quad transition that always lands
                            ; behind one.  MEASURED worst 320 us for the
                            ; pair, against 390.
; C_WSTEP, the 19.27 us the wedge's Bresenham pays per edge step, is 20
; and is spelled out as 16*D + 4*D inside raster.asm -- see rq_wedge.

    if PACE_FRAMES>=1
PACED       equ 1               ; march.asm, kernel.asm and project.asm
    endif                       ; compile their cost hooks only when this
                                ; exists, so the test harnesses in
                                ; engine2/test -- which include those files
                                ; without main3.asm -- still assemble.

; =====================================================================
;  The relocating stub.  This is what the BASIC loader CALLs, and the
;  only part of the file that ever executes at LOAD_ORG.
;
;  IT USED TO LOAD AT #8000 AND THAT WAS A LANDMINE.  #8000 is the back
;  buffer, which nothing has drawn into yet, so it looks free -- but the
;  file is loaded by AMSDOS, and on a 6128 AMSDOS's own work area sits
;  just above HIMEM at #A67B.  `MEMORY &1FFF` in the BASIC loader moves
;  BASIC's HIMEM down; it does NOT move the area AMSDOS reserved at boot.
;  At #8000 this file already ran to #A751, two hundred bytes INTO that
;  area, and got away with it because the first couple of hundred bytes
;  there are scratch.  Adding raster_joint pushed it three bytes further
;  and the machine started dying inside mul8x8u, executing the stale copy
;  of itself still in the back buffer -- and the failure moved when the
;  code moved by THREE BYTES, which is what a corrupted loader looks like
;  and nothing like a rasteriser bug.
;
;  #2000 has room to the same #A67B for thirty-four kilobytes, and the
;  LDIR down to #0040 is a forward copy with the destination BELOW the
;  source, so the overlap is safe.  gentab.py asserts the headroom.
; =====================================================================
LOAD_ORG    equ #7000       ; ...and disc3.bas CALLs this, and the
AMSDOS_LOW  equ #A67B       ; Makefile gives iDSK the same address
    org LOAD_ORG

    di                              ; first instruction: a pending BASIC
    ld   bc,#7F8C                   ; interrupt here would be fatal
    out  (c),c                      ; mode 0, both ROMs out
    ld   sp,#BFF0                   ; scratch stack, inside the back buffer
    ld   hl,body
    ld   de,GAME_ORG
    ld   bc,body_len
    ldir
    jp   start                      ; ...and `start` pages bank 4 in

; NOTHING HERE MAY TOUCH THE RAM CONFIGURATION.  Paging bank 4 in is the
; first thing `start` does, and it has to be, because this stub lives
; INSIDE the window bank 4 is paged into: an `out (c),c` here would swap
; the table data over the very instructions about to execute.  That is
; also why the file cannot be loaded at #4000 or #2000 -- both put the
; stub, or the tail of the body it is copying, under that window.

body        equ $                   ; ... and the body is emitted here,
    org GAME_ORG,$                  ; but assembled for GAME_ORG


; =====================================================================
start
    ld   bc,#7FC4                   ; RAM config 4: bank 4 at #4000.  This
    out  (c),c                      ; is the FIRST thing, because the stub
                                    ; that got us here was sitting in the
                                    ; window and could not do it itself,
                                    ; and set_palette below reads a table
                                    ; out of the bank.
    ld   sp,STACKTOP
    call set_palette

    ld   hl,SCR_BACK                ; both buffers black first: hud_static
    call clear_16k                  ; paints furniture, not background, and
    ld   hl,SCR_FRONT               ; leaves the gaps between its rectangles
    call clear_16k                  ; as whatever was there

    ld   hl,MAZEDATA                ; the kernel's map lives at SOLID and
    ld   de,SOLID                   ; the doors move it about, so the
    ld   bc,256                     ; pristine copy stays in the code
    ldir

    call march_init                 ; the one full MARK wipe: march_setup
                                    ; only sweeps four bytes a frame
    call frame_init                 ; bank 4 is paged in; bg and raster
    call game_init                  ; copy out what they need.  game_init
                                    ; sets plr_a, which the needle needs.

    call hud_init                   ; the HUD's furniture goes in ONCE per
    ld   a,#C0                      ; buffer -- 101.5 ms each, startup only
    call hud_setbuf                 ; -- and then only the compass needle
    call hud_static                 ; is repainted, and only when the
    call hud_update                 ; heading actually changes.
    ld   a,#80
    call hud_setbuf
    call hud_static
    call hud_update

    ld   a,#30                      ; display the front buffer
    call crtc_r12

; ---------------------------------------------------------------------
main_loop
    ld   hl,(frame_ctr)             ; game frames completed -- the only
    inc  hl                         ; way to MEASURE the real cadence
    ld   (frame_ctr),hl
    ld   a,(backbuf)
    call frame_setbuf
    ld   a,(backbuf)                ; the HUD paints into the same buffer
    call hud_setbuf
    if GUN
    ld   a,(backbuf)                ; ...and so does the weapon
    call gun_setbuf
    endif
    if PACE_FRAMES>=1
    ; ---- the cost accumulator.  (cost_acc) is NOT cleared here: it
    ; still holds the flip and the game_step that ran after the last
    ; wait, and C_TAIL is what those two cost.  The budget, though, is
    ; fresh: five waits, spent by cost_room/cost_unit as the work asks
    ; for them and by pace_drain at the end.
    ld   hl,(cost_acc)
    ld   de,C_TAIL
    add  hl,de
    ld   (cost_acc),hl
    ld   a,PACE_FRAMES
    ld   (pace_left),a

    ld   bc,C_BG
    call cost_unit
    call bg_fill
    ld   bc,C_MSETUP
    call cost_unit
    call march                      ; charges C_CELL per popped cell
    call project_all                ; charges per candidate face
    call raster_paced               ; charges per quad
    ld   bc,C_HUD
    call cost_unit
    call hud_update
    if GUN
    call gun_paced                  ; the weapon goes on TOP of the finished
    endif                           ; view; bg_fill erases it next frame
    call pace_drain                 ; spend whatever the view did not
    else
    call frame_draw
    call hud_update
    if GUN
    call gun_step
    call gun_draw
    endif
    call wait_vsync
    endif
    call flip
    call game_step
    or   a
    jp   z,main_loop
    ; fall through to quit


; ---------------------------------------------------------------------
;  quit -- ESC.  Put the machine back the way the firmware likes it and
;  restart it; that is the cheap clean exit, and it lands on "Ready".
;
;  THE TAIL HAS TO RUN FROM #4000.  This program lives at #0040, and the
;  instruction that switches the lower ROM back in makes #0000-#3FFF read
;  as ROM -- so the very next instruction fetched would come out of the
;  OS ROM at whatever address `quit` happens to sit at, not out of this
;  code.  That is a runaway, and it is what the first version of this
;  routine did (it reached BASIC about one time in three, depending on
;  what the ROM bytes underneath it happened to decode to).  With both
;  ROMs in, #4000-#7FFF is the only window that is still plain RAM, so
;  the five instructions after the switch are copied there and jumped to.
; ---------------------------------------------------------------------
quit
    ld   a,#30                      ; show the front buffer again
    call crtc_r12
    ld   bc,#7FC0                   ; RAM config 0: bank 4 goes away, and
    out  (c),c                      ; #4000 becomes ordinary RAM
    ld   hl,qtail
    ld   de,#4000
    ld   bc,qtail_end-qtail
    ldir
    jp   #4000

qtail
    ld   bc,#7F81                   ; mode 1, both ROMs back in.  From
    out  (c),c                      ; here on #0000-#3FFF is the OS ROM.
    ld   sp,#C000
    jp   #0000                      ; the firmware's cold start
qtail_end


; ---------------------------------------------------------------------
;  flip -- show the buffer just drawn, and make the other one the back.
;  CRTC R12 bits 4-5 pick the base: #30 = &C000, #20 = &8000.
; ---------------------------------------------------------------------
flip
    ld   a,(backbuf)
    cp   #80
    ld   a,#20
    jr   z,fl_do
    ld   a,#30
fl_do
    call crtc_r12
    ld   a,(backbuf)
    xor  #40                        ; #80 <-> #C0
    ld   (backbuf),a
    ret

crtc_r12                            ; A = the R12 value
    ld   bc,#BC0C
    out  (c),c
    inc  b
    out  (c),a
    ld   bc,#BC0D
    out  (c),c
    inc  b
    xor  a
    out  (c),a
    ret

wait_vsync
    ld   b,#F5
wv_hi
    in   a,(c)
    rra
    jr   c,wv_hi                    ; let any pulse in progress finish
wv_lo
    in   a,(c)
    rra
    jr   nc,wv_lo                   ; then catch the next rising edge
    ret




; ---------------------------------------------------------------------
;  set_palette -- the 16 gate-array bytes PALETTE holds in bank 4, in
;  pen order (engine2/tools/pal.py builds them).
; ---------------------------------------------------------------------
set_palette
    ld   hl,PALETTE
    ld   c,0
sp_loop
    ld   b,#7F
    out  (c),c                      ; pen number doubles as the selector
    ld   a,(hl)
    out  (c),a
    inc  hl
    inc  c
    ld   a,c
    cp   16
    jr   nz,sp_loop
    ld   bc,#7F10                   ; border, in the pen-0 colour
    out  (c),c
    ld   a,(PALETTE)
    out  (c),a
    ret


; ---------------------------------------------------------------------
;  clear_16k -- HL = #8000 or #C000.
; ---------------------------------------------------------------------
clear_16k
    ld   bc,#4000
cl_l
    ld   (hl),0
    inc  hl
    dec  bc
    ld   a,b
    or   c
    jr   nz,cl_l
    ret


; --------------------------------------------------------- variables ---
backbuf     db #80                  ; the buffer frame_draw paints next
frame_ctr   dw 0


; ------------------------------------------------------------ engine ---
    include "frame.asm"
    include "kernel.asm"
    include "march.asm"
    include "project.asm"
    include "raster.asm"
    if VPCOL
    include "rastcol.asm"
    endif
    include "bg.asm"
    include "game.asm"
    include "hud2.asm"
    if GUN
    include "gun.asm"
    endif
    include "gen_slopes.inc"
    include "gen_maze.inc"

    if PACE_FRAMES>=1
; =====================================================================
;  THE COST ACCUMULATOR
;
;  Two primitives and a drain.  (cost_acc) is the estimated cost, in CPC
;  microseconds, of everything done since the last vsync wait;
;  (pace_left) is how many waits this frame may still spend.
;
;    cost_unit   BC = both the room the work needs and what it costs, for
;                work whose cost is known BEFORE it runs: bg_fill,
;                march_setup, one flood cell, one quad, hud_update.
;                ROOM THEN CHARGE, against COST_THI = 19456.
;    cost_face   the projector's faces, whose cost is not known until the
;                face has run: it reads (pf_ok) and (pf_nclip) and
;                CHARGES THEN TESTS, against the lower FACE_THI = 15360.
;
;  Two thresholds, because the two rules bound the interval differently.
;  A roomed unit cannot take the interval past COST_THI at all.  A charged
;  unit can take it up to FACE_THI + C_FACE_MAX = 19530.  Both are under
;  one 19968 us period, which is the only thing that matters -- and since
;  every C_* is the measured cost ROUNDED UP, so is the real time.
;
;  WHY NOT ROOM THE FACES TOO, which is what this used to do.  Because
;  rooming reserves the worst case and then throws the difference away:
;  C_FACE_MAX is 4170 us and the median face charges 480, so every
;  face-driven yield left up to 4170 us of a 19456 us interval unused.
;  MEASURED, tracing the greedy rule over the worst reachable states, the
;  wasted tails were 426 / 3946 / 4156 / 1640 / 5144 us -- 15 ms of a
;  97 ms budget, which is a whole vsync period and a half.  Charging
;  afterwards and testing against a threshold that is one face lower
;  wastes nothing and bounds the interval just as hard.
;
;  They all preserve every register, because they are called from the
;  middle of the march (where SP is the flood stack and BC holds the cell
;  being popped) and from the middle of the projector's bucket walk.
; =====================================================================

; --- BC = both the room the work needs and what it costs --------------
cost_unit
    push af
    push hl
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
    ld   (cost_acc),bc              ; this unit opens the new interval
    call pace_wait
    jr   cu_ret

; --- BC = what work that has ALREADY RUN cost.  No test, no wait ------
;  For work outside the paced part of the frame: game.asm's door_act runs
;  after pace_drain, where (pace_left) is zero and a wait would buy a
;  seventh period rather than fit inside six.  Leaving the microseconds
;  in (cost_acc) hands them to the next frame's first interval, which is
;  the same thing C_TAIL does for the flip and game_step.
cost_add
    push af
    push hl
    ld   hl,(cost_acc)
    add  hl,bc
    ld   (cost_acc),hl
    pop  hl
    pop  af
    ret

; --- one wait.  ALWAYS a wait, budget or no budget --------------------
;  THE FRAME MUST NEVER FREE-RUN.  The version this replaces did
;
;      ld a,(pace_left) / or a / ret z
;
;  -- i.e. when the budget was gone it RETURNED WITHOUT WAITING, and the
;  rest of that frame then ran unpaced.  The flip therefore landed at an
;  arbitrary offset from the last vsync edge instead of a fixed one, and
;  since the offset differed from frame to frame the PERIOD stopped being
;  a whole number of vsyncs: MEASURED on the disc this file used to build,
;  (0160,0DE0) heading 69 sat at a rock-steady 109.2-110.5 ms, which is
;  5.47 periods.  A frame that occasionally takes six periods is a bug; a
;  frame that takes 5.47 is a worse one, because the stutter is then
;  aperiodic and the walking speed wobbles with it.
;
;  So the exhausted case WAITS anyway and simply does not decrement.  The
;  budget then bounds the period from below and not from above: the frame
;  takes PACE_FRAMES periods when the work fits and PACE_FRAMES+1 when it
;  does not, but it is always a WHOLE number of periods, because every
;  interval between two waits ends on a vsync edge and the tail from the
;  last wait to the flip is the same three instructions every time.
pace_wait
    ld   a,(pace_left)
    or   a
    jr   z,pw_go                    ; budget gone: wait anyway
    dec  a
    ld   (pace_left),a
pw_go
    jp   wait_vsync

; --- spend the rest of the budget, at the end of the frame ------------
;  AND AT LEAST ONE WAIT, ALWAYS.  This is the other half of the same
;  argument: the flip must follow a wait_vsync at a fixed distance, so
;  the frame has to END on a vsync edge even when the work already spent
;  everything.  `ret z` here was the second free-run.
pace_drain
    ld   a,(pace_left)
    or   a
    jr   nz,pd_have
    inc  a                          ; nothing left -- still end on an edge
pd_have
    ld   b,a
    xor  a
    ld   (pace_left),a
    ld   h,a
    ld   l,a
    ld   (cost_acc),hl              ; the waits below end this interval
pd_l
    push bc
    call wait_vsync
    pop  bc
    djnz pd_l
    ret


; ---------------------------------------------------------------------
;  cost_face -- charge the candidate face proj_face has just finished,
;  then give the NEXT one room.  One call does both, which is 41 us a
;  face cheaper than two.
;
;  (pf_ok) says whether the face became a quad and (pf_nclip) how many
;  clip lerps it paid for, and those two are the whole of the projector's
;  cost spread: MEASURED on the built disc, 1315 us for a face that
;  survives, 453 for one that does not, 874 for each lerp, R^2 0.9991
;  over 40 states.  kernel.asm takes the room for the FIRST face itself.
; ---------------------------------------------------------------------
; --- the gate: get the interval under FACE_THI, charging nothing ------
;  kernel.asm calls this once, on the way into the bucket walk.  It is
;  the entry condition for the charge-then-test rule below; see the note
;  at project_all for the frame that proved it is needed.
cost_gate
    push af
    push hl
    ld   hl,(cost_acc)
    ld   a,h
    cp   FACE_THI
    jr   c,cg_ret
    ld   hl,0
    ld   (cost_acc),hl
    call pace_wait
cg_ret
    pop  hl
    pop  af
    ret

cost_face
    push af
    push bc
    push hl
    ld   hl,C_REJ
    ld   a,(pf_ok)
    or   a
    jr   z,cf_n
    ld   hl,C_FACE
cf_n
    ld   a,(pf_nclip)
    or   a
    jr   z,cf_done
    ld   bc,C_CLIP
cf_l
    add  hl,bc
    dec  a
    jr   nz,cf_l
cf_done
    ld   bc,(cost_acc)
    add  hl,bc
    ld   (cost_acc),hl
    ld   a,h
    cp   FACE_THI               ; CHARGE THEN TEST -- see the note above
    jr   c,cf_ret
    ld   hl,0
    ld   (cost_acc),hl
    call pace_wait
cf_ret
    pop  hl
    pop  bc
    pop  af
    ret


; ---------------------------------------------------------------------
;  raster_paced -- the quad list, paced.
;
;  IT IS raster_frame NOW.  This used to be a copy of that loop with a
;  `call pace_quad` in front of every quad: pace_quad re-read the record,
;  predicted the whole quad's cost and roomed it, for 141 us a quad.  The
;  accumulator's hooks live INSIDE raster_quad since it started yielding
;  mid-quad (raster.asm, rq_bchunk / rq_wchunk), and a quad that charges
;  itself needs nothing wrapped round it -- so the two loops became the
;  same loop, and the 141 us a quad went with the duplication.
;
;  The label stays because it is what main_loop and the harnesses call:
;  engine2/tools/emu_pacefit.py benches RASTER_PACED by name.
; ---------------------------------------------------------------------
raster_paced
    if VPCOL
    jp   raster_colframe        ; every BAND charges its own scanlines
    else
    if RQ_PACED
    jp   raster_frame               ; every quad charges its own scanlines
    else
    ld   a,(fg_nquad)
    or   a
    ret  z
    ld   b,a
    ld   hl,QUADS
rp_l
    push bc
    push hl
    call pace_quad                  ; HL = record; costs it AND charges it
    pop  hl
    push hl
    call raster_quad                ; HL -> the next record
    ex   (sp),hl                    ; stack = the next, HL = this record
    if COURSES
; THE JOINTS ARE A UNIT OF THEIR OWN.  Folding them into pace_quad would
; add them to the largest atomic unit in the frame, which is what sets the
; period; charged separately, the yield may fall between a face and its
; joints, and nothing is flipped there.
;
; AND THE CHARGE IS NOW GATED THE SAME WAY raster_joint GATES ITSELF.  It
; was not, and that single omission is why the joints looked twice as
; expensive as they are.  raster_joint early-outs on kind != 0 or on
; k > JOINT_KMAX, so most quads pay nothing and do nothing -- but every
; quad was still being billed C_JOINT.  A seventeen-quad frame charged
; 17 x 7400 = 125,800 us for at most seven faces of real work, and the
; accumulator then bought vsync periods to cover microseconds nobody was
; ever going to spend.  The 239.8 ms this was measured at is therefore NOT
; what the joints cost; it is what an ungated charge costs.
;
; Reading the two bytes is ~12 us a quad and HL is already on the record.
    push hl
    ld   de,6
    add  hl,de
    ld   a,(hl)                     ; +6 kind -- a door is not masonry
    or   a
    jr   nz,rp_nojoint
    inc  hl
    ld   a,(hl)                     ; +7 k -- and neither is a far face
    cp   JOINT_KMAX+1
    jr   nc,rp_nojoint
    pop  hl
    push hl                         ; HL back to the head of the record
    call pace_joint                 ; BC = what THIS face's joints cost
    call cost_unit
rp_nojoint
    pop  hl
    call raster_joint
    endif
    pop  hl
    pop  bc
    djnz rp_l
    ret
    endif
    endif


    if GUN
; ---------------------------------------------------------------------
;  gun_paced -- the weapon, charged.  One ROOM-THEN-CHARGE unit of C_GUN
;  in front of gun_step + gun_draw, which is all the accumulator needed
;  to hear about the sprite.
;
;  WHY IT IS A ROUTINE AND NOT THREE INLINE LINES IN main_loop.  Because
;  then it has an address, and engine2/tools/emu_pacefit.py can bench THE
;  CHARGED BLOCK -- hook, step and blit together, the way the frame runs
;  it -- and check C_GUN clears the number it gets.  Every other C_* in
;  this file is one-sided against a measurement of the shipped code; this
;  one is too, and it is 8 us of call and ret to keep it that way.
;
;  ROOM THEN CHARGE IS THE WHOLE FIX.  cost_unit yields first and runs
;  the weapon second whenever the interval could not hold 3250 us more,
;  so the blit always starts inside a fresh interval with 16 ms of it
;  spare and can never be the thing that crosses a vsync edge.  Charging
;  it AFTER the fact -- the cost_face rule -- would not do: the view's
;  last unit and the weapon would already have shared an interval by the
;  time anyone noticed.
;
;  gun_step is charged at its WALKING cost even when the player is
;  standing (163.1 us against 42.0), because an estimate here is only
;  allowed to be wrong upwards, and 121 us is not worth a branch.
; ---------------------------------------------------------------------
gun_paced
    if GUN_CHARGED
    ld   bc,C_GUN
    call cost_unit
    endif
    call gun_step
    jp   gun_draw
    endif


    if RQ_PACED == 0
; ---------------------------------------------------------------------
    if COURSES
; ---------------------------------------------------------------------
;  pace_joint -- HL = a quad record -> BC = what raster_joint will cost
;  on it, in microseconds.  Clobbers AF DE HL.
;
;  THIS WAS A FLAT CONSTANT AND THAT IS WHY THE DISC DID NOT LOCK.  A
;  joint's cost is dominated by its ROW COUNT, and that varies by more
;  than thirty to one across the faces one frame produces: two mirrored
;  rows on a wall seen square on, seventy on a steeply raked one.  One
;  constant has to cover the worst of them, so C_JOINT = 7400 billed the
;  worst state's six jointed faces 44,400 us for about ten milliseconds
;  of real work, and the accumulator bought vsync periods to cover
;  microseconds nobody was ever going to spend.  Replayed over all
;  4,055,040 reachable states:
;
;      flat 7400      worst charged frame 147,894 us   407 states need a
;                                                      NINTH period
;      per row pair   worst charged frame 112,090 us   0 states need an
;                                                      EIGHTH
;
;  Not one pixel changes.  5.56 fps with excursions becomes 7.15 locked.
;
;      us = 1150 + 192*pairs + 12*D
;
;  pairs = j1e - j0 is the mirrored row range raster_joint's own loop
;  runs over and D = |bhi - blo| the face width -- the two numbers that
;  bound the loop.  192 = 128 + 64, two shifts and an add,
;  never a multiply, and j0 / j1 come out of the SAME DIV3 table
;  raster_joint indexes.  engine2/tools/pacemodel.py:joint_cost is the
;  same arithmetic and pacescan.py replays it.
;
;  IT STAYS ONE-SIDED.  The row range is taken BEFORE raster_joint's own
;  "face under a byte wide" and "joint past the horizon" drop-outs, so a
;  face can be charged and draw nothing -- never the reverse, which is
;  the direction that would break the frame lock.
; ---------------------------------------------------------------------
pace_joint
    ld   a,(hl)                     ; +0 blo
    inc  hl
    ld   e,(hl)                     ; +1 bhi
    sub  e
    jr   nc,pj_dpos
    neg
pj_dpos
    ld   (pj_d),a                   ; D = |bhi - blo|
    inc  hl
    ld   e,(hl)                     ; +2 hlo low
    inc  hl
    ld   d,(hl)                     ; +3 hlo high
    inc  hl
    push hl                         ; -> +4
    ex   de,hl
    call pj_row                     ; A = j0
    pop  hl
    ld   (pj_j0),a
    ld   e,(hl)                     ; +4 hhi low
    inc  hl
    ld   d,(hl)                     ; +5 hhi high
    ex   de,hl
    call pj_row                     ; A = j1
    cp   RQ_RC
    jr   nc,pj_j1c
    inc  a                          ; ...plus the thickening row
pj_j1c
    ld   hl,pj_j0
    sub  (hl)                       ; A = pairs
    jr   nc,pj_pok
    xor  a
pj_pok
    ld   l,a
    ld   h,0
    add  hl,hl
    add  hl,hl
    add  hl,hl
    add  hl,hl
    add  hl,hl
    add  hl,hl                      ; HL = 64*pairs
    ld   d,h
    ld   e,l                        ; DE = 64*pairs
    add  hl,hl                      ; HL = 128*pairs
    add  hl,de                      ; 192*pairs = 128 + 64
    ld   a,(pj_d)
    ld   e,a
    ld   d,0
    add  hl,de
    add  hl,de
    add  hl,de
    add  hl,de
    add  hl,de
    add  hl,de
    add  hl,de
    add  hl,de
    add  hl,de
    add  hl,de
    add  hl,de
    add  hl,de                      ; + 12*D  (D <= VP_BW, so no multiply)
    ld   de,1150
    add  hl,de
    ld   b,h
    ld   c,l
    ret

; HL = a Q12.4 half height -> A = the joint row it lands on, clamped to
; the horizon.  This is raster_joint's own j0 derivation, verbatim.
pj_row
    ld   de,J_OFF
    or   a
    sbc  hl,de
    ld   a,RQ_RC
    ret  nc                         ; at or past the horizon
    add  hl,de
    call rq_sh4                     ; A = h>>4, <= 3*RQ_RC+2
    ld   h,DIV3/256
    ld   l,a
    ld   a,(hl)
    ret

pj_d        db 0
pj_j0       db 0
    endif


; ---------------------------------------------------------------------
;  pace_quad -- HL = quad record -> costs it, charges it, and takes the
;  wait if it does not fit.  Falls into cost_unit.  Clobbers AF BC DE HL.
;
;  THE WHOLE QUAD, CHARGED BEFORE A PIXEL OF IT IS DRAWN.  That is what
;  makes one quad the smallest thing between two possible yields -- up to
;  12486 us MEASURED, 63% of a vsync period -- and raster.asm's RQ_SPLIT
;  is the alternative, with the measurement that says why this one is
;  still the one that ships.
;
;  IT WALKS THE RECORD WITH HL, NOT IX, and it keeps jlo / jhi / the
;  multiplier in D / C / E instead of in three memory temporaries.
;  MEASURED before 203 us a quad, after 141 -- and 178.9 on the booted
;  disc with cost_unit's own yield path in it (emu_atomic.py).
;
;  MEASURED on the built disc, 40 states / 262 quads, least squares:
;
;      us = 863*n + 43.23*jlo + 133.49*wl2 + 1.9771*bw*(jlo + jhi)
;      R^2 0.9988, RMS residual 299 us
;
;  where bw = |bhi - blo| in whole bytes, jlo = the last constant-width
;  row and wl2 = jhi - jlo, both in PAIRS of scanlines.  Round those up
;  to 920, 46, 138 and 2, put s = jlo + jhi = 2*jlo + wl2, and
;
;      46*jlo + 138*wl2  ==  23*s + 115*wl2
;
;  exactly, so the estimate collapses to 920 + s*(23 + 2*bw) + 115*wl2 --
;  one 8x8 multiply, both factors under 112.  115 is rounded up to 128 so
;  the wedge term is a SHIFT rather than a second multiply.
; ---------------------------------------------------------------------
pace_quad
    ld   a,(hl)                     ; +0 blo
    inc  hl
    ld   d,a
    ld   a,(hl)                     ; +1 bhi
    inc  hl
    sub  d
    jr   nc,pq_bw1
    neg
pq_bw1
    add  a,a                        ; 2*bw
    add  a,C_QS                     ; + 22;  <= 2*VP_BW + 22, no carry
    ld   e,a                        ; E = the multiplier

    ld   c,(hl)                     ; +2 hlo low, Q12.4
    inc  hl
    ld   a,(hl)                     ; +3 hlo high
    inc  hl
    cp   CYH/16                     ; at or past the horizon?
    jr   nc,pq_locl
    add  a,a
    add  a,a
    add  a,a
    add  a,a                        ; the high byte's contribution, x16
    ld   b,a
    ld   a,c
    rrca
    rrca
    rrca
    rrca
    and  #0F
    add  a,b
    jr   pq_look
pq_locl
    ld   a,CYH
pq_look
    ld   d,a                        ; D = jlo

    ld   c,(hl)                     ; +4 hhi low
    inc  hl
    ld   a,(hl)                     ; +5 hhi high
    cp   CYH/16
    jr   nc,pq_hicl
    add  a,a
    add  a,a
    add  a,a
    add  a,a
    ld   b,a
    ld   a,c
    rrca
    rrca
    rrca
    rrca
    and  #0F
    add  a,b
    jr   pq_hiok
pq_hicl
    ld   a,CYH
pq_hiok
    ld   c,a                        ; C = jhi
    sub  d                          ; A = wl2 = jhi - jlo
    ld   h,a
    ld   l,0                        ; HL = 256*wl2
    srl  h
    rr   l                          ; HL = 128*wl2
    push hl
    ld   a,c
    add  a,d                        ; A = s = jlo + jhi <= 2*CYH
    ld   c,e                        ; C = 22 + 2*bw
    call mul8x8u                    ; HL = s * (22 + 2*bw)
    pop  de
    add  hl,de
    ld   de,C_QUAD
    add  hl,de
    ld   b,h
    ld   c,l
    jp   cost_unit                  ; ...and charge it
    endif

cost_acc    dw 0
pace_left   db 0
    endif




game_end
body_len    equ game_end-start

; The LOADED file -- stub plus body -- must land clear of AMSDOS's work
; area.  This is the check that would have caught the #8000 landmine on
; the day it was laid; see the note on the stub.
    assert body + body_len <= AMSDOS_LOW

    assert game_end <= BUCK0        ; the body must fit under the march's
                                    ; working RAM, which starts at #2700
