; =====================================================================
;  engine2/test/tst_byte.asm -- WHAT DOES A SCREEN BYTE COST?
;
;  Nothing here is part of the game.  This is a pure instruction-cost
;  harness for the ONE question every textured-renderer architecture
;  hangs on: how many microseconds to place a screen byte when you
;  cannot use PUSH DE.
;
;  Every subject is a CALLed routine.  The driver (engine2/tools/
;  emu_byte.py) runs each entry inside an identical counting loop and
;  takes the SLOPE across two byte counts, so the loop, the call/ret,
;  and all per-run setup cancel exactly.
;
;  Memory:   #8000-       this harness
;            #7FF0        stack
;            #7000        TEX   256-byte texture page (page aligned)
;            #7200        SRC   256-byte linear source buffer
;            #C000        the screen buffer being written
; =====================================================================

STACK   equ #7FF0
TEX     equ #7000
SRC     equ #7200
POKETAB equ #7400                   ; addr-lo, addr-hi, colour triples
SCR     equ #C000
VP_BX   equ 18
VP_BW   equ 44
VPB     equ SCR+VP_BX               ; viewport line 0, left byte
MAXB    equ 44                      ; longest run any block can do, BYTES
SCR_W   equ 80

    org #8000

    di
    jp  e_nop
    di
    jp  e_empty
    di
    jp  e_push
    di
    jp  e_across
    di
    jp  e_ldi
    di
    jp  e_ldir
    di
    jp  e_popst
    di
    jp  e_rowcopy
    di
    jp  e_dnaive
    di
    jp  e_dunroll
    di
    jp  e_dfull
    di
    jp  e_tex
    di
    jp  e_texpop
    di
    jp  e_texbc
    di
    jp  e_mortar
    di
    jp  e_push2
    di
    jp  e_pushimm
    di
    jp  e_colpush
    di
    jp  e_colimm
    di
    jp  e_colpair
    di
    jp  e_colrun

; ---------------------------------------------------------------------
romoff
    ld  bc,#7F8C                    ; mode 0, both ROMs disabled
    out (c),c
    ret

s_null
    ret

; =====================================================================
;  THE COUNTING LOOPS.  One per entry; each is byte-identical apart
;  from the CALL target and the register setup in front of it.
; =====================================================================

; --- calibration: 100 NOPs must come out at exactly 100.0 us ----------
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

; --- the empty control ------------------------------------------------
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

; --- 1. PUSH DE across a scanline, raster.asm's exact shape -----------
e_push
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ep_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_push
    jp  ep_l

; --- 2. LD (HL),A / INC L across a scanline ---------------------------
e_across
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ea_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_across
    jp  ea_l

; --- 3. unrolled LDI across a scanline --------------------------------
e_ldi
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
el_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_ldi
    jp  el_l

; --- 4. LDIR across a scanline ----------------------------------------
e_ldir
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
er_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_ldir
    jp  er_l

; --- 5. POP HL / LD (nn),HL, addresses baked into the code ------------
e_popst
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
eps_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_popst
    jp  eps_l

; --- 6. LD A,(BC) / INC C / LD (HL),A / INC L across -----------------
e_rowcopy
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
erc_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_rowcopy
    jp  erc_l

; --- 7. LD (HL),A DOWN a column, naive per-line wrap test ------------
e_dnaive
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
edn_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_dnaive
    jp  edn_l

; --- 8. LD (HL),A DOWN a column, unrolled 8, wrap hoisted ------------
e_dunroll
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
edu_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_dunroll
    jp  edu_l

; --- 9. the same, fully unrolled, no counter at all -------------------
e_dfull
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
edf_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_dfull
    jp  edf_l

; --- 10. textured strip, 16-bit fractional step, down the interleave --
e_tex
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
et_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_tex
    jp  et_l

; --- 11. precomputed column, POP-fed, down the interleave -------------
e_texpop
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
etp_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_texpop
    jp  etp_l

; --- 12. precomputed column, LD A,(BC) fed ----------------------------
e_texbc
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
etb_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_texbc
    jp  etb_l

; --- 13. scattered mortar pokes: address AND colour from a table ------
e_mortar
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
em_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_mortar
    jp  em_l


; --- 14. PUSH DE / PUSH BC alternating: a 4-byte repeating pattern ----
e_push2
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ep2_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_push2
    jp  ep2_l

; --- 15. LD DE,nn / PUSH DE: an ARBITRARY pattern baked into code -----
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


; --- 16. PUSH DE DOWN a two-byte-wide column strip, constant colour ---
e_colpush
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ecp_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_colpush
    jp  ecp_l

; --- 19. TEXTURED column PAIR: one sample feeds both screen bytes -----
e_colpair
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ecq_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_colpair
    jp  ecq_l

; --- 20. the same, sampled once per TWO scanlines (2x magnified) ------
e_colrun
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
ecr_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_colrun
    jp  ecr_l

; --- 17. the same with the two bytes RELOADED per scanline ------------
e_colimm
    ld  sp,STACK
    call romoff
    ld  hl,0
    ld  (counter),hl
eci_l
    ld  hl,(counter)
    inc hl
    ld  (counter),hl
    call s_colimm
    jp  eci_l


; =====================================================================
;  THE SUBJECTS
; =====================================================================

; ---------------------------------------------------------------------
;  s_push -- (nlines) scanlines of (nbytes) bytes, PUSH DE.
;  This is rq_bline verbatim, including the character-row wrap.
; ---------------------------------------------------------------------
s_push
    ld  (spsave),sp
    ld  de,#4C4E                    ; a fill word with the vertical grain
    ld  a,(nbytes)
    srl a                           ; npush = bytes/2
    neg
    add a,MAXB/2
    ld  (sp_e+1),a
    ld  hl,VPB+VP_BW                ; one past the right end of line 0
    ld  a,(nlines)
    ld  b,a
    ld  c,8
    ld  ix,sp_next
sp_line
    ld  sp,hl
sp_e
    jp  PUSHBLK
sp_next
    ld  a,h
    add a,8
    ld  h,a
    dec c
    jr  z,sp_wrap
sp_cont
    djnz sp_line
    ld  sp,(spsave)
    ret
sp_wrap
    ld  c,8
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  sp_cont

; ---------------------------------------------------------------------
;  s_push2 -- the same, but the block alternates PUSH DE and PUSH BC, so
;  the run carries a 4-byte (8 Mode 0 pixel) repeating pattern.  Two
;  register pairs cost exactly what one does.
; ---------------------------------------------------------------------
s_push2
    ld  (spsave),sp
    ld  de,#4C4E
    ld  bc,#4E4C
    ld  a,(nbytes)
    srl a
    neg
    add a,MAXB/2
    ld  (p2_e+1),a
    ld  hl,VPB+VP_BW
    ld  ix,p2_next
    ld  a,(nlines)
    ld  (p2_n),a
p2_line
    ld  sp,hl
p2_e
    jp  PUSHBLK2
p2_next
    ld  a,h
    add a,8
    ld  h,a
    ld  a,(p2_c)
    dec a
    ld  (p2_c),a
    jr  z,p2_wrap
p2_cont
    ld  a,(p2_n)
    dec a
    ld  (p2_n),a
    jr  z,p2_done
    jr  p2_line
p2_done
    ld  sp,(spsave)
    ret
p2_wrap
    ld  a,8
    ld  (p2_c),a
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  p2_cont

; ---------------------------------------------------------------------
;  s_pushimm -- LD DE,nn / PUSH DE.  The pattern is an IMMEDIATE, so an
;  arbitrary, non-repeating span can be laid down at whatever the two
;  instructions cost, provided something generated the block first.
; ---------------------------------------------------------------------
s_pushimm
    ld  (spsave),sp
    ld  a,(nbytes)
    srl a
    neg
    add a,MAXB/2
    add a,a
    add a,a                         ; 4 bytes of code per unit
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
;  s_colpush -- PUSH DE walking DOWN, two bytes wide.  SP decrements in
;  the HORIZONTAL direction, so it cannot walk a column: it has to be
;  reloaded every scanline.  What that buys is that the reload covers a
;  PAIR of byte columns at once.  Constant colour: DE is loaded once.
;  (nrows) x 8 scanlines x 2 bytes.
; ---------------------------------------------------------------------
s_colpush
    ld  (spsave),sp
    ld  hl,VPB+2                    ; one past the right of the pair
    ld  bc,#0800
    ld  de,#4C4E
    ld  a,(nrows)
    ld  ixl,a
cp_row
    repeat 7
    ld  sp,hl
    push de
    add hl,bc
    rend
    ld  sp,hl
    push de
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C8
    ld  h,a
    dec ixl
    jr  nz,cp_row
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_colimm -- the same strip with a DIFFERENT pair of bytes on every
;  scanline, baked in as an immediate.  This is a textured 2-byte-wide
;  strip with the texture lookup already done at code-generation time.
; ---------------------------------------------------------------------
s_colimm
    ld  (spsave),sp
    ld  hl,VPB+2
    ld  bc,#0800
    ld  a,(nrows)
    ld  ixl,a
ciw = #4C4E
ci_row
    repeat 7
    ld  sp,hl
    ld  de,ciw
    push de
    add hl,bc
ciw = ciw + #0101
    rend
    ld  sp,hl
    ld  de,ciw
    push de
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C8
    ld  h,a
    dec ixl
    jr  nz,ci_row
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_colpair -- THE COLUMN RENDERER'S CANDIDATE INNER LOOP.
;
;  A TEXTURED two-byte-wide strip walked DOWN the Mode 0 interleave.  It
;  is the answer to the only architectural question a column renderer
;  has: a screen byte written by PUSH costs 2.000 us in ROW order, and
;  the whole point of column order is that PUSH still works -- SP just
;  has to be reloaded every scanline, and the reload covers a PAIR of
;  byte columns, so the screen half of the loop is 8 us for TWO bytes.
;
;  The texture half is one sample and one 16-bit fractional step, and it
;  needs its own HL, so the two halves live in the two register banks and
;  the loop pays two EXX.  That is the whole design:
;
;    main set   HL = texture coord, H = index, L = fraction
;               BC = step, 8.8;  D = TEX>>8, E scratch
;    alt set    HL'= screen, one past the right byte of the pair
;               BC'= &0800, the within-character-row step
;               DE'= the word being pushed
;
;  ONE SAMPLE FEEDS BOTH SCREEN BYTES.  A texture byte is already two
;  Mode 0 pixels, so a pair carries a 4-pixel group of the texture; what
;  it costs to give the two columns DIFFERENT texture bytes is a second
;  sample and a second index, and there is no register left to hold
;  either without a third EXX -- 24 us against 18, which is worse than
;  the single-column LD (HL),A loop this replaces.
;
;  (nrows) x 8 scanlines x 2 bytes.  Wrap hoisted to the row boundary.
; ---------------------------------------------------------------------
s_colpair
    ld  (spsave),sp
    exx
    ld  hl,VPB+2                    ; one past the right of the pair
    ld  bc,#0800
    exx
    ld  hl,#0000                    ; texture coord, 8.8
    ld  bc,#0180                    ; step 1.5 texels per scanline
    ld  d,TEX/256
    ld  a,(nrows)
    ld  ixl,a
cq_row
    repeat 7
    ld  e,h
    ld  a,(de)
    add hl,bc
    exx
    ld  d,a
    ld  e,a
    ld  sp,hl
    push de
    add hl,bc
    exx
    rend
    ld  e,h
    ld  a,(de)
    add hl,bc
    exx
    ld  d,a
    ld  e,a
    ld  sp,hl
    push de
    ld  a,l                         ; the character-row wrap, once in 8
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C8
    ld  h,a
    exx
    dec ixl
    jr  nz,cq_row
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_colrun -- the same strip with the sample taken once per TWO
;  scanlines, i.e. a wall magnified 2x, where one texture row covers two
;  screen rows.  It prices the run-structured variant of the loop above:
;  the sample and the step are hoisted and only the eight microseconds
;  of LD SP,HL / PUSH DE / ADD HL,BC repeat.
;
;  IT IS NOT WHAT SHIPS, and the reason is the shape of the trade.  This
;  is faster than s_colpair only where the texture is magnified, which is
;  where the wall is NEARER than half a cell; at exactly one cell the
;  wall already fills the viewport and the two loops do identical work,
;  so a charge covering both has to bound s_colpair anyway.
;
;  (nrows) x 8 scanlines x 2 bytes, same as s_colpair, so the two are
;  directly comparable.
; ---------------------------------------------------------------------
s_colrun
    ld  (spsave),sp
    exx
    ld  hl,VPB+2
    ld  bc,#0800
    exx
    ld  hl,#0000
    ld  bc,#00C0                    ; step 0.75: one sample, two scanlines
    ld  d,TEX/256
    ld  a,(nrows)
    ld  ixl,a
cr_row
    repeat 3
    ld  e,h
    ld  a,(de)
    add hl,bc
    exx
    ld  d,a
    ld  e,a
    ld  sp,hl
    push de
    add hl,bc
    ld  sp,hl
    push de
    add hl,bc
    exx
    rend
    ld  e,h
    ld  a,(de)
    add hl,bc
    exx
    ld  d,a
    ld  e,a
    ld  sp,hl
    push de
    add hl,bc
    ld  sp,hl
    push de
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C8
    ld  h,a
    exx
    dec ixl
    jr  nz,cr_row
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_across -- LD (HL),A / INC L, left to right.  Same per-line walk.
; ---------------------------------------------------------------------
s_across
    ld  a,(nbytes)
    neg
    add a,MAXB
    add a,a                         ; 2 bytes of code per unit
    ld  (ac_e+1),a
    ld  a,#4C
    ld  hl,VPB
    ld  ix,ac_next
    ld  a,(nlines)
    ld  b,a
    ld  c,8
ac_line
    push hl
    ld  a,#4C
ac_e
    jp  ACRBLK
ac_next
    pop hl
    ld  a,h
    add a,8
    ld  h,a
    dec c
    jr  z,ac_wrap
ac_cont
    djnz ac_line
    ret
ac_wrap
    ld  c,8
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  ac_cont

; ---------------------------------------------------------------------
;  s_ldi -- unrolled LDI, SRC -> screen, left to right.
; ---------------------------------------------------------------------
s_ldi
    ld  a,(nbytes)
    neg
    add a,MAXB
    add a,a                         ; LDI is 2 bytes
    ld  (li_e+1),a
    ld  ix,li_next
    ld  a,(nlines)
    ld  (li_n),a
    ld  de,VPB
li_line
    push de
    ld  hl,SRC
    ld  bc,256
li_e
    jp  LDIBLK
li_next
    pop de
    ld  a,d
    add a,8
    ld  d,a
    ld  a,(li_c)
    dec a
    ld  (li_c),a
    jr  z,li_wrap
li_cont
    ld  a,(li_n)
    dec a
    ld  (li_n),a
    ret z
    jr  li_line
li_wrap
    ld  a,8
    ld  (li_c),a
    ld  a,e
    add a,SCR_W
    ld  e,a
    ld  a,d
    adc a,#C0
    ld  d,a
    jr  li_cont

; ---------------------------------------------------------------------
;  s_ldir -- one LDIR per scanline.
; ---------------------------------------------------------------------
s_ldir
    ld  a,(nlines)
    ld  (lr_n),a
    ld  de,VPB
lr_line
    push de
    ld  hl,SRC
    ld  a,(nbytes)
    ld  c,a
    ld  b,0
    ldir
    pop de
    ld  a,d
    add a,8
    ld  d,a
    ld  a,(lr_c)
    dec a
    ld  (lr_c),a
    jr  z,lr_wrap
lr_cont
    ld  a,(lr_n)
    dec a
    ld  (lr_n),a
    ret z
    jr  lr_line
lr_wrap
    ld  a,8
    ld  (lr_c),a
    ld  a,e
    add a,SCR_W
    ld  e,a
    ld  a,d
    adc a,#C0
    ld  d,a
    jr  lr_cont

; ---------------------------------------------------------------------
;  s_popst -- POP HL / LD (nn),HL with the DESTINATION baked into the
;  instruction.  SP walks the linear source upward; nothing at all is
;  spent on a screen pointer.  Because nn is an immediate this only
;  ever writes ONE scanline, so `nlines` here means "repeat that line",
;  which costs the same microseconds whatever address it hits.
; ---------------------------------------------------------------------
s_popst
    ld  (spsave),sp
    ld  a,(nbytes)
    neg
    add a,MAXB
    add a,a                         ; 4 bytes of code per 2 screen bytes
    ld  (ps_e+1),a
    ld  ix,ps_next
    ld  a,(nlines)
    ld  b,a
ps_line
    ld  sp,SRC
ps_e
    jp  POPBLK
ps_next
    djnz ps_line
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_rowcopy -- LD A,(BC) / INC C / LD (HL),A / INC L
; ---------------------------------------------------------------------
s_rowcopy
    ld  a,(nbytes)
    neg
    add a,MAXB
    add a,a
    add a,a                         ; 4 bytes of code per unit
    ld  (rc_e+1),a
    ld  ix,rc_next
    ld  a,(nlines)
    ld  (rc_n),a
    ld  hl,VPB
rc_line
    push hl
    ld  bc,SRC
rc_e
    jp  RCBLK
rc_next
    pop hl
    ld  a,h
    add a,8
    ld  h,a
    ld  a,(rc_c)
    dec a
    ld  (rc_c),a
    jr  z,rc_wrap
rc_cont
    ld  a,(rc_n)
    dec a
    ld  (rc_n),a
    ret z
    jr  rc_line
rc_wrap
    ld  a,8
    ld  (rc_c),a
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    jr  rc_cont

; ---------------------------------------------------------------------
;  s_dnaive -- a solid column, (nbytes) scanlines tall, one LD (HL),A
;  per scanline and the character-row test taken every scanline.
; ---------------------------------------------------------------------
s_dnaive
    ld  hl,VPB
    ld  de,#0800
    ld  a,(nbytes)
    ld  b,a
    ld  c,8
    ld  a,#4C
dn_l
    ld  (hl),a
    dec c
    jr  z,dn_wrap
    add hl,de
dn_cont
    djnz dn_l
    ret
dn_wrap
    ld  c,8
    add hl,de
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C0
    ld  h,a
    ld  a,#4C
    jr  dn_cont

; ---------------------------------------------------------------------
;  s_dunroll -- the same column, unrolled a whole character row at a
;  time, so the wrap costs nothing per scanline.  (nrows) x 8 bytes.
;  BC carries the row-to-row delta (-7*&800 + 80) so A, which holds the
;  pixel, is never clobbered; the row counter lives in IXL.
; ---------------------------------------------------------------------
s_dunroll
    ld  hl,VPB
    ld  de,#0800
    ld  bc,#C850                    ; 80 - 7*&800
    ld  a,(nrows)
    ld  ixl,a
    ld  a,#4C
du_row
    repeat 7
    ld  (hl),a
    add hl,de
    rend
    ld  (hl),a
    add hl,bc
    dec ixl
    jr  nz,du_row
    ret

; ---------------------------------------------------------------------
;  s_dfull -- 96 scanlines with no loop control whatever.  The floor
;  for a solid column of full viewport height.
; ---------------------------------------------------------------------
s_dfull
    ld  hl,VPB
    ld  de,#0800
    ld  bc,#C850
    ld  a,#4C
    repeat 12
    repeat 7
    ld  (hl),a
    add hl,de
    rend
    ld  (hl),a
    add hl,bc
    rend
    ret

; ---------------------------------------------------------------------
;  s_tex -- THE RAYCASTER INNER LOOP.  A textured vertical strip with a
;  16-bit fractional texture step, written down the Mode 0 interleave.
;
;    main set   HL = texture coord, H = index, L = fraction
;               BC = step, 8.8
;               D  = TEX>>8, E scratch  -> LD E,H / LD A,(DE) samples
;    alt set    HL'= screen pointer
;               DE'= &0800, the within-character-row step
;               BC'= &C850, the row-to-row step
;
;  (nrows) x 8 bytes, unrolled a character row at a time.
; ---------------------------------------------------------------------
s_tex
    exx
    ld  hl,VPB
    ld  de,#0800
    ld  bc,#C850
    exx
    ld  hl,#0000                    ; texture coord
    ld  bc,#0180                    ; step 1.5 texels per scanline
    ld  d,TEX/256
    ld  a,(nrows)
    ld  ixl,a
tx_row
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
    jr  nz,tx_row
    ret

; ---------------------------------------------------------------------
;  s_texpop -- the strip when the scale is one of a SMALL SET, so the
;  column has already been expanded into a linear buffer and there is
;  no fractional step at all.  SP feeds two bytes per POP.
;
;    SP = source, HL = screen, DE = &0800, B,C = the two source bytes.
;  The row-to-row step has to be done on A because BC is the data.
; ---------------------------------------------------------------------
s_texpop
    ld  (spsave),sp
    ld  hl,VPB
    ld  de,#0800
    ld  a,(nrows)
    ld  ixl,a
    ld  sp,SRC
tp_row
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
    jr  nz,tp_row
    ld  sp,(spsave)
    ret

; ---------------------------------------------------------------------
;  s_texbc -- the same precomputed column read one byte at a time,
;  LD A,(BC) / INC C, so the row-to-row step must go through A too.
; ---------------------------------------------------------------------
s_texbc
    ld  hl,VPB
    ld  de,#0800
    ld  bc,SRC
    ld  a,(nrows)
    ld  ixl,a
tb_row
    repeat 7
    ld  a,(bc)
    inc c
    ld  (hl),a
    add hl,de
    rend
    ld  a,(bc)
    inc c
    ld  (hl),a
    ld  a,l
    add a,SCR_W
    ld  l,a
    ld  a,h
    adc a,#C8
    ld  h,a
    dec ixl
    jr  nz,tb_row
    ret

; ---------------------------------------------------------------------
;  s_mortar -- the "PUSH the field, then poke the joints in" model.
;  Each poke reads a 16-bit screen address and a colour byte out of a
;  packed 3-byte table:  LD E,(HL)/INC L/LD D,(HL)/INC L/LD A,(HL)/
;  INC L/LD (DE),A.  (nbytes) pokes.
; ---------------------------------------------------------------------
MOMAX   equ 22                      ; pokes in the block

s_mortar
    ld  a,MOMAX
    ld  hl,nbytes
    sub (hl)
    add a,a
    add a,a
    add a,a                         ; 8 bytes of code per poke
    ld  (mo_e+1),a
    ld  ix,mo_next
    ld  a,(nlines)
    ld  b,a
mo_line
    push bc
    ld  hl,POKETAB
mo_e
    jp  MOBLK
mo_next
    pop bc
    djnz mo_line
    ret


; =====================================================================
;  THE PAGE-ALIGNED BLOCKS.  Entering at (MAXB - n) * unitsize runs
;  exactly n units and falls into the tail, so run length costs one LD
;  and one JP and NOTHING is charged to loop control.
; =====================================================================

    align 256
PUSHBLK
    repeat MAXB/2
    push de
    rend
    jp  (ix)

    align 256
PUSHBLK2
    repeat MAXB/4
    push de
    push bc
    rend
    jp  (ix)

    align 256
PUSHIMM
piw = #4C4E
    repeat MAXB/2
    ld  de,piw
    push de
piw = piw + #0101
    rend
    jp  (ix)

    align 256
ACRBLK
    repeat MAXB
    ld  (hl),a
    inc l
    rend
    jp  (ix)

    align 256
LDIBLK
    repeat MAXB
    ldi
    rend
    jp  (ix)

    align 256
POPBLK
pbc = 0
    repeat MAXB/2
    pop hl
    ld  (VPB+pbc),hl
pbc = pbc + 2
    rend
    jp  (ix)

    align 256
RCBLK
    repeat MAXB
    ld  a,(bc)
    inc c
    ld  (hl),a
    inc l
    rend
    jp  (ix)

    align 256
MOBLK
    repeat MOMAX
    ld  e,(hl)
    inc l
    ld  d,(hl)
    inc l
    ld  a,(hl)
    inc l
    ld  (de),a
    nop                             ; pad the unit to 8 bytes
    rend
    jp  (ix)

; =====================================================================
    align 256
counter dw  0
nbytes  db  44
nlines  db  96
nrows   db  12
spsave  dw  0
li_n    db  0
li_c    db  8
lr_n    db  0
lr_c    db  8
rc_n    db  0
rc_c    db  8
p2_n    db  0
p2_c    db  8
