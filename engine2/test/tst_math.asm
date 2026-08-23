; =====================================================================
;  engine2/test/tst_math.asm -- emulator harness for the math primitives
;
;  Two kinds of entry point, both entered with set_pc():
;
;    t_*   BATCH FUNCTIONAL TEST.  Reads (BT_N) records from BT_IN, writes
;          results to BT_OUT, stores #AA at BT_DONE and spins.
;    m_*   TIMING LOOP.  Zeroes a 24-bit counter at CTR and loops forever
;          doing "set up args / call TRAMP / bump counter".  TRAMP is a
;          3-byte JP that the driver points either at the routine under
;          test or at a bare RET, so the loop overhead cancels exactly.
; =====================================================================

BT_IN    equ #7000
BT_OUT   equ #7800
BT_N     equ #7E00          ; byte, record count
BT_DONE  equ #7E01
CTR      equ #7E02          ; 3 bytes
ARGS     equ #7E08          ; 8 bytes of fixed operands for the timing loops
TRAMP    equ #7E10          ; 3 bytes: JP <routine under test>
TSTACK   equ #7FC0

    include "mathdata.inc"

    org #6000

; ---------------------------------------------------------------------
;  batch functional tests
; ---------------------------------------------------------------------
t_mul8x8                        ; rec: a,b -> lo,hi
    di
    ld   sp,TSTACK
    call bt_init
tb8_l
    ld   hl,(bt_ip)
    ld   a,(hl)
    inc  hl
    ld   c,(hl)
    inc  hl
    ld   (bt_ip),hl
    call mul8x8u
    ld   de,(bt_op)
    ex   de,hl
    ld   (hl),e
    inc  hl
    ld   (hl),d
    inc  hl
    ld   (bt_op),hl
    call bt_next
    jr   nz,tb8_l
    jp   bt_end

t_mul8x8i                       ; same, against the interleaved word table
    di
    ld   sp,TSTACK
    call bt_init
tb8i_l
    ld   hl,(bt_ip)
    ld   a,(hl)
    inc  hl
    ld   c,(hl)
    inc  hl
    ld   (bt_ip),hl
    call mul8x8i
    ld   de,(bt_op)
    ex   de,hl
    ld   (hl),e
    inc  hl
    ld   (hl),d
    inc  hl
    ld   (bt_op),hl
    call bt_next
    jr   nz,tb8i_l
    jp   bt_end

t_mul16x8u                      ; rec: alo,ahi,b -> p0,p1,p2
    di
    ld   sp,TSTACK
    call bt_init
tb16u_l
    ld   hl,(bt_ip)
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    inc  hl
    ld   c,(hl)
    inc  hl
    ld   (bt_ip),hl
    call mul16x8u
    call bt_st24
    call bt_next
    jr   nz,tb16u_l
    jp   bt_end

t_mul16x8s                      ; rec: alo,ahi,b -> p0,p1,p2
    di
    ld   sp,TSTACK
    call bt_init
tb16s_l
    ld   hl,(bt_ip)
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    inc  hl
    ld   c,(hl)
    inc  hl
    ld   (bt_ip),hl
    call mul16x8s
    call bt_st24
    call bt_next
    jr   nz,tb16s_l
    jp   bt_end

t_recip                         ; rec: zvlo,zvhi -> rlo,rhi
    di
    ld   sp,TSTACK
    call bt_init
trc_l
    ld   hl,(bt_ip)
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    inc  hl
    ld   (bt_ip),hl
    ex   de,hl
    call recip_zv
    ld   de,(bt_op)
    ex   de,hl
    ld   (hl),e
    inc  hl
    ld   (hl),d
    inc  hl
    ld   (bt_op),hl
    call bt_next
    jr   nz,trc_l
    jp   bt_end

t_rotate                        ; rec: dxlo,dxhi,dylo,dyhi,ang -> xv,zv
    di
    ld   sp,TSTACK
    call bt_init
trt_l
    ld   hl,(bt_ip)
    ld   de,rp_dx
    ld   bc,5
    ldir                        ; rp_dx,rp_dy,rp_ang are contiguous
    ld   (bt_ip),hl
    call rotate_point
    call bt_st_xvzv
    call bt_next
    jr   nz,trt_l
    jp   bt_end

t_lattice                       ; rec: ang,fx,fy,jx+8,jy+8 -> xv,zv
    di
    ld   sp,TSTACK
    call bt_init
tlt_l
    ld   hl,(bt_ip)
    ld   a,(hl)
    ld   (rp_ang),a
    inc  hl
    ld   a,(hl)
    ld   (rp_fx),a
    inc  hl
    ld   a,(hl)
    ld   (rp_fy),a
    inc  hl
    ld   a,(hl)
    ld   (tl_jx),a
    inc  hl
    ld   a,(hl)
    ld   (tl_jy),a
    inc  hl
    ld   (bt_ip),hl
    call rot_setup
    ld   a,(tl_jx)
    ld   b,a
    ld   a,(tl_jy)
    ld   c,a
    call rot_lattice
    call bt_st_xvzv
    call bt_next
    jr   nz,tlt_l
    jp   bt_end

; --- batch helpers -----------------------------------------------------
bt_init
    ld   hl,BT_IN
    ld   (bt_ip),hl
    ld   hl,BT_OUT
    ld   (bt_op),hl
    ld   a,(BT_N)
    ld   (bt_cnt),a
    xor  a
    ld   (BT_DONE),a
    ret

bt_next
    ld   a,(bt_cnt)
    dec  a
    ld   (bt_cnt),a
    ret

bt_st24                         ; store A:HL as 3 little-endian bytes
    ld   (bt_t24),hl
    ld   (bt_t24+2),a
    ld   de,(bt_op)
    ld   hl,bt_t24
    ld   bc,3
    ldir
    ld   (bt_op),de
    ret

bt_st_xvzv
    ld   de,(bt_op)
    ld   hl,(rp_xv)
    ex   de,hl
    ld   (hl),e
    inc  hl
    ld   (hl),d
    inc  hl
    ex   de,hl
    ld   hl,(rp_zv)
    ex   de,hl
    ld   (hl),e
    inc  hl
    ld   (hl),d
    inc  hl
    ld   (bt_op),hl
    ret

bt_end
    ld   a,#AA
    ld   (BT_DONE),a
    di
bt_spin
    jr   bt_spin

; ---------------------------------------------------------------------
;  timing loops
; ---------------------------------------------------------------------
m_mul8x8
    di
    ld   sp,TSTACK
    call tm_init
mm8_l
    ld   a,(ARGS+1)
    ld   c,a
    ld   a,(ARGS)
    call TRAMP
    call ctr_inc
    jr   mm8_l

m_mul16x8
    di
    ld   sp,TSTACK
    call tm_init
mm16_l
    ld   de,(ARGS)
    ld   a,(ARGS+2)
    ld   c,a
    call TRAMP
    call ctr_inc
    jr   mm16_l

m_recip
    di
    ld   sp,TSTACK
    call tm_init
mrc_l
    ld   hl,(ARGS)
    call TRAMP
    call ctr_inc
    jr   mrc_l

m_rotate
    di
    ld   sp,TSTACK
    call tm_init
mrt_l
    ld   hl,(ARGS)
    ld   (rp_dx),hl
    ld   hl,(ARGS+2)
    ld   (rp_dy),hl
    ld   a,(ARGS+4)
    ld   (rp_ang),a
    call TRAMP
    call ctr_inc
    jr   mrt_l

m_rotsetup
    di
    ld   sp,TSTACK
    call tm_init
mrs_l
    ld   a,(ARGS+4)
    ld   (rp_ang),a
    ld   a,(ARGS)
    ld   (rp_fx),a
    ld   a,(ARGS+1)
    ld   (rp_fy),a
    call TRAMP
    call ctr_inc
    jr   mrs_l

m_lattice
    di
    ld   sp,TSTACK
    call tm_init
    ld   a,(ARGS+4)
    ld   (rp_ang),a
    ld   a,(ARGS)
    ld   (rp_fx),a
    ld   a,(ARGS+1)
    ld   (rp_fy),a
    call rot_setup
mlt_l
    ld   a,(ARGS+2)
    ld   b,a
    ld   a,(ARGS+3)
    ld   c,a
    call TRAMP
    call ctr_inc
    jr   mlt_l

tm_init
    xor  a
    ld   (CTR),a
    ld   (CTR+1),a
    ld   (CTR+2),a
    ret

ctr_inc
    push af
    push hl
    ld   hl,(CTR)
    inc  hl
    ld   (CTR),hl
    ld   a,h
    or   l
    jr   nz,ci_x
    ld   a,(CTR+2)
    inc  a
    ld   (CTR+2),a
ci_x
    pop  hl
    pop  af
    ret

; The same quarter-square multiply against an INTERLEAVED word table
; (QSQ[i] at base+2i) instead of split low/high byte tables.  Assembled
; only so the layout decision can be measured rather than argued.
mul8x8i
    ld   b,a
    add  a,c
    ld   l,a
    ld   h,0
    rl   h
    add  hl,hl
    ld   de,QSQW
    add  hl,de
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    ld   a,b
    sub  c
    jr   nc,m8i_pos
    neg
m8i_pos
    ld   l,a
    ld   h,0
    add  hl,hl
    ld   bc,QSQW
    add  hl,bc
    ld   c,(hl)
    inc  hl
    ld   b,(hl)
    ex   de,hl
    or   a
    sbc  hl,bc
    ret

ret_only
    ret

; methodology self-check: exactly 10 NOPs, so us/call must come out at
; 10 + 5 (CALL) + 3 (RET) = 18.00 exactly, or the accounting is wrong.
ten_nops
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    ret

bt_ip    dw 0
bt_op    dw 0
bt_cnt   db 0
bt_t24   ds 3
tl_jx    db 0
tl_jy    db 0

    include "math.asm"
