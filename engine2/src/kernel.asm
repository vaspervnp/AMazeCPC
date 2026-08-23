; =====================================================================
;  engine2/src/kernel.asm -- the whole per-frame GEOMETRY kernel
;
;  frame_geom = march + proj_face over every candidate face, emitting a
;  painter-ordered list of screen-space quads.  Nothing is drawn; this is
;  exactly the work the rasteriser is handed.
;
;  There is no proj_setup in that list any more.  The march carries
;  view-space coordinates through the flood and files each face with both
;  endpoints already transformed (see the FACE RECORD in march.asm), so
;  the four 17-entry lattice tables proj_setup built every frame, and the
;  two lat_view lookups per face that read them, are gone.
;
;  IN   (plr_x) (plr_y)  world position, unsigned 16-bit 8.8
;       (plr_a)          heading 0..71
;       SOLID            16x16 map, 0 open / 1 wall / 2 shut door
;  OUT  QUADS            (fg_nquad) records of 8 bytes, back to front:
;         +0  blo  byte column of the SHORTER endpoint, 0..VP_BW
;         +1  bhi  byte column of the TALLER  endpoint, 0..VP_BW
;         +2  hlo  Q12.4  projected HALF height at the shorter endpoint
;         +4  hhi  Q12.4  ...and at the taller one
;         +6  kind 0 = wall, 1 = door
;         +7  k    L1 cell distance 1..7 (painter key / ramp index)
;
;  WHY THIS FORM AND NOT (xa,yat,yab,xb,ybt,ybb).  The old record was the
;  projector's natural output, and raster.asm then spent 522 us per quad
;  undoing it: rounding xa and xb to whole bytes, subtracting yat and ybt
;  back out of CY_Q4 into half heights, and sorting the two endpoints by
;  height to find the edge that is pinned in both wedges.  The projector
;  ALREADY HAS all three -- s_ha and s_hb are half heights, and one
;  compare orders them -- so it emits them, and yab/ybb, which are
;  2*CY_Q4-yat and 2*CY_Q4-ybt exactly and which nothing ever read, are
;  not computed at all.  x survives only as a byte column because that is
;  the only resolution a PUSH DE run has.
;  MEASURED (100-NOP calibration 100.08 us, empty-loop overhead
;  subtracted).  raster.asm's per-quad setup, on the xa == xb probe that
;  draws nothing (emu_rast.py time):     522.2 us  ->  340.9 us
;  Whole frames on 30 fixed player states, geometry AND fill, on the
;  emulator (emu_frame.py's rig): 162 quads, 225.5 us a quad faster.
;      worst reachable state (0770,06F0) a55, 16 quads  76.91 -> 73.51 ms
;      17-quad stress state  (0120,0DE0) a68            81.07 -> 77.31 ms
;      28-state sample: median 38.06 -> 37.30, mean 41.14 -> 40.09 ms
;  proj_face itself is UNCHANGED in cost (run_proj_test.py: march-fed
;  unclipped 1033.9 us against 1028 before) -- the emit block trades four
;  CY_Q4 adds for two roundings and a compare, and comes out even.
;
;  Face record -> projector.  march.asm files 16 bytes per face; this
;  loop copies the first twelve straight into proj_face's input block
;  (c_xa c_za c_xb c_zb, then pf_nd, the wall/door flag, and pf_i0 pf_j0
;  for the backface test) and calls it.  Endpoint A is named exactly as
;  free.py:face_endpoints() names it.
;
;  Clobbers AF BC DE HL IX.  march uses SP as its flood-stack pointer, so
;  interrupts must be off.  Restores SP itself.
;
;  PACING.  When main3.asm defines PACED, the bucket walk charges main3's
;  cost accumulator once per CANDIDATE face -- cost_face, from (pf_ok) and
;  (pf_nclip) -- AFTER the face has run, testing against FACE_THI, which
;  is set low enough that one more face still fits inside the period.  The
;  old code roomed C_FACE_MAX before every face instead, and threw away up
;  to 4170 us of the interval doing it.  MEASURED on
;  the built disc: 1327 us for a face that becomes a quad, 467 for one that
;  is rejected, 864 for each clip lerp, R^2 0.998.  A vsync wait can be
;  taken between any two faces, which is what stops a 25 ms project_all
;  from overrunning a period; the hook is 109 us a face and preserves every
;  register.
;
;  ------------------------------------------------------------------
;  MEASURED end to end on a cycle-accurate CPC 6128, WITH BOTH HALVES
;  OF THE REWRITE IN (incremental view-space march + table-driven
;  projector with screen-space side clipping).  engine2/tools/
;  emu_kernel.py time, 100-NOP calibration 100.08 us, loop overhead
;  39.11 us subtracted, 31392 player states surveyed:
;
;      total_us = 3281 + 544.7*ref_cells + 506.3*cand_faces
;      R^2 0.9759, RMS 1164 us, mean 14043 us over 127 sampled states
;
;      median 11.26 ms   p90 22.90 ms   p99 28.23 ms   worst 36.71 ms
;
;    per-frame floor          march_setup   1401 us   (proj_setup gone)
;    per marched cell         flood          275 us marginal, 363 mean
;    proj_face, march-fed     unclipped     1028 us
;                             one side plane1852
;                             two side planes 2596
;                             near-clip reject 987
;                             backface early out 62
;
;    quad list still BIT-EXACT: 472 frames / 1937 quads, 0 mismatches.
;
;    AGAINST THE TARGETS (450 us/face, 1 ms floor, 18 ms worst):
;    the floor landed (1.4 ms), the face missed by 2.3x and the worst
;    frame by 2.0x.  What is left is two proj_pt calls per face
;    (321 us each, 44% of which is the 16x8 multiply) plus pf_side
;    (149 us) which the march could hand over for free.
;  ------------------------------------------------------------------
;  (superseded)  the same harness before the projector rewrite:
;      median 11.2 ms   p90 21.8 ms   worst 35.0 ms
;      us = 3480 + 667.8*ref_cells + 208.7*cand_faces, R^2 0.988
;  ------------------------------------------------------------------
;  (superseded)  MEASURED end to end on a cycle-accurate CPC 6128
;  (engine2/tools/emu_kernel.py; timing method calibrated against a
;  100-NOP loop to 100.08 us; the quad list is bit-exact against
;  marchmodel.py + projmodel.py over 472 frames / 1937 quads)
;  ------------------------------------------------------------------
;    31392 player states surveyed = 109 floor cells x 4 sub-cell offsets
;    x 72 headings, on the shipped maze, viewport 48x128 bytes, 60 FOV.
;
;      NOTE: these four are the OLD march AND the OLD projector.  With
;      the view-space march plus the cheap projector (PXT lookup and
;      screen-space side clipping, see project.asm), measured end to end
;      through E_ALL on the same 31392 states:
;         median 11.3 ms   p90 22.9 ms   p99 28.2 ms   worst 36.7 ms
;      and the quad list is still bit-exact against the model (112
;      frames / 523 quads).  What is left is the march flood itself,
;      which the fit puts at 545 us per referenced cell against 506 us
;      per candidate face.
;
;      median frame                       17.0 ms
;      p90                                30.6 ms
;      p99                                36.8 ms
;      worst of those 31392               44.1 ms
;      WORST FOUND, over 62784 states (8 sub-cell offsets, every
;      heading, engine2/tools/emu_worst.py)
;                                         46.5 ms   (cell 1,9 fx=0x1a
;                                         heading 14: 32 marched cells,
;                                         19 candidate faces)
;
;    breakdown of the 44.1 ms frame: march 10.1 ms, proj_setup 1.9 ms,
;    22 x proj_face 32.2 ms.  proj_face is 70% of the kernel.
;
;    least squares over 127 states, in free.py's own counters:
;      us = 7672 + 543.5*cells_visited + 1233.5*n_faces
;      R^2 0.9873, RMS residual 983 us
;    (per CANDIDATE face rather than per drawn face: 700 us; there are
;     1.604 candidates per drawn face at this viewport.)
;
;    THE HAND ESTIMATE THIS REPLACES was 60 us/cell + 500 us/face and no
;    constant term: 2.9 ms at the mean state where the hardware measures
;    20.1 ms.  The kernel is 7x the estimate.
;
;    Open rooms are NOT the worst case (engine2/tools/emu_room.py): a
;    9x9 hall costs 22.2 ms because its walls are far away and few faces
;    survive.  A tight maze corner with many near walls is worse.
;
;  ------------------------------------------------------------------
;  WHAT THIS COSTS THE VIEWPORT (engine2/tools/vpsweep_measured.py)
;  ------------------------------------------------------------------
;    The geometry kernel's cost does NOT depend on the viewport size --
;    at a fixed 60 deg FOV and a fixed 6-cell march radius the frustum
;    is the same shape whatever the window is, so cells_visited and the
;    face count are unchanged.  Shrinking the viewport only buys fill
;    time.  With ~47 ms of the 80 ms budget gone before a single byte is
;    written, the fill budget is ~32 ms, which is about 3300 byte-cells:
;
;      48 x 128 bytes (the decided target)   worst 104.3 ms   OVER
;      44 x  76 bytes                        worst  79.8 ms   fits
;      40 x  80 bytes                        worst  79.2 ms   fits
;      32 x  86 bytes                        worst  78.2 ms   fits
;
;    Levers that DO move the geometry, at 48x128 (mean / worst ms):
;      60 deg, R=6  (as built)     65.5 / 103.6
;      60 deg, R=4                 62.9 /  88.8
;      45 deg, R=4                 60.0 /  83.5
; =====================================================================

    include "memmap.inc"       ; QUADS -- shared with engine2/test
QRECSZ      equ 8


frame_geom
    call march
    ; fall through

; ---------------------------------------------------------------------
;  project_all -- buckets 7..1, back to front, into QUADS
;
;  The march files every face ALREADY IN VIEW SPACE (see the record layout
;  in march.asm), so this loop is a 12-byte copy into the projector's
;  input block and a call.  Nothing here transforms anything, and
;  proj_setup is not called at all any more: its four 17-entry lattice
;  tables existed only to serve the per-face transform the march now
;  carries incrementally, at 1901 us of every frame.
; ---------------------------------------------------------------------
project_all
    ifdef PACED
    ; ---- PACING.  cost_face CHARGES a face after it has run and tests
    ; against FACE_THI, which is safe only while the interval is under
    ; FACE_THI when the face STARTS.  cost_face itself maintains that for
    ; every face after the first; the first one inherits whatever the
    ; march left behind, which can be anything under COST_THI.  This gate
    ; is what makes it true on entry.  It charges nothing.
    ;
    ; WITHOUT IT the first face is charged on top of a nearly full
    ; interval: MEASURED on the disc, (0E10,0968) h13 came out of the
    ; march at 18990 us, the first face added 2310, and 21300 us of work
    ; between two vsync waits is a 20 ms period and a bit -- so the frame
    ; took SEVEN periods instead of six.  Three states in 1595 did it.
    call cost_gate
    endif
    ld   hl,QUADS
    ld   (fg_outp),hl
    xor  a
    ld   (fg_nquad),a
    ld   a,7
    ld   (fg_k),a

fg_bucket
    ld   h,FTAB/256             ; how far this bucket was filled
    ld   a,(fg_k)
    add  a,O_BPTR
    ld   l,a
    ld   a,(hl)
    ld   (fg_end),a
    ld   a,(fg_k)               ; bucket k IS the page BUCKHI+k
    add  a,BUCKHI
    ld   h,a
    ld   l,0
    ld   (fg_cur),hl

fg_rec
    ld   hl,(fg_cur)
    ld   a,(fg_end)
    cp   l
    jr   z,fg_bkdone
    ld   a,l
    add  a,BUCKSZ
    ld   (fg_cur),a             ; only the low byte moves inside the page

    ld   de,c_xa                ; +0..7  xa za xb zb, view space Q6.10
    ldi
    ldi
    ldi
    ldi
    ldi
    ldi
    ldi
    ldi
    ld   a,(hl)                 ; +8  face normal
    ld   (pf_nd),a
    inc  l
    ld   a,(hl)                 ; +9  wall / door
    ld   (fg_kind),a
    inc  l
    ld   a,(hl)                 ; +10 i0, read only by the backface test
    ld   (pf_i0),a
    inc  l
    ld   a,(hl)                 ; +11 j0
    ld   (pf_j0),a

    call proj_face

    ; ---- PACING.  cost_face charges what this face actually cost and
    ; then, if the interval has passed FACE_THI, takes the wait.  Testing
    ; AFTER rather than rooming BEFORE is what keeps the interval full:
    ; the headroom FACE_THI leaves (C_FACE_MAX = a survivor plus three
    ; clip lerps) is only ever spent when a face really needs it.
    ; main3.asm owns it and it preserves every register.
    ifdef PACED
    call cost_face
    endif

    ld   a,(pf_ok)
    or   a
    jp   z,fg_rec
    ld   hl,pf_blo
    ld   de,(fg_outp)
    repeat QRECSZ-2             ; = PFRECSZ, pf_blo..pf_hhi; kind and k are
    ldi                         ; appended below.  LDI, not LDIR: see the
    rend                        ; note in raster.asm:raster_quad.
    ld   a,(fg_kind)
    ld   (de),a
    inc  de
    ld   a,(fg_k)
    ld   (de),a
    inc  de
    ld   (fg_outp),de
    ld   hl,fg_nquad
    inc  (hl)
    jp   fg_rec

fg_bkdone
    ld   hl,fg_k
    dec  (hl)
    jp   nz,fg_bucket
    ret


; ------------------------------------------------------------ variables ---
fg_k        db 0
fg_kind     db 0
fg_nquad    db 0
fg_end      db 0                ; write offset the march left in this bucket
fg_cur      dw 0                ; page:offset of the record being projected
fg_outp     dw 0
