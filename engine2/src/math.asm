; =====================================================================
;  engine2/src/math.asm -- fixed-point arithmetic primitives
;
;  FIXED POINT CONVENTIONS
;    world / view coordinates   Q8.8   signed 16-bit, 1 cell = 256
;    cos / sin                  magnitude 0..128 in an unsigned byte plus a
;                               sign bit, so cos(0) = 1.0 is EXACT.  (A
;                               signed 1.7 byte could only hold 127/128 and
;                               would put a 0.78% scale error on the four
;                               cardinal headings -- the ones you can see
;                               best.)  The quarter-square multiply wants
;                               unsigned operands anyway, so magnitude+sign
;                               costs nothing extra.
;    reciprocal of depth        Q4.12  unsigned 16-bit, 1.0 = 4096.
;                               Range 1/4096 .. 15.9998; the near plane
;                               ZNEAR = 0.08 gives 12.5, so no saturation
;                               can occur on legal input.
;
;  Nothing here touches IX/IY.  mul16x8u / mul16x8s / rotate_point use EXX,
;  so the ALTERNATE REGISTER SET IS CLOBBERED.  rot_setup uses SP as a table
;  pointer, so it must run with interrupts off.
; =====================================================================


; ---------------------------------------------------------------------
;  mul8x8u -- exact unsigned 8x8 -> 16 via quarter squares
;
;    a*b = floor((a+b)^2/4) - floor((a-b)^2/4)
;
;  exact because a+b and a-b have the same parity, so the two floors cancel.
;
;  in:   A = a (0..255)   C = b (0..255)
;  out:  HL = a*b
;  kill: A, B, C, D, E
; ---------------------------------------------------------------------
mul8x8u
    ld   b,a                    ; keep a
    add  a,c                    ; a+b, CY = bit 8
    ld   l,a
    ld   a,QSLO/256
    adc  a,0
    ld   h,a
    ld   e,(hl)
    inc  h
    inc  h                      ; +512 -> QSHI; correct from either page
    ld   d,(hl)                 ; DE = QS[a+b]
    ld   a,b
    sub  c
    jr   nc,m88_pos
    neg
m88_pos
    ld   l,a
    ld   h,QSLO/256             ; |a-b| <= 255, single page
    ld   c,(hl)
    inc  h
    inc  h
    ld   b,(hl)                 ; BC = QS[|a-b|]
    ex   de,hl
    or   a
    sbc  hl,bc
    ret


; ---------------------------------------------------------------------
;  mul16x8u -- unsigned 16 x 8 -> 24
;  in:   DE = a16   C = b8
;  out:  A:HL  (A = bits 23..16)
;  kill: AF, BC, DE, HL and the alternate set
; ---------------------------------------------------------------------
mul16x8u
    ld   a,d
    exx
    ld   b,a                    ; B' = a16 high
    exx
    ld   a,c
    exx
    ld   c,a                    ; C' = b8
    exx
    ld   a,e
    call mul8x8u                ; HL = alo*b
    push hl
    exx                         ; B = a16 high, C = b8
    ld   a,b
    call mul8x8u                ; HL = ahi*b
    pop  de                     ; DE = alo*b
    ld   a,d
    add  a,l                    ; middle byte
    ld   d,a
    ld   a,h
    adc  a,0                    ; high byte
    ld   h,d
    ld   l,e
    ret


; ---------------------------------------------------------------------
;  mul16x8s -- signed 16 x signed 8 -> signed 24
;  in:   DE = a16 (signed)   C = b8 (signed)
;  out:  A:HL sign-extended 24-bit product
; ---------------------------------------------------------------------
mul16x8s
    xor  a
    ld   (m_sgn),a
    bit  7,d
    jr   z,ms_dpos
    xor  a                      ; DE = -DE
    sub  e
    ld   e,a
    sbc  a,a
    sub  d
    ld   d,a
    ld   a,1
    ld   (m_sgn),a
ms_dpos
    bit  7,c
    jr   z,ms_cpos
    ld   a,c
    neg
    ld   c,a
    ld   a,(m_sgn)
    xor  1
    ld   (m_sgn),a
ms_cpos
    call mul16x8u
    ld   b,a
    ld   a,(m_sgn)
    or   a
    ld   a,b
    ret  z
    ld   b,a                    ; negate the 24-bit A:HL
    xor  a
    sub  l
    ld   l,a
    ld   a,0
    sbc  a,h
    ld   h,a
    ld   a,0
    sbc  a,b
    ret


; ---------------------------------------------------------------------
;  recip_zv -- 1/zv by normalise + table
;
;  in:   HL = zv, Q8.8, STRICTLY POSITIVE (caller has clipped to ZNEAR)
;  out:  HL = round(4096/zv) in Q4.12, saturated to #FFFF
;  kill: AF, B, DE
;
;  The raw integer v is written v = m * 2^k with a NINE-bit mantissa
;  m in [256,511]; then 4096/zv = 2^20/v = RT[m] >> k with
;  RT[m] = round(2^20/m) a 256-entry table pair indexed by m-256 (which is
;  just the low byte, because bit 8 is known set).  k is at most +-7 over
;  the whole legal input range, so the normalise loop is short and bounded.
;
;  Error budget: the mantissa is rounded, not truncated (<= 1/1024 = 0.1%),
;  the table holds 11-12 significant bits (<= 0.025%) and the final shift
;  rounds (<= 0.5 LSB of the result).  An 8-bit mantissa was measured at
;  0.68% worst -- enough to make a wall's height wobble by half a scanline
;  as you walk, so it was not enough.
; ---------------------------------------------------------------------
recip_zv
    ld   a,h
    cp   2
    jr   nc,rz_big              ; v >= 512
    or   a
    jr   nz,rz_look             ; H = 1: 256 <= v <= 511, k = 0
    ld   a,l
    or   a
    jr   z,rz_sat               ; v = 0 -> saturate
    ld   b,0
rz_norm
    add  hl,hl
    inc  b
    ld   a,h
    or   a
    jr   z,rz_norm              ; until bit 8 is set
    ld   h,RECLO/256            ; L is m-256
    ld   e,(hl)
    inc  h
    ld   d,(hl)
    ex   de,hl                  ; HL = RT[m]
rz_shl
    add  hl,hl
    jr   c,rz_sat
    djnz rz_shl
    ret

rz_look                         ; k = 0
    ld   h,RECLO/256
    ld   e,(hl)
    inc  h
    ld   d,(hl)
    ex   de,hl
    ret

rz_big                          ; v >= 512: shift right until 256 <= v <= 511
    ld   b,0
rz_sr
    srl  h
    rr   l
    inc  b
    sbc  a,a                    ; A = #FF if a 1 fell off the bottom
    ld   c,a
    ld   a,h
    cp   2
    jr   nc,rz_sr
    inc  c                      ; round the mantissa to nearest
    jr   nz,rz_nr
    inc  hl
    ld   a,h
    cp   2
    jr   nz,rz_nr
    ld   hl,#0100               ; m rounded up to 512 == m 256 with k+1
    inc  b
rz_nr
    ld   h,RECLO/256            ; L is m-256
    ld   e,(hl)
    inc  h
    ld   d,(hl)
    ex   de,hl                  ; HL = RT[m]
rz_shr
    srl  h
    rr   l
    djnz rz_shr
    ret  nc                     ; DJNZ preserves CY -> round to nearest
    inc  hl
    ret

rz_sat
    ld   hl,#FFFF
    ret


; ---------------------------------------------------------------------
;  rotate_point -- general view-space transform (any dx, dy)
;
;    xv =  dy*cos - dx*sin          (lateral)
;    zv =  dx*cos + dy*sin          (depth)
;
;  matching free.py to_view() with fwd = (cos,sin), rgt = (-sin,cos).
;
;  in:   (rp_dx) (rp_dy)  Q8.8 signed 16-bit
;        (rp_ang)         heading 0..71
;  out:  (rp_xv) (rp_zv)  Q8.8 signed 16-bit
;
;  Four unsigned 24-bit partial products |coord| * magnitude, then each
;  output is one add-or-subtract, one conditional negate, +64 for round to
;  nearest, and a >>7 done as "shift left once, keep the top 16 bits".
; ---------------------------------------------------------------------
rotate_point
    ; ---- trig for this heading ----
    ld   a,(rp_ang)
    ld   l,a
    ld   h,TRIG/256
    ld   a,(hl)                 ; COSMAG
    ld   (rp_cm),a
    ld   a,l
    add  a,72
    ld   l,a
    ld   a,(hl)                 ; SINMAG
    ld   (rp_sm),a
    ld   a,l
    add  a,72
    ld   l,a
    ld   a,(hl)                 ; SGNS: b0 = cos<0, b1 = sin<0
    ld   b,a
    and  1
    ld   (rp_cs),a
    ld   a,b
    rrca
    and  1
    ld   (rp_ss),a

    ; ---- magnitudes and signs of dx, dy ----
    xor  a
    ld   (rp_dxs),a
    ld   (rp_dys),a
    ld   hl,(rp_dx)
    bit  7,h
    jr   z,rp_dxp
    xor  a
    sub  l
    ld   l,a
    sbc  a,a
    sub  h
    ld   h,a
    ld   a,1
    ld   (rp_dxs),a
rp_dxp
    ld   (rp_adx),hl
    ld   hl,(rp_dy)
    bit  7,h
    jr   z,rp_dyp
    xor  a
    sub  l
    ld   l,a
    sbc  a,a
    sub  h
    ld   h,a
    ld   a,1
    ld   (rp_dys),a
rp_dyp
    ld   (rp_ady),hl

    ; ---- four partial products ----
    ld   de,(rp_adx)
    ld   a,(rp_cm)
    ld   c,a
    call mul16x8u
    ld   (rp_p1),hl
    ld   (rp_p1+2),a            ; P1 = |dx| * |cos|

    ld   de,(rp_ady)
    ld   a,(rp_sm)
    ld   c,a
    call mul16x8u
    ld   (rp_p2),hl
    ld   (rp_p2+2),a            ; P2 = |dy| * |sin|

    ld   de,(rp_ady)
    ld   a,(rp_cm)
    ld   c,a
    call mul16x8u
    ld   (rp_p3),hl
    ld   (rp_p3+2),a            ; P3 = |dy| * |cos|

    ld   de,(rp_adx)
    ld   a,(rp_sm)
    ld   c,a
    call mul16x8u
    ld   (rp_p4),hl
    ld   (rp_p4+2),a            ; P4 = |dx| * |sin|

    ; ---- zv = (-1)^s1 P1 + (-1)^s2 P2 ----
    ld   a,(rp_dxs)
    ld   b,a
    ld   a,(rp_cs)
    xor  b
    ld   c,a                    ; C = s1
    ld   a,(rp_dys)
    ld   b,a
    ld   a,(rp_ss)
    xor  b                      ; A = s2
    xor  c
    jr   nz,rp_zsub             ; s1 != s2  ->  P1 - P2
    ld   hl,rp_p1
    ld   de,rp_p2
    call add24
    jr   rp_zsig
rp_zsub
    ld   hl,rp_p2
    ld   de,rp_p1
    call sub24                  ; (rp_t) = P1 - P2
rp_zsig
    ld   a,c
    or   a
    call nz,neg24
    call shr7
    ld   (rp_zv),hl

    ; ---- xv = (-1)^s3 P3 - (-1)^s4 P4 ----
    ld   a,(rp_dys)
    ld   b,a
    ld   a,(rp_cs)
    xor  b
    ld   c,a                    ; C = s3
    ld   a,(rp_dxs)
    ld   b,a
    ld   a,(rp_ss)
    xor  b                      ; A = s4
    xor  c
    jr   z,rp_xsub              ; s3 == s4  ->  P3 - P4
    ld   hl,rp_p3
    ld   de,rp_p4
    call add24
    jr   rp_xsig
rp_xsub
    ld   hl,rp_p4
    ld   de,rp_p3
    call sub24                  ; (rp_t) = P3 - P4
rp_xsig
    ld   a,c
    or   a
    call nz,neg24
    call shr7
    ld   (rp_xv),hl
    ret


; --- 24-bit helpers -----------------------------------------------------
add24                           ; (rp_t) = (DE) + (HL)
    ld   a,(de)
    add  a,(hl)
    ld   (rp_t),a
    inc  hl
    inc  de
    ld   a,(de)
    adc  a,(hl)
    ld   (rp_t+1),a
    inc  hl
    inc  de
    ld   a,(de)
    adc  a,(hl)
    ld   (rp_t+2),a
    ret

sub24                           ; (rp_t) = (DE) - (HL)
    ld   a,(de)
    sub  (hl)
    ld   (rp_t),a
    inc  hl
    inc  de
    ld   a,(de)
    sbc  a,(hl)
    ld   (rp_t+1),a
    inc  hl
    inc  de
    ld   a,(de)
    sbc  a,(hl)
    ld   (rp_t+2),a
    ret

neg24                           ; (rp_t) = -(rp_t)
    ld   hl,(rp_t)
    ld   a,(rp_t+2)
    ld   b,a
    xor  a
    sub  l
    ld   l,a
    ld   a,0
    sbc  a,h
    ld   h,a
    ld   a,0
    sbc  a,b
    ld   (rp_t),hl
    ld   (rp_t+2),a
    ret

shr7                            ; HL = round((rp_t) / 128), signed
    ld   hl,(rp_t)
    ld   a,(rp_t+2)
    ld   de,64
    add  hl,de
    adc  a,0
    add  hl,hl                  ; <<1, then keep the top 16 bits = >>7
    rla
    ld   l,h
    ld   h,a
    ret


; ---------------------------------------------------------------------
;  LATTICE ROTATOR
;
;  Every wall-face endpoint sits on an INTEGER lattice point, so
;    dx = jx - fx,  dy = jy - fy      jx,jy integer, fx,fy the player's
;                                     fractional cell position
;  and the transform becomes affine in (jx, jy):
;
;    zv = zv0 + jx*cos + jy*sin
;    xv = xv0 + jy*cos - jx*sin       zv0,xv0 = rotate(-fx, -fy)
;
;  rot_setup builds jx*cos and jx*sin for jx = -8..+8 once per frame (a
;  17-entry table each, written with PUSH), then every endpoint costs four
;  table reads and three 16-bit adds -- no multiply at all.
;
;  rot_setup   in: (rp_ang), (rp_fx), (rp_fy)   [fx,fy = Q0.8 fractions]
;  rot_lattice in: B = jx+8 (0..16), C = jy+8   out: (rp_xv), (rp_zv)
; ---------------------------------------------------------------------
rot_setup
    ld   (rs_sp),sp
    ld   a,(rp_ang)
    add  a,a
    ld   l,a
    ld   h,COSQ88/256
    ld   e,(hl)
    inc  l
    ld   d,(hl)                 ; DE = round(cos*256), signed
    ld   h,d
    ld   l,e
    add  hl,hl
    add  hl,hl
    add  hl,hl                  ; HL = 8*cos
    ld   sp,JTAB+34
    ld   b,17
rs_jc
    push hl
    or   a
    sbc  hl,de
    djnz rs_jc

    ld   a,(rp_ang)
    add  a,a
    ld   l,a
    ld   h,SINQ88/256
    ld   e,(hl)
    inc  l
    ld   d,(hl)                 ; DE = round(sin*256), signed
    ld   h,d
    ld   l,e
    add  hl,hl
    add  hl,hl
    add  hl,hl
    ld   sp,JTAB+68
    ld   b,17
rs_js
    push hl
    or   a
    sbc  hl,de
    djnz rs_js
    ld   sp,(rs_sp)

    ld   a,(rp_fx)              ; dx = -fx
    ld   l,a
    ld   h,0
    xor  a
    sub  l
    ld   l,a
    sbc  a,a
    sub  h
    ld   h,a
    ld   (rp_dx),hl
    ld   a,(rp_fy)              ; dy = -fy
    ld   l,a
    ld   h,0
    xor  a
    sub  l
    ld   l,a
    sbc  a,a
    sub  h
    ld   h,a
    ld   (rp_dy),hl
    call rotate_point
    ld   hl,(rp_xv)
    ld   (rp_xv0),hl
    ld   hl,(rp_zv)
    ld   (rp_zv0),hl
    ret


rot_lattice                     ; B = jx+8, C = jy+8
    ; zv = zv0 + JC[jx] + JS[jy]
    ld   h,JTAB/256
    ld   a,b
    add  a,a
    ld   l,a
    ld   e,(hl)
    inc  l
    ld   d,(hl)                 ; DE = JC[jx]
    ld   hl,(rp_zv0)
    add  hl,de
    ex   de,hl                  ; DE = zv0 + JC[jx]
    ld   a,c
    add  a,a
    add  a,34
    ld   l,a
    ld   h,JTAB/256
    ld   a,(hl)
    inc  l
    ld   h,(hl)
    ld   l,a                    ; HL = JS[jy]
    add  hl,de
    ld   (rp_zv),hl
    ; xv = xv0 + JC[jy] - JS[jx]
    ld   h,JTAB/256
    ld   a,c
    add  a,a
    ld   l,a
    ld   e,(hl)
    inc  l
    ld   d,(hl)                 ; DE = JC[jy]
    ld   hl,(rp_xv0)
    add  hl,de
    ex   de,hl                  ; DE = xv0 + JC[jy]
    ld   a,b
    add  a,a
    add  a,34
    ld   l,a
    ld   h,JTAB/256
    ld   a,(hl)
    inc  l
    ld   h,(hl)
    ld   l,a                    ; HL = JS[jx]
    ex   de,hl
    or   a
    sbc  hl,de
    ld   (rp_xv),hl
    ret


; ---------------------------------------------------------------------
;  variables
; ---------------------------------------------------------------------
m_sgn    db 0
rs_sp    dw 0
rp_dx    dw 0
rp_dy    dw 0
rp_ang   db 0
rp_fx    db 0
rp_fy    db 0
rp_xv    dw 0
rp_zv    dw 0
rp_xv0   dw 0
rp_zv0   dw 0
rp_cm    db 0
rp_sm    db 0
rp_cs    db 0
rp_ss    db 0
rp_dxs   db 0
rp_dys   db 0
rp_adx   dw 0
rp_ady   dw 0
rp_p1    ds 3
rp_p2    ds 3
rp_p3    ds 3
rp_p4    ds 3
rp_t     ds 3
