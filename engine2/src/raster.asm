; =====================================================================
;  engine2/src/raster.asm -- ONE QUAD -> horizontal PUSH DE runs.
;
;  The geometry kernel (kernel.asm) hands over a painter-ordered list of
;  8-byte quads.  This file turns each of them into filled scanlines.
;
;  QUAD RECORD (kernel.asm owns this; do not change it here)
;      +0  blo  byte column of the SHORTER endpoint, 0..VP_BW
;      +1  bhi  byte column of the TALLER  endpoint, 0..VP_BW
;      +2  hlo  Q12.4  projected HALF height at the shorter endpoint
;      +4  hhi  Q12.4  ...and at the taller one
;      +6  kind 0 = wall, 1 = door
;      +7  k    L1 cell distance 1..7  (painter key AND ramp index)
;
;  THIS FILE NO LONGER DERIVES ANY OF THAT.  It used to arrive as
;  (xa,yat,yab,xb,ybt,ybb) in Q12.4 and cost 522 us a quad to undo -- round
;  x to bytes, subtract y back out of CY_Q4 into half heights, sort the
;  endpoints by height.  The projector had all three already, so it emits
;  them (project.asm:pf_emit) and the setup here is now 341 us MEASURED.
;  What is left of it is jlo/jhi, the Bresenham denominator, and the
;  colour.
;
;  ------------------------------------------------------------------
;  THE SHAPE, AND WHY IT SPLITS INTO THREE
;  ------------------------------------------------------------------
;  A projected wall face has VERTICAL left and right edges (at xa and xb)
;  and STRAIGHT top and bottom edges, so as y sweeps down it is
;
;      top wedge     yat..ybt   one x edge moves, the other is pinned
;      body          the middle -- span is CONSTANT [xa, xb]
;      bottom wedge  ybb..yab   the mirror of the top wedge
;
;  and only the wedges pay per-scanline work.  That split is the whole
;  reason a free-movement view is affordable at 4 MHz.
;
;  ------------------------------------------------------------------
;  ...AND WHY IT IS ACTUALLY RASTERISED OUTWARD FROM THE HORIZON
;  ------------------------------------------------------------------
;  The camera sits at wall mid-height and cannot pitch, so the projector
;  never emitted ytop and ybot separately at all: they are CY_Q4 -+ hh for
;  one projected HALF height hh (projmodel.py).  The quad is therefore
;  SYMMETRIC about the horizon row CYH, and is fully described by
;  (blo, hlo, bhi, hhi) -- which is exactly what the record carries.
;
;  Rewrite the coverage test in terms of u = |y - CYH| in Q12.4:
;
;      scanline y is inside the quad  <=>  u <= h(x at that scanline)
;
;  and CY_Q4 is a whole number of scanlines (CYH*16), so rows CYH-j and
;  CYH+j share the SAME u = 16j -- and therefore the same span.  Three
;  things fall out of that, all of them wins:
;
;   1. the moving x edge is interpolated ONCE per PAIR of scanlines, so
;      the wedge's generation cost halves;
;   2. u only ever runs over [0, CYH*16], so a wall closer than one cell
;      -- whose yat is hundreds of scanlines above the screen -- needs no
;      y clipping arithmetic at all, just a loop bound of CYH.  There is
;      no divide anywhere in this file;
;   3. the body is still a CONTIGUOUS row range [CYH-jlo, CYH+jlo], so it
;      still gets the cheap src/render.asm draw_rect treatment: set the
;      run length once, then step the screen address per line.
;
;  ------------------------------------------------------------------
;  THE MOVING EDGE IS INTERPOLATED IN u, NOT IN WHOLE ROWS
;  ------------------------------------------------------------------
;  Coverage is u <= h(x) and h is linear in x, so the moving edge is
;  linear in u -- in HALF HEIGHTS.  jlo = hlo>>4 and jhiu = hhi>>4 are
;  TRUNCATIONS of its two ends, and the Bresenham used to run between
;  THOSE: numerator |bhi - blo| in bytes, denominator jhiu - jlo in rows.
;  That walks the edge across its whole travel in up to a row less than it
;  really takes, so the edge always LED the exact one, and on a wedge one
;  or two rows tall it reached the pinned column a full row early and the
;  face's span on that row vanished.  12 one-byte gaps between walls over
;  37 frames were exactly that -- e.g. the junction state (0780,0380,
;  heading 2), rows 35 and 61, byte column 21, where the quad (blo=31,
;  bhi=20, hlo=207, hhi=217) has jlo=12 and jhiu=13, so its ONE step took
;  the edge the whole 11 bytes onto column 20 although the exact geometry
;  covers 20.75..29.95 at that scanline.
;
;  So the denominator is N = hhi - hlo, in Q12.4, and the step is 16*D per
;  row of u (D = |bhi - blo| <= VP_BW, or half that in the WORD shape).
;  Row j means u = 16*j, which is f = hlo & 15 BELOW hlo, so the
;  accumulator is pre-biased by D*f -- four shift-and-adds, since f < 16.
;  A wedge that runs off the top of the screen still stops early with the
;  correct slope: N is still the UNCLIPPED height.
;
;  IT ROUNDS THE EDGE DOWN, not to nearest.  acc0 carries a further -N,
;  which turns the division into a floor, so the moving edge LAGS onto the
;  byte boundary OUTSIDE the exact edge -- the same direction npush and
;  project.asm's columns already round, and what makes a run cover all of
;  the record's geometry instead of splitting a byte off it.  Measured
;  over the same 37 frames (emu_sliver.py states 30): interpolating in u
;  and rounding to nearest leaves 6 of the 12 gaps and 338 of the 774
;  holes; flooring leaves 2 and 82.
;
;  N <= 6144 (hh at the near plane, projmodel.py HTAB) and D <= VP_BW, so
;  acc0 = -N - D*f, and everything the loop does to it, stay inside a
;  SIGNED 16-bit word.  rq_wchk tests its sign with BIT 7,H.
;
;  ------------------------------------------------------------------
;  RUNS
;  ------------------------------------------------------------------
;  PUSH DE writes two HORIZONTALLY ADJACENT bytes in 4 us, so SP is the
;  screen pointer and runs are byte-granular with EVEN length.  Per
;  scanline this file produces exactly the two things src/render.asm
;  wants: the address ONE PAST the right end of the run, and the entry
;  byte MAXPUSH-npush into the page-aligned unrolled PUSH block.
;
;  AN ODD BYTE WIDTH ROUNDS OUTWARD, NOT INWARD.  It used to round in --
;  npush = w>>1 -- and since PUSH walks backwards from the end, that
;  dropped the run's LEFTMOST byte.  Two faces meeting at a depth step
;  could then both lose the byte they share, leaving a 2-pixel stripe of
;  ceiling between two walls: 118 such slivers and 22 more leaking down
;  the viewport's left edge were COUNTED in one frame, 2152 and 1616 over
;  37 (engine2/tools/emu_sliver.py).  npush is now (w+1)>>1, which takes
;  the extra byte on the LEFT, and project.asm rounds the columns
;  themselves outward as well -- left edge down, right edge up.  Adjacent
;  faces therefore OVERLAP by a byte, which is invisible because the
;  painter order draws the nearer one last, instead of leaving a gap,
;  which is not.  Measured after: 0 left-edge leaks and 12 slivers over
;  the same 37 frames, none of them from run rounding -- they were the
;  wedge interpolation, and the section above is that fix.  2 remain.
;  It costs 2.0 us per body scanline pair and 1.0 us per wedge scanline
;  pair plus the extra bytes: raster 30.0 -> 35.3 ms on the worst frame
;  in the maze, whole frame 73.9 -> 78.9 ms (emu_frame.py, 100.08 us
;  calibration).
;
;  THE LAST TWO ARE NOT THIS FILE'S TO FIX.  With the interpolation exact
;  the rasteriser reproduces its own RECORD faithfully -- but the record's
;  columns are the exact edges rounded OUTWARD, blo below xa and bhi above
;  xb, so the line between them is not the exact top edge: it starts up to
;  a byte wide of the short end and arrives up to a byte wide of the tall
;  one, which tilts the wedge INWARD near the tall end.  Both residual
;  gaps are that and nothing else.  In the state (017F,0950,69), rows 29
;  and 67, the quad (13,28,278,307) comes from exact columns 13.44 and
;  27.28; row 29 needs byte 25 and the record -- interpolated in REAL
;  arithmetic, no Bresenham involved -- puts its edge at 26.45.  Closing
;  them means giving the rasteriser sub-byte columns, or having
;  project.asm extrapolate hlo and hhi out to the rounded columns so that
;  the record's top edge is the same LINE as the exact one.  The latter
;  was modelled: 0 artefacts, 8 holes, the two remaining one-byte gaps
;  being REAL 2-pixel gaps in the geometry -- for 424 more wedge scanlines
;  over the 37 frames, about 0.7 ms a frame.  A constant half-byte lag in
;  the wedge would also clear them (0 artefacts, 9 holes, ~0.1 ms) but it
;  is a fudge: it over-paints every wedge row to compensate for a rounding
;  error committed in another file, and the bias it cancels can be a whole
;  byte, so it is not a guarantee either.
;
;  THE EXPANSION IS CLIPPED TO THE VIEWPORT, and the clip costs nothing
;  per scanline because it is arranged for at setup:
;    * the run's right end is bb <= VP_BW and never grows;
;    * the left end is ba, or a moving edge that never goes below ba, and
;      the odd byte is only ever taken when ba >= 1.  project.asm
;      guarantees that: a face with ba == 0 gets an EVEN bb, so every span
;      cut out of it is already even -- except in the one shape whose
;      moving edge is on the RIGHT with the pinned edge at column 0, and
;      that one steps its moving edge in WORDS (rq_lt0 below).
;  3000 reachable states, 12745 quads, 764722 runs: none outside the
;  viewport.
;
;  x needs no clipping: proj_face clamped xa and xb to [0, XMAX_Q4] before
;  rounding them, and rounding is monotone, so 0 <= blo, bhi <= VP_BW.
;  y needs no clipping either, per (2) above.
;
;  ------------------------------------------------------------------
;  COLOUR
;  ------------------------------------------------------------------
;  RAMP[(kind<<3) | k] -- 16 bytes in bank 4, built by engine2/tools/
;  pal.py.  k is the quad's own L1 depth 1..7 and kind picks the wall
;  ramp (white -> cyan -> blue) or the door ramp (yellow -> orange ->
;  red).  pal.py repalettes engine2 so that EVERY ramp step is strictly
;  brighter than both ceiling bands; the shipped discs put the darkest
;  wall step and the near ceiling on the same firmware ink, which made
;  far walls dissolve into the ceiling.
;
;  ------------------------------------------------------------------
;  NOTE ON THE VIEWPORT.  Everything below was measured at 44x96 bytes.
;  vpcfg.inc now says 40x96: whole frames were measured end to end
;  (engine2/src/frame.asm, engine2/tools/emu_frame.py) and 44 missed the
;  80 ms budget by 0.96 ms on the worst state in the maze.  The four
;  per-scanline and per-byte costs below do not depend on the width; only
;  the byte counts fed to them do.
;
;  MEASURED on a cycle-accurate CPC 6128, viewport 44x96 bytes, 60 FOV.
;  engine2/tools/emu_rast.py; 16-bit counter, interrupts off, empty-loop
;  overhead (14.00 us) subtracted, method calibrated to 100.08 us on 100
;  NOPs.  49 designed probes that vary body lines, body bytes, wedge
;  lines and wedge bytes INDEPENDENTLY (they are collinear in any
;  triangle, and a lazy sweep hands back a per-byte cost below the PUSH
;  DE floor, which is how you know the design was wrong):
;
;      us = 622  +  16.01*body_lines  +  1.989*body_bytes
;                +  56.07*wedge_lines +  2.136*wedge_bytes
;      R^2 0.9965, RMS residual 211 us, worst 590 us
;      (in whole ROWS, before the u-unit interpolation: 661 + 16.38
;       + 2.001 + 62.61 + 1.921, R^2 0.9966.  The wedge's line and byte
;       costs are collinear over any ONE quad and the u-unit runs are a
;       byte wider, so the split between 56.5 and 2.13 moved even though
;       the instructions did not; their SUM is what predicts.)
;
;    per-quad setup, nothing drawn      274 us   (measured directly, on a
;                                                 quad with zero width AND
;                                                 no wedge; 342 before the
;                                                 wedgeless hoist, 522
;                                                 with the old record)
;    BODY  scanline                    16.0 us + 1.99 us/byte
;    WEDGE scanline                    56.1 us + 2.14 us/byte
;    -- so at the full 44-byte width a body line is 104 us and a wedge
;    line 150 us, against a PUSH DE floor of 88 us.  The body runs at
;    1.19x the floor; the whole-quad figure is worse only because of the
;    274 us of setup.
;
;    103 REAL quads out of march/project frames:
;      mean 3108 us, median 2272 us, worst 10653 us
;      mean 624 bytes pushed, worst 4224 (the whole viewport)
;      the fit above predicts every one of them to within 343 us
;      (the 2597 / 1695 / 10376 and 521 bytes here before were measured
;       BEFORE the odd-width outward rounding as well, so most of that
;       step is its extra bytes, not the interpolation's)
;
;  WHOLE FRAMES, this rasteriser MEASURED and the geometry kernel and
;  background taken from their own measured fits (kernel.asm: 3281 +
;  544.7*ref_cells + 506.3*cand_faces; bg.asm: 9036 us).  702 player
;  states surveyed with the model, the 20 worst of them MEASURED plus a
;  40-state spread:
;
;      pctile  quads   bytes  overdraw   geom     bg   raster   TOTAL
;      min         1     384     0.09x    7.0    9.0     3.0    19.1 ms
;      median      6    3762     0.89x   16.6    9.0    21.2    46.8 ms
;      p90        13    3200     0.76x   26.6    9.0    31.4    67.1 ms
;      worst      13    5684     1.35x   33.0    9.0    30.1    72.2 ms
;
;    against an 80 ms (4 vsync frame, 12.5 fps) budget: EVERY frame fits,
;    the worst with 8.0 ms to spare.  The geometry kernel's own known
;    worst is 36.7 ms rather than the 33.0 this survey found, which would
;    put a true worst frame at about 76 ms -- still inside, but that is
;    the number to watch.  44x96 holds and there is no need to fall back
;    to 40x88.
;
;    THE u-UNIT INTERPOLATION COST, A/B on the SAME states and the same
;    protocol, the only difference being which raster.asm is assembled
;    (the wedgeless hoist is in these numbers too, which is why the first
;    three are negative):
;
;      per-quad setup, nothing drawn             342.0 ->   274.0 us
;      body only, full width, full height      10796.8 -> 10652.7 us
;      body only, 22 rows                       2905.7 ->  2843.1 us
;      wedge, 6 B wide, to h=768                6285.2 ->  6652.7 us
;      wedge, 44 B wide, to h=768              10796.8 -> 10944.9 us
;      one-row wedge (the junction sliver)      1771.7 ->  1787.8 us
;      FRAME worst frame in the maze           35104.5 -> 35817.6 us
;      FRAME junction (0780,0380,2)            24495.8 -> 25687.4 us
;      FRAME corridor                          27395.8 -> 27997.2 us
;      FRAME (017F,0950,69)                    21631.0 -> 22319.9 us
;
;    THE SHIPPED FRAME PERIOD IS UNAFFECTED.  main3.asm paces on estimated
;    microseconds and its C_* are upper bounds; on the booted disc
;    (emu_pacefit.py, 40 states, seeded) the worst frame goes 70.88 ->
;    72.63 ms against an unchanged 74.17 ms charge, and the tightest
;    estimate-minus-actual margin over the sample actually WIDENS, +979 ->
;    +1124 us, because the states that bind it are wedgeless ones that the
;    hoist made faster.  Every frame is still exactly 5 vsyncs
;    (emu_verify3.py).  Per wedge line pair the shipped code now measures
;    139 us against pacemodel.py's C_QW = 128 -- see the note there.
;
;    i.e. +0.6 to +1.2 ms on a real frame, 2 to 5%.  Almost none of it is
;    arithmetic -- the wedge loop is the same instruction count, the 16-bit
;    step riding in the ADC that already carried -- it is the SPANS that
;    used to vanish and now get painted: 1522 -> 1763 wedge scanlines and
;    12290 -> 14408 wedge bytes over the 37 emu_sliver.py frames.
;
;    Overdraw is only ~1x the viewport even at p90, because the painter
;    order is back to front and near walls are few and large.  The fill
;    is therefore NOT the problem: 5684 bytes is 11.4 ms of PUSH DE out of
;    30.0 ms of rasteriser.
;
;  THE RECORD FORMAT WAS THE NEXT LEVER, AND IT HAS BEEN PULLED.  522 us
;  of every quad was setup -- 17 quads x 522 = 8.9 ms of the worst frame --
;  and almost all of it was undoing the Q12.4 screen-space form the quad
;  used to arrive in.  kernel.asm's output contract is now
;  (blo, bhi, hlo, hhi, kind, k), 8 bytes instead of 14, and MEASURED on
;  the same probe as the 522 above (emu_rast.py time, the xa == xb quad,
;  100-NOP calibration 100.08 us, 14.00 us loop overhead subtracted):
;
;      per-quad setup, nothing drawn   522.2 us  ->  340.9 us
;      the four per-line and per-byte costs are UNCHANGED to within the
;      fit's noise (they are the same instructions):
;          us = 661 + 16.38*body_lines + 2.001*body_bytes
;                   + 62.61*wedge_lines + 1.921*wedge_bytes
;          R^2 0.99663, RMS 203 us   (was 844 + 16.35 + 1.999 + 62.66
;                                     + 1.900, R^2 0.99658)
;      103 REAL quads: mean 2779 -> 2597 us, worst 10512 -> 10376 us
;
;  THE WEDGE-LESS QUAD WAS THE NEXT LEVER, AND IT HAS BEEN PULLED.  29.6%
;  of the quads in the maze (1653 counted over 400 reachable states) have
;  jhi == jlo -- a wall seen square on, or one so near that both ends clip
;  -- and for those N, acc0 and the step were computed and never read.
;  The jhi == jlo test now sits above all of it (rq_nowedge), which is
;  worth 68.1 us MEASURED on a quad that draws nothing, and pays for most
;  of what the u-unit setup adds to the quads that do have a wedge.  What
;  is left of the setup is jlo, jhi, the colour, and -- only when there is
;  a wedge -- N, 16*D and the D*f bias.
;
;  THE NEXT LEVER IS THE WEDGE SCANLINE ITSELF, at 56.5 us fixed against a
;  body line's 16.0.  It is not the Bresenham (one microsecond a step): it
;  is that every wedge line re-reads VPLINE, re-assembles a screen address
;  and re-patches two JP operands, where the body sets its run length once
;  and steps the address.  A wedge line that repeats the previous line's
;  span -- which is most of them on a shallow wedge, since the edge moves
;  less than a byte a row -- could skip the patching entirely.
;  ------------------------------------------------------------------
;  IN   HL = quad record; raster_init and raster_setbuf done once
;  OUT  the quad painted.  SP restored.
;  Clobbers AF BC DE HL IX.  Interrupts must be OFF (SP is the screen).
; =====================================================================

; Needs from vpcfg.inc:  VP_BX VP_BW VP_Y VP_H CYH CY_Q4 MAXPUSH
; Needs from tab_equ.inc: LINETAB RAMP
; Needs from kernel.asm:  QUADS QRECSZ fg_nquad

RQ_RC       equ CYH                 ; the horizon, as a VIEWPORT-relative row
SCR_W       equ 80

; ---------------------------------------------------------------------
;  THE PACING CHUNK -- how many scanlines raster_quad draws between two
;  points at which main3.asm's accumulator is allowed to take its vsync.
;
;  WHY THIS EXISTS.  The accumulator can only yield where something calls
;  cost_unit, and until now the smallest thing that called it was a WHOLE
;  QUAD: 12486 us MEASURED on the worst shape this viewport can produce
;  (0 -> 8x overheight, full width), which is 63% of a 19968 us vsync
;  period.  The frame's WORK fits five periods with 5 ms to spare; its
;  PACKING does not, because greedy next-fit can waste most of an atomic
;  unit at every bin boundary and four boundaries of 12.5 ms is 50 ms.
;  The binding constraint on the frame rate is the largest atomic unit,
;  not the total slack -- so raster_quad yields INSIDE itself now.
;
;  HOW THE TWO SIZES WERE CHOSEN.  The atomic unit has to stay
;  comfortably inside one period at the WIDEST viewport this engine is
;  meant to grow into, which is 48 bytes (VP_BW 48 x VP_H 128 is the big
;  variant vpcfg.inc documents).  MEASURED per-scanline costs, this file,
;  emu_rast.py's protocol with the Bresenham's edge steps separated out
;  as a regressor of their own -- they are collinear with wedge lines in
;  a lazy sweep, and that collinearity is how the old whole-quad estimate
;  came to under-charge a steep short wedge by 600 us:
;
;      body  scanline   18.78 us + 1.976 us/byte
;      wedge scanline   59.05 us + 1.760 us/byte
;      wedge edge step  19.27 us   (D of them over the whole wedge)
;      one chunk hook  ~220 us     (engine2/tools/emu_atomic.py, A/B
;                                   against the hookless build)
;
;  so at 48 bytes a body scanline is 113.6 us and a wedge PAIR 287.1, and
;  the whole of a wedge's edge stepping -- up to 19.27*48 = 925 us -- can
;  land in ONE pair.  The two sizes are then chosen to make the two kinds
;  of chunk cost about the SAME, because the atomic unit is the worse of
;  them and buying a finer grain on one while the other stays coarse buys
;  nothing at all:
;
;                            at VP_BW 40 (shipped)   at VP_BW 48
;      body  32 scanlines          3.4 ms               3.9 ms
;      wedge  8 pairs + steps      2.9 ms               3.2 ms
;
;  -- 20% of a 19968 us period at the widest viewport intended and 17% at
;  the one that ships, against 63% before, which is the whole point.
;  MEASURED end to end, the largest interval any quad produces is 3.32 ms
;  (emu_atomic.py, which times raster_quad up to the k'th hook and
;  differences it rather than modelling it).
;
;  SMALLER WOULD PACK BETTER AND COST MORE.  Every chunk boundary is a
;  hook and the hook is pure overhead: at 16/8 the worst frame's
;  rasteriser grew by 12.4 ms, at 32/8 it grows by 8.5 ms, and the
;  ESTIMATE the accumulator carries fell with it -- replayed over the
;  movement lattice the worst charged frame goes 103.0 -> 98.2 ms.  32/8
;  is where that trade sits.  Both must be POWERS OF TWO: a full chunk's
;  charge is a shift, and only the short last one is multiplied out.
; ---------------------------------------------------------------------
RQ_BLOG     equ 5
RQ_BCH      equ 1<<RQ_BLOG          ; body scanlines per chunk
RQ_WLOG     equ 3
RQ_WCH      equ 1<<RQ_WLOG          ; wedge scanline PAIRS per chunk

; ---------------------------------------------------------------------
;  RQ_SPLIT -- 1 compiles the mid-quad yield, 0 leaves raster_quad as one
;  atomic unit and hands the charging back to main3.asm's pace_quad.
;
;  IT SHIPS AT 0, AND THE MEASUREMENT IS WHY.  Everything above works and
;  is verified -- emu_rast.py compares 180 screens byte for byte in BOTH
;  builds, and emu_atomic.py measures the atomic unit down from 12665 us
;  to 3324.  What it costs is the problem.  Each hook is ~220 us MEASURED
;  and the worst frame in this maze draws 16 quads, which is 42 chunk
;  hooks where there used to be 16 pace_quads:
;
;      worst frame (0150,0DF0) h67   work 93.00 -> 101.50 ms
;      the rasteriser's CHARGE       40.33 -> 59.01 ms
;
;  and the accumulator's budget is PACE_FRAMES * COST_THI = 116.74 ms.
;  The frame charge goes to 116.34, the greedy rule then asks for a SIXTH
;  wait, and the frame takes SEVEN periods.  MEASURED on the booted disc,
;  1400 states / 11200 frames at 250 us sampling (emu_pace.py):
;
;      RQ_SPLIT 1    6 vsyncs 99.79%,  7 vsyncs 0.21% -- (0160,0DE0) h69
;                    and h67, and (0150,0DF0) h67
;      RQ_SPLIT 0    6 vsyncs 100.00%                          LOCKED
;
;  -- the exact shape of an over-charged frame, and the exact defect this
;  project has removed three times.  A CONSTANT period is worth more than
;  a smaller atomic unit, so 0 is what the disc carries until the hook is
;  cheap enough to pay for itself.  Chunk sizes were swept offline first
;  (engine2/tools/pacemodel.py replays the rule): no power-of-two pair
;  from 16/8 up to 96/48 gets the worst state back to five waits, because
;  the floor is one body hook and one wedge hook per quad whatever the
;  chunk size, and 32 hooks is already 8.3 ms of charge.
; ---------------------------------------------------------------------
    ifndef RQ_SPLIT             ; ...and `rasm -DRQ_SPLIT=1` builds the
RQ_SPLIT    equ 0                   ; other one, which is how emu_rast.py
    endif                           ; verifies it and emu_atomic.py times it

    ifdef PACED
RQ_PACED    equ RQ_SPLIT
    else
RQ_PACED    equ 0
    endif

    assert CY_Q4 == RQ_RC*16        ; the horizon is a whole scanline
    assert RQ_RC*2 == VP_H          ; ...and it is the middle one
    assert MAXPUSH*2 == VP_BW       ; one PUSH DE = two bytes
    assert VP_H*2 <= 256            ; VPLINE is one page, indexed by row*2
    assert VP_BX+VP_BW <= SCR_W
    assert (VP_Y&7) == 0            ; keeps the crow arithmetic honest


; ---------------------------------------------------------------------
;  raster_init -- build VPLINE.  Bank 4 must be paged in.  Call once.
;
;  VPLINE[r] = the screen OFFSET of the first byte of viewport row r,
;  i.e. (y&7)*&800 + (y>>3)*80 + VP_BX for y = VP_Y+r, with the &C000
;  that LINETAB bakes in stripped off.  The buffer base is added back as
;  an immediate inside the loops (raster_setbuf patches it), which is why
;  one 192-byte table serves both buffers.
; ---------------------------------------------------------------------
raster_init
    ld   hl,LINETAB+VP_Y*2
    ld   de,VPLINE
    ld   b,VP_H
ri_l
    ld   a,(hl)
    inc  hl
    add  a,VP_BX
    ld   (de),a
    inc  de
    ld   a,(hl)
    inc  hl
    adc  a,0
    and  #3F                    ; offset only; < &4000 even at row VP_H-1
    ld   (de),a
    inc  de
    djnz ri_l
    ret


; ---------------------------------------------------------------------
;  raster_setbuf -- A = #C0 (front) or #80 (back).  Patches the three
;  places a screen address is assembled.
; ---------------------------------------------------------------------
raster_setbuf
    if VPCOL
    ld   (rc_buf+1),a           ; the column renderer's two sites
    ld   (rc_ebuf+1),a
    else
    ld   (rq_bufb+1),a
    ld   (rq_bufu+1),a
    ld   (rq_bufl+1),a
    if COURSES
    ld   (rj_bufu+1),a          ; ...and the two the course joints use
    ld   (rj_bufl+1),a
    endif
    endif
    ret


; ---------------------------------------------------------------------
;  EVERYTHING BELOW IS THE SPAN RENDERER, and vpcfg.inc's VPCOL compiles
;  it out.  raster_init, raster_setbuf and VPLINE above and below it are
;  shared: the column renderer walks the same viewport row table and is
;  patched with the same buffer base, so only the quad-to-runs machinery
;  and its two page-aligned PUSH blocks are conditional.
;
;  IT HAS TO GO, NOT JUST BE UNUSED.  raster_quad plus PUSHBLK and
;  PUSHBLK_L is a kilobyte, two pages of it page-ALIGNED, and main3.asm's
;  `assert game_end <= BUCK0` fires with both renderers in the build --
;  which is the assert doing its job, and the third time it has.
; ---------------------------------------------------------------------
    if VPCOL == 0


; ---------------------------------------------------------------------
;  raster_frame -- every quad in the kernel's list, back to front, and
;  then that quad's two COURSE JOINTS on top of it.
;
;  The joints are a second pass over the SAME record, not a second record:
;  raster_joint derives them from (blo, bhi, hlo, hhi) and nothing else,
;  so the geometry kernel is untouched and its quad list is still what it
;  always was.  Face first, joints after -- they overdraw the stone.
; ---------------------------------------------------------------------
raster_frame
    ld   a,(fg_nquad)
    or   a
    ret  z
    ld   b,a
    ld   hl,QUADS
rf_l
    push bc
    push hl                     ; the record; raster_quad consumes it
    call raster_quad            ; leaves HL past the record
    ex   (sp),hl                ; stack = the next record, HL = this one
    if COURSES
    call raster_joint
    endif
    pop  hl
    pop  bc
    djnz rf_l
    ret


; =====================================================================
;  raster_quad -- HL = quad record.  Returns HL past it.
; =====================================================================
raster_quad
    if RQ_PACED
    ld   bc,C_QSET              ; the setup below, and the first chunk hook
    call cost_unit              ; -- room then charge, on the CPU stack,
    endif                       ; which is still SP at this point
    ld   (rq_sp),sp
    ld   de,rq_blo              ; the record, into locals; HL -> next record
    repeat QRECSZ               ; LDI, not LDIR: the gate array stretches
    ldi                         ; LDIR's 21T to 24 and LDI's 16T to 16, so
    rend                        ; unrolling is 8 bytes for 2 us a byte
    ld   (rq_next),hl

    ; ---- ONE signed subtraction settles four things: the Bresenham
    ;      numerator D, its direction, the body width (which IS D, since
    ;      {bhi,blo} = {ba,bb}), and WHICH endpoint is taller -- because
    ;      the projector paired the taller height with its own column, so
    ;      bhi >= blo exactly when the RIGHT endpoint is the taller one.
    ;      A tie is either case: both patchings then read the same byte.
    ld   a,(rq_blo)
    ld   c,a
    ld   a,(rq_bhi)
    sub  c                      ; A = bhi - blo
    jr   c,rq_ltall

    ; --- right endpoint taller: bb = bhi, and the run ENDS at bhi on
    ;     every wedge scanline, so rq_wspan becomes LD A,bhi / SUB C and
    ;     the two address sites become LD A,bhi.
    ld   (rq_bw),a              ; = D >= 0
    ld   (rq_d),a
    ld   a,#0C                  ; INC C -- the moving edge walks right
    ld   (rq_dir),a
    ld   a,(rq_bhi)
    ld   (rq_bb),a
    ld   h,a
    ld   l,#3E                  ; LD A,n
    ld   (rq_wspan),hl
    ld   (rq_ea1),hl
    ld   (rq_ea2),hl
    if RQ_PACED
    ld   (rq_wspan2),hl         ; the chunk hook reads the span too
    endif
    ld   a,#91                  ; SUB C
    ld   (rq_wspan+2),a
    if RQ_PACED
    ld   (rq_wspan2+2),a
    endif
    jr   rq_tall_done

    ; --- left endpoint taller: bb = blo, and the run ends at the MOVING
    ;     edge, which lives in C, so rq_wspan is LD A,C / SUB bhi and the
    ;     address sites are LD A,C / NOP.
rq_ltall
    neg
    ld   (rq_bw),a              ; = D > 0
    ld   (rq_d),a
    ld   a,#0D                  ; DEC C -- ...the moving edge walks left
    ld   (rq_dir),a
    ld   a,c                    ; blo is the RIGHT column here
    ld   (rq_bb),a
    ld   a,(rq_bhi)
    or   a
    jr   z,rq_lt0               ; the pinned LEFT edge is at column 0
    ld   (rq_wspan+2),a
    if RQ_PACED
    ld   (rq_wspan2+2),a
    endif
    ld   hl,#D679               ; LD A,C : SUB n
    ld   (rq_wspan),hl
    if RQ_PACED
    ld   (rq_wspan2),hl
    endif
    ld   hl,#0079               ; LD A,C : NOP
    ld   (rq_ea1),hl
    ld   (rq_ea2),hl
    jr   rq_tall_done

    ; --- ...and the one quad shape that cannot pay for an odd byte by
    ;     widening to the LEFT, because there is no column -1: pinned at
    ;     column 0, with the moving edge on the RIGHT.  It steps that edge
    ;     in WORDS instead -- C counts PUSH DE pairs, not bytes -- so the
    ;     run is [0, 2C) and is even by construction, with no expansion
    ;     and no clipping.  bb is EVEN here (project.asm made it so when
    ;     ba == 0), so D = bb/2 and the wedge keeps its slope; only the
    ;     moving edge's horizontal quantisation coarsens, from 2 px to 4,
    ;     and only on an edge that faces the ceiling rather than another
    ;     face.  rq_wspan becomes LD A,C : ADD A,A : NOP and the two
    ;     address sites LD A,C : ADD A,A -- the same 3 us and 2 us as the
    ;     other two patchings, so this shape costs nothing per scanline.
rq_lt0
    ld   a,(rq_bb)
    srl  a
    ld   (rq_blo),a             ; the moving edge starts at bb/2 words
    ld   (rq_d),a               ; D = bb/2 - 0
    ld   hl,#8779               ; LD A,C : ADD A,A
    ld   (rq_wspan),hl
    ld   (rq_ea1),hl
    ld   (rq_ea2),hl
    xor  a
    ld   (rq_wspan+2),a         ; NOP
    if RQ_PACED
    ld   hl,#8779
    ld   (rq_wspan2),hl
    xor  a
    ld   (rq_wspan2+2),a
    endif
rq_tall_done

    ; ---- jlo = min(RC, hlo>>4): the last row of the CONSTANT-width body,
    ;      counted OUTWARD from the horizon row.
    ld   hl,(rq_hlo)
    ld   de,RQ_RC*16
    or   a
    sbc  hl,de
    ld   a,RQ_RC
    jr   nc,rq_jlo_set
    add  hl,de
    call rq_sh4
rq_jlo_set
    ld   (rq_jlo),a

    ; ---- jhi = min(RC, hhi>>4): the last wedge row.  hhi>>4 can be as
    ;      much as 384 (the near plane), so a nonzero H already means it
    ;      clips.  It is not needed unclipped any more -- the Bresenham
    ;      denominator is a height now, not a row count.
    ld   hl,(rq_hhi)
    srl  h
    rr   l
    srl  h
    rr   l
    srl  h
    rr   l
    srl  h
    rr   l
    ld   a,h
    or   a
    jr   nz,rq_jhi_clip
    ld   a,l
    cp   RQ_RC+1
    jr   c,rq_jhi_set
rq_jhi_clip
    ld   a,RQ_RC
rq_jhi_set
    ld   (rq_jhi),a

    ; ---- iterations = jhi - jlo, and NOTHING below is read unless there
    ;      is at least one.  29.6% of the quads in the maze are wedgeless
    ;      -- a wall seen square on, or one so near that both ends clip --
    ;      so the test is worth hoisting above the whole Bresenham setup.
    ld   hl,rq_jlo
    sub  (hl)                   ; A = jhi - jlo
    ld   (rq_wn),a
    jr   z,rq_nowedge
    jr   c,rq_nowedge           ; jhi < jlo cannot happen; cheap insurance

    ; ---- THE BRESENHAM RUNS IN u, NOT IN WHOLE ROWS.  Denominator
    ;      N = hhi - hlo, numerator 16*D per row of u.  See the header:
    ;      jlo and jhiu are TRUNCATIONS of the edge's real endpoints, so
    ;      interpolating between them ran the edge home a row early.
    ;      N <= 6144 (hh at the near plane) and 16*D <= 16*VP_BW, so the
    ;      accumulator below stays inside a SIGNED 16-bit word, which is
    ;      what rq_wchk's BIT 7,H tests.
    ;      -N is what the loop actually adds, so subtract the other way
    ;      round and never form N at all.
    ld   de,(rq_hhi)
    ld   hl,(rq_hlo)
    or   a
    sbc  hl,de                  ; HL = hlo - hhi = -N < 0
    ld   a,l
    ld   (rq_nl+1),a
    ld   a,h
    ld   (rq_nh+1),a
    push hl                     ; -N: acc0 starts there

    ; ---- the step: D bytes per 16 of u.  16-bit now, so the wedge loop's
    ;      second half-add carries a high byte instead of just the carry.
    ;      DE = D is left set up for the multiply below.
    ld   a,(rq_d)
    ld   e,a
    ld   d,0
    ld   l,a
    ld   h,d
    add  hl,hl
    add  hl,hl
    add  hl,hl
    add  hl,hl                  ; HL = 16*D
    ld   a,l
    ld   (rq_dl+1),a
    ld   a,h
    ld   (rq_dh+1),a

    ; ---- acc0 = -N - D*f, f = hlo & 15.  Step j means u = 16*j, which is
    ;      f BELOW hlo, so the accumulator starts D*f short of the edge;
    ;      the -N makes the division FLOOR, i.e. the moving edge lags to
    ;      the byte boundary OUTSIDE the exact edge, the same direction
    ;      npush and project.asm's columns already round.
    ;      f < 16, so the multiply is four shift-and-adds.  It is a LOOP
    ;      and not unrolled for SPACE: the variables below end at #10FE and
    ;      PUSHBLK must stay on the #1100 page, so there is ONE byte spare.
    ;      Unrolling costs 16 and pushes PUSHBLK, PUSHBLK_L and VPLINE a
    ;      whole page down, which costs 256 bytes of the 179 free under the
    ;      march buckets and does not fit (main3.asm's memory map, and its
    ;      `assert game_end <= BUCKETS`).  The four DJNZ are ~16 us of a
    ;      setup that runs once a quad and only when there IS a wedge.
    ld   a,(rq_hlo)
    and  #0F
    ld   hl,0                   ; the product
    jr   z,rq_mdone             ; hlo already whole: no bias to pay
    add  a,a
    add  a,a
    add  a,a
    add  a,a                    ; f into bits 7..4, consumed MSB first
    ld   b,4
rq_ml
    add  hl,hl
    add  a,a                    ; next bit of f out of the top, into carry
    jr   nc,rq_mnb              ; (ADD HL,rr leaves A alone, so A is the
    add  hl,de                  ;  shift register and C stays free)
rq_mnb
    djnz rq_ml
rq_mdone
    ex   de,hl                  ; DE = D*f
    pop  hl                     ; HL = -N
    or   a
    sbc  hl,de
    ld   (rq_acc),hl            ; acc0 = -N - D*f
rq_nowedge

    ; ---- the fill WORD: WRAMP[(kind<<4) | (k<<1)] ----
    ;
    ; THIS USED TO READ ONE BYTE AND COPY IT INTO BOTH HALVES OF DE, which
    ; threw away three quarters of what a PUSH can say.  PUSH writes E at
    ; the LOWER address -- E is the LEFT screen byte -- and each byte is two
    ; independent Mode 0 pens, so a fill word that is not byte-symmetric
    ; lays a vertical line every four pixels FOR NOTHING: the pushes are
    ; the same pushes, the block is the same block, and no scanline costs a
    ; microsecond more.  The whole price is here, once per quad: one extra
    ; RLCA, one ADD A,A, and reading two bytes instead of one.
    ;
    ; See pal.GRAIN for which pen the left pixel carries and why it is not
    ; the mortar.
    ld   a,(rq_kind)
    and  1
    rlca
    rlca
    rlca
    rlca
    ld   c,a
    ld   a,(rq_k)
    add  a,a
    add  a,c
    ld   c,a
    ld   b,0
    ld   hl,WRAMP
    add  hl,bc
    ld   e,(hl)                 ; E = the left byte of the pair
    inc  hl                     ; INC HL, not INC L: WRAMP is placed by
    ld   d,(hl)                 ; gentab.py and must be free to move page
                                ; DE is the fill word from here to the end


; ---------------------------------------------------------------------
;  BODY -- rows RC-jlo .. min(VP_H-1, RC+jlo), constant span [ba, bb].
;  One address and one entry byte, then src/render.asm's draw_rect
;  stepper: +&800 per scanline, -&4000+80 across a character row.
; ---------------------------------------------------------------------
    ld   a,(rq_bw)
    inc  a                      ; ROUND THE RUN OUTWARD, not inward: an odd
    srl  a                      ; byte width takes the byte to its LEFT,
    jp   z,rq_wedge             ; since PUSH walks backwards from the end.
    if RQ_PACED
    ; ---- WHAT ONE BODY SCANLINE COSTS, once per quad.  MEASURED 18.78 us
    ;      + 1.976 us/byte and the run is 2*npush bytes, so the charge is
    ;      C_BLINE + 4*npush -- 2 us a byte, one-sided like every other
    ;      constant in this engine.  A full chunk is that shifted left
    ;      RQ_BLOG, plus the hook C_CHUNK; the last, SHORT chunk of the
    ;      body is the only one that has to be multiplied out (rq_pmul).
    ld   l,a                    ; npush; A survives all of this
    ld   h,0
    add  hl,hl
    add  hl,hl
    ld   bc,C_BLINE
    add  hl,bc
    ld   (rq_bpl),hl
    repeat RQ_BLOG
    add  hl,hl
    rend
    ld   bc,C_CHUNK
    add  hl,bc
    ld   (rq_bchg),hl
    endif
    neg                         ; ba is never 0 when bw is odd -- see
                                ; project.asm, pf_bok -- so the extra byte
                                ; is always inside the viewport.
    add  a,MAXPUSH
    ld   (rq_be+1),a

    ld   a,(rq_jlo)
    ld   c,a
    ld   a,RQ_RC
    sub  c
    ld   (rq_r0),a              ; first row = RC - jlo
    ld   b,a
    ld   a,c
    add  a,RQ_RC                ; last row = RC + jlo, clipped to VP_H-1
    cp   VP_H
    jr   c,rq_blast
    ld   a,VP_H-1
rq_blast
    sub  b
    inc  a
    ld   (rq_bh),a              ; height, >= 1

    ld   a,(rq_r0)
    add  a,a
    ld   h,VPLINE/256
    ld   l,a
    ld   a,(hl)
    inc  l
    ld   h,(hl)
    ld   l,a
    ld   a,(rq_bb)
    add  a,l
    ld   l,a
    ld   a,h
rq_bufb
    adc  a,#C0                  ; buffer base; patched by raster_setbuf
    ld   h,a                    ; HL = one past the right end of the first row

    ld   a,(rq_r0)
    add  a,VP_Y
    and  7
    ld   c,a
    ld   a,8
    sub  c
    ld   c,a                    ; C = scanlines left in this character row
    ld   a,(rq_bh)
    if RQ_PACED
    ld   (rq_bleft),a           ; the chunk loop owns the row count now
    ld   ix,rq_bnext
    jp   rq_bchunk
    else
    ld   b,a
    ld   ix,rq_bnext
    endif
rq_bline
    ld   sp,hl
rq_be
    jp   PUSHBLK                ; low byte patched above
rq_bnext
    ld   a,h                    ; next scanline is +&800 ...
    add  a,8
    ld   h,a
    dec  c
    jr   z,rq_bwrap
rq_bcont
    djnz rq_bline
    if RQ_PACED
    jp   rq_bchunk              ; ...and THAT is where the vsync can fall
    else
    jp   rq_wedge
    endif
rq_bwrap                        ; ... except across a character row, where
    ld   c,8                    ; it is -&4000 + one row of 80 bytes
    ld   a,l
    add  a,SCR_W
    ld   l,a
    ld   a,h
    adc  a,#C0
    ld   h,a
    jr   rq_bcont


; ---------------------------------------------------------------------
;  WEDGES -- j = jlo+1 .. jhi.  Each j is ONE Bresenham step and TWO
;  scanlines: RC-j above the horizon and RC+j below it.
;
;  Registers for the whole loop:  DE the fill word, B the UPPER row index
;  doubled, C the moving edge in bytes, HL scratch, IX the upper row's
;  continuation.  The lower row's index is 2*VP_H - B, one SUB, so it does
;  not need a register of its own -- which is what frees C for the moving
;  edge and takes the Bresenham step down from nine microseconds to one.
;
;  Three sites are self-modified per QUAD rather than branched per
;  scanline: rq_wspan (which end of the span is pinned), rq_ea1/rq_ea2
;  (where the run's right end comes from) and rq_dir.
; ---------------------------------------------------------------------
rq_wedge
    ld   a,(rq_wn)              ; iterations = jhi - jlo, counted at setup
    or   a
    jp   z,rq_end
    if RQ_PACED
    ld   (rq_wleft),a           ; the chunk loop owns the pair count now
    endif

    ld   a,(rq_jlo)
    inc  a                      ; j = jlo+1
    ld   c,a
    ld   a,RQ_RC
    sub  c
    add  a,a
    ld   b,a                    ; B = 2*(RC-j), the upper row's index
    ld   a,(rq_blo)
    ld   c,a                    ; C = the moving edge, at the SHORT end
    ld   ix,rq_ubk
    if RQ_PACED
    jp   rq_wchunk
    endif

rq_wloop
    ; --- one Bresenham step: acc += 16*D; while acc >= 0: acc -= N, C += dir
    ;     16*D needs both halves patched, which is the same three
    ;     microseconds the carry-only version cost.
    ld   hl,(rq_acc)
    ld   a,l
rq_dl
    add  a,0                    ; + 16*D low   (patched)
    ld   l,a
    ld   a,h
rq_dh
    adc  a,0                    ; + 16*D high  (patched)
    ld   h,a
rq_wchk
    bit  7,h
    jr   nz,rq_wstep_done
    ld   a,l
rq_nl
    add  a,0                    ; + (-N)  (patched)
    ld   l,a
    ld   a,h
rq_nh
    adc  a,0
    ld   h,a
rq_dir
    inc  c                      ; patched INC C / DEC C
    jr   rq_wchk
rq_wstep_done
    ld   (rq_acc),hl

    ; --- span width.  Three bytes, patched per quad to whichever of
    ;       LD A,bhi : SUB C          (the right end is pinned)
    ;       LD A,C   : SUB bhi        (the left end is pinned)
    ;     this quad needs.  Both are three microseconds.
rq_wspan
    db   #3E,#00,#91

    inc  a                      ; ceil, not floor: the odd byte is taken on
    srl  a                      ; the LEFT, which is where the run has room
    jr   z,rq_wnext             ; under two bytes: nothing to push
    neg
    add  a,MAXPUSH
    ld   (rq_eu+1),a
    ld   (rq_el+1),a

    ; --- the scanline ABOVE the horizon ---
    ld   h,VPLINE/256
    ld   l,b
    ld   a,(hl)
    inc  l
    ld   h,(hl)
    ld   l,a
rq_ea1
    db   #79,#00                ; LD A,C : NOP   or   LD A,bhi  (patched)
    add  a,l
    ld   l,a
    ld   a,h
rq_bufu
    adc  a,#C0
    ld   h,a
    ld   sp,hl
rq_eu
    jp   PUSHBLK                ; low byte patched above; returns via IX
rq_ubk

    ; --- and its mirror BELOW.  j = RC (the top row of the viewport) has
    ;     no partner: row RC+RC = VP_H is off the bottom.  B = 0 says so.
    ld   a,b
    or   a
    jr   z,rq_wnext
    ld   h,VPLINE/256
    ld   a,(VP_H*2)&255         ; lower row index = 2*VP_H - B
    sub  b
    ld   l,a
    ld   a,(hl)
    inc  l
    ld   h,(hl)
    ld   l,a
rq_ea2
    db   #79,#00
    add  a,l
    ld   l,a
    ld   a,h
rq_bufl
    adc  a,#C0
    ld   h,a
    ld   sp,hl
rq_el
    jp   PUSHBLK_L              ; a block whose tail is JP rq_wnext

rq_wnext
    ld   a,b
    sub  2
    ld   b,a
    ld   hl,rq_wn
    dec  (hl)
    jp   nz,rq_wloop
    if RQ_PACED
    jp   rq_wchunk              ; ...and THAT is where the vsync can fall
    endif

rq_end
    ld   sp,(rq_sp)
    ld   hl,(rq_next)
    ret


; ------------------------------------------------------------ helpers ---
; A = (HL >> 4), for HL < 4096.  HL is left shifted.
rq_sh4
    ld   a,l
    srl  h
    rra
    srl  h
    rra
    srl  h
    rra
    srl  h
    rra
    ret


; ----------------------------------------------------------- variables ---
; The record, copied in one LDIR -- these SIX must stay in this order and
; adjacent, because that is the layout kernel.asm writes.
rq_blo      db 0                ; the shorter endpoint's byte column
rq_bhi      db 0                ; the taller one's (the pinned wedge edge)
rq_hlo      dw 0                ; half height at the shorter endpoint, Q12.4
rq_hhi      dw 0                ; ...and at the taller one
rq_kind     db 0
rq_k        db 0

rq_bb       db 0                ; max(ba, bb): the right end of the body run
rq_bw       db 0                ; body width in bytes = |bhi - blo|
rq_bh       db 0                ; body height in scanlines
rq_d        db 0                ; Bresenham numerator: |bhi - blo| in BYTES,
                                ; or half that in the rq_lt0 WORD shape
rq_jlo      db 0                ; last body row, counted out from the horizon
rq_jhi      db 0                ; last wedge row (clipped to the viewport)
rq_r0       db 0
rq_acc      dw 0
rq_wn       db 0
rq_e        db 0                ; right end of the current wedge run
rq_next     dw 0
rq_sp       dw 0

    if RQ_PACED
rq_bleft    db 0                ; body scanlines not yet drawn
rq_bn       db 0                ; ...and how many of them this chunk draws
rq_bpl      dw 0                ; the charge for ONE body scanline
rq_bchg     dw 0                ; ...and for a full RQ_BCH of them, + C_CHUNK
rq_wleft    db 0                ; wedge PAIRS not yet drawn
rq_wst      dw 0                ; ...and the edge-step allowance, C_WSTEP*w
rq_mul      dw 0                ; rq_pmul's per-unit operand
    endif


; ---------------------------------------------------------------------
;  The unrolled PUSH block.  Page aligned and MAXPUSH long, so entering
;  at low byte (MAXPUSH - npush) executes exactly npush pushes and then
;  falls into the return.  Selecting a run length is one LD and one JP.
; ---------------------------------------------------------------------
    align 256
PUSHBLK
    repeat MAXPUSH
    push de
    rend
PUSHBLK_END
    jp   (ix)

; The wedge's LOWER scanline gets a block of its own whose tail is a
; direct JP: that is one page of RAM in exchange for the two LD IX,nn a
; shared block would need on every wedge scanline pair.
    align 256
PUSHBLK_L
    repeat MAXPUSH
    push de
    rend
    jp   rq_wnext

    endif                       ; VPCOL == 0

; ---------------------------------------------------------------------
;  VPLINE -- viewport row -> screen offset, built by raster_init.
;  Page aligned so the lookup is LD H,page / LD L,row*2.
;  SHARED: both renderers index it, so it is outside the VPCOL guard.
; ---------------------------------------------------------------------
    align 256
VPLINE
    defs VP_H*2

    if RQ_PACED
; =====================================================================
;  THE MID-QUAD YIELD
;
;  These three live HERE, in the 64 bytes VPLINE leaves spare on its own
;  page, because everything above them is page-aligned and code inserted
;  before PUSHBLK costs a whole 256-byte page of padding.
;
;  SP IS THE SCREEN POINTER inside a fill, so a hook that CALLs anything
;  has to borrow a real stack first.  raster_quad already parks the
;  caller's SP in (rq_sp) -- that is the same trick bg.asm, hud_rect and
;  project.asm's ps_fill use to get SP back at the end -- so the hooks
;  reload it, push what they need BELOW the caller's return address, and
;  let the fill loops put the screen back themselves: rq_bline and the
;  wedge's two scanlines both do LD SP,HL before they push a pixel.
;  Nothing here has to restore SP.
;
;  WHAT IS CHARGED IS WHAT HAS BEEN DRAWN -- the chunk in front of the
;  hook, not the whole quad.  Charging the quad up front (which is what
;  main3.asm:pace_quad used to do, and it is 141 us a quad lighter for
;  losing the job) would put the yield at the head of a 12 ms unit and
;  leave the accumulator believing the interval was full for the whole of
;  it: the yield would land in the wrong place and the interval after it
;  would be short by exactly the amount the quad had already spent.
;
;  cost_unit preserves AF, DE, HL and IX, but its yield path goes through
;  wait_vsync, which loads B with #F5 -- so BC is saved by hand.  C is
;  the character-row countdown in the body and the MOVING EDGE in the
;  wedge; losing it would corrupt the picture, not just the timing.
; =====================================================================

; ---------------------------------------------------------------------
;  rq_bchunk -- charge the next RQ_BCH body scanlines and draw them.
;  Entered with HL = the screen pointer, C = scanlines left in the
;  character row, DE = the fill word, IX = rq_bnext.
; ---------------------------------------------------------------------
rq_bchunk
    ld   sp,(rq_sp)             ; SP is the SCREEN: borrow the real stack
    ld   a,(rq_bleft)
    or   a
    jp   z,rq_wedge
    push bc                     ; C = scanlines to the character-row wrap
    push de                     ; the fill word
    push hl                     ; the screen pointer
    cp   RQ_BCH
    jr   c,rq_bcn
    ld   a,RQ_BCH
rq_bcn
    ld   (rq_bn),a
    ld   c,a
    ld   a,(rq_bleft)
    sub  c
    ld   (rq_bleft),a
    ld   a,c
    cp   RQ_BCH
    ld   bc,(rq_bchg)           ; the full-chunk charge, shifted at setup
    jr   z,rq_bcgo
    ld   hl,(rq_bpl)            ; a SHORT chunk -- the last one -- has to
    ld   (rq_mul),hl            ; be multiplied out, once per quad
    call rq_pmul
    ld   b,h
    ld   c,l
rq_bcgo
    call cost_unit
    pop  hl
    pop  de
    pop  bc
    ld   a,(rq_bn)
    ld   b,a
    jp   rq_bline

; ---------------------------------------------------------------------
;  rq_wchunk -- charge the next RQ_WCH wedge scanline PAIRS and draw them.
;  Entered with B = the upper row index doubled, C = the moving edge,
;  DE = the fill word, IX = rq_ubk.
;
;  THE WIDTH IT CHARGES IS THE ONE AT THE FIRST ROW OF THE CHUNK, taken
;  through a second copy of the patched span site.  The moving edge only
;  ever walks TOWARDS the pinned one, so the wedge narrows monotonically
;  and that width bounds every row in the chunk -- which is what makes
;  the charge one-sided without measuring each row.
;
;  AND THE SAME WIDTH BOUNDS THE BRESENHAM.  An edge step is 19.27 us
;  MEASURED, and the wedge takes exactly D of them over its whole travel
;  -- but WHERE is not known: a wedge whose two ends differ by one row
;  takes all D in that one pair.  They cannot therefore be charged per
;  pair, and charging all D up front does not work either, because a
;  yield between the charge and the work resets the accumulator and
;  STRANDS them: the interval that then does the stepping has no estimate
;  covering it, which is exactly the failure this whole file is about.
;  So each chunk carries C_WSTEP * w as well, and that is sound for the
;  same reason the width bound is: the edge cannot step past the pinned
;  column, so it cannot take more than w steps from here on, let alone
;  in this chunk.  It over-charges a tall wedge -- the sum of w over its
;  chunks is bigger than D -- and that is the price of not stranding.
; ---------------------------------------------------------------------
rq_wchunk
    ld   sp,(rq_sp)
    ld   a,(rq_wleft)
    or   a
    jp   z,rq_end
    push bc                     ; C = the moving edge
    push de                     ; the fill word
    cp   RQ_WCH
    jr   c,rq_wcn
    ld   a,RQ_WCH
rq_wcn
    ld   (rq_wn),a              ; pairs this chunk; the loop counts it down
    ld   e,a
    ld   a,(rq_wleft)
    sub  e
    ld   (rq_wleft),a
rq_wspan2
    db   #3E,#00,#91            ; patched with rq_wspan -> A = the span
    ld   l,a
    ld   h,0
    add  hl,hl
    add  hl,hl                  ; 4*w: 2 us a byte, two scanlines a pair
    ld   b,h
    ld   c,l
    add  hl,hl
    add  hl,hl                  ; 16*w
    add  hl,bc                  ; 20*w = C_WSTEP*w, the edge steps this
    ld   (rq_wst),hl            ; chunk could possibly take
    ld   h,b
    ld   l,c                    ; back to 4*w
    ld   bc,C_WPAIR
    add  hl,bc                  ; HL = what one pair of THIS chunk costs
    ld   a,e
    cp   RQ_WCH
    jr   nz,rq_wcpart
    repeat RQ_WLOG
    add  hl,hl
    rend
    ld   bc,C_CHUNK
    add  hl,bc
    jr   rq_wcgo
rq_wcpart
    ld   (rq_mul),hl
    call rq_pmul
rq_wcgo
    ld   bc,(rq_wst)
    add  hl,bc
    ld   b,h
    ld   c,l
    call cost_unit
    pop  de
    pop  bc
    jp   rq_wloop

; ---------------------------------------------------------------------
;  rq_pmul -- A = n (0..16), (rq_mul) = one unit -> HL = C_CHUNK + n*unit.
;  Five bits, unrolled MSB first.  Clobbers AF DE HL; BC and IX survive,
;  which is what the two hooks above need.
;
;  It ends at C_CHUNK + C_PMUL rather than at zero, so the hook charges
;  for ITSELF as well as for the work -- every chunk is followed by
;  exactly one more hook -- and a SHORT chunk, which is the only kind
;  that comes through here, charges the extra that this multiply and the
;  end-of-body or end-of-quad transition behind it cost.
; ---------------------------------------------------------------------
rq_pmul
    ld   de,(rq_mul)
    ld   hl,0
    add  a,a
    add  a,a
    add  a,a                    ; n into bits 7..3, consumed MSB first
    repeat 5
    add  hl,hl
    add  a,a
    jr   nc,$+3
    add  hl,de
    rend
    ld   de,C_CHUNK+C_PMUL      ; a SHORT chunk pays for this multiply too
    add  hl,de
    ret
    endif


    if COURSES
; =====================================================================
;  raster_joint -- THE COURSE JOINTS.
;
;  IT IS ASSEMBLED ONLY WHEN COURSES IS 1.  It used to be assembled
;  either way, on the argument that flipping COURSES was then a one-line
;  change -- but it is 500 bytes, it is the largest single block of dead
;  code in the build at COURSES = 0, and engine2/src/gun.asm needed the
;  room.  Flipping COURSES back on is STILL a one-line change here; what
;  it now costs is that the joints and the weapon cannot both be had (the
;  joints want pen 14, which is the weapon's slide -- gentab.py asserts
;  it) and that the body would no longer fit under BUCKETS.  Nothing was
;  deleted: the code below is exactly what it was.
;
;  500 BYTES OF CODE, AND WHERE THEY CAME FROM.  main3.asm's body ran to
;  #232C against march working RAM at #2400, so this did not fit; the
;  march's buckets, flood stack and three page-aligned tables moved up
;  three pages into the dead #3300-#35FF hole between MARK and QUADS,
;  which is exactly the move main3.asm's memory map says to make when the
;  `assert game_end <= BUCKETS` fires.  Nothing else changed: QUADS, the
;  stack and bank 4 are where they were.
;
;  ------------------------------------------------------------------
;  THREE COURSES, AND THE COUNT MUST BE ODD
;  ------------------------------------------------------------------
;  The camera sits at wall mid-height and cannot pitch, so a course
;  boundary at v = 0.5 projects to a DEAD HORIZONTAL line across the
;  whole screen -- the horizon row itself -- and reads as a rendering
;  artefact, not as masonry.  An ODD count puts the boundaries either
;  side of eye level, at v = 1/3 and 2/3, where they converge on the
;  vanishing point the way real courses do.  Verified by eye in
;  prototype/free-angle/stone.py: 2 and 4 look broken, 3 looks right.
;
;  ------------------------------------------------------------------
;  WHY IT IS AFFORDABLE: NOTHING IS RE-PROJECTED
;  ------------------------------------------------------------------
;  At a fixed screen x the projection of wall height is LINEAR, so the
;  boundary's y at each end of the face is a straight interpolation
;  between that end's own top and bottom y.  This engine's record is
;  already written about the horizon -- ytop = CY - h, ybot = CY + h --
;  so the interpolation collapses to
;
;      v = 1/3   ->   y = CY - h/3
;      v = 2/3   ->   y = CY + h/3
;
;  the SAME distance h/3 from the horizon, above and below.  Both joints
;  of a face are therefore one pass of the same mirrored row loop the
;  wedge already uses, over the line u = h(x)/3, and the only new number
;  in the whole file is a divide by three -- a DIV3 lookup in bank 4.
;  No march, no projection, no new face, no new quad record.
;
;  AND IT IS NOT AN UNDERPASS.  Painting the face in mortar and insetting
;  the stones on top -- what the Python preview did -- doubles the fill.
;  raster_quad draws the face EXACTLY as before and this overdraws two
;  thin bands, so the fill goes up by a few per cent, not by 100.
;
;  ------------------------------------------------------------------
;  THE BAND, AND WHERE ITS THICKNESS COMES FROM
;  ------------------------------------------------------------------
;  Rows are u = 16j, so the line crosses row j at the column where
;  h(x) = 48j: the Bresenham is the wedge's, with the numerator stepping
;  48*D per row instead of 16*D and the denominator N = hhi - hlo
;  unchanged.  j0 = hlo/48 and j1 = hhi/48 are its two ends.
;
;  The span painted on row r is [E(r-1), E(r+1)] -- the leading edge C
;  runs one row AHEAD and the trailing edge P one row BEHIND -- and the
;  loop runs one row past j1.  That single rule gives the joint two
;  scanlines of thickness whichever way it is raked: a square-on wall
;  (N = 0, one crossing row) gets two full-width scanlines, and a steeply
;  raked one gets one scanline per row but two rows' worth of x, which is
;  the same perpendicular thickness.  P lagging is also what makes the
;  spans TILE: their union is the whole face width, with no holes at the
;  ends, because E is clamped to blo before j0 and to bhi after j1.
;
;  ------------------------------------------------------------------
;  LEVEL OF DETAIL, AND THE MORTAR PEN
;  ------------------------------------------------------------------
;  No joints past k = JOINT_KMAX, straight off the quad's own depth byte.
;  Past about three and a half cells a whole course is thinner than the
;  joint, so the joints stop being masonry and become noise.
;
;  The mortar is pal.MORTAR, ONE dedicated dark pen at every depth, not
;  two steps down the wall ramp: that ramp runs grey -> bright blue and
;  gets MORE saturated as it recedes, so joints drawn from it glow
;  instead of receding.  See pal.py for why it had to be firmware ink 1.
;
;  IN   HL = the quad record raster_quad has just painted
;  OUT  its two course boundaries overdrawn.  SP restored.
;  Clobbers AF BC DE HL IX and HL is NOT preserved.
; =====================================================================

JOINT_KMAX  equ 3               ; the LOD cut, in L1 cells
J_OFF       equ (3*RQ_RC+3)*16  ; the first half height whose joint row is
                                ; past the horizon -- and the first DIV3
                                ; index that would be out of range

raster_joint
    ld   (rj_sp),sp
    push hl
    ld   de,6
    add  hl,de
    ld   a,(hl)                 ; +6 kind -- a door is not masonry
    inc  hl
    or   a
    jr   nz,rj_no
    ld   a,(hl)                 ; +7 k    -- the LOD key
    cp   JOINT_KMAX+1
    jr   c,rj_go
rj_no
    pop  hl
    ret
rj_go
    pop  hl
    ld   de,rj_blo
    ld   bc,QRECSZ
    ldir

    ; ---- D, the direction, and where the leading edge has to stop.
    ;      bA = blo, the SHORT end, is where it starts; bB = bhi, the
    ;      TALL end, is where the line runs out of face.
    ld   a,(rj_blo)
    ld   c,a
    ld   a,(rj_bhi)
    ld   b,a
    sub  c
    ret  z                      ; a face under a byte wide paints nothing,
    jr   c,rj_dleft             ; so its joints must not either
    ld   (rj_d),a
    ld   a,#0C                  ; INC C: the edge walks RIGHT, so the right
    ld   (rj_dir),a             ; end of the span is C and the trailing
    ld   hl,#0079               ; LD A,C : NOP    edge P is the SUB operand
    ld   (rj_rget),hl
    ld   a,#D6                  ; SUB n
    ld   (rj_span),a
    ld   hl,rj_span+1
    ld   a,b
    inc  a                      ; CP bB+1 / JR C -- C must not pass bB
    ld   (rj_cpv+1),a
    ld   a,#38
    jr   rj_ddone
rj_dleft
    neg
    ld   (rj_d),a
    ld   a,#0D                  ; DEC C: the edge walks LEFT, so the right
    ld   (rj_dir),a             ; end is P and P is the LD A,n operand
    ld   a,#3E                  ; LD A,n
    ld   (rj_rget),a
    ld   hl,#0091               ; SUB C : NOP
    ld   (rj_span),hl
    ld   hl,rj_rget+1
    ld   a,b                    ; CP bB / JR NC
    ld   (rj_cpv+1),a
    ld   a,#30
rj_ddone
    ld   (rj_cc),a
    ld   (rj_pw+1),hl           ; ...and THAT is the byte the row loop
    ld   a,b                    ; rewrites with the trailing edge
    ld   (rj_cset+1),a

    ; ---- j0 = hlo/48.  Past the horizon there is no viewport left.
    ld   hl,(rj_hlo)
    ld   de,J_OFF
    or   a
    sbc  hl,de
    ret  nc
    add  hl,de
    call rq_sh4                 ; A = hlo>>4, <= 3*RC+2
    ld   h,DIV3/256
    ld   l,a
    ld   a,(hl)
    ld   (rj_j0),a

    ; ---- the last row is hhi/48 PLUS ONE, the thickening row, clipped
    ;      to the horizon row.
    ld   hl,(rj_hhi)
    ld   de,J_OFF
    or   a
    sbc  hl,de
    ld   a,RQ_RC
    jr   nc,rj_j1
    add  hl,de
    call rq_sh4
    ld   h,DIV3/256
    ld   l,a
    ld   a,(hl)
    inc  a
    cp   RQ_RC+1
    jr   c,rj_j1
    ld   a,RQ_RC
rj_j1
    ld   hl,rj_j0
    sub  (hl)
    inc  a
    ld   (rj_n),a               ; rows to paint, >= 1

    ; ---- f = hlo - 48*j0, and the accumulator's D*f bias.  Row j means
    ;      h = 48*j, which is f BELOW hlo, exactly as the wedge's f is
    ;      hlo & 15 below it.
    ld   a,(hl)
    ld   l,a
    ld   h,0
    add  hl,hl
    add  hl,hl
    add  hl,hl
    add  hl,hl
    ld   d,h
    ld   e,l                    ; DE = 16*j0
    add  hl,hl
    add  hl,de                  ; HL = 48*j0
    ex   de,hl
    ld   hl,(rj_hlo)
    or   a
    sbc  hl,de                  ; HL = f, 0..47
    ld   a,(rj_d)
    ld   e,a
    ld   d,0                    ; DE = D
    ld   a,l                    ; A  = f, six bits, consumed MSB first --
    ld   hl,0                   ; a loop, not math.asm's mul8x8u, because
    or   a                      ; tst_rast.asm includes this file ALONE
    jr   z,rj_mdone
    add  a,a
    add  a,a
    ld   b,6
rj_ml
    add  hl,hl
    add  a,a
    jr   nc,rj_mnb
    add  hl,de
rj_mnb
    djnz rj_ml
rj_mdone
    push hl                     ; D*f

    ; ---- -N, and the 48*D the accumulator steps per row
    ld   de,(rj_hhi)
    ld   hl,(rj_hlo)
    or   a
    sbc  hl,de                  ; HL = -N <= 0
    ld   a,h
    or   l
    jr   nz,rj_slope
    ; --- N == 0: the wall is seen SQUARE ON and the boundary is one
    ;     horizontal line the full width of the face.  Park the leading
    ;     edge at the tall end, leave the trailing one at the short end
    ;     and STOP UPDATING IT, so both rows get the whole width.  -1
    ;     rather than 0 keeps the accumulator negative for ever, which is
    ;     what stops the step loop spinning on a zero denominator.
    dec  hl
    ld   bc,0
    ld   a,(rj_bhi)
    ld   (rj_c0),a
    ld   a,rj_pdone-rj_pupd-2
    jr   rj_pset
rj_slope
    ld   a,(rj_blo)
    ld   (rj_c0),a
    push hl
    ld   a,(rj_d)
    ld   l,a
    ld   h,0
    add  hl,hl
    add  hl,hl
    add  hl,hl
    add  hl,hl
    ld   d,h
    ld   e,l                    ; DE = 16*D
    add  hl,hl
    add  hl,de                  ; HL = 48*D
    ld   b,h
    ld   c,l
    pop  hl                     ; HL = -N
    ld   a,rj_pgo-rj_pupd-2
rj_pset
    ld   (rj_pupd+1),a
    ld   a,c
    ld   (rj_dl+1),a
    ld   a,b
    ld   (rj_dh+1),a
    ld   a,l
    ld   (rj_nl+1),a
    ld   a,h
    ld   (rj_nh+1),a
    pop  de                     ; DE = D*f
    or   a
    sbc  hl,de
    ld   (rj_acc),hl            ; acc0 = -N - D*f

    ; ---- the row loop's registers: DE the mortar word, C the leading
    ;      edge, B the upper row's VPLINE index doubled.
    ld   a,(MORTAR)
    ld   d,a
    ld   e,a
    ld   a,(rj_c0)
    ld   c,a
    ld   a,(rj_blo)
    ld   hl,(rj_pw+1)
    ld   (hl),a                 ; the trailing edge starts at the short end
    ld   a,(rj_j0)
    ld   b,a
    ld   a,RQ_RC
    sub  b
    add  a,a
    ld   b,a

rj_loop
    ld   a,c
    ld   (rj_t),a               ; E(r): next row's trailing edge

    ; --- one Bresenham step: acc += 48*D; while acc >= 0: acc -= N, C += dir
    ld   hl,(rj_acc)
    ld   a,l
rj_dl
    add  a,0
    ld   l,a
    ld   a,h
rj_dh
    adc  a,0
    ld   h,a
rj_chk
    bit  7,h
    jr   nz,rj_stepdone
    ld   a,l
rj_nl
    add  a,0
    ld   l,a
    ld   a,h
rj_nh
    adc  a,0
    ld   h,a
rj_dir
    inc  c                      ; patched INC C / DEC C
    jr   rj_chk
rj_stepdone
    ld   (rj_acc),hl

    ; --- the leading edge is EXTRAPOLATED a row past the end of the line
    ;     -- that is where the thickness comes from -- so it has to be
    ;     stopped at the tall end or the joint would run off the face.
    ld   a,c
rj_cpv
    cp   0                      ; patched: bB+1 (walking right) or bB
rj_cc
    jr   c,rj_cok               ; patched: JR C / JR NC
rj_cset
    ld   c,0                    ; patched: bB
rj_cok

    ; --- the span.  Two patched slots, exactly like the wedge's: the
    ;     first leaves the RIGHT end in A, the second turns it into the
    ;     width.  Which of C and P is the right end is fixed per face by
    ;     the direction, so neither costs a branch.
rj_rget
    db   #79,#00                ; LD A,C : NOP   |   LD A,P
    ld   (rj_r),a
rj_span
    db   #D6,#00                ; SUB P          |   SUB C : NOP

    or   a
    jr   nz,rj_w1
    inc  a                      ; a steep joint can move less than a byte
rj_w1                           ; in two rows; give it one anyway
    ld   l,a
    ld   a,(rj_r)
    sub  l                      ; A = the left end
    jr   nz,rj_lok
    bit  0,l
    jr   z,rj_lok
    inc  l                      ; the odd byte is taken on the LEFT by
    ld   a,(rj_r)               ; npush and there is no column -1, so
    inc  a                      ; widen to the RIGHT instead
    ld   (rj_r),a
rj_lok
    ld   a,l
    inc  a
    srl  a                      ; npush = (w+1)>>1

; ---- AND NOW MAKE THAT FIT.  The row writes [rj_r - 2*npush, rj_r-1], so
;      it starts left of column 0 whenever rj_r < 2*npush.
;
;      The test above is not enough and the comment it used to carry --
;      "bhi is even when a face touches column 0, so this can never leave
;      the viewport" -- was reasoning about the FACE.  It does not hold for
;      the JOINT, because the joint's two edges COLLAPSE ONTO EACH OTHER on
;      its last row: the leading edge is extrapolated one row past the end
;      of the line to give the band its thickness, the trailing edge has
;      already arrived, the span comes out zero wide, `inc a` above forces
;      it to one byte, and npush then rounds that byte OUTWARD -- to the
;      left, where there is no column.  The zero test only catches the odd
;      case; the even one walks straight past it.
;
;      MEASURED.  raster_quad alone wrote 0 bytes outside the viewport over
;      168 screens.  raster_frame -- the same quads plus their joints --
;      wrote 2, both at viewport column -1, on the two mirrored outermost
;      rows of a face whose tall end sits at column 0.  On the disc that is
;      a mortar-coloured byte blinking in the HUD's black margin as you
;      turn past such a wall.  emu_rast.py reported it as 3 of 180 screens.
;
;      Widening to the RIGHT rather than dropping a push keeps the joint
;      the same thickness, and there is always room: this can only fire
;      when rj_r is within two bytes of column 0.
;      rastermodel.py:joint_runs carries the same rule.
    ld   l,a                    ; L = npush
    add  a,a                    ; A = 2*npush, the bytes this row writes
    ld   h,a
    ld   a,(rj_r)
    cp   h
    jr   nc,rj_rok
    ld   a,h
    ld   (rj_r),a               ; ...so the run starts exactly at column 0
rj_rok
    ld   a,l
    neg
    add  a,MAXPUSH
    ld   (rj_eu+1),a
    ld   (rj_el+1),a

    ; --- the scanline ABOVE the horizon ---
    ld   h,VPLINE/256
    ld   l,b
    ld   a,(hl)
    inc  l
    ld   h,(hl)
    ld   l,a
    ld   a,(rj_r)
    add  a,l
    ld   l,a
    ld   a,h
rj_bufu
    adc  a,#C0                  ; buffer base; patched by raster_setbuf
    ld   h,a
    ld   sp,hl
    ld   ix,rj_ubk
rj_eu
    jp   PUSHBLK
rj_ubk

    ; --- and its mirror BELOW.  Row RC+RC is off the bottom; B = 0 says so.
    ld   a,b
    or   a
    jr   z,rj_pupd
    ld   h,VPLINE/256
    ld   a,(VP_H*2)&255
    sub  b
    ld   l,a
    ld   a,(hl)
    inc  l
    ld   h,(hl)
    ld   l,a
    ld   a,(rj_r)
    add  a,l
    ld   l,a
    ld   a,h
rj_bufl
    adc  a,#C0
    ld   h,a
    ld   sp,hl
    ld   ix,rj_pupd
rj_el
    jp   PUSHBLK

rj_pupd
    jr   rj_pgo                 ; patched to skip when N == 0
rj_pgo
    ld   a,(rj_t)
rj_pw
    ld   (0),a                  ; target patched: rj_span+1 or rj_rget+1
rj_pdone
    ld   a,b
    sub  2
    ld   b,a
    ld   hl,rj_n
    dec  (hl)
    jp   nz,rj_loop
    ld   sp,(rj_sp)
    ret

; ----------------------------------------------------- joint variables ---
rj_blo      db 0                ; the record, copied in one LDIR
rj_bhi      db 0
rj_hlo      dw 0
rj_hhi      dw 0
rj_kind     db 0
rj_k        db 0

rj_d        db 0                ; |bhi - blo|, the Bresenham numerator
rj_j0       db 0                ; hlo/48: the row the boundary starts on
rj_n        db 0                ; rows left
rj_c0       db 0                ; where the leading edge starts
rj_t        db 0                ; E(r), on its way to becoming P
rj_r        db 0                ; the right end of this row's run
rj_acc      dw 0
rj_sp       dw 0
    endif
