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
;               which is the safe direction.
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
C_CFRAME    equ 420         ; raster_colframe's own setup, once a frame:
                            ; the two LDIRs that clear the occlusion
                            ; state, the bank switch and the walk's head.
                            ; MEASURED 389.
C_CFACE     equ 1700        ; rc_face TOP to the first pair hook: the
                            ; record copy, the span ordering, the pair
                            ; range, the open scan, the normalise, the
                            ; w2 multiply, the ONE 16-bit division the
                            ; half-height Bresenham needs, and the first
                            ; pair's occlusion test and charge
                            ; arithmetic.  MEASURED 1633.
C_CSKIP     equ 760         ; one pair a nearer face already owns:
                            ; rc_pnext's whole-pair step, the loop, the
                            ; next pair's occlusion test -- and the next
                            ; pair's rc_charge arithmetic, which runs
                            ; BEFORE that pair's own hook and so bills
                            ; backwards to this one.  MEASURED 697, and
                            ; on only two hooks of 435: a skipped pair
                            ; that is not also a clamped step is rare,
                            ; so this one carries margin the others do
                            ; not need.
C_COLS      equ 1980        ; ONE DRAWN PAIR, fixed part: rc_column's
                            ; whole setup (the u division, the two
                            ; Bresenham probes, CTABT, the row range),
                            ; the band setup, its rc_pnext step and the
                            ; same next-pair tail C_CSKIP carries.
                            ; MEASURED 1915.
                            ;
                            ; IT IS LARGE BECAUSE THE SETUP IS FINALLY
                            ; IN ITS OWN INTERVAL.  The old C_COLS was
                            ; 330 and the old charge was taken AFTER
                            ; that setup, so about 1000 us a pair was
                            ; billed to whatever hook came before --
                            ; usually a 60 us C_CEDGE.  Nothing got
                            ; cheaper here; the bill moved to the payer.
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
                            ; being two screen bytes.  MEASURED 20.5 --
                            ; and independently, the ten instructions of
                            ; the fill unit are 20.25 us (emu_byte.py,
                            ; `colpair`).  The two agree, which is the
                            ; check that the row bound is really a bound.
C_CEDGE     equ 170         ; per possible EDGE row, bounded by
                            ; min(2*(j_hi - j_lo), rows still free) -- a
                            ; single byte of the taller column of a pair,
                            ; outside the PUSH, drawn by rc_edge's
                            ; rebuild-the-address-every-row loop.
                            ; MEASURED 160.
C_CSTEP     equ 125         ; one single-column step of rc_pnext's slow
                            ; path, on top of the C_CSKIP its hook also
                            ; charges.  MEASURED 114.
