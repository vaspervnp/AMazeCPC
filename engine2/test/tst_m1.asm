; =====================================================================
;  engine2/test/tst_m1.asm -- WHAT DOES A *TEXTURED* SPAN COST?
;
;  tst_byte.asm answered "how many microseconds to place a screen byte".
;  This one answers the question that decides whether the C64 block-
;  texture reference is reachable at all: a span renderer can only carry
;  an arbitrary (foreshortened) horizontal pattern by BAKING it into the
;  fill code as immediates -- `ld de,nn : push de`, 3.500 us/byte, item
;  #3 of tst_byte.  That is +1.5 us on every painted byte, and it is only
;  half the bill.  The other half is GENERATING the immediates, and
;  nobody has priced it.
;
;  So the subjects here are the three pieces of the per-FACE setup:
;
;     patchimm   fill the unrolled block's immediates with one constant
;                (the stone word) -- unrolled `ld (nn),hl`
;     patchpop   fill them from a linear buffer -- `pop hl : ld (nn),hl`
;     joint      poke ONE vertical mortar pixel into one immediate:
;                read-modify-write with an address and a mask pair taken
;                off the stack (`pop de : pop bc : ld a,(de) : and c :
;                or b : ld (de),a`)
;
;  plus two whole-face controls that differ ONLY in the fill block --
;
;     faceflat   96 body scanlines x 44 bytes through PUSHBLK   (today)
;     facetex    the same 96 x 44 through PUSHIMM, patch included
;
;  -- so the difference between them is the whole price of a textured
;  wall face, measured rather than added up.
;
;  And one thing that might make the price go away:
;
;     push12     push de : push bc : push hl : exx : (again) : exx
;                -- SIX pattern words = 12 screen bytes of ARBITRARY
;                pattern per repeat, no reload.  If a face's mortar
;                spacing were periodic over 12 bytes this would cost
;                almost nothing.  It is not; the number is here to say
;                by how much it is not.
;
;  Memory:   #8000-       this harness
;            #7FF0        stack
;            #7200        SRC   256-byte linear source buffer
;            #7400        JTAB  joint records: addr-lo addr-hi and or
;            #C000        the screen buffer being written
; =====================================================================

STACK   equ #7FF0
SRC     equ #7200
JTAB    equ #7400
TTAB    equ #7600                   ; 3 pages: t for p = 1, 2, 3 vs R
SCR     equ #C000
VP_BX   equ 18
VP_BW   equ 44
VPB     equ SCR+VP_BX
SCR_W   equ 80
MAXW    equ 22                      ; VP_BW/2 -- one PUSH is two bytes
MAXJ    equ 16                      ; most vertical joints on one face
MAXP12  equ 8                       ; 8 x 12 = 96 bytes, > VP_BW

    org #8000

    di
    jp  e_nop
    di
    jp  e_empty
    di
    jp  e_patchimm
    di
    jp  e_patchpop
    di
    jp  e_joint
    di
    jp  e_push12
    di
    jp  e_pushimm
    di
    jp  e_faceflat
    di
    jp  e_facetex
    di
    jp  e_jcol
    di
    jp  e_jcol2

; ---------------------------------------------------------------------
romoff
    ld  bc,#7F8C                    ; mode 0, both ROMs disabled.  The MODE
    out (c),c                       ; BITS DO NOT MOVE ANY OF THESE NUMBERS
    ret                             ; -- see the note at the foot of the file.

s_null
    ret

; =====================================================================
;  THE COUNTING LOOPS
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

e_patchimm
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
epa_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_patchimm
    jp  epa_l

e_patchpop
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
epp_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_patchpop
    jp  epp_l

e_joint
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ej_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_joint
    jp  ej_l

e_push12
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
e12_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_push12
    jp  e12_l

e_pushimm
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
epi_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_pushimm
    jp  epi_l

e_faceflat
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
eff_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_faceflat
    jp  eff_l

e_facetex
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
eft_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_facetex
    jp  eft_l

e_jcol
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ejc_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_jcol
    jp  ejc_l

e_jcol2
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ej2_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_jcol2
    jp  ej2_l


; =====================================================================
;  THE SUBJECTS
; =====================================================================

; ---------------------------------------------------------------------
;  s_patchimm -- write the STONE word into the last (nwords) immediates
;  of PUSHIMM.  Unrolled, entered at (MAXW-nwords)*3, so it patches
;  exactly the entries a run of that length will execute.
; ---------------------------------------------------------------------
s_patchimm
    ld  a,(nwords)
    neg
    add a,MAXW
    ld  b,a
    add a,a
    add a,b                         ; *3: one LD (nn),HL is three bytes
    ld  (pa_e+1),a
    ld  hl,#4C4E
    ld  ix,pa_done
pa_e
    jp  PATCHBLK
pa_done
    ret

; ---------------------------------------------------------------------
;  s_patchpop -- the same immediates, but each word comes from a linear
;  buffer through SP.  This is what a per-face pattern GENERATOR would
;  feed, and it is tst_byte's item #5 with the store sites pointing at
;  code instead of screen.
; ---------------------------------------------------------------------
s_patchpop
    ld  (spsave),sp
    ld  a,(nwords)
    neg
    add a,MAXW
    add a,a
    add a,a                         ; *4: POP HL + LD (nn),HL
    ld  (pp_e+1),a
    ld  ix,pp_done
    ld  sp,SRC
pp_e
    jp  POPPATCH
pp_done
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_joint -- (njoint) vertical mortar pixels poked into the immediate
;  array.  A mortar line is ONE pixel wide, which is half a byte in mode
;  0 and a QUARTER of one in mode 1, so it cannot be written: it has to
;  be merged.  Address and the AND/OR mask pair come off the stack, which
;  is the cheapest way to feed three 16-bit operands per site.
; ---------------------------------------------------------------------
s_joint
    ld  (spsave),sp
    ld  a,(njoint)
    neg
    add a,MAXJ
    ld  b,a
    add a,a
    add a,a
    add a,a
    sub b
    sub b                           ; *6
    ld  (jo_e+1),a
    ld  ix,jo_done
    ld  sp,JTAB
jo_e
    jp  JOINTBLK
jo_done
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_push12 -- (nunit) repeats of a SIX-WORD pattern: three registers,
;  EXX, three more, EXX back.  12 screen bytes per repeat with no reload
;  at all.  (nunit)*12 bytes on ONE scanline; the driver takes the slope.
; ---------------------------------------------------------------------
s_push12
    ld  (spsave),sp
    ld  a,(nunit)
    neg
    add a,MAXP12
    add a,a
    add a,a
    add a,a                         ; *8 bytes of code per repeat
    ld  (p12_e+1),a
    ld  de,#4C4E
    ld  bc,#4E4C
    ld  hl,#4C4C
    exx
    ld  de,#4E4E
    ld  bc,#4C4E
    ld  hl,#4E4C
    exx
    ld  ix,p12_done
    ld  sp,VPB+VP_BW+56             ; room for MAXP12*12 bytes to the left
p12_e
    jp  PUSH12BLK
p12_done
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_pushimm -- the control: LD DE,nn / PUSH DE across (nbytes), for
;  (nlines) scanlines, in raster.asm's exact rq_bline shape.  Must
;  reproduce tst_byte's 3.500 us/byte.
; ---------------------------------------------------------------------
s_pushimm
    ld  (spsave),sp
    ld  a,(nbytes)
    srl a
    neg
    add a,MAXW
    add a,a
    add a,a                         ; 4 bytes of code per word
    ld  (pi_e+1),a
    ld  hl,VPB+VP_BW
    ld  ix,pi_next
    ld  a,(nlines)
    ld  b,a
    ld  c,8
pi_line
    ld  sp,hl
pi_e
    jp  PUSHIMM
pi_next
    ld  a,h
    add a,8
    ld  h,a
    dec c
    jr  z,pi_wrap
pi_cont
    djnz pi_line
    ld  sp,(spsave)
    ret
pi_wrap
    ld  c,8
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  pi_cont

; ---------------------------------------------------------------------
;  s_faceflat -- a whole wall-face BODY the way raster.asm draws one
;  today: (nlines) scanlines, (nbytes) wide, one flat fill word, through
;  the page-aligned PUSH DE block.
; ---------------------------------------------------------------------
s_faceflat
    ld  (spsave),sp
    ld  de,#4C4E
    ld  a,(nbytes)
    srl a
    neg
    add a,MAXW
    ld  (ff_e+1),a
    ld  hl,VPB+VP_BW
    ld  ix,ff_next
    ld  a,(nlines)
    ld  b,a
    ld  c,8
ff_line
    ld  sp,hl
ff_e
    jp  PUSHBLK
ff_next
    ld  a,h
    add a,8
    ld  h,a
    dec c
    jr  z,ff_wrap
ff_cont
    djnz ff_line
    ld  sp,(spsave)
    ret
ff_wrap
    ld  c,8
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  ff_cont

; ---------------------------------------------------------------------
;  s_facetex -- THE SAME FACE, textured.  One patch of the immediates
;  (stone word, then (njoint) mortar pixels merged in), then the same
;  (nlines) scanlines through PUSHIMM.  Everything else -- the address
;  walk, the character-row wrap, the entry arithmetic -- is byte for
;  byte what s_faceflat does, so the difference between the two is the
;  texture and nothing else.
; ---------------------------------------------------------------------
s_facetex
    call s_patchimm
    call s_joint
    jp   s_pushimm

; ---------------------------------------------------------------------
;  s_jcol -- WHERE DO THE VERTICAL MORTAR LINES GO?  This is the one
;  piece of the reference picture that cannot be got for nothing.
;
;  The horizontal course joints are free to derive: at a fixed screen x
;  the projection of wall height is LINEAR, so raster_joint interpolates
;  them straight (see rastermodel.py's COURSE JOINTS note).  The VERTICAL
;  ones are the other axis and they are projective.  With hh proportional
;  to 1/z -- which it is, that is what a half-height IS -- the screen x of
;  the wall parameter u = p/Q is
;
;      t = p*wa / ( p*wa + (Q-p)*wb ),      x = xa + t*(xb - xa)
;
;  where wa, wb are the quad record's OWN hlo and hhi.  So no
;  re-projection and no new march: one divide and one multiply per joint,
;  off six bytes the rasteriser is already holding.  For Q = 4 the
;  multiplies by p and Q-p are 1, 2, 3 -- add chains, not multiplies.
;
;  Everything here is shift-and-add, no tables: this is the ONE-SIDED
;  UPPER BOUND, in the same spirit as every other constant in this
;  project.  A table-driven reciprocal would beat it and the number below
;  says by how much it would have to.
;
;  (njoint) joints for ONE face, ending in the same read-modify-write
;  s_joint measures on its own.
; ---------------------------------------------------------------------
s_jcol
    ld  a,1
    ld  (jc_p),a
jc_loop
    ; --- HL = p*wa, by adds ---
    ld  hl,(jc_wa)
    ld  d,h
    ld  e,l
    ld  a,(jc_p)
    dec a
    jr  z,jc_n1
jc_add1
    add hl,de
    dec a
    jr  nz,jc_add1
jc_n1
    push hl                         ; N = p*wa
    ; --- HL = (Q-p)*wb, by adds ---
    ld  hl,(jc_wb)
    ld  d,h
    ld  e,l
    ld  a,4
    ld  b,a
    ld  a,(jc_p)
    ld  c,a
    ld  a,b
    sub c
    dec a
    jr  z,jc_n2
jc_add2
    add hl,de
    dec a
    jr  nz,jc_add2
jc_n2
    pop de                          ; DE = N
    push de
    add hl,de                       ; HL = S = N + (Q-p)*wb
    pop de
    ; --- normalise N and S together until S fits in a byte ---
jc_norm
    ld  a,h
    or  a
    jr  z,jc_normd
    srl h
    rr  l
    srl d
    rr  e
    jr  jc_norm
jc_normd
    ld  c,l                         ; C = S, 1..255
    ld  h,e                         ; HL = N*256
    ld  l,0
    ld  b,8
jc_div                              ; t = N*256/S, 8 bits
    add hl,hl
    ld  a,h
    sub c
    jr  c,jc_dnc
    ld  h,a
    inc l
jc_dnc
    djnz jc_div
    ld  a,l
    ld  (jc_t),a
    ; --- x = xa + ((xb-xa) * t) >> 8 ---
    ld  a,(jc_xd)
    ld  e,a
    ld  d,0
    ld  hl,0
    ld  a,(jc_t)
    ld  b,8
jc_mul
    add hl,hl
    rlca
    jr  nc,jc_mnc
    add hl,de
jc_mnc
    djnz jc_mul
    ld  a,(jc_xa)
    add a,h                         ; A = x, in QUARTER-byte units (mode 1
                                    ; pixels): 0..VP_BW*4-1
    ; --- x -> which immediate, which byte of it, which pixel of that ---
    ld  e,a
    and 3
    ld  c,a                         ; pixel within the byte
    ld  a,e
    rrca
    rrca
    and #3F                         ; byte column
    ld  e,a
    and 1
    ld  d,a                         ; low/high byte of the PUSHed word
    ld  a,e
    srl a
    add a,a
    add a,a                         ; 4 bytes of code per word
    add a,d
    inc a                           ; ...past the LD DE opcode
    ld  l,a
    ld  h,PUSHIMM/256
    ; --- the AND/OR pair for that pixel ---
    ld  a,c
    add a,a
    ld  e,a
    ld  d,0
    push hl
    ld  hl,JMASK
    add hl,de
    ld  c,(hl)
    inc hl
    ld  b,(hl)
    pop hl
    ; --- merge the mortar pixel into the immediate ---
    ld  a,(hl)
    and c
    or  b
    ld  (hl),a
    ; --- next joint ---
    ld  a,(jc_p)
    inc a
    ld  (jc_p),a
    ld  b,a
    ld  a,(njoint)
    cp  b
    jp  nc,jc_loop
    ret

JMASK                               ; AND, OR per mode-1 pixel of a byte
    db  #77,#88
    db  #BB,#44
    db  #DD,#22
    db  #EE,#11

; ---------------------------------------------------------------------
;  s_jcol2 -- THE SAME ANSWER WITH THE TABLES THIS ENGINE ALREADY KEEPS
;  A WHOLE BANK FOR.
;
;  The expensive thing in s_jcol is that it solves the projective
;  division ONCE PER JOINT.  It does not have to.  t depends only on the
;  RATIO of the two half heights:
;
;      t_p = p / ( p + (Q-p) * (wb/wa) )
;
;  so ONE divide per FACE produces R = 256*min(wa,wb)/max(wa,wb), and each
;  joint is then a single table read -- three 256-byte tables for Q = 4,
;  one per p, and the wb > wa case is the mirror t_p = 1 - t_(Q-p), so R
;  never leaves 0..255 and no fourth table is needed.
;
;  What is left per joint is the interpolation x = xa + t*(xb-xa), and
;  that is an 8x8 multiply -- unrolled, no loop control, since only the
;  high byte is wanted.
;
;  The per-FACE divide is the intercept and the per-JOINT work is the
;  slope, so timing at njoint 1 and 3 separates them.
; ---------------------------------------------------------------------
s_jcol2
    ; ---- ONCE PER FACE: R = 256*min/max, MIRROR = wb > wa -------------
    ld  hl,(jc_wa)
    ld  de,(jc_wb)
    xor a
    ld  (jc_mir),a
    ld  a,h
    cp  d
    jr  nz,jc2_c1
    ld  a,l
    cp  e
jc2_c1
    jr  nc,jc2_ord
    ex  de,hl                       ; HL = max, DE = min
    ld  a,1
    ld  (jc_mir),a
jc2_ord
jc2_norm
    ld  a,h
    or  a
    jr  z,jc2_nd
    srl h
    rr  l
    srl d
    rr  e
    jr  jc2_norm
jc2_nd
    ld  c,l                         ; C = max, 1..255
    ld  h,e                         ; HL = min*256
    ld  l,0
    ld  b,8
jc2_div
    add hl,hl
    ld  a,h
    sub c
    jr  c,jc2_dnc
    ld  h,a
    inc l
jc2_dnc
    djnz jc2_div
    ld  a,l
    ld  (jc_r),a                    ; R, the whole face's geometry

    ; ---- PER JOINT ---------------------------------------------------
    ld  a,1
    ld  (jc_p),a
jc2_loop
    ; t = TTAB[p][R], mirrored to TTAB[Q-p][R] complemented
    ld  a,(jc_p)
    ld  b,a
    ld  a,(jc_mir)
    or  a
    jr  z,jc2_nomir
    ld  a,4
    sub b
    ld  b,a
jc2_nomir
    ld  a,b
    dec a
    add a,TTAB/256                  ; one page per p
    ld  h,a
    ld  a,(jc_r)
    ld  l,a
    ld  a,(hl)
    ld  b,a
    ld  a,(jc_mir)
    or  a
    ld  a,b
    jr  z,jc2_t
    neg                             ; 256 - t
jc2_t
    ; --- x = xa + ((xb-xa)*t)>>8, unrolled: only the high byte is wanted
    ld  (jc_t),a
    ld  a,(jc_xd)
    ld  e,a
    ld  d,0                         ; DE = xb - xa
    ld  hl,0
    ld  a,(jc_t)
    repeat 8
    add hl,hl
    rlca
    jr  nc,$+3
    add hl,de
    rend
    ld  a,(jc_xa)
    add a,h
    ; --- x -> immediate, byte, pixel: the same tail s_jcol has ---------
    ld  e,a
    and 3
    ld  c,a
    ld  a,e
    rrca
    rrca
    and #3F
    ld  e,a
    and 1
    ld  d,a
    ld  a,e
    srl a
    add a,a
    add a,a
    add a,d
    inc a
    ld  l,a
    ld  h,PUSHIMM/256
    ld  a,c
    add a,a
    ld  e,a
    ld  d,0
    push hl
    ld  hl,JMASK
    add hl,de
    ld  c,(hl)
    inc hl
    ld  b,(hl)
    pop hl
    ld  a,(hl)
    and c
    or  b
    ld  (hl),a
    ld  a,(jc_p)
    inc a
    ld  (jc_p),a
    ld  b,a
    ld  a,(njoint)
    cp  b
    jp  nc,jc2_loop
    ret


; =====================================================================
;  THE UNROLLED BLOCKS
; =====================================================================

    align 256
PUSHBLK
    repeat MAXW
    push de
    rend
    jp  (ix)

    align 256
PUSHIMM
piw = #4C4E
    repeat MAXW
    ld  de,piw
    push de
piw = piw + #0101
    rend
    jp  (ix)

    align 256
PATCHBLK
pai = 0
    repeat MAXW
    ld  (PUSHIMM+4*pai+1),hl
pai = pai + 1
    rend
    jp  (ix)

    align 256
POPPATCH
ppi = 0
    repeat MAXW
    pop hl
    ld  (PUSHIMM+4*ppi+1),hl
ppi = ppi + 1
    rend
    jp  (ix)

    align 256
JOINTBLK
    repeat MAXJ
    pop de                          ; the immediate's address
    pop bc                          ; C = AND mask, B = OR mask
    ld  a,(de)
    and c
    or  b
    ld  (de),a
    rend
    jp  (ix)

    align 256
PUSH12BLK
    repeat MAXP12
    push de
    push bc
    push hl
    exx
    push de
    push bc
    push hl
    exx
    rend
    jp  (ix)

; =====================================================================
;  WHY THE MODE BITS ARE NOT A VARIABLE HERE
;
;  Every number this file produces is a Z80 instruction timing into RAM.
;  The gate array's mode bits change how the CRTC's fetched bytes are
;  DECODED into pixels; they do not change the number of bytes on a
;  scanline (80 in every mode), the screen's address interleave, or the
;  cost of any instruction.  So mode 1 costs exactly what mode 0 costs
;  per BYTE -- and buys twice the pixels for it.  Running the harness at
;  #7F8D instead of #7F8C would produce the same table with a scrambled
;  picture, which is why it is not parameterised.
; =====================================================================

    align 256
counter dw  0
nbytes  db  44
nlines  db  96
nwords  db  22
njoint  db  4
nunit   db  8
spsave  dw  0
jc_wa   dw  6144                    ; the near end's half height (projmodel
jc_wb   dw  768                     ; HTAB's ceiling) against a far end --
jc_xa   db  0                       ; the most oblique face there is
jc_xd   db  175                     ; xb - xa, quarter-byte units
jc_p    db  0
jc_t    db  0
jc_r    db  0
jc_mir  db  0
