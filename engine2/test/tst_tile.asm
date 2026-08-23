; =====================================================================
;  engine2/test/tst_tile.asm -- WHAT DOES A TILE BLIT COST?
;
;  The "fake the C64's character mode" architecture: precompile a set of
;  8x8-pixel (4-byte x 8-scanline) tiles as CODE, choose one per screen
;  cell from the projected wall grid, and blit it.  This harness prices
;  the blit and the per-tile dispatch that has to go with it.
;
;  THE ALIGNMENT THAT MAKES IT POSSIBLE.  vpcfg.inc has VP_Y = 0 and
;  VP_H = 96, so viewport row r IS screen scanline r and the viewport is
;  exactly 12 whole character rows.  An 8-scanline tile placed at y = 8k
;  therefore lives entirely inside ONE character row, and its 8 rows are
;  at a CONSTANT +&800 stride -- `add hl,bc` with BC = &0800, no wrap
;  test, no -&3800+80 correction.  CYH = 48 is 8-aligned too, so the
;  horizon is a tile-row boundary.
;
;  ABI for every tile fragment:
;      in   HL = screen address ONE PAST the right end of the top row
;                (same convention as raster.asm's rq_bline)
;           BC = &0800
;           IY = return address
;      out  HL = entry HL + 7*&800   (it walked 8 rows)
;           clobbers AF DE SP
;      ends with JP (IY)
;
;  Memory:  #8000-  harness
;           #7FF0   stack
;           #7500   TLIST, one tile id per screen cell
;           #9000-  tile code, 256-byte stride, 16 tiles
;           #C000   screen
; =====================================================================

STACK   equ #7FF0
SCR     equ #C000
VP_BX   equ 18
VP_BW   equ 44
VPB     equ SCR+VP_BX
TLIST   equ #7500
TILEPG  equ #90                     ; tile code base page, 256-byte stride
MAXB    equ 44                      ; widest band, BYTES
SCR_W   equ 80

    org #8000

    di
    jp  e_nop
    di
    jp  e_empty
    di
    jp  e_t4reg
    di
    jp  e_t4brick
    di
    jp  e_t4imm
    di
    jp  e_t8reg
    di
    jp  e_t8imm
    di
    jp  e_t4disp
    di
    jp  e_bandimm
    di
    jp  e_bandreg
    di
    jp  e_gen

; ---------------------------------------------------------------------
romoff
    ld  bc,#7F8C                    ; mode 0, both ROMs disabled
    out (c),c
    ret

s_null
    ret

; =====================================================================
;  THE COUNTING LOOPS
; =====================================================================
    macro LOOPER ent,sub
{ent}
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
{ent}_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call {sub}
    jp  {ent}_l
    mend

    LOOPER e_nop, s_nop100
    LOOPER e_empty, s_null
    LOOPER e_t4reg, s_t4reg
    LOOPER e_t4brick, s_t4brick
    LOOPER e_t4imm, s_t4imm
    LOOPER e_t8reg, s_t8reg
    LOOPER e_t8imm, s_t8imm
    LOOPER e_t4disp, s_t4disp
    LOOPER e_bandimm, s_bandimm
    LOOPER e_bandreg, s_bandreg
    LOOPER e_gen, s_gen

s_nop100
    repeat 100
    nop
    rend
    ret

; =====================================================================
;  THE SUBJECTS.  Each blits (ntiles) tiles, stepping 4 (or 8) bytes to
;  the right each time.  The slope across two tile counts is therefore
;  the WHOLE per-tile cost: blit, screen-address advance and loop.
; =====================================================================

; ---------------------------------------------------------------------
;  s_t4reg -- the FLOOR.  4x8 bytes, ONE pattern word held in DE for the
;  whole tile.  Visually this is a flat tile with at most a 4-pixel
;  horizontal repeat and NO horizontal mortar; it exists to show what
;  the pointer work alone costs.
; ---------------------------------------------------------------------
s_t4reg
    ld  (spsave),sp
    ld  bc,#0800
    ld  iy,t4r_back
    ld  hl,VPB+4
    ld  a,(ntiles)
    ld  ixl,a
t4r_go
    jp  T4REG
t4r_back
    ld  a,l
    add a,4
    ld  l,a
    ld  a,h
    sub #38
    ld  h,a
    dec ixl
    jr  nz,t4r_go
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_t4brick -- THE REALISTIC ONE.  4x8 bytes, two pattern words (body
;  colour and the byte carrying the vertical mortar) held in DE and in
;  the alternate DE', with one row swapped out for the horizontal mortar
;  course.  This is the cheapest shape that can show mortar in BOTH
;  axes inside one tile, which is what the reference picture needs.
; ---------------------------------------------------------------------
s_t4brick
    ld  (spsave),sp
    ld  bc,#0800
    ld  iy,t4b_back
    ld  hl,VPB+4
    ld  a,(ntiles)
    ld  ixl,a
t4b_go
    jp  T4BRICK
t4b_back
    ld  a,l
    add a,4
    ld  l,a
    ld  a,h
    sub #38
    ld  h,a
    dec ixl
    jr  nz,t4b_go
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_t4imm -- 4x8 bytes, EVERY byte arbitrary: the pattern is an
;  immediate in the tile's own code.  The upper bound on a 4-byte tile.
; ---------------------------------------------------------------------
s_t4imm
    ld  (spsave),sp
    ld  bc,#0800
    ld  iy,t4i_back
    ld  hl,VPB+4
    ld  a,(ntiles)
    ld  ixl,a
t4i_go
    jp  T4IMM
t4i_back
    ld  a,l
    add a,4
    ld  l,a
    ld  a,h
    sub #38
    ld  h,a
    dec ixl
    jr  nz,t4i_go
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_t8reg / s_t8imm -- the same with a 16-pixel-wide tile (8 bytes),
;  which halves the number of `ld sp,hl` per screen byte.
; ---------------------------------------------------------------------
s_t8reg
    ld  (spsave),sp
    ld  bc,#0800
    ld  iy,t8r_back
    ld  hl,VPB+8
    ld  a,(ntiles)
    ld  ixl,a
t8r_go
    jp  T8REG
t8r_back
    ld  a,l
    add a,8
    ld  l,a
    ld  a,h
    sub #38
    ld  h,a
    dec ixl
    jr  nz,t8r_go
    ld  sp,(spsave)
    ret

s_t8imm
    ld  (spsave),sp
    ld  bc,#0800
    ld  iy,t8i_back
    ld  hl,VPB+8
    ld  a,(ntiles)
    ld  ixl,a
t8i_go
    jp  T8IMM
t8i_back
    ld  a,l
    add a,8
    ld  l,a
    ld  a,h
    sub #38
    ld  h,a
    dec ixl
    jr  nz,t8i_go
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_t4disp -- the SAME t4imm tiles, but reached the way a renderer has
;  to reach them: one byte of tile id per screen cell, read out of a
;  page-aligned list, turned into a code address by the 256-byte stride
;  and jumped to indirectly.  The list pointer and the tile counter live
;  in the ALTERNATE set, which the tiles never touch.
; ---------------------------------------------------------------------
s_t4disp
    ld  (spsave),sp
    exx
    ld  hl,TLIST
    ld  a,(ntiles)
    ld  c,a
    exx
    ld  bc,#0800
    ld  iy,t4d_back
    ld  ix,TILEPG*256               ; IXL = 0 and stays 0
    ld  hl,VPB+4
t4d_go
    exx
    ld  a,(hl)                      ; tile id
    inc l
    exx
    add a,TILEPG
    ld  ixh,a
    jp  (ix)
t4d_back
    ld  a,l
    add a,4
    ld  l,a
    ld  a,h
    sub #38
    ld  h,a
    exx
    dec c
    exx
    jr  nz,t4d_go
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_bandimm -- the CONTROL the tile idea has to beat: one aligned band
;  of 8 scanlines, (nbytes) wide, filled by `ld de,nn : push de` out of
;  a page-aligned block.  Because the band never crosses a character row
;  the per-scanline walk is only `ld sp,hl` + `add hl,bc` + the block
;  entry -- no wrap test at all, unlike raster.asm's rq_bline.
;  (nrows) bands are drawn, each 8 scanlines.
; ---------------------------------------------------------------------
s_bandimm
    ld  (spsave),sp
    ld  a,(nbytes)
    srl a
    neg
    add a,MAXB/2
    add a,a
    add a,a                         ; 4 bytes of code per push unit
    ld  (bi_e+1),a
    ld  hl,VPB+VP_BW
    ld  bc,#0800
    ld  ix,bi_next
    ld  a,(nrows)
    ld  (bi_n),a
bi_band
    ld  a,8
    ld  (bi_c),a
bi_line
    ld  sp,hl
bi_e
    jp  BANDIMM
bi_next
    add hl,bc
    ld  a,(bi_c)
    dec a
    ld  (bi_c),a
    jr  nz,bi_line
    ; next band: -7*&800 + 80
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C8
    ld  h,a
    ld  a,(bi_n)
    dec a
    ld  (bi_n),a
    jr  nz,bi_band
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_bandreg -- the same band filled with PUSH DE / PUSH BC out of two
;  held registers: a 4-byte repeating pattern, which is the only thing
;  that is free.  BC is the pattern here, so the +&800 step goes through
;  A, which costs 1 us more per scanline than `add hl,bc`.
; ---------------------------------------------------------------------
s_bandreg
    ld  (spsave),sp
    ld  a,(nbytes)
    srl a
    srl a
    neg
    add a,MAXB/4
    add a,a                         ; 2 bytes of code per push PAIR
    ld  (br_e+1),a
    ld  hl,VPB+VP_BW
    ld  de,#4C4E
    ld  bc,#4E4C
    ld  ix,br_next
    ld  a,(nrows)
    ld  (br_n),a
br_band
    ld  a,8
    ld  (br_c),a
br_line
    ld  sp,hl
br_e
    jp  BANDREG
br_next
    ld  a,h
    add a,8
    ld  h,a
    ld  a,(br_c)
    dec a
    ld  (br_c),a
    jr  nz,br_line
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C8
    ld  h,a
    ld  a,(br_n)
    dec a
    ld  (br_n),a
    jr  nz,br_band
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_gen -- THE COST TILES EXIST TO AVOID.  A span renderer that wants an
;  arbitrary, foreshortened pattern has to GENERATE the `ld de,nn`
;  immediates before it can run them.  This copies (nbytes) screen bytes
;  worth of already-computed words out of a linear table into BANDIMM's
;  immediate fields, which sit at a stride of 4.  It does NOT include
;  sampling the texture to produce those words in the first place.
; ---------------------------------------------------------------------
s_gen
    ld  a,(nbytes)
    srl a
    neg
    add a,MAXB/2
    add a,a
    add a,a
    ld  (gn_e+1),a
    ld  ix,gn_next
    ld  a,(nrows)
    ld  b,a
gn_line
    ld  hl,BANDIMM+1
    ld  de,#7600                ; the precomputed word table
gn_e
    jp  GENBLK
gn_next
    djnz gn_line
    ret

; =====================================================================
;  THE PAGE-ALIGNED BAND BLOCKS
; =====================================================================
    align 256
GENBLK
    repeat MAXB/2
    ld  a,(de)
    inc e
    ld  (hl),a
    inc l
    ld  a,(de)
    inc e
    ld  (hl),a
    inc l
    inc l
    inc l
    rend
    jp  (ix)

    align 256
BANDIMM
biw = #4C4E
    repeat MAXB/2
    ld  de,biw
    push de
biw = biw + #0101
    rend
    jp  (ix)

    align 256
BANDREG
    repeat MAXB/4
    push de
    push bc
    rend
    jp  (ix)

; =====================================================================
;  THE TILE FRAGMENTS.  Written once each here; the dispatch test needs
;  sixteen of them at a 256-byte stride, which T4IMM is replicated into.
; =====================================================================

    align 256
T4REG
    ld  de,#4C4E
    repeat 7
    ld  sp,hl
    push de
    push de
    add hl,bc
    rend
    ld  sp,hl
    push de
    push de
    jp  (iy)

    align 256
T4BRICK
    exx
    ld  de,#0C0E                    ; the mortar course
    exx
    ld  de,#4C4E                    ; body colour, right half
    repeat 6
    ld  sp,hl
    push de
    push de
    add hl,bc
    rend
    ; row 6: the vertical mortar byte, from the alternate DE
    ld  sp,hl
    push de
    exx
    push de
    exx
    add hl,bc
    ; row 7: the horizontal mortar course, both words
    ld  sp,hl
    exx
    push de
    push de
    exx
    jp  (iy)

    align 256
T8REG
    ld  de,#4C4E
    repeat 7
    ld  sp,hl
    push de
    push bc
    push de
    push bc
    ld  a,h
    add a,8
    ld  h,a
    rend
    ld  sp,hl
    push de
    push bc
    push de
    push bc
    jp  (iy)

    align 256
T8IMM
t8w = #4C4E
    repeat 7
    ld  sp,hl
    repeat 4
    ld  de,t8w
    push de
t8w = t8w + #0101
    rend
    add hl,bc
    rend
    ld  sp,hl
    repeat 4
    ld  de,t8w
    push de
t8w = t8w + #0101
    rend
    jp  (iy)

; ---- sixteen copies of the arbitrary 4x8 tile, 256-byte stride -------
    org #9000
    repeat 16
tst = $
t4w = #4C4E
    repeat 7
    ld  sp,hl
    ld  de,t4w
    push de
    ld  de,t4w+#0101
    push de
t4w = t4w + #0202
    add hl,bc
    rend
    ld  sp,hl
    ld  de,t4w
    push de
    ld  de,t4w+#0101
    push de
    jp  (iy)
    defs 256-($-tst)
    rend

T4IMM   equ #9000

; =====================================================================
    org #8C00
counter dw  0
ntiles  db  16
nbytes  db  44
nrows   db  8
spsave  dw  0
bi_n    db  0
bi_c    db  8
br_n    db  0
br_c    db  8
