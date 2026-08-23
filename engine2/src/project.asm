; =====================================================================
;  engine2/src/project.asm -- wall-face geometry kernel
;
;  Turns ONE wall face, given as its two endpoints ALREADY IN VIEW SPACE,
;  into the screen-space quad the PUSH DE rasteriser consumes:
;
;      xa, ya_top, ya_bot,  xb, yb_top, yb_bot        all Q12.4
;
;  including backface culling, near-plane clipping and side clipping.
;  The bit-exact Python spec is engine2/tools/projmodel.py; the emulator
;  test engine2/test/tst_proj.asm asserts the Z80 reproduces it EXACTLY.
;
;  ------------------------------------------------------------------
;  WHAT CHANGED, AND WHY IT IS FASTER
;  ------------------------------------------------------------------
;  1. NO ROTATION.  proj_face is handed (xv, z) per endpoint.  The march
;     carries them forward with two 16-bit adds per cell step, because a
;     grid corner's view coordinates are affine in the grid indices.
;     proj_face_ij below is the STUB that still builds them from the old
;     per-frame lattice tables, for as long as the old march is in place.
;
;  2. NO RUNTIME NORMALISE.  The projection factor FOCAL_H/z used to be
;     normalised to an 8-bit mantissa at runtime: a BITLEN lookup plus a
;     shift loop, ~80 us on every endpoint.  gentab.py now ships that
;     pre-chewed in PXT[zq] = pm + (sh << 8), so an endpoint is
;
;         zq = clamp((z + 2) >> 2)          the depth index
;         hh = HTAB[zq]                     projected HALF height, Q12.4
;         xs = CX_Q4 +- ((|xv| * PXT.pm) >> PXT.sh)
;
;     TWO table lookups and ONE 16x8 multiply.  The height needs no
;     multiply at all, and because the camera sits at wall mid-height
;     with no pitch, ytop and ybot are CY -+ hh -- mirror images.  Only
;     hh is ever carried, and only hh is ever interpolated.
;
;  3. SIDE CLIPPING MOVED TO SCREEN SPACE.  The projection of a straight
;     3D line is a straight 2D line, so hh is LINEAR in xs along the
;     edge: clamping xs to [0, VP_PW*16] and interpolating hh is exact,
;     and it replaces a view-space clip of z plus a re-projection of the
;     clipped endpoint (which cost a lerp AND a second projection).
;     Only the near plane still has to be clipped in view space, because
;     a point at or behind the eye does not project at all.
;
;  ------------------------------------------------------------------
;  WHY AN ENDPOINT CAN BE REJECTED FOR BEING TOO FAR OUT
;  ------------------------------------------------------------------
;  An endpoint far outside the frustum projects to an arbitrarily large
;  xs, which would not fit int16 and would wreck the clip interpolation.
;  proj_pt therefore reports "too far" for |xs - CX| >= 16384 Q12.4, and
;  proj_face rejects the whole face.  That is SAFE: a face is one cell
;  long and both endpoints have z >= ZNEAR = 0.125, so if any part of it
;  is inside the frustum then
;      |xs - CX| <= (FOCAL_H/ZNEAR) * (K*ZNEAR + max_s(K*s + sqrt(1-s^2)))
;                 = 665 * (0.0722 + 1.1547) = 816 half-byte units
;                 = 13056 Q12.4,
;  a 25% margin under the test.  The same bound keeps xb - xa (needed as
;  the clip denominator) inside int16: |xs| <= 17151, so xb - xa <= 32766.
;
;  ------------------------------------------------------------------
;  FIXED POINT  (owned by engine2/tools/gentab.py, see tab_equ.inc)
;  ------------------------------------------------------------------
;      VIEW   int16 Q6.10   xv (+right) and z (+forward), 1024 = one cell
;      ZQ     uint16        (z_q10 + 2) >> 2, clamped to [32 .. 2047]
;      SX/SY  int16 Q12.4   screen x in half-byte units, y in scanlines
;
;  ------------------------------------------------------------------
;  MEASURED on a cycle-accurate CPC 6128 (engine2/tools/run_proj_test.py
;  and worst_proj.py; CPC microseconds, the timing method calibrated
;  against a 100-NOP loop to 100.01 us).  "march-fed" is proj_face handed
;  view-space endpoints, i.e. what it costs once the new march exists;
;  the other column still pays lat_view twice (proj_face_ij).
;  ------------------------------------------------------------------
;                                     BEFORE    now     march-fed
;    backfacing, early out               51      62        62
;    behind the player                  310     296        97
;    wholly outside the frustum         304     289        90
;    unclipped face                    1424    1227      1028
;    one side plane                    2311    2047      1852
;    two side planes                   3318    2802      2596
;    crosses the near plane            1394    1190       987
;
;    proj_pt,  per endpoint             360     321
;    lerp,     per clipped endpoint     757     672
;    pf_side,  per surviving face         -     149    (dies with the march)
;    mul16x8u                           142     142    (44% of proj_pt)
;    proj_setup, once per frame        1927    1927    (STUB, dies too)
;    lat_view, per endpoint              90      90    (STUB, dies too)
;
;    Worst frame the marcher can produce on the shipped maze is 28
;    candidate faces: 24.35 ms of proj_face + 1.97 ms of proj_setup =
;    26.3 ms, against 31.0 ms before.  Feeding it view space instead
;    (drop 2 x lat_view per face and the whole setup) takes the same
;    frame to 28 x 670 = 18.8 ms.
;
;    Whole geometry kernel over 31392 player states, predicted from the
;    measured fit (engine2/tools/emu_kernel.py time):
;       median 17.0 -> 11.3 ms,  p90 30.6 -> 22.9,  worst 44.1 -> 36.7
;    -- and that still contains the OLD march, which is 10 ms of it.
;
;    WHAT IS LEFT.  Two thirds of an unclipped face is the two
;    projections, and 44% of a projection is one 16x8 quarter-square
;    multiply.  The octave-normalised route (PROJN/HTN) would make it an
;    8x8 but needs a variable shift of xv, which measured out at only
;    ~35 us better per endpoint for twice the error, so it was not taken.
;    The next real lever is the clip: hh is affine in xs, so ONE
;    normalised slope (hb-ha)/(xb-xa) computed per face would replace
;    both 672 us lerps with one divide plus one multiply each.
;
;  PACING.  proj_face counts its clip lerps in (pf_nclip) -- zero on entry,
;  one per near-plane or side-plane lerp -- and nothing in the projector
;  reads it.  main3.asm:cost_face does: a lerp is 864 us MEASURED and it is
;  the whole of the spread between a 1327 us face and a 3919 us one, so
;  counting them is what lets the cost accumulator charge a face for what
;  it actually did instead of for the worst it could have done.  Four
;  instructions after each of the four `call lerp` sites, and nothing else.
;
;  Needs from tab_equ.inc: QSQ HTAB PXT BITLEN RCP BASIS
;                          ZNEAR_Q10 ZNEAR_Q8 ZFAR_Q8 CX_Q4 CY_Q4 VP_PW
;  Clobbers AF BC DE HL and IX.  proj_setup (the stub) uses SP to fill
;  its tables with PUSH, so interrupts must be off there.
; =====================================================================

    assert QSQ == #4000         ; mul8x8u adds the base with SET 6,H

; XMAX_Q4, the right edge of the viewport in Q12.4, is VP_PW*16 and comes
; from src/vpcfg.inc -- the one file that owns the viewport geometry.


; =====================================================================
;  proj_face -- once per candidate wall face
;
;    in:  (c_xa) (c_za)   endpoint A in VIEW space, Q6.10
;         (c_xb) (c_zb)   endpoint B
;         (pf_i0) (pf_j0) cell offset of endpoint A (backface test only)
;         (pf_nd)         face normal 0=N 1=E 2=S 3=W
;    out: (pf_ok) 0 = rejected, 1 = quad written
;         (pf_blo) (pf_bhi)   byte columns, SHORTER endpoint first
;         (pf_hlo) (pf_hhi)   the projected half heights there, Q12.4
;         -- six contiguous bytes, the first six of a quad record.
;    The c_* input block is CLOBBERED (the near clip works in place).
; =====================================================================
proj_face
    xor  a
    ld   (pf_ok),a
    ld   (pf_nclip),a           ; PACING: how many clip lerps this face
    call pf_cull                ; pays for.  main3.asm:cost_face reads it,
                                ; and nothing else in the engine does.
    ret  c
    jr   pf_core

; ---------------------------------------------------------------------
;  proj_face_ij -- STUB entry, kept until the new march lands.
;  Same as proj_face but builds the view-space endpoints itself from the
;  lattice tables, i.e. it still pays proj_setup once per frame and
;  lat_view twice per face.
;    in:  (pf_i0),(pf_j0),(pf_i1),(pf_j1) cell offsets, (pf_nd)
; ---------------------------------------------------------------------
proj_face_ij
    xor  a
    ld   (pf_ok),a
    ld   (pf_nclip),a
    call pf_cull
    ret  c
    ld   a,(pf_i0)
    ld   b,a
    ld   a,(pf_j0)
    ld   c,a
    call lat_view
    ld   (c_xa),hl
    ld   (c_za),de
    ld   a,(pf_i1)
    ld   b,a
    ld   a,(pf_j1)
    ld   c,a
    call lat_view
    ld   (c_xb),hl
    ld   (c_zb),de
    ; fall through

; ---------------------------------------------------------------------
pf_core
    ; ---- near plane: z >= ZNEAR ------------------------------------
    ; Classified in-line, because "both endpoints are in front" is the
    ; overwhelmingly common answer and it must be cheap.
    ld   hl,(c_za)
    ld   de,-ZNEAR_Q10
    add  hl,de
    ld   (cl_da),hl
    ld   b,h
    ld   hl,(c_zb)
    add  hl,de
    ld   (cl_db),hl
    ld   a,h
    and  b
    ret  m                      ; both behind the near plane
    ld   a,h
    or   b
    jp   p,pf_pr                ; both in front
    ld   a,b
    or   a
    jp   p,pf_nb                ; B is the one behind
    ld   hl,(c_xa)
    ld   (l_a),hl
    ld   hl,(c_xb)
    ld   (l_b),hl
    call cl_seta
    call lerp
    push hl                     ; PACING: one clip lerp, 884.4 us MEASURED
    ld   hl,pf_nclip
    inc  (hl)
    pop  hl
    ld   (c_xa),hl
    ld   hl,ZNEAR_Q10
    ld   (c_za),hl
    jr   pf_pr
pf_nb
    ld   hl,(c_xb)
    ld   (l_a),hl
    ld   hl,(c_xa)
    ld   (l_b),hl
    call cl_setb
    call lerp
    push hl                     ; PACING: one clip lerp, 884.4 us MEASURED
    ld   hl,pf_nclip
    inc  (hl)
    pop  hl
    ld   (c_xb),hl
    ld   hl,ZNEAR_Q10
    ld   (c_zb),hl

    ; ---- cheap side REJECT (not a clip) ----------------------------
    ; Projecting an endpoint costs 320 us, so a face that is wholly off
    ; one side must die before that.  This is a sign test on the two
    ; frustum half-planes, L = xv + K*z and R = K*z - xv, which is
    ; exactly what the new march carries incrementally -- DELETE pf_side
    ; and pass the two flags in when that lands.
pf_pr
    call pf_side
    ret  c

    ld   hl,(c_xa)
    ld   de,(c_za)
    call proj_pt
    ret  c                      ; far outside -> the whole face is
    ld   (s_xa),hl
    ld   (s_ha),de
    ld   hl,(c_xb)
    ld   de,(c_zb)
    call proj_pt
    ret  c
    ld   (s_xb),hl
    ld   (s_hb),de

    ; ---- order by projected x, reject zero width -------------------
    ld   de,(s_xa)
    or   a
    sbc  hl,de                  ; HL = xb - xa, no overflow (see header)
    jp   p,pf_ord
    ld   hl,(s_xa)              ; swap the two endpoints
    ld   de,(s_xb)
    ld   (s_xa),de
    ld   (s_xb),hl
    ld   hl,(s_ha)
    ld   de,(s_hb)
    ld   (s_ha),de
    ld   (s_hb),hl
    jr   pf_wid
pf_ord
    ld   a,h
    or   l
    ret  z                      ; zero width
pf_wid

    ; ---- side clipping, in SCREEN space ----------------------------
    ; Reject what is wholly off one side; the survivors have
    ; xa < XMAX and xb > 0, so both clip denominators are positive.
    ld   hl,(s_xb)
    bit  7,h
    ret  nz                     ; xb < 0: wholly left of the viewport
    ld   hl,(s_xa)
    ld   de,-XMAX_Q4
    add  hl,de
    bit  7,h
    ret  z                      ; xa >= XMAX: wholly right of it

    ld   hl,(s_xa)              ; left edge: xa < 0 ?
    bit  7,h
    jr   z,pf_cr
    ex   de,hl
    ld   hl,0
    or   a
    sbc  hl,de
    ld   (l_na),hl              ; na = -xa
    ld   hl,(s_xb)
    ld   (l_nb),hl              ; nb = xb   (na + nb = the width)
    ld   hl,(s_ha)
    ld   (l_a),hl
    ld   hl,(s_hb)
    ld   (l_b),hl
    call lerp
    push hl                     ; PACING: one clip lerp, 884.4 us MEASURED
    ld   hl,pf_nclip
    inc  (hl)
    pop  hl
    ld   (s_ha),hl
    ld   hl,0
    ld   (s_xa),hl

pf_cr
    ld   hl,(s_xb)              ; right edge: xb > XMAX ?
    ld   de,-XMAX_Q4
    add  hl,de
    bit  7,h
    jr   nz,pf_emit
    ld   a,h
    or   l
    jr   z,pf_emit
    ld   (l_na),hl              ; na = xb - XMAX
    ld   hl,XMAX_Q4
    ld   de,(s_xa)
    or   a
    sbc  hl,de
    ld   (l_nb),hl              ; nb = XMAX - xa
    ld   hl,(s_hb)
    ld   (l_a),hl
    ld   hl,(s_ha)
    ld   (l_b),hl
    call lerp
    push hl                     ; PACING: one clip lerp, 884.4 us MEASURED
    ld   hl,pf_nclip
    inc  (hl)
    pop  hl
    ld   (s_hb),hl
    ld   hl,XMAX_Q4
    ld   (s_xb),hl

    ; ---- emit ------------------------------------------------------
    ; The output is the RASTERISER'S form, not the projector's: byte
    ; columns rather than Q12.4 x, half heights rather than ytop/ybot,
    ; and the two endpoints sorted by HEIGHT rather than by x.  All three
    ; are free here -- s_ha and s_hb are already half heights and the
    ; sort is one compare -- and each of them used to cost raster.asm
    ; real work per quad.  See the RECORD note in kernel.asm.
pf_emit
    ld   hl,(s_xb)              ; anything left after clamping?
    ld   de,(s_xa)
    or   a
    sbc  hl,de
    ld   a,h
    or   l
    ret  z

    ; ---- byte columns, ROUNDED OUTWARD: the left edge DOWN and the right
    ;      edge UP, so ba = x >> 5 and bb = (x + 31) >> 5, i.e. <<3 and
    ;      take H.  x is clamped to [0, XMAX_Q4] above, so 0 <= ba <= bb
    ;      <= VP_BW and the shift cannot overflow (XMAX_Q4+31 << 3 <
    ;      32768).
    ;
    ;      ROUNDING TO NEAREST LEFT GAPS.  Two faces that meet at a depth
    ;      step share one projected x; rounded to nearest both land on the
    ;      same byte, and a run length must be EVEN (PUSH DE writes two
    ;      bytes), so that byte could be dropped by BOTH of them -- a
    ;      2-pixel stripe of ceiling between two walls.  Rounded outward
    ;      the two faces OVERLAP by a byte instead, and overlap is
    ;      invisible: the painter order draws the nearer face last.
    ld   hl,(s_xa)
    add  hl,hl
    add  hl,hl
    add  hl,hl
    ld   b,h                    ; B = ba = xa >> 5,      rounded DOWN
    ld   hl,(s_xb)
    ld   de,31
    add  hl,de
    add  hl,hl
    add  hl,hl
    add  hl,hl
    ld   c,h                    ; C = bb = (xb+31) >> 5, rounded UP

    ; ---- column 0 is the one edge a run cannot be widened to the LEFT
    ;      of, so when the face starts there hand the rasteriser an EVEN
    ;      bb and it never has to: with the left edge at 0 and the right
    ;      edge even, every span it cuts out of this quad has an even byte
    ;      width.  bb is odd in that branch, so bb+1 <= VP_BW, which is
    ;      even.  raster.asm:rq_lt0 is the other half of this rule.
    ld   a,b
    or   a
    jr   nz,pf_bok
    bit  0,c
    jr   z,pf_bok
    inc  c
pf_bok

    ; ---- which endpoint is TALLER?  Its byte column is the edge that is
    ;      PINNED in both of the rasteriser's wedges.  hb >= ha counts as
    ;      "right", which is what rastermodel.py's `if hb < ha` says.
    ld   hl,(s_hb)
    ld   de,(s_ha)
    or   a
    sbc  hl,de                  ; hb - ha
    jr   c,pf_lt

    ld   hl,(s_hb)              ; right endpoint taller
    ld   (pf_hhi),hl
    ld   (pf_hlo),de            ; DE is still ha
    ld   a,b
    ld   (pf_blo),a
    ld   a,c
    ld   (pf_bhi),a
    jr   pf_edone
pf_lt
    ld   hl,(s_hb)              ; left endpoint taller
    ld   (pf_hlo),hl
    ld   (pf_hhi),de
    ld   a,c
    ld   (pf_blo),a
    ld   a,b
    ld   (pf_bhi),a
pf_edone
    ld   a,1
    ld   (pf_ok),a
    ret


; ---------------------------------------------------------------------
;  pf_cull -- backface test, CY set = cull.
;  The face lies on an integer grid line and the player is inside cell 0,
;  so "player on the outward side" is a test against 0:
;    N: j >= 1   E: i <= 0   S: j <= 0   W: i >= 1
; ---------------------------------------------------------------------
pf_cull
    ld   a,(pf_nd)
    ld   hl,pf_ctab
    ld   d,0
    ld   e,a
    add  hl,de
    ld   a,(hl)
    ld   c,a                    ; b0 = axis (0 = j, 1 = i), b1 = sense
    rrca
    ld   a,(pf_j0)
    jr   nc,pf_cax
    ld   a,(pf_i0)
pf_cax
    bit  1,c
    jr   nz,pf_cle
    or   a                      ; need >= 1
    scf
    ret  z
    bit  7,a
    scf
    ret  nz
    or   a
    ret
pf_cle
    or   a                      ; need <= 0
    ret  z
    bit  7,a
    ret  nz
    scf
    ret

pf_ctab
    db   #00                    ; N : axis j, need >= 1
    db   #03                    ; E : axis i, need <= 0
    db   #02                    ; S : axis j, need <= 0
    db   #01                    ; W : axis i, need >= 1


; ---------------------------------------------------------------------
;  pf_side -- reject a face that is wholly outside ONE side plane.
;    in:  the c_* view-space endpoints, z >= ZNEAR
;    out: CY set = reject
;  Endpoint A is tested first and, if it is inside both planes, B is not
;  tested at all: no reject is possible then.  The half-angle is
;  K = 0.578125 (three shifts) against tan(30) = 0.577350, i.e. the test
;  frustum is 0.13% WIDER than the real one, so it can never throw away
;  a face that has a visible pixel.
; ---------------------------------------------------------------------
pf_side
    ld   hl,(c_za)
    call khz
    ld   (ck_a),hl
    ld   de,(c_xa)
    or   a
    sbc  hl,de                  ; ra = K*za - xa
    bit  7,h
    jr   nz,ps_ro
    ld   hl,(ck_a)
    add  hl,de                  ; la = K*za + xa
    bit  7,h
    jr   nz,ps_lo
    or   a                      ; A is inside both planes
    ret
ps_ro
    ld   hl,(c_zb)
    call khz
    ld   de,(c_xb)
    or   a
    sbc  hl,de
    bit  7,h
    jr   nz,ps_rej
    or   a
    ret
ps_lo
    ld   hl,(c_zb)
    call khz
    ld   de,(c_xb)
    add  hl,de
    bit  7,h
    jr   nz,ps_rej
    or   a
    ret
ps_rej
    scf
    ret

; ---------------------------------------------------------------------
;  khz -- HL = 0.578125 * HL, HL >= 0
; ---------------------------------------------------------------------
khz
    srl  h
    rr   l
    ld   d,h
    ld   e,l                    ; DE = z/2
    srl  h
    rr   l
    srl  h
    rr   l
    srl  h
    rr   l                      ; HL = z/16
    ld   b,h
    ld   c,l
    srl  h
    rr   l
    srl  h
    rr   l                      ; HL = z/64
    add  hl,bc
    add  hl,de
    ret


; endpoint A is the outside one
cl_seta
    ld   de,(cl_da)
    ld   hl,0
    or   a
    sbc  hl,de
    ld   (l_na),hl
    ld   hl,(cl_db)
    ld   (l_nb),hl
    ret

; endpoint B is the outside one
cl_setb
    ld   de,(cl_db)
    ld   hl,0
    or   a
    sbc  hl,de
    ld   (l_na),hl
    ld   hl,(cl_da)
    ld   (l_nb),hl
    ret


; ---------------------------------------------------------------------
;  proj_pt -- one view-space point -> screen
;    in:  HL = xv (Q6.10 signed), DE = z (Q6.10, >= ZNEAR)
;    out: HL = xs Q12.4, DE = hh Q12.4 (the projected HALF height),
;         CY set = the point is too far outside to be representable,
;                  which means the face cannot be visible at all.
;    Two table lookups, one 16x8 multiply, no normalise loop.
; ---------------------------------------------------------------------
proj_pt
    ld   (pp_xv),hl
    ex   de,hl
    inc  hl
    inc  hl
    srl  h
    rr   l
    srl  h
    rr   l                      ; HL = (z+2)>>2
    ld   a,h
    or   a
    jr   nz,pp_chi
    ld   a,l
    cp   ZNEAR_Q8
    jr   nc,pp_zok
    ld   hl,ZNEAR_Q8
    jr   pp_zok
pp_chi
    cp   (ZFAR_Q8/256)+1
    jr   c,pp_zok
    ld   hl,ZFAR_Q8
pp_zok
    add  hl,hl                  ; word index, 0..4094
    ld   d,h
    ld   e,l
    ld   a,h
    add  a,HTAB/256
    ld   h,a
    ld   c,(hl)
    inc  l
    ld   b,(hl)
    ld   (pp_hh),bc             ; hh = HTAB[zq]
    ex   de,hl
    ld   a,h
    add  a,PXT/256
    ld   h,a
    ld   c,(hl)                 ; pm, always 128..255
    inc  l
    ld   a,(hl)
    ld   (pp_sh),a              ; sh, always 4..10

    ld   hl,(pp_xv)
    ld   a,h
    ld   (pp_sgn),a
    bit  7,h
    jr   z,pp_abs
    ex   de,hl
    ld   hl,0
    or   a
    sbc  hl,de
pp_abs
    ex   de,hl
    call mul16x8u               ; A:HL = |xv| * pm, at most 2^24-2^16
    ld   b,a
    ld   a,(pp_sh)
    sub  8
    jr   c,pp_slow
    ld   c,a                    ; 0..2 further shifts
    ld   a,l
    ld   l,h
    ld   h,b                    ; HL = product >> 8, at most #FF00
    add  a,a                    ; CY = bit 7 of the dropped byte
    ld   de,0
    adc  hl,de                  ; round; cannot carry out
    ld   a,c
    or   a
    jr   z,pp_chk
    ld   b,a
pp_s2
    srl  h
    rr   l
    djnz pp_s2
    ld   de,0
    adc  hl,de
    jr   pp_chk
pp_slow                         ; sh = 4..7: shift the whole 24 bits
    ld   a,(pp_sh)
    ld   c,a
    ld   a,b
    ld   b,c
pp_s3
    srl  a
    rr   h
    rr   l
    djnz pp_s3
    ld   de,0
    adc  hl,de
    adc  a,0                    ; keep the carry out of HL
    or   a
    scf
    ret  nz                     ; >= 65536, far outside
pp_chk
    ld   a,h
    cp   #40
    ccf
    ret  c                      ; >= 16384 Q12.4, far outside
    ld   de,CX_Q4
    ld   a,(pp_sgn)
    bit  7,a
    jr   nz,pp_neg
    add  hl,de
    ld   de,(pp_hh)
    or   a
    ret
pp_neg
    ex   de,hl
    or   a
    sbc  hl,de
    ld   de,(pp_hh)
    or   a
    ret


; ---------------------------------------------------------------------
;  lerp -- (l_a) + ((l_b)-(l_a)) * na/(na+nb)
;    in:  (l_a) (l_b) signed, (l_na) (l_nb) unsigned, na+nb > 0
;    out: HL
;
;  t is carried at Q15 and the divisor is an 8-bit normalised mantissa,
;  so the clip parameter has ~0.4% RELATIVE error: the clipped point is
;  displaced by 0.4% of how far along the edge it moved, not of the
;  whole edge.
; ---------------------------------------------------------------------
lerp
    ld   hl,(l_na)
    ld   de,(l_nb)
    add  hl,de
    ld   a,h
    or   l
    jp   z,lp_zero
    call norm16                 ; HL = D<<B with bit 15 set
    ld   a,l
    add  a,128
    ld   a,h
    adc  a,0                    ; n = round(Dn/256)
    jr   nc,lp_n
    ld   a,255
lp_n
    ld   c,a
    ld   hl,(l_na)
    ld   a,b
    or   a
    jr   z,lp_nosh
    ld   b,a
lp_sh
    add  hl,hl
    djnz lp_sh
lp_nosh
    ld   (l_an),hl
    ld   l,c                    ; r = RCP[n] - 128, 0..128
    ld   h,0
    add  hl,hl
    ld   de,RCP
    add  hl,de
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    ld   hl,-128
    add  hl,de
    ld   a,l
    ld   (l_r),a
    ld   de,(l_an)              ; t15 = (An>>1) + ((An*r)>>8)
    ld   a,(l_r)
    ld   c,a
    call mul16x8u
    ld   l,h
    ld   h,a
    ld   (l_t),hl
    ld   hl,(l_an)
    srl  h
    rr   l
    ld   de,(l_t)
    add  hl,de
    bit  7,h
    jr   z,lp_t
    ld   hl,32767
lp_t
    ld   (l_t15),hl
    ld   hl,(l_b)               ; delta = b - a
    ld   de,(l_a)
    or   a
    sbc  hl,de
    ld   a,h
    ld   (l_sgn),a
    bit  7,h
    jr   z,lp_dp
    ex   de,hl
    ld   hl,0
    or   a
    sbc  hl,de
lp_dp
    ld   (l_ad),hl
    ld   hl,(l_t15)             ; th = t15>>7, tl = t15&127
    add  hl,hl
    ld   a,h
    ld   (l_th),a
    ld   a,(l_t15)
    and  127
    ld   (l_tl),a
    ld   de,(l_ad)
    ld   a,(l_th)
    ld   c,a
    call mul16x8u
    ld   l,h
    ld   h,a                    ; (ad*th)>>8
    ld   (l_q),hl
    ld   a,(l_tl)               ; + ((ad>>8)*tl) >> 7, an 8x8 instead of a
    ld   c,a                    ; 16x8: this term is at most ad>>8, so
    ld   a,(l_ad+1)             ; dropping ad's low byte costs under 1 LSB
    call mul8x8u
    add  hl,hl
    ld   l,h
    ld   h,0
    ld   de,(l_q)
    add  hl,de
    ld   de,(l_a)
    ld   a,(l_sgn)
    bit  7,a
    jr   nz,lp_neg
    add  hl,de
    ret
lp_neg
    ex   de,hl
    or   a
    sbc  hl,de
    ret
lp_zero
    ld   hl,(l_a)
    ret


; ---------------------------------------------------------------------
;  norm16 -- HL != 0 -> HL << B, bit 15 set
; ---------------------------------------------------------------------
norm16
    ld   b,0
    ld   a,h
    or   a
    jr   nz,n16_go
    ld   h,l
    ld   l,0
    ld   b,8
    ld   a,h
    or   a
    ret  z
n16_go
    push hl
    ld   l,a
    ld   h,BITLEN/256
    ld   a,(hl)
    pop  hl
    ld   c,a
    ld   a,8
    sub  c                      ; extra shifts 0..7
    ld   c,a
    add  a,b
    ld   b,a
    ld   a,c
    or   a
    ret  z
    ld   c,a
n16_sh
    add  hl,hl
    dec  c
    jr   nz,n16_sh
    ret


; ---------------------------------------------------------------------
;  mul8x8u -- exact unsigned 8x8 -> 16 via quarter squares
;      a*b = QSQ[a+b] - QSQ[|a-b|]
;  in: A = a, C = b   out: HL   kill: AF BC DE
; ---------------------------------------------------------------------
mul8x8u
    ld   b,a
    add  a,c
    ld   l,a
    ld   a,0
    rla
    ld   h,a
    add  hl,hl
    set  6,h
    ld   e,(hl)
    inc  l
    ld   d,(hl)
    ld   a,b
    sub  c
    jr   nc,m8_p
    neg
m8_p
    ld   l,a
    ld   h,0
    add  hl,hl
    set  6,h
    ld   c,(hl)
    inc  l
    ld   b,(hl)
    ex   de,hl
    or   a
    sbc  hl,bc
    ret


; ---------------------------------------------------------------------
;  mul16x8u -- unsigned 16 x 8 -> 24
;  in: DE = a16, C = b8   out: A:HL   kill: AF BC DE HL IX
; ---------------------------------------------------------------------
mul16x8u
    ld   ixl,c                  ; b8
    ld   ixh,d                  ; a16 high
    ld   a,e
    call mul8x8u                ; HL = alo*b
    push hl
    ld   c,ixl
    ld   a,ixh
    call mul8x8u                ; HL = ahi*b
    pop  de
    ld   a,d
    add  a,l
    ld   d,a
    ld   a,h
    adc  a,0
    ld   h,d
    ld   l,e
    ret


; =====================================================================
;  THE STUB: per-frame lattice tables, kept only until the march carries
;  (xv, z) itself.  proj_setup costs ~1.9 ms EVERY frame and lat_view
;  ~90 us per endpoint; both disappear the moment the march hands
;  proj_face view-space endpoints, which is the whole point of the
;  rewrite.  Nothing in proj_face touches LAT.
; =====================================================================

; ---------------------------------------------------------------------
;  proj_setup -- once per frame
;    in:  (pv_ang) heading 0..71
;         (pv_fx) (pv_fy)  player position inside its cell, Q0.8
;    out: LAT filled
; ---------------------------------------------------------------------
proj_setup
    ld   a,(pv_ang)
    ld   l,a
    ld   h,0
    add  hl,hl
    add  hl,hl
    add  hl,hl                  ; ang*8
    ld   de,BASIS
    add  hl,de
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    ld   (ps_rgtx),de
    inc  hl
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    ld   (ps_rgty),de
    inc  hl
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    ld   (ps_fwdx),de
    inc  hl
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    ld   (ps_fwdy),de

    ld   de,(ps_rgtx)
    ld   a,(pv_fx)
    call ps_mulf
    push hl
    ld   de,(ps_rgty)
    ld   a,(pv_fy)
    call ps_mulf
    pop  de
    add  hl,de
    ld   (ps_xv0),hl
    ld   de,(ps_fwdx)
    ld   a,(pv_fx)
    call ps_mulf
    push hl
    ld   de,(ps_fwdy)
    ld   a,(pv_fy)
    call ps_mulf
    pop  de
    add  hl,de
    ld   (ps_z0),hl

    ld   de,(ps_rgtx)           ; XR[i] = i*rgtx - xv0
    ld   hl,(ps_xv0)
    ld   bc,LAT+34
    call ps_fill
    ld   de,(ps_fwdx)           ; XF[i] = i*fwdx - z0
    ld   hl,(ps_z0)
    ld   bc,LAT+68
    call ps_fill
    ld   de,(ps_rgty)           ; YR[j] = j*rgty
    ld   hl,0
    ld   bc,LAT+102
    call ps_fill
    ld   de,(ps_fwdy)           ; YF[j] = j*fwdy
    ld   hl,0
    ld   bc,LAT+136
    call ps_fill
    ret

; (DE * A) >> 8 -- DE signed, A unsigned 0..255 -> HL signed
ps_mulf
    ld   c,a
    bit  7,d
    jr   z,pm_pos
    push bc
    xor  a
    sub  e
    ld   e,a
    sbc  a,a
    sub  d
    ld   d,a
    pop  bc
    call mul16x8u
    ld   l,h
    ld   h,a
    ex   de,hl
    ld   hl,0
    or   a
    sbc  hl,de
    ret
pm_pos
    call mul16x8u
    ld   l,h
    ld   h,a
    ret

; 17 words written DOWNWARD from BC-2: value(i) = i*DE - HL, i = 8..-8
ps_fill
    ld   (ps_sp),sp
    ld   (ps_end),bc
    push de                     ; keep the step
    ex   de,hl                  ; DE = offset, HL = step
    add  hl,hl
    add  hl,hl
    add  hl,hl                  ; HL = 8*step
    or   a
    sbc  hl,de                  ; HL = 8*step - offset
    pop  de
    ld   sp,(ps_end)
    ld   b,17
ps_fl
    push hl
    or   a
    sbc  hl,de
    djnz ps_fl
    ld   sp,(ps_sp)
    ret

; ---------------------------------------------------------------------
;  lat_view -- lattice offset (B = i, C = j) -> HL = xv, DE = z
; ---------------------------------------------------------------------
lat_view
    ld   h,LAT/256
    ld   a,b
    add  a,a
    add  a,16
    ld   l,a
    ld   e,(hl)
    inc  l
    ld   d,(hl)                 ; DE = XR[i]
    push de
    ld   a,l
    add  a,33
    ld   l,a
    ld   e,(hl)
    inc  l
    ld   d,(hl)                 ; DE = XF[i]
    push de
    ld   a,c
    add  a,a
    add  a,84
    ld   l,a
    ld   e,(hl)
    inc  l
    ld   d,(hl)                 ; DE = YR[j]
    ld   a,c
    add  a,a
    add  a,118
    ld   l,a
    ld   c,(hl)
    inc  l
    ld   b,(hl)                 ; BC = YF[j]
    pop  hl                     ; XF[i]
    add  hl,bc
    ld   (lv_z),hl              ; z
    pop  hl                     ; XR[i]
    add  hl,de                  ; xv
    ld   de,(lv_z)
    ret


; ---------------------------------------------------------------------
;  state
; ---------------------------------------------------------------------
pv_ang   db 0
pv_fx    db 0
pv_fy    db 0

pf_i0    db 0
pf_j0    db 0
pf_i1    db 0
pf_j1    db 0
pf_nd    db 0

pf_ok    db 0
pf_nclip    db 0            ; clip lerps this face paid for (pacing only)
; the emitted record, in the order kernel.asm copies it (do not reorder)
pf_blo   db 0                   ; byte column at the SHORTER endpoint
pf_bhi   db 0                   ; ...and at the taller one (the pinned edge)
pf_hlo   dw 0                   ; projected half height there, Q12.4
pf_hhi   dw 0
PFRECSZ  equ 6

ps_sp    dw 0
ps_end   dw 0
ps_rgtx  dw 0
ps_rgty  dw 0
ps_fwdx  dw 0
ps_fwdy  dw 0
ps_xv0   dw 0
ps_z0    dw 0

c_xa     dw 0                   ; view-space input, clobbered by the clip
c_za     dw 0
c_xb     dw 0
c_zb     dw 0
cl_da    dw 0
cl_db    dw 0
ck_a     dw 0
lv_z     dw 0

s_xa     dw 0                   ; screen space: x and projected half height
s_ha     dw 0
s_xb     dw 0
s_hb     dw 0

pp_xv    dw 0
pp_hh    dw 0
pp_sh    db 0
pp_sgn   db 0

l_a      dw 0
l_b      dw 0
l_na     dw 0
l_nb     dw 0
l_an     dw 0
l_t      dw 0
l_t15    dw 0
l_ad     dw 0
l_q      dw 0
l_r      db 0
l_th     db 0
l_tl     db 0
l_sgn    db 0

    align 256
LAT      ds 136                 ; XR[17] XF[17] YR[17] YF[17], Q6.10
