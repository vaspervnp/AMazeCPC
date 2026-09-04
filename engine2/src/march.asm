; =====================================================================
;  engine2 -- march.asm   (incremental view-space flood)
;
;  Walks the grid outward from the player's continuous (x, y) and files the
;  visible wall faces in painter order, ALREADY TRANSFORMED INTO VIEW
;  SPACE, ready for the projector.
;
;  This is a bit-exact implementation of engine2/tools/marchmodel.py, which
;  is itself a fixed-point model of prototype/free-angle/free.py
;  build_frame().  If the two ever disagree the model is the spec.
;
;  ------------------------------------------------------------------
;  WHY THERE IS NOT ONE MULTIPLY IN THE MARCHING LOOP, AND NOT ONE
;  TABLE BUILT PER FRAME
;
;  The view-space coordinates of a grid corner are AFFINE in the grid
;  indices: with the player at cell (pcx, pcy) + fraction (fx, fy) and the
;  corner at cell offset (i, j),
;
;      xv(i,j) = i*rgtx + j*rgty - xv0     xv0 = (fx*rgtx + fy*rgty) >> 8
;      zv(i,j) = i*fwdx + j*fwdy - z0      z0  = (fx*fwdx + fy*fwdy) >> 8
;
;  so stepping i -> i+1 ADDS the per-frame constant (rgtx, fwdx) and
;  j -> j+1 adds (rgty, fwdy).  The two frustum half-planes are affine for
;  exactly the same reason,
;
;      L = xv + KHALF*zv >= 0      inside the left plane
;      R = KHALF*zv - xv >= 0      inside the right plane
;
;  with steps dLi = rgtx + KHALF*fwdx,  dLj = rgty + KHALF*fwdy,
;             dRi = KHALF*fwdx - rgtx,  dRj = KHALF*fwdy - rgty,
;  which depend only on the heading and so come out of MARCHTAB rounded
;  ONCE (gen_slopes.inc, written by engine2/tools/gen_march.py).
;
;  The flood therefore CARRIES (xv, zv, L, R) with it, four 16-bit adds
;  per cell step, seeded once per frame by four multiplies for the
;  player's own cell corner.  There is no per-frame table build at all:
;  the six 16-entry frustum tables this file used to fill (2525 us of the
;  old 3119 us march_setup) are gone, and the projector's four 17-entry
;  lattice tables (proj_setup, 1901 us) are gone with them, because every
;  face endpoint now leaves the march already in the projector's Q6.10
;  view space.
;
;  A cell is culled iff ALL FOUR of its corners fall outside one plane,
;  i.e. iff the maximum over the corners is negative.  Each plane function
;  is an i-term plus a j-term, so that maximum is the value at the cell's
;  own (i, j) corner plus max(0, step_i) + max(0, step_j) -- per-frame
;  constants, which are FOLDED INTO THE SEED.  The whole frustum test is
;  then three sign tests on values that arrive for free:
;
;      L  < 0          cull      (left plane)
;      R  < 0          cull      (right plane)
;      zv + CZ < 0     cull      (near plane; CZ folds ZNEAR in too)
;
;  Backface culling is free for the same reason as before: the face of a
;  wall cell that looks back at open cell (cx, cy) is visible iff the
;  player is on the open side of that cell's own integer boundary -- a
;  compare of the player's cell coordinate, not a dot product.
;
;  Painter order is free too: the sort key is the L1 cell distance of the
;  wall cell, an integer 1..7, so faces are bucket-sorted as they are
;  produced and never sorted afterwards.
;
;  CONSERVATISM.  Q6.10 is one bit coarser than the 7.9 slope tables this
;  replaces, so the seed carries MSLACK (8, = 0.008 cell) of deliberate
;  widening on all three planes.  Without it a cell that sits EXACTLY on
;  a frustum plane -- which happens at grid-aligned sub-positions on
;  round headings -- can round to "outside", and because the flood prunes
;  there, a whole corridor behind it disappears.  With it the fixed-point
;  march is a strict superset of free.py's float march on every one of
;  the 62784 states check_model.py sweeps (0 missing visible faces,
;  2.7% of states keep one extra cell that the float march drops).
;
;  ------------------------------------------------------------------
;  FIXED POINT
;     plr_x, plr_y   unsigned 16-bit 8.8, high byte = cell 0..15
;     everything else signed 16-bit Q6.10 (1024 = one cell), the same
;     VIEW fixed point gentab.py hands the projector.
;
;  INPUTS   (plr_x) (plr_y) (plr_a) and the SOLID array
;  OUTPUT   BUCKETS + BPTR, see below
;  Clobbers AF BC DE HL IX.  Uses SP as the flood stack pointer, so
;  INTERRUPTS MUST BE OFF; it saves and restores the caller's SP.
;
;  PACING.  When main3.asm defines PACED, the pop loop charges main3's
;  cost accumulator C_CELL for every cell it takes off the flood stack --
;  MEASURED 679.7 us marginal, 924 fixed, on the built disc -- and that
;  accumulator may take a vsync wait right there.  It is the only way a
;  march that costs 11.7 ms can be cut across a 20 ms period boundary
;  without splitting the flood itself.  The CALL is balanced and every
;  register is preserved, so the flood does not notice; the two words it
;  pushes land in the 1000-odd bytes of flood stack that this maze never
;  reaches.  Nothing is charged when PACED is undefined, which is how the
;  engine2/test harnesses still assemble.
; =====================================================================

; ------------------------------------------------------------- memory ----
; Per-frame WORKING RAM, below #4000 so it cannot collide with the #4000
; table bank (engine2 tab_equ.inc claims #4000-#6C31).
; FTAB, SOLID, MARK must be page aligned; each bucket owns a whole page.
; THE WHOLE BLOCK MOVED UP THREE PAGES when raster.asm grew a course-joint
; rasteriser: the code ran to #232C against BUCKETS at #2400 and 500 bytes
; would not fit in 179.  #3300-#35FF, between MARK and QUADS, was dead
; space and now holds the top of it, so everything below slid up.
;
; AND UP ONE MORE PAGE when the joints were switched back ON: the gun had
; arrived in the meantime, the 500 bytes were 55 short of the 445 that
; were left, and the free space above QUADS -- #39C0-#3FEF, 1584 bytes,
; of which the CPU stack uses the top 16 -- was the only slack in the map.
; So QUADS moved up a page too, which is why it is no longer at #3600.
; The CPU stack (#3FF0) and bank 4 are untouched.
; THE WHOLE BLOCK MOVED UP THREE MORE PAGES when the column renderer
; grew its second drawing pass, its door slide and its far plane, and
; `assert game_end <= BUCK0` fired for the ELEVENTH time -- and this time
; the two pages came out of QUADS rather than out of the code.  See
; memmap.inc: the list held 120 records for a MEASURED maximum of NINE,
; so shrinking it to 56 freed 512 bytes of low RAM and let everything
; below it move UP by two pages, which is 512 bytes handed back to the
; body.  Nothing ABOVE QUADS moved, which is what keeps the door tables,
; RC_COVER and engine2/tools/emu_pacefit.py's harness where they are.
;
; AND THE FLOOD STACK GAVE UP ANOTHER PAGE, the twelfth time the assert
; fired.  It is 256 bytes now -- 25 entries against the same exhaustive
; maximum of 14, so still 1.8x over -- and BUCK0 moved up with it.
;
; The three pages
; came out of the flood stack, which had 1280 bytes for a stack that
; MEASURES 14 entries at its worst -- 8 with every door shut, 14 with
; every door open (engine2/tools/roomcost.py, exhaustive).  512 bytes was
; 51 entries, still three and a half times the worst ever seen.
MSTKBOT     equ #3900       ; flood stack, grows DOWN from MSTKTOP
MSTKTOP     equ #3A00       ; 256 bytes = 25 entries of 10, against a
                            ; MEASURED worst of 14.
FTAB        equ #3A00       ; L1 tables + bucket write pointers
O_LX1       equ #C0         ; 16 bytes, |cx - pcx|
O_LY1       equ #D0         ; 16 bytes, |cy - pcy|
O_BPTR      equ #E0         ; 8 BYTES, bucket write offset within its page

DOORMOV     equ 3           ; a door part way through its run:
                            ; SEE-THROUGH, so the flood goes past it and
                            ; the room beyond is marched, but still filed
                            ; as a face so the door itself is drawn, and
                            ; still non-zero so coll_free keeps the
                            ; player out of it.  Opacity and solidity are
                            ; different questions; this is the code that
                            ; separates them.
SOLID       equ #3B00       ; 256 bytes, idx = cy*16 + cx
                            ;   0 = open, 1 = wall, 2 = shut door,
                            ;   3 = door in motion (see DOORMOV)
MARK        equ #3C00       ; 256 bytes, flood "already pushed" flags

; BUCKET 0 IS A REAL PAGE AND IT MUST NOT BE CODE.  A bucket's page is
; BUCKHI + k, so k = 0 addresses the page BELOW BUCKETS -- and O_BPTR is
; eight bytes wide, one per k, so bucket 0 is addressable by construction
; even though the march only ever files faces at L1 = 1..7.
;
; For the whole life of this engine that page happened to be free RAM
; between the end of the code and BUCKETS, so nothing noticed.  Then the
; block moved up to make room for raster_joint, the code grew into the
; page below BUCKETS, and the machine started dying inside mul8x8u --
; executing the STALE COPY of it still sitting in the back buffer, because
; something had written over pace_quad, which is what calls it.  What
; makes that bug so unpleasant is that it is sensitive to THREE BYTES: the
; same build with the `call raster_joint` replaced by three NOPs died and
; with the call assembled out did not, because the shift decided which
; instruction the stray write landed on.
;
; So BUCKETS keeps a spare page under it, deliberately, and the assert at
; the foot of main3.asm guards THAT page rather than the first bucket.
BUCK0       equ #3100       ; bucket 0: never filed into, never read, and
                            ; deliberately not code.  `assert game_end <=
                            ; BUCK0` in main3.asm is what keeps it so.
BUCKHI      equ #31         ; bucket k (k = 1..7) is the page BUCKHI+k,
BUCKETS     equ #3200       ; i.e. #3200 (k=1) .. #3800 (k=7).
BUCKSZ      equ 16          ; face record; 16 per page, 15 usable
                            ; (measured worst bucket occupancy: 8)

; FACE RECORD, 16 bytes, ALREADY IN VIEW SPACE:
;   +0  xa   int16 Q6.10   endpoint A, lateral (+right), 1024 = one cell
;   +2  za   int16 Q6.10   endpoint A, depth   (+forward)
;   +4  xb   int16 Q6.10   endpoint B
;   +6  zb   int16 Q6.10
;   +8  dir  0=N(-y) 1=E(+x) 2=S(+y) 3=W(-x): the face's OUTWARD normal,
;            which is what the shader needs to pick the N/S ramp step
;   +9  kind 0 = wall, 1 = door
;   +10 i0   signed cell offset of endpoint A from the player's cell, x
;   +11 j0   ... y.  ONLY project.asm's backface test reads these, and it
;            can only ever agree with the march; they are here so the
;            projector keeps a self-contained face record.
;   +12..15  spare
;
; A and B are named exactly as free.py:face_endpoints() names them, i.e.
; A is the (wx, wy)-derived end; the projector may still swap them by
; projected x.  The wall cell itself is NOT in the record: the projector
; has no use for it, and the depth the shader wants is the bucket index.
;
; OUTPUT: bucket k holds the faces whose wall cell is at L1 distance k
; (k = 1..7).  It runs from offset 0 of page BUCKHI+k up to (not
; including) the offset in the byte at FTAB+O_BPTR+k.  Painter order is k
; descending, 7 down to 1.

FDIR_N      equ 0
FDIR_E      equ 1
FDIR_S      equ 2
FDIR_W      equ 3


; =====================================================================
;  march
; =====================================================================
march
    call march_setup

    ld (mv_cpusp),sp                ; SP becomes the flood stack pointer
    ld sp,MSTKTOP
    ld hl,#FFFF
    push hl                         ; sentinel: cx = #FF stops the flood
    ld hl,(mv_x0)                   ; seed = the player's own cell corner
    push hl
    ld hl,(mv_z0)
    push hl
    ld hl,(mv_r0)
    push hl
    ld hl,(mv_l0)
    push hl
    ld a,(plr_x+1)
    ld b,a                          ; B = pcx
    ld a,(plr_y+1)
    ld c,a                          ; C = pcy
    push bc
    rlca                            ; A is still pcy
    rlca
    rlca
    rlca
    or b
    ld l,a
    ld h,MARK/256
mg0 ld (hl),1                       ; the player's own cell is pushed

; ---------------------------------------------------------------------
;  Pop a cell.  Through the body:  B = cx, C = cy, and the four carried
;  values sit in cur_x / cur_z / cur_l / cur_r.
;
;  Stack entry, 10 bytes, in pop order:  (cx,cy)  L  R  zv  xv.
;  L and R are popped first because they are what usually rejects the
;  cell, and a rejected cell then never pays for the rest.
; ---------------------------------------------------------------------
mr_loop
    pop bc
    ld a,b
    inc a
    jr z,mr_done                    ; sentinel: the flood is finished

    ; ---- PACING.  One popped cell is one unit of work to the cost
    ; accumulator (main3.asm): 274.8 us marginal, MEASURED, charged at
    ; C_CELL.  cost_unit preserves every register and its CALL is
    ; balanced, so it is safe here even though SP is the flood stack --
    ; the two words it pushes land in the unused space below it, and the
    ; flood never gets within 1000 bytes of MSTKBOT.
    ifdef PACED
    push bc
    ld bc,C_CELL
    call cost_unit
    pop bc
    endif

    ld hl,m_visited
    inc (hl)

    ; ---- L1 bound.  L1 == 0 is the player's own cell: always kept and
    ; neither solid- nor frustum-tested, exactly as free.py does it.
    ld h,FTAB/256
    ld a,O_LX1
    add a,b
    ld l,a
    ld d,(hl)                       ; |cx - pcx|
    ld a,O_LY1
    add a,c
    ld l,a
    ld a,(hl)
    add a,d
    jr z,mr_own                     ; the player's own cell
    cp RMAX+1
    jr nc,mr_rej4                   ; outside the march radius

    ; No opaque test here: the flood never pushes an opaque cell, so every
    ; cell that reaches this point is already known to be open.

    ; ---- frustum: three sign tests on the carried values
    pop hl                          ; L, left plane
    bit 7,h
    jr nz,mr_rej3
    ld (cur_l),hl
    pop hl                          ; R, right plane
    bit 7,h
    jr nz,mr_rej2
    ld (cur_r),hl
    pop de                          ; zv
    ld hl,(mv_cz)
    add hl,de                       ; + max corner - ZNEAR
    bit 7,h
    jr nz,mr_rej1
    ld (cur_z),de
    pop hl
    ld (cur_x),hl
    jr mr_seen

mr_own
    pop hl
    ld (cur_l),hl
    pop hl
    ld (cur_r),hl
    pop hl
    ld (cur_z),hl
    pop hl
    ld (cur_x),hl
    jr mr_seen

mr_rej4
    pop hl
mr_rej3
    pop hl
mr_rej2
    pop hl
mr_rej1
    pop hl
    jr mr_loop

mr_done
    ld sp,(mv_cpusp)
    ret

; ---------------------------------------------------------------------
;  Visible.  File the faces of this cell's opaque neighbours, then flood.
;  mr_face is a CALL: its return address goes BELOW the flood stack
;  pointer, into the unused part of the stack, so it cannot disturb the
;  pending entries above SP.
; ---------------------------------------------------------------------
mr_seen
    ld hl,m_seen
    inc (hl)
    ld a,b                          ; this cell's signed lattice offset,
    ld hl,plr_x+1                   ; for the projector's backface test
    sub (hl)
    ld (cur_i),a
    ld a,c
    ld hl,plr_y+1
    sub (hl)
    ld (cur_j),a

    ; ---- NORTH neighbour (cx, cy-1): its SOUTH face looks back at us.
    ;      Visible iff plr_y > cy.
    ld a,(plr_y+1)
    cp c
    jr c,mr_fn_done                 ; pcy < cy
    jr nz,mr_fn                     ; pcy > cy
    ld a,(plr_y)
    or a
    jr z,mr_fn_done                 ; exactly on the edge: edge-on, cull
mr_fn
    push bc
    ld e,b
    ld a,c
    dec a
    ld d,a
    ld c,FDIR_S
    call mr_face
    pop bc
mr_fn_done

    ; ---- SOUTH neighbour (cx, cy+1): its NORTH face.  Visible iff
    ;      plr_y < cy+1, i.e. pcy <= cy.
    ld a,(plr_y+1)
    cp c
    jr z,mr_fs
    jr nc,mr_fs_done
mr_fs
    push bc
    ld e,b
    ld a,c
    inc a
    ld d,a
    ld c,FDIR_N
    call mr_face
    pop bc
mr_fs_done

    ; ---- WEST neighbour (cx-1, cy): its EAST face.  Visible iff plr_x > cx.
    ld a,(plr_x+1)
    cp b
    jr c,mr_fw_done
    jr nz,mr_fw
    ld a,(plr_x)
    or a
    jr z,mr_fw_done
mr_fw
    push bc
    ld d,c
    ld a,b
    dec a
    ld e,a
    ld c,FDIR_E
    call mr_face
    pop bc
mr_fw_done

    ; ---- EAST neighbour (cx+1, cy): its WEST face.  Visible iff
    ;      plr_x < cx+1, i.e. pcx <= cx.
    ld a,(plr_x+1)
    cp b
    jr z,mr_fe
    jr nc,mr_fe_done
mr_fe
    push bc
    ld d,c
    ld a,b
    inc a
    ld e,a
    ld c,FDIR_W
    call mr_face
    pop bc
mr_fe_done

; ---------------------------------------------------------------------
;  Flood into the four neighbours, carrying (xv, zv, L, R) with them:
;  one step in world +x adds (rgtx, fwdx, dLi, dRi), one step in +y adds
;  (rgty, fwdy, dLj, dRj), and the two negative directions subtract the
;  same words -- so the whole propagation is 16 adds per cell and no
;  table anywhere.  IXL holds the cell index; the four pushes clobber
;  everything else except B and C.
;
;  An OPAQUE neighbour is marked but never pushed.  free.py pushes it,
;  pops it and rejects it, which is 83 us of Z80 time for a cell that can
;  contribute nothing: it is not visible itself and the flood does not
;  continue through it.  Skipping the push leaves the seen set and the
;  face list bit-identical -- it only changes free.py's `cells_visited`
;  counter, which is a property of the traversal, not of the output.
;
;  The mark is a GENERATION byte patched into the code below, so the
;  256-byte MARK array only has to be cleared once every 255 frames
;  instead of costing 512 us of PUSH every frame.
; ---------------------------------------------------------------------
    ld a,c
    rlca
    rlca
    rlca
    rlca
    or b
    ld ixl,a                        ; cell index, safe from the pushes

    ld h,MARK/256                   ; --- west (cx-1, cy)
    ld a,ixl
    dec a
    ld l,a
    ld a,(hl)
mg1 cp 1
    jr z,mr_pw
mg2 ld (hl),1
    ld h,SOLID/256
    ld a,(hl)
    dec a                           ; SEE-THROUGH iff 0 or DOORMOV: (a-1)
    cp 2                            ; is 255, 0, 1, 2 for 0, 1, 2, 3, so
    jr c,mr_pw                      ; opaque is exactly (a-1) < 2 -- the
                                    ; same two instructions `or a / jr nz`
                                    ; cost.  A door part way open is
                                    ; flooded THROUGH, so the room behind
                                    ; it is marched, and is still filed as
                                    ; a face below, so the door is drawn.
    ld hl,(cur_x)
    ld de,(mv_sxi)
    or a
    sbc hl,de
    push hl
    ld hl,(cur_z)
    ld de,(mv_szi)
    or a
    sbc hl,de
    push hl
    ld hl,(cur_r)
    ld de,(mv_sri)
    or a
    sbc hl,de
    push hl
    ld hl,(cur_l)
    ld de,(mv_sli)
    or a
    sbc hl,de
    push hl
    dec b
    push bc
    inc b
mr_pw

    ld h,MARK/256                   ; --- east (cx+1, cy)
    ld a,ixl
    inc a
    ld l,a
    ld a,(hl)
mg3 cp 1
    jr z,mr_pe
mg4 ld (hl),1
    ld h,SOLID/256
    ld a,(hl)
    dec a
    cp 2
    jr c,mr_pe
    ld hl,(cur_x)
    ld de,(mv_sxi)
    add hl,de
    push hl
    ld hl,(cur_z)
    ld de,(mv_szi)
    add hl,de
    push hl
    ld hl,(cur_r)
    ld de,(mv_sri)
    add hl,de
    push hl
    ld hl,(cur_l)
    ld de,(mv_sli)
    add hl,de
    push hl
    inc b
    push bc
    dec b
mr_pe

    ld h,MARK/256                   ; --- north (cx, cy-1)
    ld a,ixl
    sub 16
    ld l,a
    ld a,(hl)
mg5 cp 1
    jr z,mr_pn
mg6 ld (hl),1
    ld h,SOLID/256
    ld a,(hl)
    dec a
    cp 2
    jr c,mr_pn
    ld hl,(cur_x)
    ld de,(mv_sxj)
    or a
    sbc hl,de
    push hl
    ld hl,(cur_z)
    ld de,(mv_szj)
    or a
    sbc hl,de
    push hl
    ld hl,(cur_r)
    ld de,(mv_srj)
    or a
    sbc hl,de
    push hl
    ld hl,(cur_l)
    ld de,(mv_slj)
    or a
    sbc hl,de
    push hl
    dec c
    push bc
    inc c
mr_pn

    ld h,MARK/256                   ; --- south (cx, cy+1)
    ld a,ixl
    add a,16
    ld l,a
    ld a,(hl)
mg7 cp 1
    jr z,mr_ps
mg8 ld (hl),1
    ld h,SOLID/256
    ld a,(hl)
    dec a
    cp 2
    jr c,mr_ps
    ld hl,(cur_x)
    ld de,(mv_sxj)
    add hl,de
    push hl
    ld hl,(cur_z)
    ld de,(mv_szj)
    add hl,de
    push hl
    ld hl,(cur_r)
    ld de,(mv_srj)
    add hl,de
    push hl
    ld hl,(cur_l)
    ld de,(mv_slj)
    add hl,de
    push hl
    inc c
    push bc
    dec c
mr_ps
    jp mr_loop


; ---------------------------------------------------------------------
;  mr_face -- file one visible face, in view space.
;    E = wall cell x, D = wall cell y, C = face direction
;  Clobbers everything except B'C' (it may not touch the flood stack
;  above SP, and it does not).
;
;  The face's two endpoints are two of the four corners of the OPEN cell
;  the march is standing on, whose (i, j) corner is the carried
;  (cur_x, cur_z):
;      dir S : A = (i,j)        B = A + i-step
;      dir N : A = (i,j+1)      B = A + i-step
;      dir E : A = (i,j)        B = A + j-step
;      dir W : A = (i+1,j)      B = A + j-step
;  which is exactly free.py:face_endpoints() written in view space.
; ---------------------------------------------------------------------
mr_face
    ld a,c
    ld (mf_dir),a

    ld a,d                          ; opaque, and is it a door?
    rlca
    rlca
    rlca
    rlca
    or e
    ld l,a
    ld h,SOLID/256
    ld a,(hl)
    or a
    ret z                           ; open: no wall face here
    cp 2                            ; 1 = wall; 2 SHUT and 3 MOVING are
    ld a,0                          ; both doors and both get a face -- a
    jr c,mf_kset                    ; moving door is see-through to the
    ld a,1                          ; flood AND drawn, which is what lets
    jr z,mf_kset                    ; the room appear behind it
    ld a,3                          ; ...and bit 1 says MOVING, which is
mf_kset                             ; what makes rastcol.asm draw it LAST
    ld (mf_kind),a                  ; and on top: 0 wall, 1 door, 3 moving

    ld h,FTAB/256                   ; painter key = L1 of the WALL cell
    ld a,O_LX1
    add a,e
    ld l,a
    ld b,(hl)
    ld a,O_LY1
    add a,d
    ld l,a
    ld a,(hl)
    add a,b                         ; A = key, 1..7

    ld c,a                          ; -> its bucket write pointer
    add a,O_BPTR
    ld l,a
    ld (mf_ptr),hl
    ld a,(hl)
    cp BUCKSZ*15
    jr z,mf_full                    ; bucket full: drop this face
    ld ixl,a
    ld a,BUCKHI
    add a,c
    ld ixh,a                        ; IX = the record

    ld a,(mf_dir)
    or a
    jp z,mf_n
    dec a
    jp z,mf_e
    dec a
    jp z,mf_s
    jp mf_w
mf_full
    ld hl,m_dropped
    inc (hl)
    ret

mf_n                                ; A = (i, j+1)   B = A + i
    ld hl,(cur_x)
    ld de,(mv_sxj)
    add hl,de
    ld (ix+0),l
    ld (ix+1),h
    ld de,(mv_sxi)
    add hl,de
    ld (ix+4),l
    ld (ix+5),h
    ld hl,(cur_z)
    ld de,(mv_szj)
    add hl,de
    ld (ix+2),l
    ld (ix+3),h
    ld de,(mv_szi)
    add hl,de
    ld (ix+6),l
    ld (ix+7),h
    ld a,(cur_j)
    inc a
    ld (ix+11),a
    ld a,(cur_i)
    jp mf_tail

mf_s                                ; A = (i, j)     B = A + i
    ld hl,(cur_x)
    ld (ix+0),l
    ld (ix+1),h
    ld de,(mv_sxi)
    add hl,de
    ld (ix+4),l
    ld (ix+5),h
    ld hl,(cur_z)
    ld (ix+2),l
    ld (ix+3),h
    ld de,(mv_szi)
    add hl,de
    ld (ix+6),l
    ld (ix+7),h
    ld a,(cur_j)
    ld (ix+11),a
    ld a,(cur_i)
    jp mf_tail

mf_e                                ; A = (i, j)     B = A + j
    ld hl,(cur_x)
    ld (ix+0),l
    ld (ix+1),h
    ld de,(mv_sxj)
    add hl,de
    ld (ix+4),l
    ld (ix+5),h
    ld hl,(cur_z)
    ld (ix+2),l
    ld (ix+3),h
    ld de,(mv_szj)
    add hl,de
    ld (ix+6),l
    ld (ix+7),h
    ld a,(cur_j)
    ld (ix+11),a
    ld a,(cur_i)
    jp mf_tail

mf_w                                ; A = (i+1, j)   B = A + j
    ld hl,(cur_x)
    ld de,(mv_sxi)
    add hl,de
    ld (ix+0),l
    ld (ix+1),h
    ld de,(mv_sxj)
    add hl,de
    ld (ix+4),l
    ld (ix+5),h
    ld hl,(cur_z)
    ld de,(mv_szi)
    add hl,de
    ld (ix+2),l
    ld (ix+3),h
    ld de,(mv_szj)
    add hl,de
    ld (ix+6),l
    ld (ix+7),h
    ld a,(cur_j)
    ld (ix+11),a
    ld a,(cur_i)
    inc a

mf_tail                             ; A = i0 of endpoint A
    ld (ix+10),a
    ld a,(mf_dir)
    ld (ix+8),a
    ld a,(mf_kind)
    ld (ix+9),a
    ld hl,(mf_ptr)
    ld a,(hl)
    add a,BUCKSZ
    ld (hl),a
    ret


; =====================================================================
;  march_init -- the one full MARK wipe.  Call it once, before the first
;  march; march_setup's rolling clear keeps it swept from then on.
;
;  It has to exist because the rolling clear needs 64 frames to cover the
;  page, and until it has, a byte of whatever the loader left behind can
;  read equal to the current generation -- which makes the flood treat an
;  unvisited cell as already pushed and quietly drop a wall.  The old
;  code had the same hole and never noticed it, because it also never
;  cleared MARK before the first frame.
; =====================================================================
; ---------------------------------------------------------------------
;  maze_unpack -- MAZEDATA -> SOLID, two bits a cell to one byte a cell.
;
;  THE MAP IS PACKED BECAUSE THE BODY BUDGET SAYS SO.  SOLID's alphabet
;  is four values wide (open, wall, shut door, door in motion), so the
;  16x16 map is 64 bytes of source and 256 bytes of working RAM, and
;  main3.asm's `assert game_end <= BUCK0` has now fired nine times.  A
;  256-byte table that is read ONCE and never again was the cheapest 192
;  bytes in the file to hand back.
;
;  It lives HERE, next to SOLID, because march.asm owns SOLID and both
;  main3.asm and engine2/src/test_march.asm need the same unpacking --
;  they used to carry an LDIR each.
;
;  Cell i is bits (i & 3)*2 of byte i >> 2, lowest cell in the lowest
;  bits, so this only ever shifts right.  Clobbers AF BC DE HL.
; ---------------------------------------------------------------------
maze_unpack
    ; ---- MAZEDATA IS IN RAM BANK 6, so page it in for the sixteen
    ;      instructions below and put bank 4 back after.  Safe because
    ;      this reads nothing else and writes SOLID at #3A00, below the
    ;      window -- and because it runs from new_game and not from a
    ;      frame.  See engine2/tools/genaux.py for the rule.
    ; ...and only where there IS a bank 6.  engine2/test/tst_kern.asm
    ; includes this file without gen_aux.inc, patches a synthetic map
    ; straight into SOLID and never calls maze_unpack at all -- so the
    ; OUT has to compile out for it, the same way MTBANK's does below.
    ;
    ; THE FLAG IS AUXBANK AND NOT `ifdef AUXCFG`, AND THAT IS MEASURED.
    ; AUXCFG comes from gen_aux.inc, which hud2.asm includes -- AFTER
    ; this file.  `ifdef` is answered where it stands, so it was FALSE
    ; here and the paging compiled out of the DISC as well: maze_unpack
    ; would have read the maze out of bank 4's tables and built a map of
    ; noise.  It assembled, it linked, and nothing said a word.  main3
    ; .asm defines AUXBANK before the includes, exactly as it defines
    ; MTBANK, so a build without a bank 6 is a build that says so.
    ifdef AUXBANK
    ld bc,#7F00+AUXCFG
    out (c),c
    endif
    ld hl,MAZEDATA
    ld de,SOLID
    ld b,64
mu_byte
    ld c,(hl)
    inc hl
    push bc
    ld b,4
mu_cell
    ld a,c
    and 3
    ld (de),a
    inc de
    srl c
    srl c
    djnz mu_cell
    pop bc
    djnz mu_byte
    ifdef AUXBANK
    ld bc,#7FC4                     ; ...and bank 4 back for everything
    out (c),c                       ; else
    endif
    ret


march_init
    ld hl,MARK
    ld de,MARK+1
    ld bc,255
    ld (hl),0
    ldir
    ld hl,MARK
    ld (ms_clp),hl
    xor a
    ld (m_gen),a
    ret


; =====================================================================
;  march_setup -- everything that is per frame rather than per cell.
;  No table is built: this is four multiplies, a handful of adds and the
;  two 16-byte housekeeping loops.
; =====================================================================
march_setup
    xor a
    ld (m_visited),a
    ld (m_seen),a
    ld (m_dropped),a

    ; ---- flood marks: bump the generation and patch it into the nine
    ; sites that test or set it.  Generation 0 is never used, so the
    ; counter runs 1..255 and REPEATS EVERY 255 FRAMES.
    ;
    ;  THE CLEAR IS AMORTISED, and it used to be a hitch.  This code was
    ;  `jp nz,ms_gen` around 128 PUSH HL -- a 256-byte wipe taken in one
    ;  go on the one frame in 255 that the counter wrapped.  MEASURED on
    ;  the booted disc (engine2/tools/emu_holes.py): march_setup 1349.2 us
    ;  on a flat frame and 1884.1 us on the wrap, a 534.9 us step that the
    ;  flat C_MSETUP charged to nobody -- so a state already close to the
    ;  vsync edge took a seventh period once every 255 frames, which is
    ;  the same shape of defect the weapon made before it was charged.
    ;
    ;  So the wipe is spread instead: FOUR bytes a frame at a rolling
    ;  index, which sweeps the whole 256-byte page every 64 frames.  That
    ;  is the correctness argument as well as the cost one -- a byte
    ;  written with generation g is zeroed within 64 frames, and g does
    ;  not come round again for 255, so no stale mark can ever be read as
    ;  current.  Clearing can only ever UNMARK, and it happens here, in
    ;  front of the flood, so nothing it touches belongs to this frame.
    ;
    ;  march_init does the one full wipe there has to be, at startup.
    ;  MEASURED cost of the four stores and the cursor: 23.6 us a frame,
    ;  so march_setup reads 1372.8 - 1445.1 us over the movement lattice
    ;  on EVERY frame, wrap or no wrap -- it was 1349.2 flat and 1884.1 on
    ;  the wrap.  (The spread is the four seed multiplies and build_l1,
    ;  not the clear; see C_MSETUP, which had never been swept either.)
    ld hl,(ms_clp)                  ; A is still 0 from the counters above.
    ld (hl),a                       ; H is MARK/256 and INC L stays inside
    inc l                           ; the page, so the cursor wraps for free
    ld (hl),a
    inc l
    ld (hl),a
    inc l
    ld (hl),a
    inc l
    ld (ms_clp),hl

    ld hl,m_gen
    inc (hl)
    jr nz,ms_gen
    ld (hl),1
ms_gen
    ld a,(hl)
    ld (mg0+1),a
    ld (mg1+1),a
    ld (mg2+1),a
    ld (mg3+1),a
    ld (mg4+1),a
    ld (mg5+1),a
    ld (mg6+1),a
    ld (mg7+1),a
    ld (mg8+1),a

    ; ---- reset the 8 bucket write offsets
    ld hl,FTAB+O_BPTR
    ld b,8
    xor a
ms_bp
    ld (hl),a
    inc l
    djnz ms_bp

    call build_l1

    ; ---- this heading's eight constants, in one LDIR:
    ;      rgtx rgty fwdx fwdy dLi dLj dRi dRj
    ld a,(plr_a)
    ld l,a
    ld h,0
    add hl,hl
    add hl,hl
    add hl,hl
    add hl,hl                       ; ang*16
    ld de,MARCHTB
    add hl,de
    ; ---- MARCHTB LIVES IN RAM BANK 5 ON THE DISC, and this is the only
    ;      code that reads it: sixteen bytes, once a frame.  1152 bytes
    ;      of code segment for one LDIR was the largest thing left to
    ;      give back, and `assert game_end <= BUCK0` had fired twelve
    ;      times.  Two OUTs is what it costs.
    ;
    ;      Bank 5 is the column renderer's texture bank and it is paged
    ;      in for the whole of raster_colframe -- but march_setup runs
    ;      before that and returns before it starts, so the two never
    ;      want the window at the same moment.
    ;
    ;      engine2/src/test_march.asm leaves MTBANK undefined and gets
    ;      the table in base RAM from gen_mtab.inc instead, because it
    ;      RUNS at &4000: paging there would swap the window out from
    ;      under its own program counter.
    ifdef MTBANK
    ld bc,#7F00+TEXCFG
    out (c),c
    endif
    ld de,mv_sxi
    ld bc,16
    ldir
    ifdef MTBANK
    ld bc,#7FC4                     ; bank 4 back before anything else
    out (c),c
    endif

    ; ---- the seed: view coords of the player's OWN cell corner,
    ;      xv = -xv0, zv = -z0.  These four multiplies are the only ones
    ;      the march performs, and they are bit-identical to the ones
    ;      project.asm's proj_setup used to do (ps_mulf), so an endpoint
    ;      that leaves here matches the projector's lattice exactly.
    ld de,(mv_sxi)
    ld a,(plr_x)
    call mv_mulf
    push hl
    ld de,(mv_sxj)
    ld a,(plr_y)
    call mv_mulf
    pop de
    add hl,de                       ; HL = xv0
    ex de,hl
    ld hl,0
    or a
    sbc hl,de
    ld (mv_x0),hl

    ld de,(mv_szi)
    ld a,(plr_x)
    call mv_mulf
    push hl
    ld de,(mv_szj)
    ld a,(plr_y)
    call mv_mulf
    pop de
    add hl,de                       ; HL = z0
    ex de,hl
    ld hl,0
    or a
    sbc hl,de
    ld (mv_z0),hl

    ; ---- L0 = xv + KHALF*zv + max(0,dLi) + max(0,dLj) + MSLACK
    call mv_kq                      ; HL = KHALF * zv
    ld (mv_q),hl
    ld de,(mv_x0)
    add hl,de
    ld de,(mv_sli)
    call mv_addpos
    ld de,(mv_slj)
    call mv_addpos
    ld de,MSLACK
    add hl,de
    ld (mv_l0),hl

    ; ---- R0 = KHALF*zv - xv + max(0,dRi) + max(0,dRj) + MSLACK
    ld hl,(mv_q)
    ld de,(mv_x0)
    or a
    sbc hl,de
    ld de,(mv_sri)
    call mv_addpos
    ld de,(mv_srj)
    call mv_addpos
    ld de,MSLACK
    add hl,de
    ld (mv_r0),hl

    ; ---- CZ = max(0,fwdx) + max(0,fwdy) - ZNEAR + MSLACK
    ld hl,0
    ld de,(mv_szi)
    call mv_addpos
    ld de,(mv_szj)
    call mv_addpos
    ld de,ZNEARM-MSLACK             ; positive: rasm mis-assembles "ld de,-x"
    or a                            ; when x is a forward-referenced EQU
    sbc hl,de
    ld (mv_cz),hl
    ret


; ---------------------------------------------------------------------
;  mv_addpos -- HL = HL + DE when DE > 0, i.e. HL += max(0, DE)
; ---------------------------------------------------------------------
mv_addpos
    bit 7,d
    ret nz
    add hl,de
    ret


; ---------------------------------------------------------------------
;  mv_kq -- HL = KHALF * (mv_z0), by three ARITHMETIC shifts:
;      1/2 + 1/16 + 1/64 = 0.578125,  tan(30) = 0.5773503  (+0.13%)
;  Used once per frame to seed L and R.  The per-step constants come
;  exactly rounded out of MARCHTAB, so this error never accumulates.
; ---------------------------------------------------------------------
mv_kq
    ld hl,(mv_z0)
    sra h
    rr l                            ; HL = z >> 1
    ld d,h
    ld e,l
    sra h
    rr l
    sra h
    rr l
    sra h
    rr l                            ; HL = z >> 4
    ld b,h
    ld c,l
    sra h
    rr l
    sra h
    rr l                            ; HL = z >> 6
    add hl,bc
    add hl,de
    ret


; ---------------------------------------------------------------------
;  mv_mulf -- HL = (DE * A) >> 8, DE signed, A an unsigned 0.8 fraction,
;  TRUNCATED TOWARDS ZERO -- which is what project.asm's ps_mulf does,
;  and the projector's lattice was built with it.
; ---------------------------------------------------------------------
mv_mulf
    ld c,a
    bit 7,d
    jr z,mvm_pos
    ld hl,0                         ; negative: shift the magnitude
    or a
    sbc hl,de
    ex de,hl
    call fracmul
    ld hl,0
    or a
    sbc hl,de
    ret
mvm_pos
    call fracmul
    ex de,hl
    ret


; ---------------------------------------------------------------------
;  build_l1 -- LX1[i] = |i - pcx|, LY1[i] = |i - pcy|.
;  Read for cells up to L1 7 away, so both are built over the full 0..15.
; ---------------------------------------------------------------------
build_l1
    ld h,FTAB/256
    ld a,(plr_x+1)
    ld c,a
    add a,O_LX1
    ld l,a
    call bl1_one
    ld h,FTAB/256
    ld a,(plr_y+1)
    ld c,a
    add a,O_LY1
    ld l,a
    ; fall through
bl1_one
    ld (hl),0
    ld a,l
    ld (bl1_sav),a
    ld a,15
    sub c
    jr z,bl1_nu
    ld b,a
    xor a
bl1_u
    inc l
    inc a
    ld (hl),a
    djnz bl1_u
bl1_nu
    ld a,(bl1_sav)
    ld l,a
    ld a,c
    or a
    ret z
    ld b,a
    xor a
bl1_d
    dec l
    inc a
    ld (hl),a
    djnz bl1_d
    ret


; ---------------------------------------------------------------------
;  fracmul -- DE = floor(DE * C / 256), DE signed, C an unsigned 0.8
;  fraction.  Builds the full 24-bit product in A:H:L and keeps A:H.
;  (mv_mulf only ever hands it a non-negative DE, but the sign extension
;  is kept: it is what makes this a general 16x8 with no table.)
; ---------------------------------------------------------------------
fracmul
    ld b,0
    bit 7,d
    jr z,fm_p
    ld b,#FF                        ; sign extension byte
fm_p
    ld hl,0
    xor a

    add hl,hl
    rla
    sla c
    jr nc,fm1
    add hl,de
    adc a,b
fm1
    add hl,hl
    rla
    sla c
    jr nc,fm2
    add hl,de
    adc a,b
fm2
    add hl,hl
    rla
    sla c
    jr nc,fm3
    add hl,de
    adc a,b
fm3
    add hl,hl
    rla
    sla c
    jr nc,fm4
    add hl,de
    adc a,b
fm4
    add hl,hl
    rla
    sla c
    jr nc,fm5
    add hl,de
    adc a,b
fm5
    add hl,hl
    rla
    sla c
    jr nc,fm6
    add hl,de
    adc a,b
fm6
    add hl,hl
    rla
    sla c
    jr nc,fm7
    add hl,de
    adc a,b
fm7
    add hl,hl
    rla
    sla c
    jr nc,fm8
    add hl,de
    adc a,b
fm8
    ld d,a
    ld e,h
    ret


; ------------------------------------------------------------ variables ---
plr_x       dw 0            ; 8.8 world x
plr_y       dw 0            ; 8.8 world y
plr_a       db 0            ; heading 0..71

m_gen       db 0            ; flood-mark generation, patched into the code
ms_clp      dw MARK         ; the rolling MARK clear's cursor; H is always
                            ; MARK/256, so only L ever moves
m_visited   db 0            ; cells popped: seen + frustum-rejected.  NOT
                            ; free.py's cells_visited, which also counts the
                            ; opaque and out-of-range cells this flood never
                            ; pushes.  Diagnostic only.
m_seen      db 0            ; cells accepted as visible
m_dropped   db 0            ; faces dropped because a bucket was full

; the eight per-heading constants, in MARCHTAB order -- KEEP CONTIGUOUS,
; march_setup LDIRs all sixteen bytes in at once.
mv_sxi      dw 0            ; rgtx : xv step for i -> i+1
mv_sxj      dw 0            ; rgty : xv step for j -> j+1
mv_szi      dw 0            ; fwdx : zv step for i
mv_szj      dw 0            ; fwdy : zv step for j
mv_sli      dw 0            ; dLi  : left-plane  step for i
mv_slj      dw 0            ; dLj  : left-plane  step for j
mv_sri      dw 0            ; dRi  : right-plane step for i
mv_srj      dw 0            ; dRj  : right-plane step for j

mv_x0       dw 0            ; seed: xv of the player's own cell corner
mv_z0       dw 0            ; seed: zv
mv_l0       dw 0            ; seed: left plane, max-corner and slack folded in
mv_r0       dw 0            ; seed: right plane
mv_cz       dw 0            ; near plane: max-corner - ZNEAR + slack
mv_q        dw 0
mv_cpusp    dw 0            ; the caller's SP while the flood owns it

cur_x       dw 0            ; the popped cell's carried values
cur_z       dw 0
cur_l       dw 0
cur_r       dw 0
cur_i       db 0            ; ... and its signed lattice offset
cur_j       db 0

mf_dir      db 0
mf_kind     db 0
mf_ptr      dw 0
bl1_sav     db 0

; =====================================================================
;  MEASURED, on the cycle-accurate headless CPC 6128, method: bump a
;  16-bit counter once per call, run with interrupts off, subtract a
;  separately measured empty loop.  engine2/tools/emu_march2.py (whole
;  kernel harness, #8018 = march_setup) and engine2/tools/emu_march.py
;  (march alone).  The method is calibrated against a 100-NOP loop to
;  100.08 us.  All numbers are CPC microseconds.
;
;                                   BEFORE (6 frustum tables)   AFTER
;    march_setup, per frame              3078 - 3304            1337 - 1401
;      of which  6 x build_axis            2525                    0
;                4 x fracmul (the seed)       0                   452
;                build_l1                   324                   324
;                marks, buckets, LDIR,      ~270                  ~625
;                  seed adds, mv_kq
;    per marched cell (free.py's cells_visited, single-variable fit)
;                                         189.8                  275.2
;    least squares, march alone, 52 states
;      before   us = 2886 + 189.8*ref_cells                (RMS 156)
;      after    us = 1115 + 275.2*ref_cells                (RMS 133)
;      after    us = 1228 + 186.9*ref_cells + 151.5*faces  (RMS  80)
;
;  Read that last fit before concluding the cell got dearer: the FLOOD
;  is unchanged at ~187 us per cell (the four carried words cost about
;  what the three table lookups cost), and the extra 151 us per FACE is
;  the view-space transform, which used to be done -- twice, at ~360 us
;  an endpoint -- inside proj_face.  Per frame:
;
;    whole march   mean 4597 us (was 5250), median 3953 (was 4935),
;                  worst measured 10855 us (was 9600 at fewer cells)
;    and proj_setup's 1901 us per frame disappears entirely, because
;    nothing reads its lattice tables any more.
;
;  Whole geometry kernel over all 31392 surveyed states, predicted from
;  the measured fit (engine2/tools/emu_kernel.py fit):
;                            BEFORE            AFTER
;      median               17.0 ms           11.2 ms
;      p90                  30.6 ms           21.8 ms
;      worst                44.1 ms           35.0 ms
;  (the projector's own rewrite -- one multiply per endpoint, screen-space
;  side clipping -- is a separate change and is not in the AFTER column.)
;
;  NEXT, not done here: test L1 and the two plane signs at PUSH time
;  instead of at pop.  35% of popped cells are rejected, and each of them
;  costs a 10-byte push plus a 10-byte pop it never uses; the values are
;  computed at push time either way.  Worth ~40 us per marched cell, at
;  the price of a traversal that no longer counts cells the way free.py
;  does.
; =====================================================================
