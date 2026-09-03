; =====================================================================
;  engine2/src/costcol.inc -- THE COLUMN RENDERER'S CHARGE.  ONE file.
;
;  These constants are what engine2/src/rastcol.asm hands cost_unit, and
;  they are included by BOTH builds that take those hooks -- main3.asm
;  (the disc) and engine2/test/tst_rcol.asm (the atomic harness) -- and
;  PARSED by engine2/tools/pacemodel.py, which is how colmodel.charge and
;  pacescan.py replay them.  They used to live in main3.asm with a copy
;  in tst_rcol.asm, which is the same two-copies trap C_BG fell into at
;  the viewport change: both copies wrong in the same way, and the model
;  agreeing with the harness because it read the one the disc was not
;  running.
;
;  THE SHAPE: ONE HOOK PER PAIR, AT THE TOP, CHARGING AN UPPER BOUND.
;
;  The first shipped shape charged a pair AFTER its setup -- the u
;  division, the two Bresenham probes, the CTABT lookup and the row
;  range all ran before the hook -- and room-then-charge bills the work
;  in front of a hook to the hook BEFORE it, so all of that setup was
;  billed to whatever came earlier, often a 60 us C_CEDGE.  MEASURED by
;  emu_rcol.py's `atomic`, which sweeps the abort hook and differences
;  consecutive prefixes:
;
;      hook 33: charged     60   MEASURED  1883   UNDER by 1823 us
;      hook 47: charged     60   MEASURED  1673   UNDER by 1613 us
;      hook 22: charged   3362   MEASURED  5101   UNDER by 1739 us
;
;  An under-charged interval overruns the 19968 us period, the yield
;  lands past the vsync edge, and the frame silently takes another
;  period: the booted disc read [10, 11, 13] vsyncs against a budget of
;  10.  A per-FRAME one-sided check cannot see this by construction.
;
;  So every hook now runs BEFORE the work it pays for, and every charge
;  is an upper bound on the interval that follows it, by construction:
;
;    C_CFRAME   raster_colframe, before its own setup, once a frame
;    C_CFACE    the TOP of rc_face, before the record is even read --
;               so every record pays it, degenerate ones too, and it is
;               FLAT because np is not known yet
;    per PAIR in the face's range, drawn or skipped, in rc_pairloop:
;      skipped  C_CSKIP -- the pair's rc_pnext step, the next pair's
;               occlusion test and the next pair's own charge arithmetic
;      drawn    C_COLS + C_CBAND*bands + C_COLR*rows + C_CEDGE*edges,
;               where bands/rows/edges are UPPER BOUNDS computed in
;               rc_charge from what is known before any setup runs:
;               (rc_h) +- (rc_hq)+1 bounds the two byte columns' half
;               heights, and the pair's own rc_up/rc_dn bound everything
;               by the rows still free.  It over-charges occluded pairs,
;               which is the safe direction.  C_CBAND is 0 and C_CEDGE is
;               8*C_COLR, so rc_charge evaluates the whole bound as
;               C_COLS + C_COLR*(rows + 8*edges) -- ONE multiply, and by
;               shifts.  rastcol.asm asserts all three relations.
;    C_CSKIP + C_CSTEP*delta   rc_pnext's CLAMPED step (delta 1..3
;               single columns instead of one whole-pair add), charged
;               by its own hook in rc_slow because it happens at most
;               twice a face and folding its worst into C_CSKIP would
;               over-charge every skipped pair by two thirds
;
;  colmodel.charge emits the SAME UNITS IN THE SAME ORDER -- the model
;  and the asm must take the same unit SEQUENCE, not just the same
;  total, or `atomic` cross-checks the wrong pairs (it has caught
;  exactly that once already: 28 model units against 54 machine hooks).
;
;  AND THE BOUND IS SHAPED, NOT FLAT, because an over-charge costs
;  periods exactly as an under-charge does.  A flat per-pair charge of
;  1100 -- one number bounding both a 96-scanline two-band pair and a
;  one-row one-band pair, billing the full 2j+1 row range -- put the
;  worst charged frame at 185134 us, eleven vsync periods for about
;  seven periods of work.  The min() against the rows still free is
;  what keeps the upper bound from re-billing, face after face, rows a
;  nearer face already owns.
;
;  (history) THE MEASUREMENT UNDER C_CBAND / C_COLR: on the booted
;  disc, a sweep varying the band count and the scanline count
;  independently -- full viewport, quarter height, one row tall
;  (emu_rcol.py):
;
;      a pair drawing TWO bands   1015 us + 19.48 per scanline
;      a pair drawing ONE band     650 us + 19.48 per scanline
;
;  = 285 fixed per pair and 365 per band.  The ten instructions of the
;  fill unit alone are 20.25 us (emu_byte.py, `colpair`); the slope
;  comes out under that because COLBLK amortises the character-row
;  re-entry in its own IXL countdown.  One EDGE row (rc_edge's
;  rebuild-the-address loop, one to three rows a run, MEASURED 82 edge
;  bytes a frame against 3600 filled ones) is bounded by C_CEDGE.
; =====================================================================
;  EVERY NUMBER BELOW IS MEASURED, by
;
;      python3 engine2/tools/emu_rcol.py fit [nstates]
;
;  which times EVERY INTERVAL of every hook -- not every frame -- and
;  solves for the smallest constants that cover all of them.  It is a
;  covering problem and not a regression: the rule is est >= actual for
;  every unit, so the fit takes the largest residual in each hook class
;  rather than the mean.  Re-run it after ANY change to rastcol.asm and
;  paste the answer here; `atomic` on a different seed is the check that
;  the sample was big enough.
C_CFRAME    equ 600         ; raster_colframe's own setup, once a frame:
                            ; the two LDIRs that clear the occlusion
                            ; state, the bank switch and the walk's head.
                            ; MEASURED 389 with no moving face on the
                            ; list -- and 490 WITH ONE, because a
                            ; non-empty overlay list means the second
                            ; pass is entered at all.  450 covered the
                            ; first and was 40 us short of the second.
                            ;
                            ; Found the same way C_COLSO was: emu_rcol's
                            ; atomic had never drawn a moving face, so
                            ; the only frame it ever timed was the one
                            ; with one pass in it.  600 clears 490 by
                            ; 110, and it is charged ONCE a frame -- 150
                            ; us more out of 194560, which is 0.08%.
C_CFACE     equ 1520        ; rc_face TOP to the first pair hook: the
                            ; record copy, the span ordering, the pair
                            ; range, the open scan, the normalise, the
                            ; w2 multiply, the ONE 16-bit division the
                            ; half-height Bresenham needs, and the first
                            ; pair's occlusion test and charge
                            ; arithmetic.  MEASURED 1449.
C_CSKIP     equ 560         ; one pair a nearer face already owns:
                            ; rc_pnext's whole-pair step, the loop, the
                            ; next pair's occlusion test -- and the next
                            ; pair's rc_charge arithmetic, which runs
                            ; BEFORE that pair's own hook and so bills
                            ; backwards to this one.  MEASURED 170 by the
                            ; fit, and 463 on a state the fit did NOT
                            ; sample: a skipped pair that is not also a
                            ; clamped step is RARE (3 hooks of 442), so
                            ; the fit barely constrains it and this one
                            ; carries margin the others do not need.
                            ; Skipped pairs are few and cheap, so
                            ; over-charging them is the affordable way
                            ; to be wrong.
C_COLS      equ 1800        ; ONE DRAWN PAIR, fixed part: rc_column's
                            ; whole setup (the u division, the two
                            ; Bresenham probes, CTABT, the row range),
                            ; the band setup, its rc_pnext step and the
                            ; same next-pair tail C_CSKIP carries.
                            ; MEASURED 1721.
                            ;
                            ; IT IS LARGE BECAUSE THE SETUP IS FINALLY
                            ; IN ITS OWN INTERVAL.  The old C_COLS was
                            ; 330 and the old charge was taken AFTER
                            ; that setup, so about 1000 us a pair was
                            ; billed to whatever hook came before --
                            ; usually a 60 us C_CEDGE.  Nothing got
                            ; cheaper here; the bill moved to the payer.
                            ; It came DOWN from 1980 when rc_charge's
                            ; own two rc_mul8 loops became six shifts --
                            ; that arithmetic runs INSIDE the interval it
                            ; is charging for, so it was paying for
                            ; itself twice over.
C_COLSO     equ 800         ; ...AND WHAT AN OVERLAY PAIR COSTS ON TOP.
                            ; Charged only when (rc_over) is set, which
                            ; is only while a door is part way through
                            ; its run -- six frames of a game, and none
                            ; at all until the player opens one.
                            ;
                            ; A moving door's pair does work no pass-1
                            ; pair does: rc_pairloop scribbles RC_RC+1
                            ; over both cover bytes so the face ignores
                            ; the occlusion interval, rc_rows takes the
                            ; lift branch, and rc_slide runs TWO rc_mul8
                            ; loops -- eight iterations each -- to raise
                            ; the bottom edge and re-seat the texture
                            ; index.  C_COLS covers the pass-1 setup and
                            ; nothing of that.
                            ;
                            ; MEASURED, emu_rcol.py's atomic with the new
                            ; `moving` flag, 6 states x the six lifts, 90
                            ; overlay pair hooks: the shortfall runs 263
                            ; to 659 us and the worst is 659 at dlift 42.
                            ; The SLOPE was never wrong -- fitting
                            ; measured against charged rows gives 20.35
                            ; against C_COLR's 21 -- it is the per-pair
                            ; INTERCEPT that was short.  800 clears 659
                            ; by 141, the margin C_HP carries.
                            ;
                            ; IT WENT UNSEEN BECAUSE atomic HAD NEVER
                            ; DRAWN A MOVING FACE.  _atomic_states emits
                            ; kinds 0 and 1 only, so for the whole life
                            ; of the paced renderer the overlay pass was
                            ; charged by a model nobody had checked
                            ; against the machine.  `emu_rcol atomic n 0
                            ; 1` is the run that shows it.
C_CBAND     equ 0           ; per BAND the pair could draw.  MEASURED 0:
                            ; the fit is free to split the fixed cost
                            ; between C_COLS and this, and the split
                            ; that over-charges least puts all of it in
                            ; C_COLS, because almost every drawn pair
                            ; carries two bands (one above the horizon
                            ; and one below) and the rare one-band pair
                            ; is cheap anyway.  Kept as a named term
                            ; because it is the shape rc_charge computes
                            ; and a future viewport may separate them.
C_COLR      equ 21          ; per scanline of the bounded row range
                            ; min(2*j_hi+1, rows still free), a scanline
                            ; being two screen bytes.  MEASURED 20.0 --
                            ; and independently, the ten instructions of
                            ; the fill unit are 20.25 us (emu_byte.py,
                            ; `colpair`).  The two agree, which is the
                            ; check that the row bound is really a bound.
                            ;
                            ; IT IS A LITERAL AND NOT `8*C_COLR`, THOUGH
                            ; THAT IS WHAT IT MEANS.  pacemodel.py reads
                            ; these with int() on the third token and
                            ; falls back to its own default when that
                            ; throws -- so an expression here assembles
                            ; perfectly and silently models a different
                            ; disc.  rastcol.asm asserts the relation.
C_CEDGE     equ 168         ; per possible EDGE row, bounded by
                            ; min(2*(j_hi - j_lo), rows still free) -- a
                            ; single byte of the taller column of a pair,
                            ; outside the PUSH, drawn by rc_edge's
                            ; rebuild-the-address-every-row loop.
                            ; MEASURED 160, and 8*C_COLR = 168 covers it
                            ; while making the whole bound one multiply.
C_CFAR      equ 300         ; THE FAR PLANE'S ENTRY: the step and page
                            ; setup and the walk down to the first pair's
                            ; hook.  The 22-iteration loop is NOT in here
                            ; any more -- every pair takes its own hook,
                            ; C_CFARP or C_CFARS below.
                            ;
                            ; IT WAS 13000 AND IT PAID FOR THE WHOLE PASS,
                            ; ONE HOOK, and that was wrong in both
                            ; directions at once.
                            ;
                            ; The comment here used to read "fills a
                            ; 13-scanline band ... about 430 us a pair ...
                            ; ~9500 for all 22".  That was true at
                            ; RC_FARH 96.  vpcfg.inc raised RC_FARH to 144
                            ; -- a NINETEEN-scanline band -- and this
                            ; constant was never re-derived.  MEASURED at
                            ; the shipped height the pass is
                            ;
                            ;     1430 us + 776.2 us a FILLED pair
                            ;
                            ; (least squares over ten states at 0, 1, 2,
                            ; 15, 16, 17, 19, 20, 21 and 22 filled pairs,
                            ; every point measured by emu_rcol.measure).
                            ; So:
                            ;
                            ;   UNDER-CHARGED wherever the far plane fills
                            ;   15 pairs or more -- 13105 us against 13000
                            ;   at 15, and 18442 against 13000 at 22.  And
                            ;   those states are REACHABLE: sampling 2928
                            ;   of them found 5 that leave 21 of the 22
                            ;   pairs to the far plane.  18442 us is 92.4%
                            ;   of a whole 19968 us vsync period IN ONE
                            ;   INTERVAL, which is precisely the failure
                            ;   the notes at the head of this file exist
                            ;   to prevent.
                            ;
                            ;   OVER-CHARGED everywhere else, and that is
                            ;   most frames: a state whose walls cover the
                            ;   horizon band leaves the far plane nothing
                            ;   to do and costs 1420 us against a charge
                            ;   of 13000.  11580 us of a 175104 us frame
                            ;   budget -- 6.6% -- thrown away on almost
                            ;   every frame.
                            ;
                            ; One hook per FILLED pair fixes both, and it
                            ; is what every other thing this renderer
                            ; draws already does.
C_CFARP     equ 1000        ; ...one pair of it that FILLS.  MEASURED
                            ; 776.2 us of band by the fit, 928 worst as a
                            ; whole interval; 72 us of margin.
C_CFAREND   equ 400         ; ...and the way out of the pass: rc_far's own
                            ; return, raster_colframe's move to the
                            ; overlay pass, and -- when no moving door
                            ; follows -- the frame epilogue.  MEASURED
                            ; 236 us at the worst state of eleven.
C_CFARS     equ 175         ; ...and one that does not: the two compares
                            ; and the loop step, nothing else.  MEASURED
                            ; 150-154 us over fourteen states; 150 was
                            ; UNDER by 4 at the worst of them, which is
                            ; the whole reason this file measures rather
                            ; than reasons.  The pass takes a hook at
                            ; EVERY pair -- see the note in
                            ; rastcol.asm:rf_pair for what forced it.
C_CSTEP     equ 260         ; one single-column step of rc_pnext's slow
                            ; path, on top of the C_CSKIP its hook also
                            ; charges.  MEASURED 213.
