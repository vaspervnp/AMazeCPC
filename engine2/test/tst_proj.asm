; =====================================================================
;  engine2/test/tst_proj.asm
;
;  Emulator harness for src/project.asm.  Three jobs:
;
;   run_list   process a list of face records and dump the quads, so the
;              driver can assert the Z80 is BIT-EXACT with projmodel.py
;   tm_*       time proj_face / proj_setup by counting iterations for a
;              known number of frames, with an empty-loop control so the
;              loop overhead can be subtracted
;
;  Interrupts are off throughout; SP is parked below the code.
; =====================================================================

    include "tab_equ_test.inc"

STACK   equ #7FF0

    org #8000

; ---------------------------------------------------------------------
;  run_list -- (n_faces) records of 5 bytes at IN_BUF -> 7 bytes each
;              at OUT_BUF.  Sets (done) = #FF when finished.
; ---------------------------------------------------------------------
run_list
    di
    ld   sp,STACK
    xor  a
    ld   (done),a
    call proj_setup
    ld   hl,OUT_BUF
    ld   (outp),hl
    ld   a,(n_faces)
    or   a
    jr   z,rl_end
    ld   b,a
    ld   hl,IN_BUF
rl_loop
    push bc
    push hl
    ld   de,pf_i0
    ld   bc,5
    ldir
    call proj_face_ij
    ld   hl,pf_ok
    ld   de,(outp)
    ld   bc,1+PFRECSZ           ; pf_ok, then the quad record
    ldir
    ld   (outp),de
    pop  hl
    ld   bc,5
    add  hl,bc
    pop  bc
    djnz rl_loop
rl_end
    ld   a,#FF
    ld   (done),a
rl_halt
    jr   rl_halt

; ---------------------------------------------------------------------
;  timing loops.  us/iteration = frames * 20000 / (counter)
; ---------------------------------------------------------------------
tm_face
    di
    ld   sp,STACK
    call proj_setup
    ld   hl,0
    ld   (counter),hl
tmf
    call proj_face_ij
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tmf

tm_empty
    di
    ld   sp,STACK
    call proj_setup
    ld   hl,0
    ld   (counter),hl
tme
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tme

; ---------------------------------------------------------------------
;  tm_facev -- proj_face fed VIEW-SPACE endpoints, i.e. what it costs once
;  the march carries (xv, z) itself.  proj_face clobbers its input block,
;  so the loop restores it from V_SAVE; tm_facev0 is the same loop with
;  only the restore, so the driver can subtract it.
; ---------------------------------------------------------------------
mkview
    call proj_setup
    ld   a,(pf_i0)
    ld   b,a
    ld   a,(pf_j0)
    ld   c,a
    call lat_view
    ld   (V_SAVE),hl
    ld   (V_SAVE+2),de
    ld   a,(pf_i1)
    ld   b,a
    ld   a,(pf_j1)
    ld   c,a
    call lat_view
    ld   (V_SAVE+4),hl
    ld   (V_SAVE+6),de
    ret

tm_facev
    di
    ld   sp,STACK
    call mkview
    ld   hl,0
    ld   (counter),hl
tmfv
    ld   hl,V_SAVE
    ld   de,c_xa
    ld   bc,8
    ldir
    call proj_face
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tmfv

tm_facev0
    di
    ld   sp,STACK
    call mkview
    ld   hl,0
    ld   (counter),hl
tmfv0
    ld   hl,V_SAVE
    ld   de,c_xa
    ld   bc,8
    ldir
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tmfv0

; pf_side alone (the transitional side reject the new march makes free);
; TM_FACEV0 is its matched empty loop.
tm_side
    di
    ld   sp,STACK
    call mkview
    ld   hl,0
    ld   (counter),hl
tmsd
    ld   hl,V_SAVE
    ld   de,c_xa
    ld   bc,8
    ldir
    call pf_side
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tmsd

tm_setup
    di
    ld   sp,STACK
    ld   hl,0
    ld   (counter),hl
tms
    call proj_setup
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tms

; ---------------------------------------------------------------------
;  micro-benchmarks for the pieces, same protocol
; ---------------------------------------------------------------------
tm_latview
    di
    ld   sp,STACK
    call proj_setup
    ld   hl,0
    ld   (counter),hl
tmv
    ld   a,(pf_i0)
    ld   b,a
    ld   a,(pf_j0)
    ld   c,a
    call lat_view
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tmv

tm_projpt
    di
    ld   sp,STACK
    call proj_setup
    ld   hl,0
    ld   (counter),hl
tmp
    ld   hl,(c_xa)
    ld   de,(c_za)
    call proj_pt
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tmp

tm_lerp
    di
    ld   sp,STACK
    ld   hl,0
    ld   (counter),hl
tml
    call lerp
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tml

tm_mul168
    di
    ld   sp,STACK
    ld   hl,0
    ld   (counter),hl
tmm
    ld   de,(l_a)
    ld   a,(l_r)
    ld   c,a
    call mul16x8u
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tmm

; ---------------------------------------------------------------------
;  tm_batch -- walk the WHOLE face list over and over, counting once per
;  face, so the average is taken over a real frame's mix of clipped,
;  unclipped and rejected faces.  tm_batch0 is the same loop with the
;  call removed, and gives the harness overhead to subtract.
; ---------------------------------------------------------------------
tm_batch
    di
    ld   sp,STACK
    call proj_setup
    ld   hl,0
    ld   (counter),hl
tb_out
    ld   a,(n_faces)
    ld   b,a
    ld   hl,IN_BUF
tb_loop
    push bc
    push hl
    ld   de,pf_i0
    ld   bc,5
    ldir
    call proj_face_ij
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    pop  hl
    ld   bc,5
    add  hl,bc
    pop  bc
    djnz tb_loop
    jr   tb_out

tm_batch0
    di
    ld   sp,STACK
    call proj_setup
    ld   hl,0
    ld   (counter),hl
tb0_out
    ld   a,(n_faces)
    ld   b,a
    ld   hl,IN_BUF
tb0_loop
    push bc
    push hl
    ld   de,pf_i0
    ld   bc,5
    ldir
    call tb_ret
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    pop  hl
    ld   bc,5
    add  hl,bc
    pop  bc
    djnz tb0_loop
    jr   tb0_out
tb_ret
    ret

; calibration: the same loop plus exactly 100 stretched NOPs, so the
; driver can prove one counted unit really is one CPC microsecond.
tm_calib
    di
    ld   sp,STACK
    ld   hl,0
    ld   (counter),hl
tmc
    repeat 100
    nop
    rend
    ld   hl,(counter)
    inc  hl
    ld   (counter),hl
    jr   tmc

; ---------------------------------------------------------------------
counter dw 0
V_SAVE  ds 8
done    db 0
n_faces db 0
outp    dw 0

    include "project.asm"

    align 256
IN_BUF  ds 5*128
    align 256
OUT_BUF ds 7*128
