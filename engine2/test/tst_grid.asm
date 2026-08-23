; =====================================================================
;  engine2/test/tst_grid.asm -- WHAT DOES A GEOMETRICALLY HONEST GRID
;  COST, PER SCANLINE AND PER JOINT ROW PAIR?
;
;  Nothing here is part of the game.  It is the same protocol as
;  tst_byte.asm: every subject is a CALLed routine timed inside an
;  identical counting loop, at TWO sizes, and the SLOPE is reported, so
;  the loop, the CALL/RET and all per-run setup cancel exactly.
;
;  THE FOUR QUESTIONS
;    1  PUSH IY vs PUSH DE.  The face's END COLUMNS are real projected
;       cell corners; drawing them means substituting ONE push at each
;       end of every run.  The register file is full (DE fill, HL screen,
;       B rows, C character-row countdown), so the substitute has to be
;       an INDEX register -- and on this machine a DD/FD prefix is a
;       whole microsecond.  Is it 4 us or 5?
;    2  a body scanline WITH both end columns, against raster.asm's
;       rq_bline verbatim.
;    3  the COURSE JOINT drawn the way raster.asm:raster_joint draws it
;       today -- a second pass that re-derives the screen address out of
;       VPLINE, reloads IX and re-enters PUSHBLK, twice per mirrored row
;       pair.
;    4  the same joint FOLDED: the Bresenham accumulator and both screen
;       pointers kept in registers across the whole pass (main set and
;       alternate set), the address STEPPED by -&800 instead of looked
;       up, the block tails hard-wired so no LD IX,nn is needed.
;
;  Memory:  #8000-  this harness      #7FF0 stack
;           #7500   VPLINE, 192 bytes, page aligned
;           #C000   the screen
; =====================================================================

STACK   equ #7FF0
VPLINE  equ #7500
SCR     equ #C000
VP_BX   equ 18
VP_BW   equ 44
VP_H    equ 96
VPB     equ SCR+VP_BX
MAXP    equ 22                      ; PUSH DE slots in a full-width block
JM      equ 8                       ; PUSH IY slots in a mortar block
SCR_W   equ 80
BB      equ 40                      ; the clamp column the joints run to

    org #8000

    di
    jp  e_nop
    di
    jp  e_empty
    di
    jp  e_bline
    di
    jp  e_bedge
    di
    jp  e_pushiy
    di
    jp  e_jorig
    di
    jp  e_jfold
    di
    jp  e_jfold1
    di
    jp  e_jmath
    di
    jp  e_jtrue

; ---------------------------------------------------------------------
romoff
    ld  bc,#7F8C                    ; mode 0, both ROMs disabled
    out (c),c
    ret

s_null
    ret

; =====================================================================
;  THE COUNTING LOOPS -- byte identical apart from the CALL target
; =====================================================================
e_nop
    ld  sp,STACK
    call romoff
    call mkvpline
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
    call mkvpline
    ld  hl,0
    ld  (counter),hl
ee_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_null
    jp  ee_l

e_bline
    ld  sp,STACK
    call romoff
    call mkvpline
    ld  hl,0
    ld  (counter),hl
eb_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_bline
    jp  eb_l

e_bedge
    ld  sp,STACK
    call romoff
    call mkvpline
    ld  hl,0
    ld  (counter),hl
ebe_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_bedge
    jp  ebe_l

e_pushiy
    ld  sp,STACK
    call romoff
    call mkvpline
    ld  hl,0
    ld  (counter),hl
epy_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_pushiy
    jp  epy_l

e_jorig
    ld  sp,STACK
    call romoff
    call mkvpline
    ld  hl,0
    ld  (counter),hl
ejo_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_jorig
    jp  ejo_l

e_jfold
    ld  sp,STACK
    call romoff
    call mkvpline
    ld  hl,0
    ld  (counter),hl
ejf_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_jfold
    jp  ejf_l

e_jfold1
    ld  sp,STACK
    call romoff
    call mkvpline
    ld  hl,0
    ld  (counter),hl
ejf1_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_jfold1
    jp  ejf1_l

e_jmath
    ld  sp,STACK
    call romoff
    call mkvpline
    ld  hl,0
    ld  (counter),hl
ejm_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_jmath
    jp  ejm_l

e_jtrue
    ld  sp,STACK
    call romoff
    call mkvpline
    ld  hl,0
    ld  (counter),hl
ejt_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_jtrue
    jp  ejt_l


; ---------------------------------------------------------------------
;  VPLINE, exactly as raster_init builds it: offset of viewport row r
; ---------------------------------------------------------------------
mkvpline
    ld  de,VPLINE
    ld  hl,VP_BX                    ; row 0
    ld  b,VP_H
    ld  c,0                         ; c = row & 7
mv_l
    ld  a,l
    ld  (de),a
    inc de
    ld  a,h
    ld  (de),a
    inc de
    ld  a,h                         ; next scanline: +&800
    add a,8
    ld  h,a
    inc c
    ld  a,c
    and 7
    jr  nz,mv_n
    ld  a,h                         ; ...and -&4000 + 80 across a char row
    sub #40
    ld  h,a
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,0
    ld  h,a
mv_n
    djnz mv_l
    ret


; =====================================================================
;  1.  s_bline -- raster.asm:rq_bline VERBATIM.  The baseline.
;      (nlines) scanlines, (nbytes) bytes each.
; =====================================================================
s_bline
    ld  (spsave),sp
    ld  de,#4C4E
    ld  a,(nbytes)
    srl a
    neg
    add a,MAXP
    ld  (bl_e+1),a
    ld  hl,VPB+VP_BW
    ld  a,(nlines)
    ld  b,a
    ld  c,8
    ld  ix,bl_next
bl_line
    ld  sp,hl
bl_e
    jp  PUSHBLK
bl_next
    ld  a,h
    add a,8
    ld  h,a
    dec c
    jr  z,bl_wrap
bl_cont
    djnz bl_line
    ld  sp,(spsave)
    ret
bl_wrap
    ld  c,8
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  bl_cont

; =====================================================================
;  2.  s_bedge -- the same scanline with the face's TWO END COLUMNS.
;
;  The rightmost byte pair is an explicit PUSH IY in front of the block;
;  the leftmost is the block's PINNED LAST SLOT, also PUSH IY.  The block
;  therefore runs npush-2 PUSH DE, so the run is the SAME LENGTH and the
;  SAME number of pushes as s_bline: any difference in the slope is the
;  DD/FD prefix and nothing else.  The tail is a hard JP, not JP (IX),
;  because IX is no longer a return vector -- there is one block per
;  call site instead.
; =====================================================================
s_bedge
    ld  (spsave),sp
    ld  de,#4C4E
    ld  iy,#4C4C                    ; the mortar pair
    ld  a,(nbytes)
    srl a                           ; npush
    dec a
    dec a                           ; ...of which npush-2 come from the block
    neg
    add a,MAXP-1
    ld  (be_e+1),a
    ld  hl,VPB+VP_BW
    ld  a,(nlines)
    ld  b,a
    ld  c,8
    ld  ix,be_next                  ; IX is still free: ONE mortar word does
be_line                             ; both ends, so the tail stays JP (IX)
    ld  sp,hl
    push iy                         ; the RIGHT end column
be_e
    jp  PUSHBLKE                    ; ...and the block's last slot is the LEFT
be_next
    ld  a,h
    add a,8
    ld  h,a
    dec c
    jr  z,be_wrap
be_cont
    djnz be_line
    ld  sp,(spsave)
    ret
be_wrap
    ld  c,8
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  be_cont

; =====================================================================
;  3.  s_pushiy -- a run made ENTIRELY of PUSH IY, so the per-push cost
;      is a slope and not a difference of differences.
; =====================================================================
s_pushiy
    ld  (spsave),sp
    ld  iy,#4C4E
    ld  a,(nbytes)
    srl a
    neg
    add a,MAXP
    add a,a                         ; 2 bytes of code per push
    ld  (py_e+1),a
    ld  hl,VPB+VP_BW
    ld  a,(nlines)
    ld  b,a
    ld  c,8
    ld  ix,py_next
py_line
    ld  sp,hl
py_e
    jp  PUSHIYBLK
py_next
    ld  a,h
    add a,8
    ld  h,a
    dec c
    jr  z,py_wrap
py_cont
    djnz py_line
    ld  sp,(spsave)
    ret
py_wrap
    ld  c,8
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  py_cont


; =====================================================================
;  4.  s_jorig -- raster.asm:raster_joint's ROW LOOP, as it ships.
;
;  One iteration = one mirrored PAIR: the Bresenham step, the clamp, the
;  span, npush, and then TWO scanlines each of which
;      * indexes VPLINE with the row number doubled,
;      * adds the run's right column,
;      * adds the buffer base,
;      * LD SP,HL, LD IX,continuation, JP into PUSHBLK.
;  Everything through memory, exactly as the shipped code does it.
;  (npairs) iterations.
; =====================================================================
s_jorig
    ld  (spsave),sp
    ld  de,#4C4C                    ; the mortar word
    ld  a,BB
    ld  c,a                         ; C = the leading edge
    ld  (jo_p),a                    ; P = the trailing edge
    ld  hl,-1
    ld  (jo_acc),hl
    ld  a,(npairs)
    ld  (jo_n),a
    ld  b,2*40                      ; upper row index, doubled
jo_loop
    ld  a,c
    ld  (jo_t),a
    ld  hl,(jo_acc)
    ld  a,l
jo_dl
    add a,0
    ld  l,a
    ld  a,h
jo_dh
    adc a,0
    ld  h,a
jo_chk
    bit 7,h
    jr  nz,jo_sd
    ld  a,l
jo_nl
    add a,0
    ld  l,a
    ld  a,h
jo_nh
    adc a,0
    ld  h,a
jo_dir
    dec c
    jr  jo_chk
jo_sd
    ld  (jo_acc),hl
    ld  a,c
    cp  BB
    jr  c,jo_cok
    ld  c,BB
jo_cok
    ld  a,(jo_p)                    ; walking left: the right end is P
    ld  (jo_r),a
    sub c
    jr  nz,jo_w1
    inc a
jo_w1
    inc a
    srl a
    neg
    add a,MAXP
    ld  (jo_eu+1),a
    ld  (jo_el+1),a
    ; --- the scanline ABOVE the horizon
    ld  h,VPLINE/256
    ld  l,b
    ld  a,(hl)
    inc l
    ld  h,(hl)
    ld  l,a
    ld  a,(jo_r)
    add a,l
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    ld  sp,hl
    ld  ix,jo_ubk
jo_eu
    jp  PUSHBLK
jo_ubk
    ; --- and its mirror BELOW
    ld  h,VPLINE/256
    ld  a,(VP_H*2)&255
    sub b
    ld  l,a
    ld  a,(hl)
    inc l
    ld  h,(hl)
    ld  l,a
    ld  a,(jo_r)
    add a,l
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    ld  sp,hl
    ld  ix,jo_lbk
jo_el
    jp  PUSHBLK
jo_lbk
    ld  a,(jo_t)
    ld  (jo_p),a
    ld  a,b
    sub 2
    ld  b,a
    ld  hl,jo_n
    dec (hl)
    jp  nz,jo_loop
    ld  sp,(spsave)
    ret


; =====================================================================
;  5.  s_jfold -- THE FOLDED JOINT.  Same geometry, same pixels, but
;
;    * the Bresenham accumulator lives in DE for the whole pass instead
;      of being LD HL,(nn) / LD (nn),HL round every row;
;    * the UPPER row's screen pointer lives in HL and the LOWER row's in
;      HL', so the pair costs one EXX and two -&800 / +&800 steps
;      instead of two VPLINE lookups;
;    * the character-row countdowns live in IXL and IXH;
;    * the mortar blocks have HARD-WIRED tails, so there is no LD IX,nn
;      per scanline;
;    * the run's right column is patched into the two ADD A,n that build
;      the address, once per pair rather than read from memory twice.
;
;  The joint is drawn as its own short run ON TOP of the face, which
;  raster_quad has already filled -- the same overdraw raster_joint does.
;  (npairs) iterations.
; =====================================================================
s_jfold
    xor a
    ld  (jf_dl+1),a                 ; step 0: the accumulator never reaches
    ld  (jf_dh+1),a                 ; zero, so the edge never moves
    jr  jf_go
s_jfold1
    ld  a,48                        ; +48 a row against -N = -48: exactly one
    ld  (jf_dl+1),a                 ; edge step per row.  -N MUST be patched
    xor a                           ; too -- left at zero the step loop never
    ld  (jf_dh+1),a                 ; drives the accumulator negative again
    ld  a,(256-48)&255              ; and spins for ever.
    ld  (jf_nl+1),a
    ld  a,#FF
    ld  (jf_nh+1),a
jf_go
    ld  (spsave),sp
    ld  iy,#4C4C                    ; the mortar word
    ld  de,-1                       ; the accumulator
    ld  b,BB                        ; B = P, the trailing edge
    ld  c,BB                        ; C = the leading edge
    ld  a,(npairs)
    ld  (jf_n),a
    ; The two bases must be REAL viewport rows and the countdowns must
    ; match them, or the pointers walk out of the buffer.  Row 47 upward
    ; (offset 7*&800 + 5*80, and 47&7 = 7, so eight steps to the wrap) and
    ; row 48 downward (offset 0 + 6*80, 48&7 = 0, eight steps likewise).
    ld  hl,VPB+7*#800+5*SCR_W
    exx
    ld  hl,VPB+6*SCR_W
    exx
    ld  a,8
    ld  ixl,a                       ; scanlines left in the upper char row
    ld  ixh,a                       ; ...and in the lower one
jf_loop
    ; ---- one Bresenham step on DE
    ld  a,e
jf_dl
    add a,48
    ld  e,a
    ld  a,d
jf_dh
    adc a,0
    ld  d,a
jf_chk
    bit 7,d
    jr  nz,jf_sd
    ld  a,e
jf_nl
    add a,0
    ld  e,a
    ld  a,d
jf_nh
    adc a,0
    ld  d,a
jf_dir
    dec c
    jr  jf_chk
jf_sd
    ; ---- clamp the leading edge to the tall end
    ld  a,c
    cp  BB+1
    jr  c,jf_cok
    ld  c,BB
jf_cok
    ; ---- the span.  Walking left, so the right end is the TRAILING edge.
    ld  a,b
    ld  (jf_au+1),a                 ; patch the two address adds...
    ld  (jf_al+1),a
    neg
    ld  (jf_bu+1),a                 ; ...and the two that undo them
    ld  (jf_bl+1),a
    ld  a,b
    sub c
    jr  nz,jf_w1
    inc a
jf_w1
    inc a
    srl a                           ; npush
    add a,a                         ; 2 bytes of code per PUSH IY
    neg
    add a,2*JM
    ld  (jf_eu+1),a
    ld  (jf_el+1),a
    ld  b,c                         ; P := C
    ; ---- the scanline ABOVE the horizon
    ld  a,l
jf_au
    add a,0
    ld  l,a
    jr  nc,jf_au2
    inc h
jf_au2
    ld  sp,hl
jf_eu
    jp  JMBLKU
jf_ubk
    ld  a,l
jf_bu
    add a,0
    ld  l,a
    jr  nc,jf_bu2
    dec h
jf_bu2
    ld  a,h                         ; up one scanline
    sub 8
    ld  h,a
    dec ixl
    jr  z,jf_uwrap
jf_ucont
    ; ---- and its mirror BELOW
    exx
    ld  a,l
jf_al
    add a,0
    ld  l,a
    jr  nc,jf_al2
    inc h
jf_al2
    ld  sp,hl
jf_el
    jp  JMBLKL
jf_lbk
    ld  a,l
jf_bl
    add a,0
    ld  l,a
    jr  nc,jf_bl2
    dec h
jf_bl2
    ld  a,h                         ; down one scanline
    add a,8
    ld  h,a
    dec ixh
    jr  z,jf_lwrap
jf_lcont
    exx
    ld  a,(jf_n)
    dec a
    ld  (jf_n),a
    jp  nz,jf_loop
    ld  sp,(spsave)
    ret
jf_uwrap
    ld  a,8
    ld  ixl,a
    ld  a,l
    sub SCR_W
    ld  l,a
    ld  a,h
    sbc a,#C0
    ld  h,a
    jr  jf_ucont
jf_lwrap
    ld  a,8
    ld  ixh,a
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  jf_lcont


; =====================================================================
;  6.  s_jmath -- the SPAN ARITHMETIC ALONE.  Same instructions as
;      s_jfold's head, no addresses, no pushes, no screen.  This is the
;      floor under any folding whatever: it is what one joint row pair
;      costs before a single pixel is placed.
; =====================================================================
s_jmath
    ld  de,-1
    ld  b,BB
    ld  c,BB
    ld  a,(npairs)
    ld  (jn_n),a
jn_loop
    ld  a,e
jn_dl
    add a,0                         ; step 0, to match s_jfold's 0-step case
    ld  e,a
    ld  a,d
jn_dh
    adc a,0
    ld  d,a
jn_chk
    bit 7,d
    jr  nz,jn_sd
    ld  a,e
jn_nl
    add a,#FF
    ld  e,a
    ld  a,d
jn_nh
    adc a,#FF
    ld  d,a
jn_dir
    dec c
    jr  jn_chk
jn_sd
    ld  a,c
    cp  BB+1
    jr  c,jn_cok
    ld  c,BB
jn_cok
    ld  a,b
    ld  (jn_au+1),a
    ld  (jn_al+1),a
    neg
    ld  (jn_bu+1),a
    ld  (jn_bl+1),a
    ld  a,b
    sub c
    jr  nz,jn_w1
    inc a
jn_w1
    inc a
    srl a
    add a,a
    neg
    add a,2*JM
    ld  (jn_eu+1),a
    ld  (jn_el+1),a
    ld  b,c
    ld  a,(jn_n)
    dec a
    ld  (jn_n),a
    jp  nz,jn_loop
    ret
jn_au   db 0,0
jn_al   db 0,0
jn_bu   db 0,0
jn_bl   db 0,0
jn_eu   db 0,0
jn_el   db 0,0
jn_n    db 0


; =====================================================================
;  7.  s_jtrue -- THE JOINT FOLDED ALL THE WAY IN, which is the thing
;      vpcfg.inc's note asks for: drawn from INSIDE the body scanline
;      loop, on the row raster_quad has just filled, with HL already the
;      screen address and no VPLINE lookup, no row stepping of its own
;      and no second screen pointer.  The joint state lives in the
;      ALTERNATE set, so entering and leaving it is two EXX.
;
;      IT IS PER SCANLINE, NOT PER PAIR.  The body loop walks rows
;      top to bottom, not outward from the horizon in mirrored pairs, so
;      the row RC-j and the row RC+j are visited at different times and
;      the span arithmetic has to be done TWICE.  That is the whole
;      trade this subject exists to price: an address saved, an
;      arithmetic paid twice.
; =====================================================================
s_jtrue
    ld  (spsave),sp
    ld  de,#4C4E
    ld  iy,#4C4C
    ld  a,(nbytes)
    srl a
    neg
    add a,MAXP
    ld  (jt_e+1),a
    ld  hl,VPB+VP_BW
    ld  a,(nlines)
    ld  b,a
    ld  c,8
    ld  ix,jt_next
    exx
    ld  de,-1                       ; the accumulator
    ld  b,BB                        ; P, the trailing edge
    ld  c,BB                        ; the leading edge
    exx
jt_line
    ld  sp,hl
jt_e
    jp  PUSHBLK                     ; the face's own run, as today
jt_next
    exx
    ld  a,e
jt_dl
    add a,0
    ld  e,a
    ld  a,d
jt_dh
    adc a,0
    ld  d,a
jt_chk
    bit 7,d
    jr  nz,jt_sd
    ld  a,e
jt_nl
    add a,#FF
    ld  e,a
    ld  a,d
jt_nh
    adc a,#FF
    ld  d,a
jt_dir
    dec c
    jr  jt_chk
jt_sd
    ld  a,c
    cp  BB+1
    jr  c,jt_cok
    ld  c,BB
jt_cok
    ld  a,VP_BW                     ; delta = the face's right column minus
    sub b                           ; the joint run's, both in bytes
    ld  (jt_ad+1),a
    ld  (jt_sb+1),a
    ld  a,b
    sub c
    jr  nz,jt_w1
    inc a
jt_w1
    inc a
    srl a
    add a,a
    neg
    add a,2*JM
    ld  (jt_je+1),a
    ld  b,c
    exx
    ld  a,l                         ; HL is ALREADY this row's address
jt_ad
    sub 0
    ld  l,a
    jr  nc,jt_ad2
    dec h
jt_ad2
    ld  sp,hl
jt_je
    jp  JMBLKT
jt_jbk
    ld  a,l
jt_sb
    add a,0
    ld  l,a
    jr  nc,jt_sb2
    inc h
jt_sb2
    ld  a,h
    add a,8
    ld  h,a
    dec c
    jr  z,jt_wrap
jt_cont
    djnz jt_line
    ld  sp,(spsave)
    ret
jt_wrap
    ld  c,8
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  jt_cont


; =====================================================================
;  THE PAGE-ALIGNED BLOCKS
; =====================================================================
    align 256
PUSHBLK
    repeat MAXP
    push de
    rend
    jp  (ix)

    align 256
PUSHBLKE
    repeat MAXP-1
    push de
    rend
    push iy                         ; the PINNED slot: the LEFT end column
    jp  (ix)

    align 256
PUSHIYBLK
    repeat MAXP
    push iy
    rend
    jp  (ix)

    align 256
JMBLKU
    repeat JM
    push iy
    rend
    jp  jf_ubk

    align 256
JMBLKL
    repeat JM
    push iy
    rend
    jp  jf_lbk

    align 256
JMBLKT
    repeat JM
    push iy
    rend
    jp  jt_jbk

; =====================================================================
    align 256
counter dw  0
nbytes  db  44
nlines  db  32
npairs  db  16
spsave  dw  0
jo_acc  dw  0
jo_p    db  0
jo_t    db  0
jo_r    db  0
jo_n    db  0
jf_n    db  0
