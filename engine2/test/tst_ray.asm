; =====================================================================
;  engine2/test/tst_ray.asm -- WHAT DOES A COLUMN RAYCASTER COST?
;
;  Nothing here is part of the game.  This is a cost harness for the
;  "throw away the span list, cast 44 rays, draw 44 textured vertical
;  strips" architecture.  It measures, on the real 6128:
;
;    * mul8x8u / mul16x8u / recip_zv           (math.asm, verbatim)
;    * ONE DDA grid step                       slope over step count
;    * the per-ray fixed cost                  intercept of the same fit
;    * the per-column post-hit block           (dist -> h, texcol, addr)
;    * the textured strip, POP-fed from a precomputed column cache
;    * the textured strip, true per-pixel fractional step
;
;  Same counting-loop method as tst_byte.asm: every subject is CALLed
;  from a byte-identical loop, timed at two parameter values, and the
;  SLOPE is taken so the loop, the CALL/RET and all setup cancel.
;
;  Memory:  #6000-  harness      #4000-#4AFF  mathdata (banked in low RAM)
;           #7000   MAP    256-byte page-aligned 16x16 grid
;           #7100   DDTAB  per-column (ddx,ddy) records
;           #7200   SRC    precomputed texture column cache
;           #7300   HTAB   depth -> projected height, 2x256 pages
;           #7500   TEXSTEP / STARTOFF tables
;           #7600   LINETAB
;           #7FF0   stack            #C000  screen
; =====================================================================

MAP     equ #7000
DDTAB   equ #7100
SRC     equ #7200
HTABLO  equ #7300
HTABHI  equ #7400
TEXSTEP equ #7500
STARTOF equ #7580
LINETAB equ #7600
TEXPAGE equ #7700
STACK   equ #7FF0
SCR     equ #C000
VP_BX   equ 18
VPB     equ SCR+VP_BX
SCR_W   equ 80

    include "mathdata.inc"

    org #6000

    di
    jp  e_nop
    di
    jp  e_empty
    di
    jp  e_mul8
    di
    jp  e_mul16
    di
    jp  e_recip
    di
    jp  e_ray
    di
    jp  e_post
    di
    jp  e_strip
    di
    jp  e_stex
    di
    jp  e_raycheap
    di
    jp  e_baked
    di
    jp  e_rayy
    di
    jp  e_rayopt
    di
    jp  e_post8

romoff
    ld  bc,#7F8C                    ; mode 0, both ROMs disabled
    out (c),c
    ret

s_null
    ret

; =====================================================================
;  counting loops
; =====================================================================
e_nop
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
en_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_nop100
    jp  en_l
s_nop100
    repeat 100
    nop
    rend
    ret

e_empty
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ee_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_null
    jp  ee_l

e_mul8
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
em8_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ld  a,#B7
    ld  c,#5D
    call mul8x8u
    jp  em8_l

e_mul16
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
em16_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ld  de,#3B71
    ld  c,#5D
    call mul16x8u
    jp  em16_l

e_recip
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
er_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    ld  hl,#0B37
    call recip_zv
    jp  er_l

e_ray
    ld  sp,STACK
    call romoff
    call ray_init
    ld  hl,0
    ld  (counter),hl
ery_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_ray
    jp  ery_l

e_raycheap
    ld  sp,STACK
    call romoff
    call ray_init
    ld  hl,0
    ld  (counter),hl
erc_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_raycheap
    jp  erc_l

e_rayy
    ld  sp,STACK
    call romoff
    call ray_inity
    ld  hl,0
    ld  (counter),hl
eyy_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_ray
    jp  eyy_l

e_rayopt
    ld  sp,STACK
    call romoff
    call ray_init
    ld  hl,0
    ld  (counter),hl
eo_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_rayopt
    jp  eo_l

e_post8
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
e8_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_post8
    jp  e8_l

e_post
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ep_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_post
    jp  ep_l

e_strip
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
es_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_strip
    jp  es_l

e_baked
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
eb_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_baked
    jp  eb_l

e_stex
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ex_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_stex
    jp  ex_l


; =====================================================================
;  ray_init -- build the map so that the DDA hits a wall after exactly
;  (nsteps) grid steps.  Player sits at cell (0,0) offset (0.5,0.5),
;  the ray is nearly along +X (rayDirY = rayDirX/64) so every step is
;  an X step until sideDistY (= 32 cells) is passed, which it never is
;  for nsteps <= 15.  The wall goes at cell (nsteps, 0).
; =====================================================================
ray_init
    ld  hl,MAP                      ; clear the map
    ld  de,MAP+1
    ld  bc,255
    ld  (hl),0
    ldir
    ld  a,(nsteps)
    ld  l,a
    ld  h,MAP/256
    ld  (hl),1                      ; wall at cell (nsteps, 0)
    ; per-column delta record: ddx = 1.00 cell, ddy = 64.00 cells
    ld  hl,DDTAB
    ld  (hl),#00
    inc hl
    ld  (hl),#01                    ; ddx = #0100 Q8.8
    inc hl
    ld  (hl),#00
    inc hl
    ld  (hl),#40                    ; ddy = #4000 Q8.8
    ret


; ---------------------------------------------------------------------
;  ray_inity -- the same, but the ray runs along +Y, so every grid step
;  takes the Y branch (the one that has to EX DE,HL round the add and
;  step the map pointer by a whole row).
; ---------------------------------------------------------------------
ray_inity
    ld  hl,MAP
    ld  de,MAP+1
    ld  bc,255
    ld  (hl),0
    ldir
    ld  a,(nsteps)
    add a,a
    add a,a
    add a,a
    add a,a                         ; nsteps * 16
    ld  l,a
    ld  h,MAP/256
    ld  (hl),1
    ld  hl,DDTAB
    ld  (hl),#00
    inc hl
    ld  (hl),#40                    ; ddx = 64.00 cells
    inc hl
    ld  (hl),#00
    inc hl
    ld  (hl),#01                    ; ddy = 1.00 cell
    ret


; =====================================================================
;  s_ray -- ONE COLUMN of a Wolfenstein DDA, honestly.
;
;  Per-ray setup:
;    * step the camera-plane ray direction (rayDir[i+1] = rayDir[i] +
;      2/w * plane) -- two 16-bit adds, no multiply, the standard trick
;    * read the (ddx, ddy) record for this column out of DDTAB (the
;      per-heading table: deltaDist depends only on heading and column,
;      so it is ROM, not computed)
;    * quadrant dispatch on the two direction signs
;    * seed sideDistX = fx*ddx and sideDistY = fy*ddy -- TWO multiplies,
;      because fx/fy are per-frame and ddx/ddy are per-column
;    * patch the two `ld bc,nn` immediates the inner loop steps by
;
;  Then the DDA loop, then the post-hit block.
;
;  Registers in the loop:  HL = sideDistX   DE = sideDistY
;                          BC = scratch     HL' = map pointer
; =====================================================================
s_ray
    ; --- ray direction carried incrementally, 2 x 16-bit add ---------
    ld  hl,(rdx)
    ld  bc,(pstepx)
    add hl,bc
    ld  (rdx),hl
    ld  hl,(rdy)
    ld  bc,(pstepy)
    add hl,bc
    ld  (rdy),hl
    ; --- the column's deltaDist record -------------------------------
    ld  hl,DDTAB
    ld  e,(hl)
    inc l
    ld  d,(hl)
    inc l
    ld  (ddx_i+1),de                ; patch the X-step immediate
    ld  c,(hl)
    inc l
    ld  b,(hl)
    ld  (ddy_i+1),bc                ; patch the Y-step immediate
    ; --- quadrant dispatch -------------------------------------------
    ld  a,(rdx+1)
    rlca
    and 1
    ld  c,a
    ld  a,(rdy+1)
    rlca
    and 1
    add a,a
    or  c
    add a,a
    ld  c,a
    ld  b,0
    ld  hl,qtab
    add hl,bc
    ld  a,(hl)
    inc hl
    ld  h,(hl)
    ld  l,a
    ld  (qdisp+1),hl
    ; --- sideDist seeds: fx*ddx and fy*ddy ---------------------------
    ld  de,(ddx_i+1)
    ld  a,(fx)
    ld  c,a
    call mul16x8u                   ; A:HL, sideDist = (A:H) = product>>8
    ld  l,h
    ld  h,a
    ld  (sdx),hl
    ld  de,(ddy_i+1)
    ld  a,(fy)
    ld  c,a
    call mul16x8u
    ld  l,h
    ld  h,a
    ld  (sdy),hl
    ; --- enter the walk ----------------------------------------------
    ld  hl,(sdx)
    ld  de,(sdy)
    exx
    ld  hl,MAP                      ; map pointer, page aligned
    exx
qdisp
    jp  dda_pp

; ---------------------------------------------------------------------
;  the +X/+Y quadrant of the walk.  The other three are byte-identical
;  with `inc l` -> `dec l` and +16 -> -16, so only this one is timed.
; ---------------------------------------------------------------------
dda_pp
    or  a
    sbc hl,de                       ; sideDistX - sideDistY
    add hl,de
    jr  nc,dda_y
dda_x
ddx_i
    ld  bc,#0100                    ; deltaDistX, patched
    add hl,bc
    exx
    inc l                           ; mapX += stepX
    ld  a,(hl)
    exx
    or  a
    jp  z,dda_pp
    ; --- hit on an X face --------------------------------------------
    ld  bc,(ddx_i+1)
    or  a
    sbc hl,bc                       ; perpendicular distance, Q8.8
    jp  hit
dda_y
ddy_i
    ld  bc,#4000                    ; deltaDistY, patched
    ex  de,hl
    add hl,bc
    ex  de,hl
    exx
    ld  a,l
    add a,16                        ; mapY += stepY
    ld  l,a
    ld  a,(hl)
    exx
    or  a
    jp  z,dda_pp
    ld  bc,(ddy_i+1)
    ex  de,hl
    or  a
    sbc hl,bc
    jp  hit

hit
    ld  (perp),hl
    jp  s_post

; ---------------------------------------------------------------------
;  s_raycheap -- identical, but the two sideDist seeds use mul8x8u
;  (8 bits of deltaDist mantissa) instead of mul16x8u.  Everything else
;  is the same code, so the difference is exactly the multiply cost.
; ---------------------------------------------------------------------
s_raycheap
    ld  hl,(rdx)
    ld  bc,(pstepx)
    add hl,bc
    ld  (rdx),hl
    ld  hl,(rdy)
    ld  bc,(pstepy)
    add hl,bc
    ld  (rdy),hl
    ld  hl,DDTAB
    ld  e,(hl)
    inc l
    ld  d,(hl)
    inc l
    ld  (ddx_i+1),de
    ld  c,(hl)
    inc l
    ld  b,(hl)
    ld  (ddy_i+1),bc
    ld  a,(rdx+1)
    rlca
    and 1
    ld  c,a
    ld  a,(rdy+1)
    rlca
    and 1
    add a,a
    or  c
    add a,a
    ld  c,a
    ld  b,0
    ld  hl,qtab
    add hl,bc
    ld  a,(hl)
    inc hl
    ld  h,(hl)
    ld  l,a
    ld  (qdisp+1),hl
    ld  a,(ddx_i+2)                 ; 8-bit mantissa of deltaDistX
    ld  hl,fx
    ld  c,(hl)
    call mul8x8u
    ld  (sdx),hl
    ld  a,(ddy_i+2)
    ld  hl,fy
    ld  c,(hl)
    call mul8x8u
    ld  (sdy),hl
    ld  hl,(sdx)
    ld  de,(sdy)
    exx
    ld  hl,MAP
    exx
    jp  qdisp

qtab
    dw  dda_pp, dda_pp, dda_pp, dda_pp


; =====================================================================
;  s_post -- everything between "the DDA hit a wall" and "the strip
;  loop may start".  (perp) = perpendicular distance, Q8.8 cells.
;
;    depth index   zq = perp >> 2, clamped to the table
;    height        h  = HTAB[zq]           (projected FULL height)
;    clip          h  > 96 -> h = 96, and the texture start offset for
;                  a clipped strip is a function of h alone -> STARTOF
;    texture col   wallY = posy + perp*rdy   ONE 16x8 multiply,
;                  fractional byte -> texture column
;    source ptr    SRC + texcol*64 + STARTOF[h]
;    screen addr   LINETAB[ytop] + column,  ytop = 48 - h/2
;    length        h scanlines
; =====================================================================
s_post
    ld  hl,(perp)
    ; zq = perp >> 2, clamp to 0..511
    srl h
    rr  l
    srl h
    rr  l
    ld  a,h
    cp  2
    jr  c,po_ok
    ld  hl,511
po_ok
    ld  a,h
    add a,HTABLO/256
    ld  h,a
    ld  a,(hl)                      ; height low
    inc h
    inc h                           ; -> HTABHI page pair
    ld  h,(hl)
    ld  l,a                         ; HL = projected height, Q12.4
    ; h = HL >> 4, saturating at 96
    ld  a,l
    srl h
    rra
    srl h
    rra
    srl h
    rra
    srl h
    rra
    or  h
    jr  z,po_hok
    ld  a,96
po_hok
    cp  97
    jr  c,po_h2
    ld  a,96
po_h2
    ld  (hgt),a
    ; texture column: wallY = posy + perp*rdy   (one 16x8 multiply)
    ld  de,(perp)
    ld  a,(rdy+1)
    ld  c,a
    call mul16x8u
    ld  a,(posy)
    add a,h                         ; fractional cell coordinate
    and #C0                         ; 4 texture columns
    rrca
    rrca                            ; *64/4 -> column offset
    ld  l,a
    ld  h,SRC/256
    ld  a,(hgt)
    ld  e,a
    ld  d,STARTOF/256
    ld  a,(de)                      ; start texel for a clipped strip
    add a,l
    ld  l,a
    ld  (srcp),hl
    ; screen address: ytop = (96 - h)/2
    ld  a,(hgt)
    neg
    add a,96
    srl a
    add a,a                         ; word index into LINETAB
    ld  l,a
    ld  h,LINETAB/256
    ld  a,(hl)
    inc l
    ld  h,(hl)
    ld  l,a
    ld  bc,VP_BX+20                 ; + the column
    add hl,bc
    ld  (scrp),hl
    ret



; =====================================================================
;  s_rayopt -- the same ray with every avoidable microsecond removed:
;    * no rayDir carry at all (the fan's quadrant is hoisted out of the
;      column loop -- the sign of rayDirX/Y changes at most twice across
;      a 60 degree fan, so the 44 columns split into <= 3 runs, each
;      entering its own specialised DDA)
;    * mul8x8u seeds instead of mul16x8u (8-bit deltaDist mantissa)
;    * mul8x8u for the texture column too (s_post8): 8 texture columns
;      instead of 256, which is what a chunky block texture wants anyway
;  Everything else -- the DDTAB read, the two patched immediates, the
;  height table, the clip, the source and screen pointers -- is intact.
; =====================================================================
s_rayopt
    ld  hl,DDTAB
    ld  e,(hl)
    inc l
    ld  d,(hl)
    inc l
    ld  (ddx_i+1),de
    ld  c,(hl)
    inc l
    ld  b,(hl)
    ld  (ddy_i+1),bc
    ld  a,(ddx_i+2)
    ld  hl,fx
    ld  c,(hl)
    call mul8x8u
    ld  (sdx),hl
    ld  a,(ddy_i+2)
    ld  hl,fy
    ld  c,(hl)
    call mul8x8u
    ld  (sdy),hl
    ld  hl,(sdx)
    ld  de,(sdy)
    exx
    ld  hl,MAP
    exx
    jp  dda_pp8

dda_pp8
    or  a
    sbc hl,de
    add hl,de
    jr  nc,dda_y8
ddx_i8
    ld  bc,#0100
    add hl,bc
    exx
    inc l
    ld  a,(hl)
    exx
    or  a
    jp  z,dda_pp8
    ld  bc,(ddx_i+1)
    or  a
    sbc hl,bc
    ld  (perp),hl
    jp  s_post8
dda_y8
ddy_i8
    ld  bc,#4000
    ex  de,hl
    add hl,bc
    ex  de,hl
    exx
    ld  a,l
    add a,16
    ld  l,a
    ld  a,(hl)
    exx
    or  a
    jp  z,dda_pp8
    ld  bc,(ddy_i+1)
    ex  de,hl
    or  a
    sbc hl,bc
    ld  (perp),hl
    jp  s_post8

; --- s_post8: s_post with an 8x8 texture-column multiply --------------
s_post8
    ld  hl,(perp)
    srl h
    rr  l
    srl h
    rr  l
    ld  a,h
    cp  2
    jr  c,p8_ok
    ld  hl,511
p8_ok
    ld  a,h
    add a,HTABLO/256
    ld  h,a
    ld  a,(hl)
    inc h
    inc h
    ld  h,(hl)
    ld  l,a
    ld  a,l
    srl h
    rra
    srl h
    rra
    srl h
    rra
    srl h
    rra
    or  h
    jr  z,p8_hok
    ld  a,96
p8_hok
    cp  97
    jr  c,p8_h2
    ld  a,96
p8_h2
    ld  (hgt),a
    ld  a,(perp+1)
    ld  hl,rdy+1
    ld  c,(hl)
    call mul8x8u
    ld  a,(posy)
    add a,h
    and #E0
    rrca
    rrca
    ld  l,a
    ld  h,SRC/256
    ld  a,(hgt)
    ld  e,a
    ld  d,STARTOF/256
    ld  a,(de)
    add a,l
    ld  l,a
    ld  (srcp),hl
    ld  a,(hgt)
    neg
    add a,96
    srl a
    add a,a
    ld  l,a
    ld  h,LINETAB/256
    ld  a,(hl)
    inc l
    ld  h,(hl)
    ld  l,a
    ld  bc,VP_BX+20
    add hl,bc
    ld  (scrp),hl
    ret


; =====================================================================
;  s_strip -- the textured strip, POP-fed out of a precomputed scaled
;  texture column.  (nrows) groups of 8 scanlines; the group is the
;  cheapest column write this machine has (tst_byte #11, 7.750 us/byte).
;  The prologue is the real per-strip entry: save SP, point it at the
;  cache entry, fetch the screen address, restore SP on the way out.
; =====================================================================
s_strip
    ld  (spsave),sp
    ld  hl,(scrp)
    ld  hl,VPB
    ld  de,#0800
    ld  a,(nrows)
    ld  ixl,a
    ld  sp,SRC
st_row
    repeat 3
    pop bc
    ld  (hl),c
    add hl,de
    ld  (hl),b
    add hl,de
    rend
    pop bc
    ld  (hl),c
    add hl,de
    ld  (hl),b
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C8
    ld  h,a
    dec ixl
    jr  nz,st_row
    ld  sp,(spsave)
    ret


; =====================================================================
;  s_baked -- the strongest column-major write this machine has.  The
;  SCREEN ADDRESS OF EVERY SCANLINE IS BAKED INTO THE CODE, so there is
;  no pointer, no 16-bit add and no character-row wrap at all: two
;  `ld (nnnn),a` per POP.  One such block exists PER BYTE COLUMN (the
;  address carries the column), 432 bytes each, 44 of them = 19 KB.
;  Entering at (48-n) units runs exactly n units, so length is free.
; =====================================================================
s_baked
    ld  (spsave),sp
    ld  a,(nrows)
    add a,a
    add a,a                         ; units = nrows*4  (8 bytes a row)
    ld  b,a
    ld  a,48
    sub b
    ld  l,a
    ld  h,0
    ld  b,h
    ld  c,l
    add hl,hl
    add hl,hl
    add hl,hl                       ; *8
    add hl,bc                       ; *9 = unit size, in bytes
    ld  bc,COLBLK
    add hl,bc
    ld  (cb_j+1),hl
    ld  sp,SRC
cb_j
    jp  COLBLK
cb_back
    ld  sp,(spsave)
    ret

    align 256
COLBLK
    repeat 48,IDX
    pop bc
    ld  a,c
    ld  (SCR+(((IDX-1)*2)&7)*#800+(((IDX-1)*2)/8)*80+VP_BX+20),a
    ld  a,b
    ld  (SCR+(((IDX-1)*2+1)&7)*#800+(((IDX-1)*2+1)/8)*80+VP_BX+20),a
    rend
    jp  cb_back


; =====================================================================
;  s_stex -- the same strip WITHOUT a cache: a true per-pixel
;  fractional walk of the texture (tst_byte #10, 13.625 us/byte).
; =====================================================================
s_stex
    exx
    ld  hl,VPB
    ld  de,#0800
    ld  bc,#C850
    exx
    ld  hl,#0000
    ld  bc,#0180
    ld  d,TEXPAGE/256
    ld  a,(nrows)
    ld  ixl,a
sx_row
    repeat 7
    ld  e,h
    ld  a,(de)
    add hl,bc
    exx
    ld  (hl),a
    add hl,de
    exx
    rend
    ld  e,h
    ld  a,(de)
    add hl,bc
    exx
    ld  (hl),a
    add hl,bc
    exx
    dec ixl
    jr  nz,sx_row
    ret


; =====================================================================
    include "math.asm"

; --- harness state ----------------------------------------------------
counter dw  0
spsave  dw  0
nsteps  db  8
nrows   db  8
rdx     dw  #0100
rdy     dw  #0004
pstepx  dw  #FFF0
pstepy  dw  #0030
fx      db  #80
fy      db  #80
sdx     dw  0
sdy     dw  0
perp    dw  0
hgt     db  0
srcp    dw  0
scrp    dw  0
posy    db  #80
