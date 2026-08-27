; =====================================================================
;  engine2/src/vpcfg.inc -- THE viewport configuration.  ONE file.
;
;  This is the single source of truth for the window the engine draws
;  into and for the projection that fills it.  It is
;
;    * INCLUDED by the Z80 (every harness gets it through the generated
;      tab_equ.inc, which starts with `include "vpcfg.inc"`), and
;    * PARSED by engine2/tools/gentab.py, which derives FOCAL_H, KHALF
;      and every zv-indexed table from exactly these numbers.
;
;  So there is no second copy to forget.  To move to another viewport,
;  edit the nine constants below, re-run
;
;      python3 engine2/tools/gentab.py
;
;  and rebuild: HTAB, PROJ, PXT, PROJN, HTN and PUSHENT all change, and
;  the asm picks the new CX_Q4 / CY_Q4 / VP_PW / MAXPUSH up from here.
;
;  VP_H IS NOT A FREE PARAMETER.  bg.asm counts CHARACTER ROWS and splits
;  each half of the viewport in two, so CYH must be a multiple of 16 and
;  VP_H a multiple of 32; raster.asm's VPLINE is one page of row*2, so
;  VP_H <= 128.  The height ladder is 128 / 96 / 64 and nothing between
;  -- 88, for instance, does not assemble.  Trade WIDTH, which is free
;  (any even VP_BW, since MAXPUSH = VP_BW/2).
;
;  amaze3 (this build):   44 x 96 bytes = 88 x 96 pixels at (18,0)
;                         HUD on scanlines 96..199, MAXPUSH 22
;  the 48x128 variant:    VP_BX 16 / VP_BW 48 / VP_H 128 / CXH 48
;                         CYH 64 / FOCAL_V 128 / MAXPUSH 24
;
;  ==================================================================
;  44 IS THE CURRENT WIDTH, AND THE PACING PAID FOR IT.  It was 40, and
;  the reason was never the DRAWING -- 44 always drew fine -- it was that
;  the frame period has to be a whole number of vsyncs FOR EVERY VIEW,
;  and the cost accumulator has to pack the worst reachable frame into
;  the budget without asking for one more vsync wait than it has.
;
;  WHAT CHANGED IS THAT THE QUESTION IS NOW ANSWERED EXHAUSTIVELY.  The
;  old answer came from sampling: a few thousand states replayed offline,
;  a few hundred measured on the disc.  A failure that lives on three
;  states in a million survives that easily, and twice in this project's
;  history it did.  engine2/tools/pacescan.py now replays the rule for
;  ALL 4055040 states a player can stand in -- 56320 positions on the
;  24/256 movement lattice that pass game.asm's OWN collision box, times
;  72 headings -- in about a minute on sixteen cores.  At 44 x 96, with
;  PACE_FRAMES 6:
;
;      states needing a 6th wait (= a 7th period):  0 of 4055040
;      worst charged frame  104024 us of a 116736 us budget
;
;  and on the booted disc the sweep is one bar at 119.81 ms.
;
;  THAT IS THE SPAN RENDERER'S ANSWER AND THE DISC DOES NOT SHIP IT.
;  VPCOL is 1 below, so the build is the column renderer at 40x96 with
;  PACE_FRAMES 9 -- and that configuration does NOT read zero.  Measured
;  the same way, exhaustively, with the HUD's charges billed where
;  main3.asm actually makes them:
;
;      doors shut     69381 of 8128512  = 0.854%  need a 10th period
;      doors open    314225 of 8792064  = 3.574%
;      doors moving 2858875 of 8128512  = 35.171%
;      worst charged frames  169232 / 190152 / 259107 us of 175104
;
;  The zero above is real, and it is about a build nobody runs.  Left
;  here because it is the reference the width work was done against --
;  but do not read it as a statement about the shipping disc.  See the
;  PACE_FRAMES block in main3.asm for that, and for the cost_add gap
;  that most of the 0.854% comes out of.
;
;  TWO CONSTANTS HAD TO MOVE WITH THE WIDTH, and both were found by
;  MEASURING at 44 rather than assuming 40's numbers carried over:
;
;    C_BG    bg_fill is 8501.3 us at 40x96 and 9215.8 at 44x96 -- 178.6
;            us a byte for a 96-line fill.  main3.asm charged 8600 at
;            both widths for a while, i.e. 616 us UNDER the truth, and
;            nothing spilled only because the march and the projector
;            over-charged by more than bg_fill under-charged.  It is
;            9320 now, and pacemodel.py reads it out of main3.asm
;            instead of keeping a second copy of it.
;    C_QUAD  pace_quad charges a scanline C_QS + 2*bw where the machine
;            really pays 18.78 + 1.976*bw, so the per-scanline margin is
;            about 4 us at ANY width while the fixed C_QUAD is what
;            carries the quad -- widen the viewport and the byte term
;            grows into the margin.  At 740 the tightest whole-frame
;            margin measured at 44x96 was +155 us over 15 quads.  It is
;            820, which pacescan.py's sweep says is the largest charge
;            with zero over-budget states.
;
;  40 x 96 is still a good configuration and needs only VP_BX 20 /
;  VP_BW 40 / CXH 40 / MAXPUSH 20 / C_BG 8600.  38 was measured too and
;  buys about 1 ms of a 90 ms frame -- the march and the projector do not
;  scale with width at all and they are 40 ms of that frame -- so it does
;  not change the answer and costs another 5% of the picture.  36 does
;  not build: gentab.py's PXT assert fires, so 38 is the floor whatever
;  else is true.
;
;  VP_BX goes with VP_BW so the window stays centred on the 80-byte line:
;  (80 - 44)/2 = 18.  genhud.py re-derives the whole HUD from these
;  numbers and emu_hud.py verifies every furniture byte against its
;  model.
;  ==================================================================
;
;  (history) 44 WAS TAKEN, AND HERE IS THE MEASUREMENT THAT PAID FOR IT.
;  This file
;  sat at 40 for as long as movement had no collision.  It does now
;  (engine2/src/game.asm, PRAD = 64/256 = 0.25 cells, box against SOLID
;  on both axes), and the closest approach to a wall plane over 36624
;  MEASURED player positions is 0.254 cells -- so the states that made 44
;  miss are unreachable.  Re-run at 44 x 96 after the switch:
;
;      120 whole frames bit-exact against the Python models
;      256536 reachable states (8x8 sub-cell grid, radius 0.25) counted,
;      120 measured uniformly + the fit's worst 80 measured:
;          median 36.75  p90 53.81  WORST MEASURED 77.21 ms
;          at (0770,06F0) heading 55, 16 quads
;      budget 80.00 ms -> FITS with 2.79 ms (3.5%) to spare, and the fit
;      puts 0.000% of all 256536 states over budget
;
;    reproduce with
;      python3 engine2/tools/gentab.py
;      python3 engine2/tools/emu_frame.py verify 120
;      python3 engine2/tools/emu_frame.py sweep 120 80 8 20260819 64
;    and the collision rule itself with
;      python3 engine2/tools/emu_game.py all
;
;  NOTE the collision test's box is STRICTER than the sweep's circle: the
;  sweep rejects a diagonal cell only when ex^2+ey^2 < r^2, the game
;  rejects it whenever both ex < r and ey < r.  The reachable set the
;  game can produce is therefore a subset of the one measured above.
;
;  ------------------------------------------------------------------
;  (history) WHY 40 WAS CHOSEN FIRST.  Complete frames were
;  MEASURED end to end (engine2/tools/emu_frame.py sweep) over the whole
;  reachable state space, 109 floor cells x 16 sub-cell offsets x 72
;  headings = 125568 states, with the worst 80 of them measured on the
;  hardware model.  The worst frame in the maze is the same state at
;  every width -- (0120,0DE0) heading 68, 17 quads out of 22 candidate
;  faces -- and it costs
;
;      44 x 96   median 36.0 ms   WORST 80.96 ms   OVER by 0.96
;      42 x 96   median 35.5 ms   WORST 80.31 ms   OVER by 0.31
;      40 x 96   median 34.2 ms   WORST 77.81 ms   FITS, 2.19 ms spare
;      38 x 96   median 33.8 ms   WORST 76.61 ms   FITS, 3.39 ms spare
;
;  against a budget of 80.00 ms (4 vsync frames, 12.5 fps), with movement
;  UNCONSTRAINED.  On that state space 44 is a 1.2% miss and 40 is the
;  largest width that fits.
;
;  44 BECAME LEGAL THE MOMENT MOVEMENT HAD COLLISION.  That worst
;  state stands 32/256 = 0.125 cells from a wall plane, which is exactly
;  project.asm's ZNEAR -- at or inside it the wall face is REJECTED and
;  the player would see straight through the wall, so the movement code
;  must keep further out than that whatever else it does.  Re-swept at
;  44 x 96 with a 0.25-cell collision radius and a finer 8x8 sub-cell
;  grid (256536 reachable states):
;
;      44 x 96, collision radius 0.25 cells  WORST 77.21 ms  FITS, 2.79
;
;  which is what this file is now set to, and what the re-run at the top
;  of this comment confirms on the real collision rule.
;
;  RULES the generator asserts (gentab.py:load_vpcfg):
;      CXH     = VP_BW           one mode-0 pixel is one half-byte unit,
;                                so the half-width in half-byte units is
;                                VP_BW*2/2 = VP_BW
;      CYH     = VP_H/2          the horizon; there is no pitch, so the
;                                horizon is a FIXED scanline
;      FOCAL_V = VP_H            a wall one cell away exactly fills the
;                                viewport height
;      MAXPUSH = VP_BW/2         one PUSH DE writes two bytes
;      VP_BX + VP_BW <= 80,  VP_Y + VP_H <= 200
;  and FOCAL_H = CXH / tan(FOV/2) is DERIVED, not stored: it is a float
;  (76.210 here), so only its Q8 form reaches the asm, as FOCAL_H_Q8 in
;  the generated tab_equ.inc.
; =====================================================================

VP_BX        equ 18                         ; viewport left edge,  BYTES from line start
VP_BW        equ 44                         ; viewport width,      BYTES (2 pixels each)
VP_Y         equ 0              ; viewport top scanline
VP_H         equ 96                         ; viewport height,     scanlines
CXH          equ 44                         ; horizon centre x, HALF-BYTE units
CYH          equ 48                         ; horizon y, scanlines
FOCAL_V      equ 96                         ; vertical focal length, scanlines
MAXPUSH      equ 22                         ; length of the unrolled PUSH DE block
FOV_X10      equ 600            ; horizontal field of view, tenths of a degree

; ---- derived, integer, computed identically by rasm and by gentab.py ----
VP_PW        equ VP_BW*2        ; viewport width in mode-0 pixels
CX_Q4        equ CXH*16         ; horizon centre x, Q12.4 half-byte units
CY_Q4        equ CYH*16         ; horizon y,        Q12.4 scanlines
XMAX_Q4      equ VP_PW*16       ; right edge of the viewport, Q12.4
VP_BOFF      equ (VP_Y&7)*#800+(VP_Y/8)*80+VP_BX
                                ; buffer base -> first byte of scanline VP_Y

; --------------------------------------------------------------------
;  COURSES -- draw two mortar joints across each wall face, so the walls
;  read as three courses of stone.  0 = flat walls.
;
;  IT IS 1 AND IT SHIPS.  What follows is the history of getting there,
;  and it is kept because two of its conclusions were WRONG and the wrong
;  ones are the instructive part.
;
;  THE COST WAS NEVER THE DRAWING.  It was the CHARGE.  A flat
;  C_JOINT billed every jointed face the worst face's price -- see
;  main3.asm:pace_joint, which replaced it with 480 + 160*pairs + 8*D and
;  took the worst charged frame from 147,894 us to 112,090 without moving
;  a pixel.  Exhaustive over all 4,055,040 reachable states: flat left 407
;  of them needing a ninth period, per-pair leaves none needing an eighth.
;  PACE_FRAMES 7, 139.78 ms, 7.15 fps, locked.
;
;  AND THE FOLD IS DEAD.  The paragraph below used to claim that moving
;  the joint into raster_quad's row loop was "a ~7x cut on the dominant
;  term".  MEASURED on the booted 6128: the shipped pair costs 153.987 us
;  and the best possible fold 148.012 -- a 4% saving, because 72.004 us of
;  the pair is span arithmetic that no amount of code motion removes.  The
;  7x figure came from assuming the per-row setup was pure address
;  rebuild, and it is not.  Do not attempt the fold.
;
;  ------------------------------------------------------------------
;  (history) THE MEASUREMENT THAT MADE IT LOOK UNAFFORDABLE.
;  raster.asm:raster_joint works, and it is byte-exact against
;  engine2/tools/rastermodel.py; it is the PRICE that is wrong, and the
;  price is not where it looks.  MEASURED on the booted disc, benching
;  raster_frame against raster_quad for the same worst-case quad:
;
;      the pixels it actually writes    70 pushes ->    280 us
;      per-row setup                                   6909 us
;      ------------------------------------------------------
;      raster_joint                                    7189 us
;
;  Ninety-six per cent overhead.  Ninety-nine microseconds a scanline to
;  place ONE push, against C_BLINE = 20 us, which is what raster_quad
;  spends per scanline to place a whole run.  The reason is that the joint
;  is a SECOND PASS: it re-derives the screen address out of VPLINE,
;  reloads SP and re-enters PUSHBLK seventy times over a face raster_quad
;  has just walked with that address already in HL.
;
;  Charged honestly at main3.asm's C_JOINT = 7400 -- it had been guessed at
;  2600, which under-charged by 2.8x and broke the frame lock, emu_pace3
;  reading 159.8 and 179.8 ms against the 139.8 that PACE_FRAMES 7
;  promises -- the worst states measure 239.8 ms.  Twelve vsync periods.
;  4.17 fps, against 8.35 with flat walls, for two mortar lines.
;
;  WHAT WOULD FIX IT IS NOT A LOOKUP TABLE.  There is nothing left to
;  precompute: the geometry is already one DIV3 and a Bresenham, and a
;  table cannot remove a single one of those seventy setups, because they
;  are not arithmetic.  The fix is to fold the joint INTO raster_quad's
;  row loop, where the address is already built and SP is already set, so
;  a joint row costs its 4 us of pushes and a compare instead of a fresh
;  setup.  That is a ~7x cut on the dominant term.  Until it is done, this
;  stays 0 and the walls are flat.
; --------------------------------------------------------------------
COURSES      equ 0

; --------------------------------------------------------------------
;  VPCOL -- 1 draws the walls with the TEXTURED COLUMN renderer
;  (engine2/src/rastcol.asm), 0 with the flat-colour span renderer
;  (engine2/src/raster.asm).  Both are built from the same quad list and
;  both are verified byte for byte against their own Python model, so
;  this is a one-line switch with no other consequence than the two the
;  measurements below name.
;
;  IT COSTS A VSYNC PERIOD, AND THE PLAN SAID IT WOULD NOT.  The column
;  architecture was costed at 6.625 us per screen byte, off the `colimm`
;  row of engine2/tools/emu_byte.py -- `ld sp,hl : ld de,nn : push de :
;  add hl,bc`.  That row cannot be reached by a renderer: `ld de,nn` is
;  an IMMEDIATE, so the texture has to be in the instruction stream
;  already, and putting it there costs 16 us a byte against the 6 that
;  sampling it costs.  Re-MEASURED on the booted 6128 with the loop
;  rastcol.asm actually runs (`colpair`, engine2/test/tst_byte.asm):
;
;      row order, PUSH DE, constant fill          2.000 us/byte
;      column pair by PUSH, constant colour       5.125   <- the floor
;      column pair by PUSH, baked immediate       6.625   <- unreachable
;      COLUMN PAIR BY PUSH, TEXTURED             10.125   <- what ships
;      single column, LD (HL),A, textured        13.625
;
;  and the frame follows from it.  Exhaustive over the reachable state
;  space (engine2/tools/colarea.py, the same 24/256 lattice x 72 headings
;  pacescan.py sweeps):
;
;      span renderer   worst 6842 bytes / 684 runs    23.2 ms
;      column renderer worst 4224 bytes /  50 bands   49.7 ms
;
;  The overdraw and the per-scanline setup the row order was spending do
;  pay for about two thirds of the texture, which is what the plan was
;  right about; they do not pay for all of it.
;
;  WHAT IT BUYS BESIDES THE TEXTURE.  The largest ATOMIC unit -- the
;  thing that decides how few vsync periods a frame can pack into, see
;  main3.asm -- falls from a whole quad at 12486 us MEASURED, 63% of a
;  period, to one BAND of at most 96 scanlines.  raster.asm needed
;  RQ_SPLIT and a chunk hook every 32 scanlines to get that number down
;  and could not afford the hooks; rastcol.asm needs neither.
;
;  AND THE BYTE COUNT IS CAPPED, which the span renderer's is not: a pair
;  carries the interval of rows a nearer face has already taken, so no
;  byte is written twice and the frame is bounded by VP_BW*VP_H however
;  many faces the kernel emits.  The span renderer's worst is 162% of the
;  viewport and grows with the face count.
; --------------------------------------------------------------------
;  ------------------------------------------------------------------
;  AND IT DOES NOT LOCK YET, WHICH IS WHY IT SHIPS AT 0.
;  ------------------------------------------------------------------
;  The renderer itself is finished and CORRECT: engine2/tools/emu_rcol.py
;  compares 192 whole screens byte for byte against colmodel.py -- the
;  hand-built quads, 127 real march/project quads one at a time, and 24
;  painter batches where the occlusion interval actually does something --
;  and all 192 are exact.  The disc built at VPCOL 1 boots and draws
;  perspective-correct textured walls.
;
;  WHAT IS NOT DONE IS THE CHARGE.  main3.asm's C_CFACE / C_COLS / C_COLR
;  were fitted to a controlled sweep (full viewport / quarter height / one
;  row tall, which separate the per-pair, per-band and per-scanline terms)
;  and they came out UNDER the truth, because most pairs carry TWO bands
;  -- one above the horizon and one below -- and the fixed per-band cost
;  was only charged once.  Exhaustive over all 4055040 states pacescan.py
;  then said eight waits was enough; the BOOTED DISC said otherwise:
;
;      emu_verify3.py at PACE_FRAMES 8:  [8, 10, 11, 12] vsyncs
;                                        159.7 / 199.7 / 219.6 / 239.6 ms
;
;  which is exactly the failure mode the pacing notes in main3.asm warn
;  about -- an offline replay of a charge cannot see that the charge is
;  wrong, because it is replaying the charge.  A one-sided C_COLS is
;  about 1040 rather than 640, and at that the worst charged frame goes
;  past nine periods.
;
;  THE LEVER IS THE PER-PAIR SETUP, AND IT IS MEASURED.  On a full-width
;  pair the fill is 2252 us and the setup 994 -- 244 per pair and 375 per
;  band -- so about 30% of the frame is arithmetic, and almost all of it
;  is 16-bit memory temporaries at four and five microseconds a go
;  (rc_num, rc_den, rc_h, rc_t2, rc_acc...).  The pair loop keeps nothing
;  in registers between pairs because the two banks are both full: HL/BC/D
;  hold the texture walk and HL'/BC' the screen.  Moving the pair state
;  into IX/IY and the alternate DE is the obvious next lever and is worth
;  perhaps a third of the setup.
;
;  Until then this is 0, the span renderer ships, and the frame period is
;  the one the whole of main3.asm's pacing note is about: 119.81 ms, 8.35
;  fps, locked over the whole reachable state space.
; ------------------------------------------------------------------
;  ONE ROUND OF THAT OPTIMISATION IS DONE and it is worth 11.1% of the
;  worst frame: COLBLK now counts its own character rows in IXL instead
;  of going back through the offset arithmetic and a self-modified JP
;  every eighth scanline (31 us a character row, and a PC histogram put
;  that at 10.1% of the whole render), and a pair whose two bands ABUT
;  reuses the coordinate the upper band's walk ended on instead of
;  multiplying for it.  A full-viewport quad went 71415 -> 63477 us and
;  the per-pair setup 1302 -> 1015.  All 192 screens stayed byte-exact
;  through both changes.
;
;  AND THE HONEST CHARGE STILL DOES NOT FIT.  With C_COLS at the measured
;  1100 rather than the wishful 640, pacescan.py over all 4055040 states:
;
;      4 waits 0.97%   5  72.52%   6  16.39%   7  7.76%
;      8 waits 2.07%   9   0.28%  10   0.003%
;      worst charged frame 185134 us
;
;  -- ten waits, so eleven periods, 219.6 ms, 4.55 fps.
;
;  THE NEXT LEVER IS THE SHAPE OF THE CHARGE, NOT ITS SIZE.  C_COLS is
;  one flat number covering a pair that draws two bands and 96 scanlines
;  and a pair that draws one band and one, and rc_column charges the FULL
;  row range 2j+1 before the occlusion interval cuts the middle out of
;  it.  On a frame full of overlapping faces that is a large
;  over-estimate, and an over-charge costs periods just as surely as an
;  under-charge does -- see main3.asm.  rc_column already knows, before
;  it draws anything, how many bands it will draw and how long they are:
;  it reads (rc_up) and (rc_dn) to find out.  Charging
;  base + C_BAND*bands + C_COLR*rows_DRAWN fits the same probes
;  (320 + 400*bands + 21*rows clears every one of them) and shrinks with
;  the real work instead of with the geometry.
;
;  Until that is done this is 0, the span renderer ships, and the frame
;  period is the one the whole of main3.asm's pacing note is about:
;  119.81 ms, 8.35 fps, locked over the whole reachable state space.
; ------------------------------------------------------------------
VPCOL        equ 1

; --------------------------------------------------------------------
;  RC_FARH -- THE FAR PLANE, in Q12.4 half-scanlines.  0 turns it off.
;
;  The march reaches L1 R_MAX and files faces to L1 R_MAX+1, and BEYOND
;  THAT NOTHING IS DRAWN -- so a sight line down a corridor or through an
;  open door simply stops, and what fills the gap is bg_fill's ceiling
;  and floor.  The room reads as an open field with a sliver of wall on
;  the horizon.
;
;  THE HONEST FIX IS TO MARCH FURTHER AND IT IS NOT AFFORDABLE.  MEASURED
;  (engine2/tools/roomcost.py and the R_MAX sweep in the handoff): the
;  flood's area grows as the square of the radius, so one more cell of
;  sight costs about TWO VSYNC PERIODS --
;
;      R_MAX 6   worst charged frame 178193 us   11 periods   4.55 fps
;      R_MAX 7                       220574      13           3.85
;      R_MAX 8                       243486      14           3.58
;
;  -- and it needs an eighth face bucket, because march.asm files by
;  |dx|+|dy| with no upper bound and a key of 8 would land in the flood
;  stack.
;
;  SO THIS DRAWS A WALL THAT IS NOT THERE.  It is a synthetic FACE, flat,
;  at a fixed half height, spanning the whole viewport, handed to the
;  ordinary rc_face after the real ones -- so the ordinary occlusion
;  decides where it lands, and it lands ONLY on the pairs no real face
;  covered.  Where the room genuinely ends within the march radius it
;  draws nothing at all.
;
;  IT IS A FAKE AND THE FAKE IS THE POINT: it costs one face and the
;  pairs that were empty anyway, and it does not touch the flood.
;
;  144 is j = 9, a 19-scanline band -- a wall about 5.3 cells off, which
;  is where R_MAX = 4 stops filing real faces, so the fake picks up
;  roughly where the real geometry leaves off and the seam does not jump.
;
;  IT MUST BE A MULTIPLE OF 16.  The band is CYH -+ RC_FARH/16 and rasm
;  and Python have to agree on that division to the row.  At 153 they did
;  not -- 153/16 is 9.5625 -- and emu_rcol went from 183 screens exact to
;  148 of 166 WRONG, every one of them off by a single row at the top and
;  bottom of the band.  A value that divides exactly cannot do that.
;
;  IT SHIPS AT 0, AND THE MEASUREMENT IS WHY.  "Cheap to draw" was wrong:
;
;      far plane OFF   worst charged frame 178193 us   11 periods
;      far plane ON                        224567      13
;      R_MAX 7 instead                     220574      13
;
;  It costs THE SAME AS MARCHING A CELL FURTHER, and marching gives real
;  walls where this gives a painted one.  The reason is the reason
;  engine2/tools/pcprof.py already found: a pair costs C_COLS = 1800 us
;  of SETUP whatever it draws, so a 13-scanline band across 22 pairs is
;  39600 us before a pixel is written -- as much as a full-height wall.
;
;  A far plane that is actually cheap has to be its own fill and not a
;  FACE: one constant band, no u division, no Bresenham probes, no CTABT,
;  no per-pair face machinery.  That is about 8000 us by the same
;  arithmetic, and it is the version worth building.
; --------------------------------------------------------------------
RC_FARH      equ 144
