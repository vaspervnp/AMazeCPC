; =====================================================================
;  engine2 table unit test -- runs on the emulator, no disc, no BASIC.
;
;  Pages RAM bank 4 in at &4000, then
;    1. copies a Python-supplied list of (address, length) probes out of
;       the bank so the layout and endianness can be checked byte-exactly;
;    2. exercises the DOCUMENTED CONTRACT of each table with real Z80 code
;       -- the quarter-square multiply, the 16x16 built on it, the
;       projection (PROJ + HTAB) and the reciprocal divide -- and writes
;       the results where Python can compare them against the reference;
;    3. sits in a counting loop so the cost of the projection can be
;       measured (TMODE = 0 gives the empty-loop baseline).
;
;  Everything the host reads back lives at &9000-&9BFF, i.e. base bank 2,
;  which cpc.read_ram() can see regardless of the RAM configuration.
; =====================================================================

    include "tab_equ.inc"

; ---- host-visible work areas (base bank 2) --------------------------
PROBES      equ #9000       ; {dw addr, db len} ... dw 0
PROBERES    equ #9200
QSN         equ #9400       ; db count
QSCASE      equ #9401       ; {db a, db b} * count
QSRES       equ #9500       ; dw a*b   * count
PJN         equ #9600       ; db count
PJCASE      equ #9601       ; {dw xv_q10, dw z_q10} * count
PJRES       equ #9700       ; {dw xs_q4, dw hs_q4} * count
RDN         equ #9800       ; db count
RDCASE      equ #9801       ; {dw v, db n} * count
RDRES       equ #9900       ; dw v/n   * count
DONE        equ #9A00       ; db  &A5 when phases 1-3 have finished
TVEC        equ #9A02       ; dw  routine the timing loop calls each pass
TXV         equ #9A04
TZ          equ #9A06
ITER        equ #9A08       ; dw  loop counter
PFRES       equ #9B00       ; {dw xs_q4, dw hs_q4} * count, PROJN/HTN route
STACKTOP    equ #9C00

    org #8000

start
    di
    ld sp,STACKTOP
    ld bc,#7FC4                 ; RAM config 4: bank 4 at &4000
    out (c),c
    xor a
    ld (DONE),a

; ---------------------------------------------------------------------
;  phase 1 -- raw probe readback
; ---------------------------------------------------------------------
    ld hl,PROBES
    ld de,PROBERES
p_loop
    ld c,(hl)
    inc hl
    ld b,(hl)
    inc hl
    ld a,b
    or c
    jr z,p_done
    ld a,(hl)                   ; length
    inc hl
    push hl
    ld h,b
    ld l,c                      ; HL = source in bank 4
    ld c,a
    ld b,0
    ldir
    pop hl
    jr p_loop
p_done

; ---------------------------------------------------------------------
;  phase 2 -- quarter-square multiply, a*b = QSQ[a+b] - QSQ[|a-b|]
; ---------------------------------------------------------------------
    ld a,(QSN)
    ld (ctr),a
    ld hl,QSCASE
    ld de,QSRES
q_loop
    ld a,(ctr)
    or a
    jr z,q_done
    dec a
    ld (ctr),a
    ld a,(hl)
    inc hl
    ld b,a
    ld a,(hl)
    inc hl
    ld c,a
    push hl
    push de
    call qsmul
    pop de
    ld a,l
    ld (de),a
    inc de
    ld a,h
    ld (de),a
    inc de
    pop hl
    jr q_loop
q_done

; ---------------------------------------------------------------------
;  phase 3a -- projection:  xs_q4 = CX_Q4 + ((xv_q10 * PROJ[zq]) >> 10)
;                           hs_q4 = HTAB[zq],  zq = (z_q10+2) >> 2
; ---------------------------------------------------------------------
    ld a,(PJN)
    ld (ctr),a
    ld hl,PJCASE
    ld de,PJRES
j_loop
    ld a,(ctr)
    or a
    jr z,j_done
    dec a
    ld (ctr),a
    ld a,(hl)
    inc hl
    ld (pv_xv),a
    ld a,(hl)
    inc hl
    ld (pv_xv+1),a
    ld a,(hl)
    inc hl
    ld (pv_z),a
    ld a,(hl)
    inc hl
    ld (pv_z+1),a
    push hl
    push de
    call project
    pop de
    ld hl,(pv_xs)
    ld a,l
    ld (de),a
    inc de
    ld a,h
    ld (de),a
    inc de
    ld hl,(pv_hs)
    ld a,l
    ld (de),a
    inc de
    ld a,h
    ld (de),a
    inc de
    pop hl
    jr j_loop
j_done

; ---------------------------------------------------------------------
;  phase 3c -- the same endpoints through the normalised PROJN/HTN route
; ---------------------------------------------------------------------
    ld a,(PJN)
    ld (ctr),a
    ld hl,PJCASE
    ld de,PFRES
f_loop
    ld a,(ctr)
    or a
    jr z,f_done
    dec a
    ld (ctr),a
    ld a,(hl)
    inc hl
    ld (pv_xv),a
    ld a,(hl)
    inc hl
    ld (pv_xv+1),a
    ld a,(hl)
    inc hl
    ld (pv_z),a
    ld a,(hl)
    inc hl
    ld (pv_z+1),a
    push hl
    push de
    call project_fast
    pop de
    ld hl,(pv_xs)
    ld a,l
    ld (de),a
    inc de
    ld a,h
    ld (de),a
    inc de
    ld hl,(pv_hs)
    ld a,l
    ld (de),a
    inc de
    ld a,h
    ld (de),a
    inc de
    pop hl
    jr f_loop
f_done

; ---------------------------------------------------------------------
;  phase 3b -- reciprocal divide:  v/n = (v * RCP[n]) >> 15
; ---------------------------------------------------------------------
    ld a,(RDN)
    ld (ctr),a
    ld hl,RDCASE
    ld de,RDRES
r_loop
    ld a,(ctr)
    or a
    jr z,r_done
    dec a
    ld (ctr),a
    ld a,(hl)
    inc hl
    ld (rd_v),a
    ld a,(hl)
    inc hl
    ld (rd_v+1),a
    ld a,(hl)
    inc hl
    ld (rd_n),a
    push hl
    push de
    call rcpdiv
    pop de
    ld a,l
    ld (de),a
    inc de
    ld a,h
    ld (de),a
    inc de
    pop hl
    jr r_loop
r_done

    ld a,#A5
    ld (DONE),a

; ---------------------------------------------------------------------
;  phase 4 -- timing loop.
;
;  Every pass does exactly the same work except for one indirect call
;  through (TVEC), so subtracting the t_nop run leaves the routine's own
;  cost plus its 4-7 us of argument setup and nothing else.  The host
;  points TVEC at t_nop / t_qsmul / t_mul16 / t_rcpdiv / t_proj in turn.
; ---------------------------------------------------------------------
    ld hl,0
    ld (ITER),hl
t_loop
    ld hl,(TXV)
    ld (pv_xv),hl
    ld hl,(TZ)
    ld (pv_z),hl
    ld hl,(TVEC)
    ld de,t_back
    push de
    jp (hl)
t_back
    ld hl,(ITER)
    inc hl
    ld (ITER),hl
    jr t_loop

t_nop                           ; the baseline: dispatch and return
    ret

t_qsmul                         ; one 8x8 quarter-square product
    ld b,200
    ld c,173
    jp qsmul

t_mul16                         ; one 16x16 -> 32 product
    ld hl,(pv_xv)
    ld (mul_a),hl
    ld hl,(pv_z)
    ld (mul_b),hl
    jp mul16

t_rcpdiv                        ; one reciprocal divide
    ld hl,(pv_z)
    ld (rd_v),hl
    ld a,37
    ld (rd_n),a
    jp rcpdiv

t_proj                          ; one full projected endpoint, PROJ/HTAB
    jp project

t_projfast                      ; one full projected endpoint, PROJN/HTN
    jp project_fast


; =====================================================================
;  qsmul -- HL = B * C, both unsigned bytes.  Exact.
;    a*b = QSQ[a+b] - QSQ[|a-b|];  both indices have the same parity as
;    a+b, so the two floor(t^2/4) truncations cancel exactly.
;  Corrupts AF DE HL.
; =====================================================================
qsmul
    ld a,b
    add a,c
    ld l,a
    ld a,0
    adc a,0
    ld h,a                      ; HL = b+c  (0..510)
    add hl,hl
    ld de,QSQ
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)                   ; DE = QSQ[b+c]
    ld a,b
    sub c
    jr nc,qs_pos
    cpl
    inc a                       ; A = |b-c|
qs_pos
    ld l,a
    ld h,0
    add hl,hl
    push de
    ld de,QSQ
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)                   ; DE = QSQ[|b-c|]
    pop hl
    or a
    sbc hl,de
    ret


; =====================================================================
;  mul16 -- (mul_r) 32-bit = (mul_a) * (mul_b), both unsigned 16-bit.
;  Four qsmul partial products.  Corrupts AF BC DE HL.
; =====================================================================
mul16
    ld a,(mul_a)
    ld b,a
    ld a,(mul_b)
    ld c,a
    call qsmul                  ; al*bl
    ld (mul_r),hl
    ld hl,0
    ld (mul_r+2),hl

    ld a,(mul_a+1)
    ld b,a
    ld a,(mul_b)
    ld c,a
    call qsmul                  ; ah*bl
    call add8

    ld a,(mul_a)
    ld b,a
    ld a,(mul_b+1)
    ld c,a
    call qsmul                  ; al*bh
    call add8

    ld a,(mul_a+1)
    ld b,a
    ld a,(mul_b+1)
    ld c,a
    call qsmul                  ; ah*bh
    ld de,(mul_r+2)
    add hl,de
    ld (mul_r+2),hl
    ret

add8                            ; mul_r += HL << 8
    ld a,(mul_r+1)
    add a,l
    ld (mul_r+1),a
    ld a,(mul_r+2)
    adc a,h
    ld (mul_r+2),a
    ld a,(mul_r+3)
    adc a,0
    ld (mul_r+3),a
    ret


; =====================================================================
;  proj -- one face endpoint.
;    in  (pv_xv) int16  Q6.10 view-space lateral, in cells
;        (pv_z)  uint16 Q6.10 view-space depth,   in cells
;    out (pv_xs) int16  Q12.4 screen x, half-byte units
;        (pv_hs) uint16 Q12.4 projected half-height, scanlines
;  Corrupts AF BC DE HL.
; =====================================================================
project
    ld hl,(pv_z)
    inc hl
    inc hl                      ; round rather than truncate
    srl h
    rr l
    srl h
    rr l                        ; HL = zq = round(z*256)
    ld de,ZNEAR_Q8
    push hl
    or a
    sbc hl,de
    pop hl
    jr nc,pj_lo
    ld hl,ZNEAR_Q8
pj_lo
    ld de,ZFAR_Q8
    push hl
    or a
    sbc hl,de
    pop hl
    jr c,pj_hi
    ld hl,ZFAR_Q8
pj_hi
    ld (pv_zq),hl

    add hl,hl
    ld de,HTAB
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (pv_hs),de               ; hs_q4 = HTAB[zq]

    ld hl,(pv_zq)
    add hl,hl
    ld de,PROJ
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (mul_b),de               ; PROJ[zq]

    ld hl,(pv_xv)
    ld a,h
    and #80
    ld (pv_sgn),a
    jr z,pj_pos
    ld a,l                      ; HL = -HL
    cpl
    ld l,a
    ld a,h
    cpl
    ld h,a
    inc hl
pj_pos
    ld (mul_a),hl
    call mul16
    ; |xv|*PROJ <= 2^20, so (mul_r+1..2) holds the whole product >> 8.
    ld hl,(mul_r+1)
    srl h
    rr l
    srl h
    rr l                        ; >> 10 in total
    ld a,(pv_sgn)
    or a
    jr z,pj_add
    ld a,l
    cpl
    ld l,a
    ld a,h
    cpl
    ld h,a
    inc hl
pj_add
    ld de,CX_Q4
    add hl,de
    ld (pv_xs),hl
    ret


; =====================================================================
;  project_fast -- same interface as `project`, but normalises z into one
;  octave first so the whole projection is ONE 8x8 quarter-square product
;  instead of a 16x16.  Uses BITLEN, PROJN, HTN, QSQ.
;  Corrupts AF BC DE HL.
; =====================================================================
project_fast
    ld hl,(pv_z)                ; s = BITLEN(z_q10) - 7
    ld a,h
    or a
    jr z,pf_lob
    ld l,a
    ld h,BITLEN/256
    ld a,(hl)
    inc a                       ; (BITLEN[hi] + 8) - 7
    jr pf_shave
pf_lob
    ld h,BITLEN/256             ; H was 0, L is already the low byte
    ld a,(hl)
    sub 7
    jr nc,pf_shave
    xor a
pf_shave
    ld (pf_sh),a

    ld b,a                      ; zn = round(z >> s)
    ld hl,(pv_z)
    or a
    jr z,pf_zdone
    dec b
    jr z,pf_zlast
pf_zsh
    srl h
    rr l
    djnz pf_zsh
pf_zlast
    inc hl
    srl h
    rr l
pf_zdone
    ld a,l
    sub 64
    add a,a                     ; j*2
    ld (pf_j2),a

    ld l,a                      ; hs_q4 = HTN[j] >> s
    ld h,0
    ld de,HTN
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ex de,hl
    ld a,(pf_sh)
    or a
    jr z,pf_hdone
    ld b,a
pf_hsh
    srl h
    rr l
    djnz pf_hsh
pf_hdone
    ld (pv_hs),hl

    ld hl,(pv_xv)               ; xn = round(|xv| >> s)
    ld a,h
    and #80
    ld (pv_sgn),a
    jr z,pf_xpos
    ld a,l
    cpl
    ld l,a
    ld a,h
    cpl
    ld h,a
    inc hl
pf_xpos
    ld a,(pf_sh)
    or a
    jr z,pf_xdone
    ld b,a
    dec b
    jr z,pf_xlast
pf_xsh
    srl h
    rr l
    djnz pf_xsh
pf_xlast
    inc hl
    srl h
    rr l
pf_xdone
    ld a,l
    ld (pf_xn),a
    ld b,a

    ld a,(pf_j2)                ; PROJN[j], split into hi bit + low byte
    ld l,a
    ld h,0
    ld de,PROJN
    add hl,de
    ld c,(hl)
    inc hl
    ld a,(hl)
    ld (pf_hi),a
    call qsmul                  ; HL = |xn| * low
    ld a,(pf_hi)
    or a
    jr z,pf_nohi
    ld a,(pf_xn)
    ld d,a
    ld e,0
    add hl,de                   ; += |xn| << 8
pf_nohi
    srl h
    rr l
    srl h
    rr l
    srl h
    rr l
    srl h
    rr l                        ; >> 4
    ld a,(pv_sgn)
    or a
    jr z,pf_add
    ld a,l
    cpl
    ld l,a
    ld a,h
    cpl
    ld h,a
    inc hl
pf_add
    ld de,CX_Q4
    add hl,de
    ld (pv_xs),hl
    ret


; =====================================================================
;  rcpdiv -- HL = (rd_v) / (rd_n), via (v * RCP[n]) >> 15.
;  Corrupts AF BC DE HL.
; =====================================================================
rcpdiv
    ld a,(rd_n)
    ld l,a
    ld h,0
    add hl,hl
    ld de,RCP
    add hl,de
    ld e,(hl)
    inc hl
    ld d,(hl)
    ld (mul_b),de
    ld hl,(rd_v)
    ld (mul_a),hl
    call mul16
    ld a,(mul_r+1)              ; >>15 = ((r>>16)<<1) | bit15
    rlca
    and 1
    ld e,a
    ld d,0
    ld hl,(mul_r+2)
    add hl,hl
    add hl,de
    ret


; ---- variables ------------------------------------------------------
ctr     defb 0
pv_xv   defw 0
pv_z    defw 0
pv_zq   defw 0
pv_xs   defw 0
pv_hs   defw 0
pv_sgn  defb 0
rd_v    defw 0
rd_n    defb 0
mul_a   defw 0
mul_b   defw 0
mul_r   defs 4
pf_sh   defb 0
pf_j2   defb 0
pf_hi   defb 0
pf_xn   defb 0
