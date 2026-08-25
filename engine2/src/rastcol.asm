; =====================================================================
;  engine2/src/rastcol.asm -- THE COLUMN RENDERER.  Textured wall faces.
;
;  raster.asm turns a quad into horizontal PUSH DE runs, one per scanline,
;  and a horizontal run can only ever push a CONSTANT -- which is why the
;  walls it draws are one flat colour.  This file turns the same quad list
;  into VERTICAL strips instead, because for a fixed screen column the
;  texture column u is constant and only v walks down it, linearly.
;
;  engine2/tools/colmodel.py is the SPEC.  Every integer operation below
;  has a one-to-one counterpart there and engine2/tools/emu_rast.py
;  asserts the two paint the same 16K buffer.  Read colmodel.py first.
;
;  ------------------------------------------------------------------
;  WHAT IT COSTS, AND WHAT THE PLAN THOUGHT IT COST
;  ------------------------------------------------------------------
;  The architecture was costed at 6.625 us per screen byte, off the
;  `colimm` row of engine2/tools/emu_byte.py -- `ld sp,hl : ld de,nn :
;  push de : add hl,bc`.  THAT ROW CANNOT BE REACHED BY A RENDERER,
;  because `ld de,nn` is an IMMEDIATE: the texture has to be in the
;  instruction stream already, and generating it there costs more per byte
;  (16 us) than sampling it does (6).
;
;  MEASURED on the booted 6128, this file's actual inner loop, benched as
;  `colpair` in engine2/test/tst_byte.asm -- slope across 96 and 192
;  bytes, 100-NOP calibration exact to 100.001 us:
;
;      row order, PUSH DE, constant fill          2.000 us/byte
;      column pair by PUSH, constant colour       5.125    <- the floor
;      column pair by PUSH, baked immediate       6.625    <- unreachable
;      COLUMN PAIR BY PUSH, TEXTURED             10.125    <- this file
;      single column, LD (HL),A, textured        13.625
;
;  and 10.125 is 20.25 us for one scanline of a PAIR, which decomposes
;  exactly into the ten instructions of rc_unit below:
;
;      ld e,h : ld a,(de) : add hl,bc     6 us  sample and step the texture
;      exx ... exx                        2 us  two banks, two 16-bit walks
;      ld d,a : ld e,a                    2 us  one sample, both bytes
;      ld sp,hl : push de : add hl,bc    10 us  the screen, 2 bytes at once
;
;  Over the whole reachable state space (engine2/tools/colarea.py, the
;  same 24/256 lattice x 72 headings pacescan.py sweeps):
;
;      span renderer   worst 6842 bytes / 684 runs =  23.2 ms
;      THIS renderer   worst 4224 bytes /  50 bands = 49.7 ms
;
;  So the texture is NOT free, and vpcfg.inc's VPCOL note carries what it
;  costs in frame period.  What column order DOES buy outright is the
;  pacing: the largest atomic unit falls from a whole quad -- 12486 us
;  MEASURED, 63% of a vsync period, the thing that forced raster.asm's
;  RQ_SPLIT and its chunk hooks -- to ONE BAND, at most 96 scanlines, so
;  under 2.1 ms.  There is no mid-quad yield here and none is needed.
;
;  ------------------------------------------------------------------
;  PAIRS, NOT COLUMNS
;  ------------------------------------------------------------------
;  PUSH writes two horizontally adjacent bytes, so SP has to be reloaded
;  every scanline but the reload covers TWO byte columns.  Half of the
;  10 us a scanline of screen pointer work is therefore free, and two
;  byte columns is the natural grain of a column renderer the same way
;  two bytes is the natural grain of raster.asm's row fill.
;
;  ONE SAMPLE FEEDS BOTH BYTES.  Giving the two columns different texture
;  bytes needs a second sample and a second index, and there is no
;  register left for either without a third EXX: 24 us against 20.25,
;  which is worse than not pairing at all.  A texture byte is already two
;  Mode 0 pixels, so a pair carries a 4-pixel group of the texture.
;
;  The face's span is rounded OUTWARD onto the pair grid, pa = xa>>1 and
;  pb = (xb+1)>>1, exactly as raster.asm rounds its runs outward by a
;  byte and for the same reason: adjacent faces OVERLAP, which the
;  occlusion below resolves in favour of the nearer one, instead of
;  leaving a gap, which nothing can resolve.
;
;  ------------------------------------------------------------------
;  FRONT TO BACK, AND WHY THE FLAG IS AN INTERVAL AND NOT A BOOLEAN
;  ------------------------------------------------------------------
;  The quad list arrives in painter order, back to front (kernel.asm:
;  project_all empties the march's buckets "7..1"), so this file reads it
;  BACKWARDS -- no sort, no key, no scratch space -- and the first face to
;  reach a pair is the nearest.
;
;  THE PLAN SAID A PAIR IS FINISHED ONCE A FACE COVERS IT FLOOR TO
;  CEILING, on the argument that the nearest face at a column is the
;  tallest there so every farther one is hidden.  MEASURED over 20736
;  states, that argument is false in 2862 of them -- 13.8% -- because the
;  painter key is the march's L1 CELL distance and not the per-column
;  depth order, so a face drawn later can still poke out above and below
;  one drawn earlier.  Skipping it leaves ceiling where the span renderer
;  draws wall.  Marking a pair done only on full coverage is safe against
;  that and gives up the cap instead: the same scan then paints 5496
;  bytes, 130% of the viewport, repainting the middle of every pair.
;
;  Both are fixed by one observation.  The camera sits at wall mid-height
;  and cannot pitch, so a face covers rows CYH-j .. CYH+j and NOTHING
;  ELSE -- an interval centred on the horizon.  The union of any number of
;  them at one pair is therefore also one interval centred on the horizon,
;  and TWO BYTES describe it exactly:
;
;      (rc_up)+p   the COUNT of uncovered rows above -- so the band above
;                  the horizon is [r0, rc_up-1] and rc_up starts at
;                  RC_RC+1, because the horizon ROW belongs to that band
;      (rc_dn)+p   the first uncovered row below, starting at RC_RC+1
;      (rc_dn)+p   the first uncovered row below
;
;  A face then paints at most two bands per pair, the rows a nearer face
;  has not already taken.  That is EXACT against the span renderer's own
;  visibility rule -- nearest face wins, which is what back-to-front
;  overdraw computes -- AND no byte is ever written twice, so the frame is
;  capped at VP_BW*VP_H however many faces the kernel emits.
;
;  ------------------------------------------------------------------
;  NO DIVIDE IN THE COLUMN LOOP
;  ------------------------------------------------------------------
;  Per pair this file needs u (which texture column), j (the half height)
;  and the vertical step.  Only u costs a division and it is FOUR BITS:
;
;      u = TEX_BW * N / D,   N = t2*hb', D = w2*ha' + t2*(hb'-ha')
;
;  with t2 = 2(x-xa)+1 and w2 = 2w.  Both N and D are linear in x with
;  INTEGER increments, so walking them is two 16-bit adds; only reading u
;  off costs the four restoring steps of rc_udiv.  See colmodel.normalise
;  for why that is the perspective-correct u and not a linear one, and
;  why ha and hb are pre-shifted (RTHRESH) to keep D under 32768.
;
;  j comes from a Bresenham set up by ONE division per face, and the
;  vertical step and start index come out of CTABT, indexed by j.  Bank 5
;  holds all of it -- see engine2/tools/gentex.py.
;
;  IN   the quad list at QUADS, (fg_nquad) of them, painter order
;  OUT  the wall faces painted, textured.  SP restored.  Bank 4 back in.
;  Clobbers everything.  Interrupts must be OFF (SP is the screen).
; =====================================================================

    include "gen_tex.inc"

; main3.asm defines PACED when it is pacing; engine2/test/tst_rcol.asm
; includes this file WITHOUT it, so the cost hooks have to be optional
; the same way raster.asm's are.
    ifndef PACED
RC_PACED    equ 0
    else
RC_PACED    equ 1
    endif

RC_RC       equ CYH                 ; the horizon, as a viewport row
RC_SCRW     equ 80

    assert CNPAIR*2 == VP_BW
    assert (VP_Y&7) == 0            ; the phase of a row IS row&7
    assert VP_H <= 128              ; rc_up / rc_dn are single bytes


; ---------------------------------------------------------------------
;  raster_colframe -- the whole quad list, front to back.
; ---------------------------------------------------------------------
raster_colframe
    ld   a,(fg_nquad)
    or   a
    ret  z
    ld   (rc_sp),sp
    if RC_PACED
    ; WHAT THE FRAME'S OWN SETUP COSTS -- the two LDIRs that clear the
    ; occlusion state, the RAM configuration switch and the backwards
    ; walk's head.  It is charged ONCE, here, and not folded into
    ; C_CFACE: a frame draws up to sixteen faces and billing every one of
    ; them for work that happens once is exactly the over-charge that
    ; costs periods.
    ld   bc,C_CFRAME
    call cost_unit
    endif

    ; ---- the occlusion state: nothing covered anywhere yet.  (rc_up) is
    ;      a COUNT of uncovered rows above the horizon, so RC_RC means the
    ;      horizon row itself is still free, and (rc_dn) is the first free
    ;      row below it, which is one lower.
    ld   hl,rc_up
    ld   de,rc_up+1
    ld   bc,CNPAIR-1
    ld   (hl),RC_RC+1           ; a COUNT, so the band is [r0, rc_up-1] and
    ldir                        ; the horizon row itself is still free
    ld   hl,rc_dn
    ld   de,rc_dn+1
    ld   bc,CNPAIR-1
    ld   (hl),RC_RC+1
    ldir

    ; ---- bank 5 over &4000-&7FFF for the whole render.  Nothing reached
    ;      from here touches bank 4: VPLINE and the quad list are in main
    ;      RAM, the cost accumulator and wait_vsync are code, and every
    ;      table this file wants is in bank 5 by construction.
    ld   bc,#7F00+TEXCFG
    out  (c),c

    ; ---- TWO PASSES, and the second one is what lets a door open all
    ;      the way.  Pass 0 draws everything EXCEPT a door in motion,
    ;      front to back with the occlusion interval as usual.  Pass 1
    ;      then draws the moving doors ON TOP, out of the occlusion
    ;      scheme entirely.
    ;
    ;      WHY IT HAS TO BE A SECOND PASS.  rc_up / rc_dn describe a
    ;      pair's covered rows as ONE interval CENTRED ON THE HORIZON.
    ;      A door rising past the horizon covers [r0, r1] with r1 above
    ;      it -- an interval that does NOT touch the horizon, which those
    ;      two bytes cannot express.  Drawn in the normal pass it had to
    ;      be clamped at the horizon, and the door stopped half way and
    ;      then vanished.  Drawn LAST and on top it needs no interval at
    ;      all: it is the nearest thing at those pairs, so painting over
    ;      what is already there IS the right answer, and the room behind
    ;      it has already been drawn by pass 0.
    xor  a
    ld   (rc_over),a
rc_pass
    ld   a,(fg_nquad)
    ld   (rc_left),a
    dec  a
    ld   l,a
    ld   h,0
    add  hl,hl
    add  hl,hl
    add  hl,hl                  ; (n-1) * QRECSZ
    ld   de,QUADS
    add  hl,de
rc_faceloop
    ld   (rc_rec),hl
    call rc_face
    ld   hl,(rc_rec)
    ld   de,-QRECSZ
    add  hl,de
    ld   a,(rc_left)
    dec  a
    ld   (rc_left),a
    jr   nz,rc_faceloop

    ld   hl,rc_over             ; ...and again for the moving doors
    inc  (hl)
    ld   a,(hl)
    cp   2
    jp   c,rc_pass

    ld   bc,#7FC4               ; bank 4 back before anything else runs
    out  (c),c
    ld   sp,(rc_sp)
    ret

    assert QRECSZ == 8


; =====================================================================
;  rc_face -- HL = one quad record.  Paints whatever of it is visible.
; =====================================================================
rc_face
    ; ---- IS THIS FACE FOR THIS PASS?  Bit 1 of the kind byte is set by
    ;      march.asm for a door part way through its run; those are drawn
    ;      in pass 1 and nothing else is.  It is tested BEFORE the charge
    ;      below, or every face would pay C_CFACE twice -- once per pass.
    push hl
    ld   de,6
    add  hl,de
    ld   a,(hl)                 ; +6 kind
    pop  hl
    and  2
    rrca                        ; bit 1 -> 0 or 1
    ld   c,a
    ld   a,(rc_over)
    cp   c
    ret  nz                     ; not this pass
    if RC_PACED
    ; ---- charged at the VERY TOP, before the record is read, because
    ;      room-then-charge bills the work in front of a hook to the hook
    ;      BEFORE it: taking this after the setup billed the setup to the
    ;      previous pair's charge (see costcol.inc for the measured
    ;      under-charges).  FLAT, because np is not known yet; it covers
    ;      everything from here to the first pair hook -- the record
    ;      copy, the ordering, the pair range, the open scan and, when
    ;      the face is not fully occluded, the whole per-face setup and
    ;      the first pair's own charge arithmetic.  A degenerate or
    ;      fully occluded face pays it too, and that is the safe
    ;      direction.
    ld   bc,C_CFACE
    call cost_unit
    endif
    ld   de,rc_blo              ; the record into locals
    repeat QRECSZ
    ldi
    rend

    ; ---- order the ends so xa < xb, each height carried with its own
    ;      column.  bhi >= blo exactly when the RIGHT endpoint is taller,
    ;      because the projector pairs the taller height with its column.
    ld   a,(rc_blo)
    ld   c,a
    ld   a,(rc_bhi)
    sub  c
    jr   c,rc_swap
    ret  z                      ; zero width paints nothing
    ld   (rc_w),a
    ld   a,c
    ld   (rc_xa),a
    ld   hl,(rc_hlo)
    ld   (rc_ha0),hl
    ld   hl,(rc_hhi)
    ld   (rc_hb0),hl
    xor  a
    jr   rc_flset
rc_swap
    neg
    ld   (rc_w),a
    ld   a,(rc_bhi)
    ld   (rc_xa),a
    ld   hl,(rc_hhi)
    ld   (rc_ha0),hl
    ld   hl,(rc_hlo)
    ld   (rc_hb0),hl
    ld   a,1
rc_flset
    ld   (rc_flip),a

    ; ---- the pair range, rounded OUTWARD onto the pair grid:
    ;      pa = xa>>1, pb = (xb+1)>>1, clipped to the viewport.
    ld   a,(rc_xa)
    srl  a
    ld   (rc_pa),a
    ld   c,a
    ld   a,(rc_xa)
    ld   hl,rc_w
    add  a,(hl)                 ; xb = xa + w
    inc  a
    srl  a
    cp   CNPAIR+1
    jr   c,rc_pbok
    ld   a,CNPAIR
rc_pbok
    sub  c
    ret  z                      ; no pair of its own
    ret  c
    ld   (rc_np),a

    ld   a,(rc_over)            ; an overlay face ignores the cover, so
    or   a                      ; "every pair finished" cannot skip it
    jr   nz,rc_open

    ; ---- IS ANY OF THEM STILL OPEN?  A fully occluded face pays this
    ;      scan and nothing else -- no normalise, no divide, no setup --
    ;      which is what makes the front-to-back order worth having.
    ld   a,(rc_np)
    ld   b,a
    ld   a,(rc_pa)
    ld   e,a
    ld   d,0
    ld   hl,rc_dn
    add  hl,de
    ex   de,hl                  ; DE -> rc_dn[pa]
    ld   a,(rc_pa)
    ld   l,a
    ld   h,0
    ld   bc,rc_up
    add  hl,bc
    ld   b,a
    ld   a,(rc_np)
    ld   b,a                    ; B = pairs to test
rc_openl
    ld   a,(hl)
    or   a
    jr   nz,rc_open             ; a row still free above
    ld   a,(de)
    cp   VP_H
    jr   c,rc_open              ; ...or below
    inc  hl
    inc  de
    djnz rc_openl
    ret                         ; every pair of this face is finished
rc_open

    ; ---- which texture
    ld   a,(rc_kind)
    and  1
    jr   z,rc_iswall
    ld   a,TEXDOOR/256
    jr   rc_texset
rc_iswall
    ld   a,TEXWALL/256
rc_texset
    ld   (rc_texpg),a

    ; ---- NORMALISE.  Shift both half heights right until the u
    ;      division's denominator stays under 32768.  RTHRESH[w2] is the
    ;      smallest max(ha,hb) that would break it, so the test is a
    ;      COMPARE and never a multiply.  See colmodel.normalise.
    ld   a,(rc_w)
    add  a,a
    ld   (rc_w2),a
    ld   e,a
    ld   d,0
    ld   hl,RTHRESH
    add  hl,de
    ld   e,(hl)
    inc  hl
    ld   d,(hl)                 ; DE = T
    ld   hl,(rc_ha0)
    ld   bc,(rc_hb0)
    ld   a,l                    ; hm = max(ha, hb), into HL
    sub  c
    ld   a,h
    sbc  a,b
    jr   nc,rc_nmax
    ld   h,b
    ld   l,c
rc_nmax
    ld   c,0                    ; C = sh
rc_nloop
    ld   a,h
    cp   d
    jr   c,rc_ndone
    jr   nz,rc_nsh
    ld   a,l
    cp   e
    jr   c,rc_ndone
rc_nsh
    srl  h
    rr   l
    inc  c
    jr   rc_nloop
rc_ndone
    ld   a,c
    ld   (rc_sh),a
    ld   hl,(rc_ha0)
    call rc_shr
    ld   (rc_han),hl
    ld   hl,(rc_hb0)
    call rc_shr
    ld   (rc_hbn),hl

    ; ---- dh' = hbn - han, and the per-PAIR increments.  t2 steps by 4
    ;      per pair (two columns, and t2 = 2(x - xa) + 1).
    ld   de,(rc_han)
    or   a
    sbc  hl,de
    ld   (rc_dhn),hl            ; hbn - han, signed
    add  hl,hl
    add  hl,hl
    ld   (rc_dden),hl             ; 4*(hbn - han)
    ld   hl,(rc_hbn)
    add  hl,hl
    add  hl,hl
    ld   (rc_dnum),hl             ; 4*hbn

    ; ---- N and D at t2 = 1.  xa is either even (2*pa == xa, so t2 = 1)
    ;      or odd (2*pa == xa-1, so t2 = -1 and the sample is CLAMPED into
    ;      the face, which is t2 = 1 as well) -- so the first pair is
    ;      t2 = 1 either way and there is no first-pair special case.
    ld   hl,(rc_hbn)
    ld   (rc_num),hl              ; N = 1 * hbn
    ld   de,(rc_han)            ; D = w2*han + (hbn - han)
    ld   hl,0
    ld   a,(rc_w2)
rc_dmul                         ; w2 <= 88: seven shift-and-adds
    srl  a
    jr   nc,rc_dmnb
    add  hl,de
rc_dmnb
    ex   de,hl
    add  hl,hl
    ex   de,hl
    or   a
    jr   nz,rc_dmul
    ld   de,(rc_dhn)
    add  hl,de
    ld   (rc_den),hl
    ; ---- t2 SAMPLES THE PAIR'S CENTRE, not its left column.  A pair
    ;      writes one sampled byte to both of its byte columns, so
    ;      whichever column the sample comes from, the other one is wrong
    ;      by however much h and u move across it: sampling the left
    ;      column made the right one wrong by a WHOLE column, sampling
    ;      the centre makes each wrong by half a column and in opposite
    ;      directions.  raw t2 = 2*(2p - xa) + 2, which is 2 at the first
    ;      pair when xa is even and 0 when it is odd -- and 0 clamps up to
    ;      1, because the pair's left column is then xa-1, outside the
    ;      face.  N, D and h were built above at t2 = 1, so the even case
    ;      steps them on by one column here.  It costs one add each.
    ld   a,1
    ld   (rc_t2),a
    ld   a,(rc_xa)
    rra
    ld   a,0
    jr   c,rc_rawset            ; xa odd: raw 0, clamped to 1, no advance
    ld   a,2
rc_rawset
    ld   (rc_raw),a

    ; ---- the half-height Bresenham.  h(t2) = ha +- (t2*|dh|)/w2, and
    ;      ONE division per face gives the step and its remainder; every
    ;      pair after that is an add and a compare.  |dh| is the
    ;      UNSHIFTED difference -- the normalise above serves the u
    ;      division's range only, and j must keep every bit.
    ld   hl,(rc_hb0)
    ld   de,(rc_ha0)
    or   a
    sbc  hl,de
    ld   a,0
    jr   nc,rc_hpos
    ex   de,hl
    ld   hl,0
    or   a
    sbc  hl,de                  ; HL = |dh|
    ld   a,1
rc_hpos
    ld   (rc_hneg),a
    ld   a,(rc_w2)
    ld   c,a
    call rc_div                 ; HL = |dh|/w2, A = remainder
    ld   (rc_hq),hl
    ld   (rc_hr),a

    ; ---- and the per-PAIR step: 4*|dh| = 4*q*w2 + 4*r, so 4*r has to be
    ;      normalised back under w2 -- at most three subtractions, each of
    ;      which is one more whole step.
    add  hl,hl
    add  hl,hl                  ; 4*q
    ld   a,(rc_hr)
    add  a,a
    add  a,a                    ; 4*r < 4*w2 <= 352, so nine bits
    ld   d,0
    jr   nc,rc_r4
    inc  d
rc_r4
    ld   e,a
    ld   a,(rc_w2)
    ld   c,a
    ld   b,0
rc_r4l
    ld   a,e
    sub  c
    ld   a,d
    sbc  a,b
    jr   c,rc_r4done
    ld   a,e
    sub  c
    ld   e,a
    ld   a,d
    sbc  a,b
    ld   d,a
    inc  hl
    jr   rc_r4l
rc_r4done
    ld   (rc_hq4),hl
    ld   a,e
    ld   (rc_hr4),a

    ; ---- h and its accumulator at t2 = 1
    ld   hl,(rc_hq)
    ld   de,(rc_ha0)
    ld   a,(rc_hneg)
    or   a
    jr   nz,rc_hsub
    add  hl,de
    jr   rc_hset
rc_hsub
    ex   de,hl
    or   a
    sbc  hl,de
rc_hset
    ld   (rc_h),hl
    ld   a,(rc_hr)
    ld   (rc_acc),a

    ; ---- ...and if the first pair's sample is t2 = 2 rather than 1, step
    ;      N, D and the half-height Bresenham on by that one column.  See
    ;      the note on the centre sample above.
    ld   a,(rc_raw)
    cp   2
    jr   nz,rc_ctrdone
    ld   a,(rc_w2)              ; ...unless the face is ONE byte wide, when
    dec  a                      ; w2-1 is 1 and the centre sample clamps
    cp   2                      ; back onto the left column anyway
    jr   c,rc_ctrdone
    ld   a,2
    ld   (rc_t2),a
    ld   hl,(rc_num)
    ld   de,(rc_hbn)
    add  hl,de
    ld   (rc_num),hl
    ld   hl,(rc_den)
    ld   de,(rc_dhn)
    add  hl,de
    ld   (rc_den),hl
    ld   de,(rc_hq)
    call rc_hadd
    ld   a,(rc_hr)
    call rc_hacc
rc_ctrdone

    ; ================= the pair loop =================
    ld   a,(rc_pa)
    ld   (rc_p),a
rc_pairloop
    ld   a,(rc_p)
    ld   e,a
    ld   d,0
    ld   hl,rc_up
    add  hl,de
    ld   (rc_pup),hl
    ld   hl,rc_dn
    add  hl,de
    ld   (rc_pdn),hl

    ld   a,(rc_over)            ; OVERLAY: forget what covered this pair.
    or   a                      ; The door is in front of all of it, and
    jr   z,rc_pnorm             ; pass 1 is the last thing to run, so
    ld   hl,(rc_pup)            ; scribbling on the interval is free.
    ld   (hl),RC_RC+1
    ld   hl,(rc_pdn)
    ld   (hl),RC_RC+1
rc_pnorm
    ld   hl,(rc_pup)
    ld   a,(hl)
    or   a
    jr   nz,rc_pdo
    ld   hl,(rc_pdn)
    ld   a,(hl)
    cp   VP_H
    jr   c,rc_pdo
    ; ---- this pair is finished.  Its rc_pnext step still runs, and so
    ;      does the NEXT pair's occlusion test and charge arithmetic, so
    ;      the skip takes a hook of its own: ONE HOOK PER PAIR, drawn or
    ;      not, is what makes every interval one pair and every charge
    ;      cover its interval by construction.
    if RC_PACED
    ld   bc,C_CSKIP
    call cost_unit
    endif
    jr   rc_pnext
rc_pdo
    if RC_PACED
    call rc_charge              ; the pair's UPPER BOUND, before ANY of
    endif                       ; rc_column's setup runs
    call rc_column
rc_pnext
    ; ---- advance t2 by 4, and N, D and h with it.  The LAST pair clamps
    ;      t2 to w2-1 so the sample never leaves the face.
    ; THE STEP IS TAKEN ON THE RAW SAMPLE AND THE CLAMP READ OFF IT.
    ; t2 = clamp(2*(2p - xa) + 1, 1, w2-1) and the raw value moves by 4 a
    ; pair -- but when xa is ODD the first pair's raw value is -1 and its
    ; clamp is 1, so the step from the FIRST pair to the second is 2 and
    ; not 4.  Stepping the clamped value by a flat 4 puts every sample on
    ; a face with an odd left edge two columns of texture too far along.
    ld   a,(rc_raw)
    add  a,4
    ld   (rc_raw),a
    ld   c,a
    ld   a,(rc_w2)
    dec  a                      ; w2 - 1
    cp   c
    jr   nc,rc_t2ok
    ld   c,a
rc_t2ok
    ld   a,(rc_t2)
    ld   b,a
    ld   a,c
    ld   (rc_t2),a
    sub  b                      ; delta, 0..4
    jr   z,rc_stepped
    cp   4
    jr   nz,rc_slow
    ld   hl,(rc_num)              ; a whole step: one add each
    ld   de,(rc_dnum)
    add  hl,de
    ld   (rc_num),hl
    ld   hl,(rc_den)
    ld   de,(rc_dden)
    add  hl,de
    ld   (rc_den),hl
    ld   de,(rc_hq4)
    call rc_hadd
    ld   a,(rc_hr4)
    call rc_hacc
    jr   rc_stepped
rc_slow                         ; a CLAMPED step: 1..3 single columns
    if RC_PACED
    ; ---- the one place a pair's step costs more than the flat C_CSKIP
    ;      or C_COLS budgeted for it: up to three single-column steps at
    ;      about 107 us each instead of one whole-pair add.  It happens
    ;      at most twice a face -- the first step off an odd left edge
    ;      and the clamp at the right one -- so it charges its own hook
    ;      here rather than fattening every skipped pair's charge by two
    ;      thirds.  A = delta survives cost_unit (it preserves AF);
    ;      B does NOT survive a yield, hence the reload below.
    push af
    ld   b,a
    ld   hl,C_CSKIP
    ld   de,C_CSTEP
rc_slchg
    add  hl,de
    djnz rc_slchg
    ld   b,h
    ld   c,l
    call cost_unit
    pop  af
    endif
    ld   b,a
rc_slowl
    push bc
    ld   hl,(rc_num)
    ld   de,(rc_hbn)
    add  hl,de
    ld   (rc_num),hl
    ld   hl,(rc_den)
    ld   de,(rc_dhn)
    add  hl,de
    ld   (rc_den),hl
    ld   de,(rc_hq)
    call rc_hadd
    ld   a,(rc_hr)
    call rc_hacc
    pop  bc
    djnz rc_slowl
rc_stepped
    ld   a,(rc_p)
    inc  a
    ld   (rc_p),a
    ld   hl,rc_np
    dec  (hl)
    jp   nz,rc_pairloop
    ret


; ---------------------------------------------------------------------
;  rc_hadd -- (rc_h) += DE, or -= it; the direction is the face's, fixed
;  at setup.  rc_hacc carries the Bresenham remainder into it.
; ---------------------------------------------------------------------
rc_hadd
    ld   hl,(rc_h)
    ld   a,(rc_hneg)
    or   a
    jr   nz,rc_hsb
    add  hl,de
    ld   (rc_h),hl
    ret
rc_hsb
    or   a
    sbc  hl,de
    ld   (rc_h),hl
    ret

rc_hacc                         ; A = the remainder to add
    ld   hl,rc_acc
    add  a,(hl)
    ld   (hl),a
    ld   hl,rc_w2
    cp   (hl)
    ret  c
    sub  (hl)
    ld   (rc_acc),a
    ld   de,1
    jr   rc_hadd


    if RC_PACED
; =====================================================================
;  rc_charge -- ONE OPEN PAIR'S UPPER BOUND, charged before any of
;  rc_column's setup runs.
;
;  Nothing rc_column will compute is known yet -- that is the point, the
;  hook must run FIRST -- but everything needed to BOUND it is:
;
;    (rc_h)  +- (rc_hq)+1 brackets the two byte columns' half heights
;            (they are one Bresenham step either side of the centre, and
;            the accumulator carry is at most 1), so
;              j_hi = min(RC_RC, max(0, h+hq+1) >> 4)   >= the taller j
;              j_lo = min(RC_RC, max(0, h-hq-1) >> 4)   <= the shorter
;    rc_up / rc_dn at this pair bound the rows a nearer face left free:
;              free = up + (VP_H - dn)  >= every row this pair can draw,
;            bands and edges together -- which is what stops the bound
;            re-billing, face after face, rows that are already owned
;
;    rows  <= min(2*j_hi + 1, free)        the PUSH-filled band rows
;    edges <= min(2*(j_hi - j_lo), free)   the taller column's own rows
;    bands <= (up > 0) + (dn < VP_H)
;
;  and the charge is C_COLS + C_CBAND*bands + C_COLR*rows + C_CEDGE*edges.
;  It over-charges an occluded or clipped pair, which is the safe
;  direction; costcol.inc carries why the previous exact-but-late charge
;  broke the lock.
;
;  Clobbers AF BC DE HL.  Falls into cost_unit, which yields if the
;  bound does not fit the interval.
; =====================================================================
;  ONE MULTIPLY, AND IT IS SHIFTS.  This ran rc_mul8 -- an eight-iteration
;  loop -- TWICE, once for the rows and once for the edges, and counted the
;  bands besides: about 500 us a pair, 11 ms of a frame at 22 pairs, of
;  pure charging overhead.  Worse, it is work that happens INSIDE the
;  interval it is charging for, so every microsecond of it also had to be
;  carried by C_COLS.  Three constraints, asserted below, remove all of it:
;
;    C_CBAND == 0        the fit puts the whole fixed cost in C_COLS (almost
;                        every drawn pair has two bands), so the band count
;                        need not be computed at all
;    C_CEDGE == 8*C_COLR an edge row is charged as eight band rows, so
;                        rows + 8*edges is ONE quantity and one multiply
;    C_COLR  == 21       21 = 16 + 4 + 1, so that multiply is six ADD HL
;
;  The asserts are the point: change a constant and the build fails rather
;  than the charge quietly meaning something else.
    assert C_CBAND == 0
    assert C_CEDGE == 8*C_COLR
    assert C_COLR == 21
rc_charge
    ld   hl,(rc_pup)
    ld   a,(hl)                 ; up = COUNT of free rows above
    ld   c,a
    ld   hl,(rc_pdn)
    ld   a,(hl)                 ; dn = first free row below, <= VP_H
    ld   e,a
    ld   a,VP_H
    sub  e
    add  a,c                    ; free = up + (VP_H - dn), <= VP_H
    ld   (rc_tf),a

    ld   hl,(rc_h)
    ld   de,(rc_hq)
    add  hl,de
    inc  hl                     ; h + hq + 1 >= both columns' h
    call rcc_j
    ld   (rc_jhi),a
    ld   hl,(rc_h)
    ld   de,(rc_hq)
    or   a
    sbc  hl,de
    dec  hl                     ; h - hq - 1 <= both columns' h
    call rcc_j
    ld   c,a                    ; C = j_lo
    ld   a,(rc_jhi)
    sub  c
    add  a,a                    ; 2*(j_hi - j_lo) >= the edge rows
    ld   hl,rc_tf
    cp   (hl)
    jr   c,rcc_eok
    ld   a,(hl)                 ; ...clipped to the free rows
rcc_eok
    ld   l,a                    ; DE = 8 * edges, <= 768
    ld   h,0
    add  hl,hl
    add  hl,hl
    add  hl,hl
    ex   de,hl
    ld   a,(rc_jhi)
    add  a,a
    inc  a                      ; 2*j_hi + 1 >= the band rows, <= 97
    ld   hl,rc_tf
    cp   (hl)
    jr   c,rcc_rok
    ld   a,(hl)
rcc_rok
    ld   l,a
    ld   h,0
    add  hl,de                  ; HL = rows + 8*edges, <= 865
    ld   d,h                    ; ...times 21, by shifts
    ld   e,l
    add  hl,hl                  ; 2
    add  hl,hl                  ; 4
    add  hl,de                  ; 5
    add  hl,hl                  ; 10
    add  hl,hl                  ; 20
    add  hl,de                  ; 21
    ld   de,C_COLS
    add  hl,de
    ld   b,h
    ld   c,l
    jp   cost_unit

; HL = a half height bound, Q12.4 signed -> A = min(RC_RC, max(0,HL)>>4)
rcc_j
    bit  7,h
    jr   z,rccj1
    xor  a                      ; negative: no rows at all
    ret
rccj1
    ld   de,RC_RC*16
    or   a
    sbc  hl,de
    jr   c,rccj2
    ld   a,RC_RC                ; at or past a full half-viewport
    ret
rccj2
    add  hl,de                  ; HL < RC_RC*16 = 768: the shift fits A
    srl  h
    rr   l
    srl  h
    rr   l
    srl  h
    rr   l
    srl  h
    rr   l
    ld   a,l
    ret
    endif


; =====================================================================
;  rc_column -- one PAIR of byte columns of one face.
; =====================================================================
rc_column
    ; ---- u = CTEX_BW * N / D, both ends clamped.  N and D can leave
    ;      their legal range at the outermost pair, where the sample
    ;      column is outside the face; clamping u is what the model's
    ;      min/max on t2 does, and it is one compare each.
    ld   hl,(rc_den)
    bit  7,h
    jr   nz,rc_u0               ; D <= 0
    ld   a,h
    or   l
    jr   z,rc_u0
    ex   de,hl                  ; DE = D
    ld   hl,(rc_num)
    bit  7,h
    jr   nz,rc_u0               ; N < 0
    or   a
    sbc  hl,de
    jr   c,rc_udo
    ld   a,CTEX_BW-1            ; N >= D: the far end
    jr   rc_uclamp
rc_u0
    xor  a
    jr   rc_uclamp
rc_udo
    add  hl,de                  ; HL = N again
    call rc_udiv                ; A = the four-bit quotient
rc_uclamp
    ld   c,a
    ld   a,(rc_flip)
    or   a
    jr   z,rc_unf
    ld   a,CTEX_BW-1
    sub  c
    ld   c,a
rc_unf
    ld   a,(rc_texpg)
    add  a,c
    ld   (rc_page),a            ; the texture page: base + u

    ; ---- EACH BYTE COLUMN OF THE PAIR HAS ITS OWN j, half a pair-step
    ;      either side of the centre sample, and that difference IS the
    ;      silhouette staircase.  MEASURED over 9424 pairs from 400 real
    ;      states: the two columns differ in 62.5% of pairs, by four
    ;      scanlines or more in 12%, and by 104 in the worst one -- so a
    ;      pair drawn to a single j does not step, it BREAKS.
    ;
    ;      The PUSH therefore fills only as far as the SHORTER column and
    ;      the taller one's remaining rows are drawn on their own, below.
    ;      That sounds like per-pixel work and is not: the extra rows
    ;      TELESCOPE, summing over a face to its total height travel
    ;      (jhi - jlo <= CYH) rather than to anything proportional to its
    ;      width.  MEASURED, it is 2.5% more bytes for a silhouette as
    ;      accurate as the span renderer's.
    call rc_hbwd                ; the LEFT column, at t2 - 1
    ld   (rc_hha),hl
    call rc_jof
    ld   (rc_ja),hl
    call rc_hfwd                ; ...and the RIGHT, at t2 + 1
    ld   (rc_hhb),hl
    call rc_jof
    ld   de,(rc_ja)
    or   a
    sbc  hl,de
    jr   c,rc_jleft
    add  hl,de                  ; HL = jB, the right column is taller
    ld   (rc_jt),hl
    ld   hl,(rc_ja)
    ld   (rc_j),hl
    ld   hl,(rc_hhb)
    ld   (rc_ht),hl
    ld   hl,(rc_hha)
    ld   (rc_hs),hl
    ld   a,1
    jr   rc_jset
rc_jleft
    add  hl,de                  ; HL = jB, the SHORT one; DE = jA, the tall
    ld   (rc_jt),de
    ld   (rc_j),hl
    ld   hl,(rc_hha)
    ld   (rc_ht),hl
    ld   hl,(rc_hhb)
    ld   (rc_hs),hl
    xor  a
rc_jset
    ld   (rc_eofs),a            ; which byte of the pair is the tall one

    ; ---- CTABT IS INDEXED BY h IN QUARTER SCANLINES, not by j.  Indexing
    ;      it by j threw away the bottom four bits the projector went to
    ;      the trouble of computing: across adjacent pairs, while h moved
    ;      less than a whole scanline j did not move at all, so the mortar
    ;      courses ran dead flat and then every one of them jumped at
    ;      once.  See colmodel.ctab.  4*(h >> 2) is h & ~3, so the finer
    ;      index costs an AND where the coarse one cost two shifts.
    ld   hl,(rc_hs)
    call rc_tix
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    inc  hl
    ld   (rc_step),de
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    ld   (rc_idx0),de
    ; ---- A DOOR IN MOTION HAS SLID UP, AND THE TEXTURE WENT WITH IT.
    ;      Raising the bottom row alone CLIPS the slab and leaves the art
    ;      nailed where it was -- the lock band sat in the middle of the
    ;      screen the whole way up.  A slab that has risen by dlift/256
    ;      of its height shows, at its first visible row, the point
    ;      dlift/256 of the way DOWN the art; the top of the slab has
    ;      gone above the lintel.  The coordinate is 8.8 over a 256-byte
    ;      page, so "dlift/256 of the whole texture" is dlift added to
    ;      its HIGH byte, and nothing else has to change: the per-row
    ;      step is unaltered, and the band below and the edge runs both
    ;      derive their start from this one.
    ld   a,(rc_kind)
    and  2
    jr   z,rc_noslide
    ld   a,(rc_dlift)
    ld   hl,rc_idx0+1
    add  a,(hl)
    ld   (hl),a
rc_noslide

    ; ---- the row range: RC_RC -+ j, clipped to the viewport
    ld   hl,(rc_j)
    ld   a,h
    or   a
    jr   nz,rc_jbig
    ld   a,l
    cp   RC_RC
    jr   c,rc_jsmall
rc_jbig
    xor  a
    ld   (rc_r0),a
    ld   a,VP_H-1
    ld   (rc_r1),a
    jr   rc_rows
rc_jsmall
    ld   c,a
    ld   a,RC_RC
    sub  c
    ld   (rc_r0),a
    ld   a,RC_RC
    add  a,c
    cp   VP_H
    jr   c,rc_r1ok
    ld   a,VP_H-1
rc_r1ok
    ld   (rc_r1),a
rc_rows
    ; ---- A DOOR PART WAY THROUGH ITS RUN HAS RISEN.  Walls never do,
    ;      so this is one test on the kind byte for everything else.
    ld   a,(rc_kind)
    and  2                          ; bit 1: a door in MOTION, and only
    jr   z,rc_nolift                ; those ever rise
    ld   a,(rc_r0)
    ld   (rc_ltop),a
    ld   a,(rc_r1)
    ld   c,a                        ; C survives rc_mul8; B does not
    ld   hl,(rc_j)
    call rc_lift
    ld   (rc_r1),a
rc_nolift
    ; (the pair's charge was taken at the TOP of rc_column, by rc_charge,
    ;  as an upper bound -- see costcol.inc.  Charging here, where the
    ;  band count and row count are exact, billed everything above this
    ;  line to the PREVIOUS hook and broke the frame lock.)

    ; ---- BAND ABOVE THE HORIZON: rows r0 .. up-1.  Its texture
    ;      coordinate is CTABT's idx0 with no arithmetic at all, because
    ;      idx0 is DEFINED as where the face's first visible row lands.
    xor  a
    ld   (rc_cont),a            ; ...unless the top band says otherwise
    ld   hl,(rc_pup)
    ld   c,(hl)                 ; up = uncovered rows above
    ld   a,(rc_r0)
    cp   c
    jr   nc,rc_nobandup
    ld   b,a
    ld   a,c
    sub  b                      ; rows = up - r0
    ld   (rc_n),a
    ld   a,b
    ld   (rc_row),a
    ld   hl,(rc_idx0)
    ld   (rc_idx),hl
    ld   hl,(rc_pdn)
    ld   a,(hl)
    cp   c                      ; dn == up: the two bands abut, so the
    jr   nz,rc_bandup           ; walk will end exactly where the lower
    ld   a,1                    ; one starts
    ld   (rc_cont),a
rc_bandup
    call rc_band
rc_nobandup

    ; ---- BAND BELOW: rows dn .. r1.  It starts wherever the nearer face
    ;      stopped, so its coordinate costs one 8x16 multiply -- and only
    ;      on a face that is PARTLY occluded, which is the rare path.
    ld   hl,(rc_pdn)
    ld   c,(hl)                 ; dn
    ld   a,c
    ld   (rc_pdn2),a
    ld   a,(rc_r1)
    cp   c
    jr   c,rc_nobanddn
    sub  c
    inc  a                      ; rows = r1 - dn + 1
    ld   (rc_n),a
    ld   a,c
    ld   (rc_row),a
    ld   a,(rc_cont)
    or   a
    jr   z,rc_dnmul
    ld   hl,(rc_idxend)         ; the top band's walk ended here
    jr   rc_dnset
rc_dnmul
    ld   a,(rc_pdn2)            ; dn
    ld   hl,rc_r0
    sub  (hl)                   ; dn - r0, 0..VP_H
    ld   de,(rc_step)
    call rc_mul8
    ld   de,(rc_idx0)
    add  hl,de
rc_dnset
    ld   (rc_idx),hl
    call rc_band
rc_nobanddn

    ; =================================================================
    ;  NOT DONE: THE SILHOUETTE STAIRCASE, and the design for it.
    ;
    ;  A pair is 4 Mode 0 pixels wide and gets ONE j, so a raked wall's
    ;  top and bottom edge steps in 4-pixel jumps where the span renderer
    ;  stepped in 2.  Centring the sample (above) halves the error at each
    ;  byte but cannot change the step, because both bytes of a PUSH share
    ;  a scanline by construction.
    ;
    ;  THE FIX IS NOT TO MOVE A BYTE, IT IS TO SHORTEN THE PUSH.  Compute
    ;  j for BOTH byte columns of the pair -- they are half a pair-step
    ;  either side of the centre j already computed, so it is one add and
    ;  one subtract of (rc_hq4)/4, not a second Bresenham.  Then:
    ;
    ;      fill rows CYH +- j_short with PUSH, as now
    ;      fill the (j_tall - j_short) rows at each end of the TALLER
    ;        column alone, with LD (HL),A -- 2 us a byte and there are
    ;        usually one or two of them
    ;      record the interval over j_TALL, so a farther face is still
    ;        correctly occluded and no byte is written twice
    ;
    ;  Which column is the taller one is fixed per FACE, not per pair: it
    ;  is the right one exactly when hb > ha, which rc_face already knows.
    ;  So it is one patched offset, like rq_wspan's, and no branch.
    ;
    ;  The cap survives -- every byte is still written once -- and the
    ;  cost is bounded by the wedge's total travel, which is what
    ;  raster.asm charges its Bresenham steps for.  It is NOT free on a
    ;  steep rake, where j_tall - j_short can be several rows, so it wants
    ;  a term in the charge (C_CEDGE per extra row) before it ships.
    ; =================================================================

    ; ---- THE TALLER COLUMN'S OWN ROWS, above and below the pair, in ONE
    ;      byte column.  They carry the taller column's own CTABT entry,
    ;      so the texture spans its real extent and not the short one's.
    ld   hl,(rc_jt)
    ld   de,(rc_j)
    or   a
    sbc  hl,de
    jp   z,rc_noedge            ; both columns agree: nothing to do

    ld   hl,(rc_ht)             ; the taller column's own mapping
    call rc_tix
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    inc  hl
    ld   (rc_estep),de
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    ld   (rc_eidx0),de
    ld   a,(rc_kind)                ; ...and the taller column slides too
    and  2
    jr   z,rc_enoslide
    ld   a,(rc_dlift)
    ld   hl,rc_eidx0+1
    add  a,(hl)
    ld   (hl),a
rc_enoslide

    ; the taller column's own row range, clipped to the viewport
    ld   hl,(rc_jt)
    ld   a,h
    or   a
    jr   nz,rc_etbig
    ld   a,l
    cp   RC_RC
    jr   c,rc_etsml
rc_etbig
    xor  a
    ld   (rc_r0t),a
    ld   a,VP_H-1
    ld   (rc_r1t),a
    jr   rc_etrows
rc_etsml
    ld   c,a
    ld   a,RC_RC
    sub  c
    ld   (rc_r0t),a
    ld   a,RC_RC
    add  a,c
    cp   VP_H
    jr   c,rc_et1ok
    ld   a,VP_H-1
rc_et1ok
    ld   (rc_r1t),a
rc_etrows
    ; ---- AND THE TALLER COLUMN RISES WITH THE PAIR, or its edge run
    ;      hangs below the door it belongs to.
    ;
    ;      IT SITS AFTER rc_etrows AND NOT BEFORE IT.  rc_etbig -- the
    ;      path taken when the taller column is TALLER THAN THE VIEWPORT,
    ;      which is every near door and every raked one -- jumps straight
    ;      here, so a lift placed on the rc_etsml path alone was skipped
    ;      by exactly the faces that needed it.  The pair's own lift is
    ;      after rc_rows for the same reason.  MEASURED: 4 of 24 moving
    ;      door batches mismatched, every one of them raked.
    ld   a,(rc_kind)
    and  2
    jr   z,rc_etnolift
    ld   a,(rc_r0t)
    ld   (rc_ltop),a
    ld   a,(rc_r1t)
    ld   c,a
    ld   hl,(rc_jt)
    call rc_lift
    ld   (rc_r1t),a
rc_etnolift

    ; the byte column: 2*p + which side
    ld   a,(rc_p)
    add  a,a
    ld   hl,rc_eofs
    add  a,(hl)
    ld   (rc_ecol),a

    ; --- ABOVE: rows r0t .. min(r0-1, up).  It starts at the taller
    ;     column's own first visible row, so its coordinate is idx0.
    ld   hl,(rc_pup)
    ld   c,(hl)                 ; rc_up is a COUNT, so the last row still
    ld   a,c                    ; free above the horizon is rc_up - 1 --
    or   a                      ; and a count of zero means none at all
    jr   z,rc_noup
    dec  c
    ld   a,(rc_r0)
    or   a
    jr   z,rc_noup              ; the pair already starts at row 0, so
    dec  a                      ; there is nothing above it -- and r0-1
    cp   c                      ; would wrap to 255 and paint the lot
    jr   c,rc_eu1
    ld   a,c
rc_eu1
    ld   c,a                    ; e1
    ld   a,(rc_r0t)
    cp   c
    jr   z,rc_eugo
    jr   nc,rc_noup
rc_eugo
    ld   b,a
    ld   a,c
    sub  b
    inc  a
    ld   (rc_en),a              ; rows
    ld   a,b
    ld   (rc_erow),a
    ld   hl,(rc_eidx0)
    ld   (rc_eidx),hl
    call rc_edge                ; charged by rc_charge's C_CEDGE bound
rc_noup

    ; --- BELOW: rows max(r1+1, dn) .. r1t.  It starts wherever the pair
    ;     stopped, which costs the one 8x16 multiply this file already has.
    ld   hl,(rc_pdn)
    ld   c,(hl)                 ; dn
    ld   a,(rc_r1)
    inc  a                      ; r1 + 1
    cp   c
    jr   nc,rc_ed1
    ld   a,c
rc_ed1
    ld   c,a                    ; e0
    ld   a,(rc_r1t)
    cp   c
    jr   c,rc_nodn
    sub  c
    inc  a
    ld   (rc_en),a
    ld   a,c
    ld   (rc_erow),a
    ld   hl,rc_r0t
    sub  (hl)                   ; e0 - r0t
    ld   de,(rc_estep)
    call rc_mul8
    ld   de,(rc_eidx0)
    add  hl,de
    ld   (rc_eidx),hl
    call rc_edge                ; charged by rc_charge's C_CEDGE bound
rc_nodn
    jr   rc_edone
rc_noedge
    ld   a,(rc_r0)
    ld   (rc_r0t),a
    ld   a,(rc_r1)
    ld   (rc_r1t),a
rc_edone

    ; ---- and the pair's covered interval grows to the TALLER column's
    ;      rows.  It has to pick one of the two, because rc_up and rc_dn
    ;      are per PAIR and the edge rows cover only one byte column.
    ;      Recording the taller one lets a farther face be skipped where
    ;      the SHORTER column is not wall, so the background shows there
    ;      -- which is what that column should show, since this face does
    ;      not reach it.  Recording the shorter one would instead let a
    ;      farther face paint OVER this face's edge, and that is the error
    ;      that looks wrong.
    ld   hl,(rc_pup)
    ld   a,(rc_r0t)
    cp   (hl)
    jr   nc,rc_upok
    ld   (hl),a
rc_upok
    ld   hl,(rc_pdn)
    ld   a,(rc_r1t)
    inc  a
    cp   (hl)
    ret  c
    ld   (hl),a
    ret


; =====================================================================
;  rc_edge -- (rc_en) rows of ONE byte column, from viewport row
;  (rc_erow), column (rc_ecol), coordinate (rc_eidx), step (rc_estep).
;
;  It rebuilds the screen address from VPLINE every row instead of
;  stepping it, which is the character-row interleave handled for free at
;  the price of about 25 us.  That is deliberate: these runs are ONE to
;  THREE rows long -- MEASURED, 82 edge bytes a frame against 3600 filled
;  ones -- so the unrolled block that pays for itself in rc_band would be
;  pure setup here.  SP is not the screen in this routine, so unlike
;  everything else in this file it may CALL freely.
; =====================================================================
rc_edge
    ld   a,(rc_erow)
    add  a,a
    ld   h,VPLINE/256
    ld   l,a
    ld   a,(hl)
    inc  l
    ld   h,(hl)
    ld   l,a
    ld   a,(rc_ecol)
    add  a,l
    ld   l,a
    ld   a,h
rc_ebuf
    adc  a,#C0                  ; buffer base; patched by raster_setbuf
    ld   h,a
    ld   a,(rc_eidx+1)          ; the index is the coordinate's high byte
    ld   e,a
    ld   a,(rc_page)
    ld   d,a
    ld   a,(de)
    ld   (hl),a
    ld   hl,(rc_eidx)
    ld   de,(rc_estep)
    add  hl,de
    ld   (rc_eidx),hl
    ld   hl,rc_erow
    inc  (hl)
    ld   hl,rc_en
    dec  (hl)
    jp   nz,rc_edge
    ret


; HL = a half height, Q12.4 -> HL = its CTABT entry.  The table is
; indexed in QUARTER scanlines, and 4*(h >> 2) is h & ~3.
rc_tix
    bit  7,h
    jr   z,rc_tx1
    ld   hl,0                   ; a negative half height reads entry 0
rc_tx1
    ld   de,CHMAX
    or   a
    sbc  hl,de
    jr   c,rc_tx2
    ld   hl,0                   ; at or past the near plane: clamp
rc_tx2
    add  hl,de
    ld   a,l
    and  #FC
    ld   l,a
    ld   de,CTABT
    add  hl,de
    ret

; A = a face's BOTTOM row -> A = it, RAISED towards the horizon by
; (rc_dlift)/256 of its distance from the horizon.
;
;  THIS IS HOW A DOOR OPENS: it goes UP.  Scaling the face's half height
;  instead moved both edges and read as the door being crushed towards
;  eye level rather than lifted out of the way.
;
;  ONLY THE BOTTOM MOVES, and it travels the face's WHOLE height --
;  from its own bottom row all the way to its own top row, so the door
;  opens completely rather than stopping half way.
;
;  IT COULD NOT DO THAT IN THE NORMAL PASS.  rc_up / rc_dn describe a
;  pair's covered rows as ONE interval CENTRED ON THE HORIZON, and a door
;  risen past the horizon covers an interval that does not touch it --
;  which those two bytes cannot express.  So it was clamped at the
;  horizon, and the door stopped half way and then vanished.  A moving
;  door is now drawn in a SECOND PASS, on top and outside the occlusion
;  scheme altogether (see raster_colframe), and the clamp goes with it.
;
;  Clobbers AF B DE HL; C is preserved by rc_mul8 and carries the input.
rc_lift
    ld   a,(rc_dlift)
    or   a
    ld   a,c
    ret  z                          ; not moving: the bottom is unchanged
    ld   (rc_lj),hl                 ; keep j
    add  hl,hl
    inc  hl                         ; full = 2j+1, the UNCLIPPED height
    ld   (rc_lfull),hl
    ; d = (full * dlift) >> 8, as two 8x8s: (hi*256 + lo)*f >> 8 is
    ; hi*f + (lo*f >> 8), and full <= 769 so hi <= 3.
    ld   a,(rc_dlift)
    ld   e,a
    ld   d,0
    ld   a,(rc_lfull+1)
    call rc_mul8
    ld   (rc_lacc),hl
    ld   a,(rc_dlift)
    ld   e,a
    ld   d,0
    ld   a,(rc_lfull)
    call rc_mul8
    ld   e,h                        ; ...the high byte of lo*f
    ld   d,0
    ld   hl,(rc_lacc)
    add  hl,de                      ; HL = d, the rows it has risen
    ex   de,hl
    ld   hl,(rc_lj)                 ; CYH + j, the UNCLIPPED bottom edge --
    ld   a,l                        ; added WITHOUT touching BC, because C
    add  a,RC_RC                    ; carries the clipped bottom across
    ld   l,a                        ; both rc_mul8 calls and `ld bc,nn`
    ld   a,h                        ; would have thrown it away
    adc  a,0
    ld   h,a
    or   a
    sbc  hl,de                      ; ...after the slide
    bit  7,h
    jr   nz,rcl_top                 ; risen clean off the top
    ld   a,h
    or   a
    jr   nz,rcl_keep                ; still below the viewport: keep clip
    ld   a,l
    cp   c
    jr   nc,rcl_keep                ; ...never lower than it already was
    ld   hl,rc_ltop
    cp   (hl)
    ret  nc
rcl_top
    ld   a,(rc_ltop)                ; never above its own top row
    ret
rcl_keep
    ld   a,c
    ret

; HL = a half height, Q12.4 -> HL = j, clamped to [0, CJMAX].
rc_jof
    bit  7,h
    jr   z,rc_jo1
    ld   hl,0                   ; a negative half height paints nothing
rc_jo1
    srl  h
    rr   l
    srl  h
    rr   l
    srl  h
    rr   l
    srl  h
    rr   l
    ld   de,CJMAX
    or   a
    sbc  hl,de
    jr   c,rc_jo2
    ld   hl,CJMAX
    ret
rc_jo2
    add  hl,de
    ret

; -> HL = the half height ONE COLUMN on from the centre sample, and
;    rc_hbwd one column back.  They are the same Bresenham step rc_pnext
;    takes, run without committing it: (rc_acc) and (rc_h) are left alone.
rc_hfwd
    ld   a,(rc_acc)
    ld   c,a
    ld   a,(rc_hr)
    add  a,c
    ld   hl,rc_w2
    ld   b,0
    cp   (hl)
    jr   c,rc_hf1
    inc  b
rc_hf1
    ld   e,b
    ld   d,0
    ld   hl,(rc_h)
    ld   a,(rc_hneg)
    or   a
    jr   nz,rc_hf2
    add  hl,de
    ld   de,(rc_hq)
    add  hl,de
    ret
rc_hf2
    or   a
    sbc  hl,de
    ld   de,(rc_hq)
    or   a
    sbc  hl,de
    ret

rc_hbwd
    ld   a,(rc_acc)
    ld   hl,rc_hr
    ld   b,0
    cp   (hl)
    jr   nc,rc_hb1
    inc  b
rc_hb1
    ld   e,b
    ld   d,0
    ld   hl,(rc_h)
    ld   a,(rc_hneg)
    or   a
    jr   nz,rc_hb2
    or   a
    sbc  hl,de
    ld   de,(rc_hq)
    or   a
    sbc  hl,de
    ret
rc_hb2
    add  hl,de
    ld   de,(rc_hq)
    add  hl,de
    ret


; =====================================================================
;  rc_band -- (rc_n) scanlines from viewport row (rc_row), of the column
;  pair (rc_p), out of texture page (rc_page) at coordinate (rc_idx),
;  stepping (rc_step).
;
;  SP IS THE SCREEN from the first unit to the last, so NOTHING between
;  them may CALL, RET, PUSH or POP -- the block entries are self-modified
;  JPs and the blocks jump back to fixed labels.  The only registers free
;  while a band is running are A, E (which every unit overwrites anyway)
;  and the index registers; HL, BC and D carry the texture and HL' and BC'
;  the screen.  That is why the run-length arithmetic below is written in
;  A and E alone.
; =====================================================================
rc_band
    ld   a,(rc_n)
    or   a
    ret  z
    ld   (rc_sp2),sp

    ; ---- the screen address of (row, pair), ONE PAST the right byte of
    ;      the pair, which is where PUSH walks back from.
    ld   a,(rc_row)
    add  a,a
    ld   h,VPLINE/256
    ld   l,a
    ld   a,(hl)
    inc  l
    ld   h,(hl)
    ld   l,a
    ld   a,(rc_p)
    add  a,a
    inc  a
    inc  a                      ; 2*p + 2
    add  a,l
    ld   l,a
    ld   a,h
rc_buf
    adc  a,#C0                  ; buffer base; patched by raster_setbuf
    ld   h,a

    ; ---- and the two banks, laid out for the unit below:
    ;        this one   HL = screen, BC = &0800
    ;        the other  HL = texture coordinate 8.8, BC = step,
    ;                   D = texture page, E = scratch
    ld   bc,#0800
    exx
    ld   hl,(rc_idx)
    ld   bc,(rc_step)
    ld   a,(rc_page)
    ld   d,a

    ; ---- run the unrolled blocks.  The character-row wrap is HOISTED
    ;      out of the inner loop -- naive it is 14.0 us a byte and hoisted
    ;      5.6, MEASURED -- so a band is cut at the character-row
    ;      boundaries it crosses: a first partial run from its own phase,
    ;      then whole rows of eight, then a tail.
    ld   a,(rc_row)
    and  7
    ld   e,a                    ; the phase of the first row
    ld   a,8
    sub  e
    ld   e,a                    ; k = scanlines to the next boundary
    ld   a,(rc_n)
    cp   e
    jr   c,rc_btail             ; n < k: the tail alone, no wrap
    sub  e                      ; A = the rows after the first block
    ld   e,a
    and  7
    ld   (rc_n),a               ; ...what the tail will draw
    ld   a,e
    rrca
    rrca
    rrca
    and  #1F                    ; ...and how many WHOLE character rows
    inc  a                      ; plus the first, partial one
    ld   ixl,a                  ; COLBLK counts them down itself
    ld   a,(rc_row)
    and  7
    jr   rc_bgo10               ; enter COLBLK at 10*phase
rc_blkend
    ; COLBLK COUNTS ITS OWN CHARACTER ROWS, in IXL, and only reaches here
    ; when they are all drawn -- so this runs ONCE per band and not once
    ; per eight scanlines.  It went through the offset arithmetic and the
    ; self-modified JP every character row to begin with, at 31 us a time,
    ; and a PC histogram of a full-viewport pair put that at 10.1% of the
    ; whole render, second only to the fill itself.  `dec ixl / jp nz` is
    ; five, and IXL is the one register the fill does not need.
    jr   rc_btail               ; ...and all that is left is the tail
rc_bgo10                        ; A = phase -> COLBLK + 10*phase
    add  a,a
    ld   e,a
    add  a,a
    add  a,a
    add  a,e
    ld   (rc_go+1),a
    jp   rc_go
rc_btail
    ld   a,(rc_n)
    or   a
    jr   z,rc_tailend
    add  a,a                    ; -> COLTAIL + 10*(8-n)
    ld   e,a
    add  a,a
    add  a,a
    add  a,e                    ; 10*n
    ld   e,a
    ld   a,COLTAIL-COLBLK+80
    sub  e
    ld   (rc_go+1),a
    jp   rc_go
rc_tailend
    ld   (rc_idxend),hl         ; where the walk got to.  When the two
    exx                         ; bands of a pair are CONTIGUOUS -- which
    ld   sp,(rc_sp2)            ; they are on any pair a nearer face has
    ret                         ; not cut -- this IS the lower band's
                                ; start coordinate, and rc_column can use
                                ; it instead of multiplying for it.
rc_go
    jp   COLBLK                 ; low byte self-modified above


; ------------------------------------------------------------ helpers ---
; HL >>= (rc_sh)
rc_shr
    ld   a,(rc_sh)
    or   a
    ret  z
    ld   b,a
rs_l
    srl  h
    rr   l
    djnz rs_l
    ret

; HL = dividend, C = divisor (<= 128) -> HL = quotient, A = remainder.
rc_div
    xor  a
    ld   b,16
rd_l
    add  hl,hl
    rla
    cp   c
    jr   c,rd_no
    sub  c
    inc  l
rd_no
    djnz rd_l
    ret

; HL = N (< D), DE = D (< 32768) -> A = floor(CTEX_BW*N/D), 0..15.
rc_udiv
    xor  a
    ld   b,4
ru_l
    add  a,a
    add  hl,hl
    sbc  hl,de
    jr   c,ru_neg
    inc  a
    djnz ru_l
    ret
ru_neg
    add  hl,de
    djnz ru_l
    ret

; A = k, DE = m -> HL = k*m, low 16 bits.
rc_mul8
    ld   hl,0
    ld   b,8
rm8_l
    add  hl,hl
    add  a,a
    jr   nc,rm8_n
    add  hl,de
rm8_n
    djnz rm8_l
    ret


; ----------------------------------------------------------- variables ---
; The record, copied in one LDI run -- these SIX must stay in this order
; and adjacent, because that is the layout kernel.asm writes.
; ----------------------------------------------------------- variables ---
; THEY LIVE IN THE FREE RAM ABOVE QUADS, not in the code segment.  This
; is 104 bytes of per-pair scratch and `assert game_end <= BUCK0` has now
; fired seven times; march.asm places SOLID and MARK the same way, game
; .asm the door tables, and rc_up / rc_dn went first.
;
; EVERY ONE OF THEM IS WRITTEN BEFORE IT IS READ inside a frame, so none
; needs the `db 0` it used to get -- raster_colframe clears the two
; occlusion arrays itself and everything else is set by the face or the
; pair that uses it.
;
; The RECORD -- rc_blo..rc_k -- must stay in this order and adjacent,
; because that is the layout kernel.asm writes and rc_face copies with
; one LDI run.  Laying them out by hand keeps that true and visible.
RC_COVER    equ #3E00
RC_VARS     equ RC_COVER+CNPAIR*2
rc_blo      equ RC_VARS+0    
rc_bhi      equ RC_VARS+1    
rc_hlo      equ RC_VARS+2    
rc_hhi      equ RC_VARS+4    
rc_kind     equ RC_VARS+6    
rc_k        equ RC_VARS+7    
rc_xa       equ RC_VARS+8    
rc_w        equ RC_VARS+9    
rc_w2       equ RC_VARS+10   
rc_sh       equ RC_VARS+11   
rc_flip     equ RC_VARS+12   
rc_pa       equ RC_VARS+13   
rc_np       equ RC_VARS+14   
rc_p        equ RC_VARS+15   
rc_ha0      equ RC_VARS+16   ; the UNSHIFTED half heights, for j
rc_hb0      equ RC_VARS+18   
rc_han      equ RC_VARS+20   ; ...and the normalised ones, for u
rc_hbn      equ RC_VARS+22   
rc_dhn      equ RC_VARS+24   
rc_num      equ RC_VARS+26   
rc_den      equ RC_VARS+28   
rc_dnum     equ RC_VARS+30   
rc_dden     equ RC_VARS+32   
rc_t2       equ RC_VARS+34   ; the sample, clamped into the face...
rc_raw      equ RC_VARS+35   ; ...and unclamped, which is what steps
rc_h        equ RC_VARS+36   ; half height at this pair, Q12.4
rc_j        equ RC_VARS+38   ; the SHORTER byte column's j...
rc_ja       equ RC_VARS+40   
rc_hha      equ RC_VARS+42   ; the two byte columns' half heights...
rc_hhb      equ RC_VARS+44   
rc_hs       equ RC_VARS+46   ; ...and which of them is short and tall
rc_ht       equ RC_VARS+48   
rc_jt       equ RC_VARS+50   ; ...and the taller one's
rc_eofs     equ RC_VARS+52   ; which byte of the pair is the tall one
rc_ecol     equ RC_VARS+53   
rc_erow     equ RC_VARS+54   
rc_en       equ RC_VARS+55   
rc_eidx     equ RC_VARS+56   
rc_eidx0    equ RC_VARS+58   
rc_estep    equ RC_VARS+60   
rc_r0t      equ RC_VARS+62   
rc_r1t      equ RC_VARS+63   
rc_hq       equ RC_VARS+64   ; the h Bresenham: per-column step...
rc_hr       equ RC_VARS+66   
rc_hq4      equ RC_VARS+67   ; ...and per-PAIR step
rc_hr4      equ RC_VARS+69   
rc_hneg     equ RC_VARS+70   
rc_acc      equ RC_VARS+71   
rc_over     equ RC_VARS+73   ; 1 while drawing the overlay pass
rc_texpg    equ RC_VARS+75   
rc_page     equ RC_VARS+76   
rc_step     equ RC_VARS+77   
rc_idx0     equ RC_VARS+79   
rc_idx      equ RC_VARS+81   
rc_idxend   equ RC_VARS+83   ; where a band's texture walk finished
rc_cont     equ RC_VARS+85   ; ...and whether the next band starts there
rc_pdn2     equ RC_VARS+86   
rc_r0       equ RC_VARS+87   
rc_r1       equ RC_VARS+88   
rc_row      equ RC_VARS+89   
rc_n        equ RC_VARS+90   
rc_pup      equ RC_VARS+91   
rc_pdn      equ RC_VARS+93   
rc_rec      equ RC_VARS+95   
rc_left     equ RC_VARS+97   
rc_sp       equ RC_VARS+98   
rc_sp2      equ RC_VARS+100  
rc_tf       equ RC_VARS+102  ; rc_charge: rows still free at the pair
rc_jhi      equ RC_VARS+103  ; ...upper bound on the taller column's j
; rc_lift's 16-bit scratch.  The slide is computed over the face's FULL
; height, 2j+1, which reaches 769 rows on a near door -- so it does not
; fit the byte arithmetic the rest of this block is made of.
rc_lj       equ RC_VARS+104     ; j, kept across the two multiplies
rc_lfull    equ RC_VARS+106     ; 2j+1
rc_lacc     equ RC_VARS+108     ; the high half of the product
rc_ltop     equ RC_VARS+110     ; the face's own top row at this pair
    assert RC_VARS+111 <= #3FF0

; ...EXCEPT this one, which stays a LABEL in the code segment because it
; is the one byte a harness has to write from outside: rasm puts only
; labels in the .sym file, never equs, so an equ here is invisible to
; engine2/tools/emu_rcol.py -- which pokes it to verify the door's slide.
; door_lift writes it on the disc; the test harness pokes it directly.
rc_dlift    db 0

; THE OCCLUSION ARRAYS LIVE IN THE FREE RAM ABOVE QUADS, not in the code
; segment.  They are CNPAIR bytes each and `assert game_end <= BUCK0`
; fired the moment the second drawing pass arrived; march.asm places
; SOLID and MARK the same way and game.asm the door tables.  QUADS ends
; at #3DBF and the door tables take #3DC0-#3DEF, so #3E00 up is free, and
; the CPU stack tops out at #3FF0.
rc_up       equ RC_COVER            ; uncovered rows above the horizon
rc_dn       equ RC_COVER+CNPAIR     ; first uncovered row below it


; =====================================================================
;  THE UNROLLED BLOCKS.  One page holds both: COLBLK at +0, whose eighth
;  unit carries the character-row wrap, and COLTAIL at +96, which never
;  wraps because it only runs the last few scanlines of a band.  Entering
;  at 10*k runs exactly the units from k on, so a run length costs one
;  self-modified JP and nothing is charged to loop control -- the same
;  trick raster.asm's PUSHBLK uses.
;
;  THE TEN INSTRUCTIONS OF A UNIT ARE THE WHOLE COST MODEL: 20.25 us a
;  scanline MEASURED, for two screen bytes.  See the header.
; =====================================================================
    align 256
COLBLK
    repeat 7
    ld   e,h                    ; the texture index IS the high byte...
    ld   a,(de)                 ; ...and D is its page: one sample, 2 us
    add  hl,bc                  ; 8.8 step
    exx
    ld   d,a                    ; one sample, both screen bytes
    ld   e,a
    ld   sp,hl                  ; SP IS THE SCREEN
    push de
    add  hl,bc                  ; next scanline, +&800
    exx
    rend
    ; the eighth: the same, but stepping ACROSS the character row
    ld   e,h
    ld   a,(de)
    add  hl,bc
    exx
    ld   d,a
    ld   e,a
    ld   sp,hl
    push de
    ld   a,l
    add  a,RC_SCRW
    ld   l,a
    ld   a,h
    adc  a,#C8                  ; -&4000 + &800, in the high byte
    ld   h,a
    exx
    dec  ixl                    ; ...one more character row of this band?
    jp   nz,COLBLK
    jp   rc_blkend

    defs COLBLK+96-$
COLTAIL
    repeat 8
    ld   e,h
    ld   a,(de)
    add  hl,bc
    exx
    ld   d,a
    ld   e,a
    ld   sp,hl
    push de
    add  hl,bc
    exx
    rend
    jp   rc_tailend
