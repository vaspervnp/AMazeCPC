; =====================================================================
;  engine2/src/hud2.asm -- the HUD: everything on the screen that is not
;  the 3D viewport.
;
;  The viewport is VP_BW x VP_H BYTES at (VP_BX, VP_Y) -- 40 x 96 at
;  (20, 0) in this build -- so the HUD is the two plates beside it and
;  the panel below it, scanlines VP_Y+VP_H .. 199.  Every pixel of it is
;  drawn HERE and no pixel of the viewport is ever touched (genhud.py
;  asserts that of every rectangle).
;
;      hud_init      once.  Says "neither buffer has a needle yet".
;      hud_setbuf    A = #C0 / #80, the buffer the next call paints.  Call
;                    it wherever frame_setbuf is called, with the same A.
;      hud_static    paint the furniture.  ONCE PER BUFFER, at startup.
;      hud_update    per frame, after frame_draw: bring this buffer's
;                    compass needle in line with (plr_a).
;      hud_force     make the next hud_update repaint whatever happens.
;
;  Both hud_static and hud_update need BANK 4 PAGED AT #4000 (they read
;  LINETAB) and INTERRUPTS OFF (hud_static's fill puts the screen pointer
;  in SP).  hud_static saves and restores SP itself; hud_update never
;  touches it.  Clobbers AF BC DE HL IX.
;
;  ------------------------------------------------------------------
;  MEASURED, engine2/tools/emu_hud.py, cycle-accurate CPC 6128, interrupts
;  off, 16-bit counter, empty-loop overhead (15.00 us) subtracted, method
;  calibrated to 100.08 us on 100 NOPs.  Verified first, byte for byte,
;  against genhud.py's model: the furniture (12160 bytes exact, 0 bytes of
;  the viewport touched) and then all 72 headings drawn IN SEQUENCE, so
;  every erase is checked as well as every draw.
;
;      hud_update, heading unchanged        20.0 us    0.03% of the frame
;      hud_update, heading changed        1360.2 us    1.70%
;      hud_static, once per buffer      101507.8 us    startup only
;
;  WHAT THAT MEANS FOR THE BUDGET.  The worst frame in the maze is 77.81 ms
;  (engine2/src/frame.asm) against 80.00, so 2.19 ms spare; a turning frame
;  spends 1.36 ms of that here and leaves 0.83 ms for the game layer.  The
;  HUD is therefore NOT free at the worst frame, and if the game layer ever
;  needs more than 0.8 ms the lever is below.
;
;  ------------------------------------------------------------------
;  WHY IT IS BUILT THIS WAY
;
;  THE FURNITURE IS DRAWN ONCE.  It is 62 rectangles and 19642 byte-writes
;  -- more than the whole viewport -- and it never changes, so it is
;  painted into each buffer at startup and then left alone.  The shipped
;  disc repainted its compass every frame and paid 4.6 ms for it
;  (src/main.asm): 5.8% of this build's budget, for four blocks that could
;  only ever show four directions.
;
;  WHAT CHANGES IS ONE NEEDLE, AND ONLY WHEN IT MOVES.  The dirty test is
;  not a flag but the truth: each buffer remembers WHICH HEADING is
;  currently drawn in it, and hud_update compares that with (plr_a).  Equal
;  -> return, 20 us, which is most frames.  Different -> take the old
;  needle down and put the new one up.  Two buffers, two remembered
;  headings, so a flip never shows a stale needle and there is no "repaint
;  it N times" counter to get wrong -- src/main.asm's hud_dirty is that
;  counter, and this replaces it.
;
;  ERASING IS A REPLAY, NOT A RECOMPUTATION.  hud_needle records the four
;  screen addresses it painted (8 bytes a buffer); hud_erase writes the
;  dial's background byte back over exactly those.  Deriving the old
;  heading again instead cost 1756 us against this 1360 -- the quadrant
;  flips, the table walk and four LINETAB lookups are the expensive part of
;  a needle, not the 28 bytes of pixels.
;
;  THE NEEDLE IS FOUR 2-BYTE BLOCKS, not a line: 14 scanlines of writes to
;  put it up, 14 to take it down.  It still resolves all 72 headings -- the
;  four blocks round differently, and genhud.py ASSERTS that the 72
;  pictures are 72 different pictures, and that every block of every one of
;  them lands on dial background so that the erase can never eat the rim,
;  a tick or the hub.
;
;  THE NEXT LEVER, if a turning frame ever has to be cheaper: 1008 us of
;  the 1360 is per-block bookkeeping (the quadrant flip, the table walk,
;  the LINETAB lookup), not pixels.  Pre-baking the four screen offsets for
;  all 72 headings instead of 19 quadrant entries would cut the repaint to
;  ~800 us, for 424 more bytes of table -- which this build does not have,
;  since the code has to fit under the working RAM at #2700.
;  ------------------------------------------------------------------
; =====================================================================

; Needs from vpcfg.inc:   VP_BX VP_BW VP_Y VP_H
; Needs from tab_equ.inc: LINETAB
; Needs from gen_hud.inc: HUDRECTS HUD_NRECT HUDNDL HUDDESC HUD_H0..H3 HUD_BG
;                         HUD_CXB HUD_CY HUD_NDOT HUD_NW
; Needs from march.asm:   plr_a          (the heading, 0..71)

    include "gen_hud.inc"

HR_N        equ 40                  ; the widest run the fill can do, in
                                    ; PUSH DE pairs: 80 bytes = the screen
    assert HUD_NW == 2              ; one block is exactly one PUSH DE wide
    assert HUD_NDOT == 4


; ---------------------------------------------------------------------
;  hud_init -- call once.  No table is precomputed: genhud.py did that.
; ---------------------------------------------------------------------
hud_init
    ld   a,#FF                      ; #FF = "no needle drawn in this buffer"
    ld   (hud_cur),a
    ld   (hud_cur+1),a
    ret


; ---------------------------------------------------------------------
;  hud_setbuf -- A = #C0 (front) or #80 (back).  Patches the two places a
;  screen address is assembled and selects that buffer's needle memory.
; ---------------------------------------------------------------------
hud_setbuf
    ld   (hr_bh+1),a
    ld   (hn_bh+1),a
    ld   hl,hud_cur
    ld   de,hud_rows
    cp   #C0
    jr   z,hs_front
    inc  hl                         ; the back buffer's heading ...
    ld   de,hud_rows+HUD_NDOT*2     ; ... and its block record
hs_front
    ld   (hud_cp),hl
    ld   (hud_rp),de
    ret


; ---------------------------------------------------------------------
;  hud_static -- paint the furniture into the current buffer.
;
;  HUDRECTS is 62 rectangles of db x, y, w, h, byte, back to front: the
;  plates, the bevel around the viewport, six readout slots, then the dial
;  (an ellipse cut into bands of equal half-width, so 74 scanlines of
;  circle are 24 rectangles), its ticks and its hub.  Startup only --
;  19642 bytes in 897 scanlines, 101.5 ms a buffer.  That is 5.2 us a byte
;  against bg.asm's 2.2, because only 39.3 ms of it is PUSH DE and 62.2 ms
;  is per-row setup -- 69 us a row, mostly the LINETAB lookup, which a
;  22-byte average run cannot amortise the way a 40-byte one does.  It runs
;  twice, at startup, so it is left alone.
; ---------------------------------------------------------------------
hud_static
    ld   (hud_sp),sp
    ld   hl,HUDRECTS
    ld   b,HUD_NRECT
hst_l
    ld   (hst_p),hl
    ld   a,(hl)
    inc  hl
    ld   (hr_x),a
    ld   a,(hl)
    inc  hl
    ld   (hr_y),a
    ld   a,(hl)
    inc  hl
    ld   (hr_w),a
    ld   a,(hl)
    inc  hl
    ld   (hr_h),a
    ld   a,(hl)
    ld   (hr_pen),a
    push bc
    call hud_rect
    pop  bc
    ld   hl,(hst_p)
    ld   de,5
    add  hl,de
    djnz hst_l
    ld   sp,(hud_sp)
    ld   hl,(hud_cp)                ; the needle is not furniture; it will
    ld   (hl),#FF                   ; be painted by the next hud_update
    ret


; ---------------------------------------------------------------------
;  hud_rect -- (hr_x) (hr_y) (hr_w) (hr_h) (hr_pen) -> the current buffer.
;
;  PUSH DE, two horizontally adjacent bytes for 4 us, is the fastest store
;  on the machine, so SP is the screen pointer.  The width is not known
;  until run time, so the run enters an unrolled block of HR_N pushes at
;  (HR_N - w/2) and leaves it through JP (IX) -- the same trick the shipped
;  span renderer uses, and the reason genhud.py insists every width is
;  even.  The entry address is computed ONCE per rectangle, not per row.
;
;  The caller must have saved SP.  Interrupts must be off.
; ---------------------------------------------------------------------
hud_rect
    ld   (hr_sp),sp                 ; SP becomes the screen pointer below,
    ld   a,(hr_h)                   ; so even RET needs it put back first
    or   a
    ret  z
    ld   (hr_rows),a                   ; rows left (B is needed elsewhere)
    ld   a,(hr_w)
    srl  a                          ; PUSH DE pairs
    ld   c,a
    ld   a,HR_N
    sub  c
    ld   l,a
    ld   h,0
    ld   de,HRPUSH
    add  hl,de
    ld   (hr_jp+1),hl               ; -> HRPUSH + (HR_N - w/2)
    ld   a,(hr_x)                   ; the run is filled BACKWARDS from its
    ld   c,a                        ; right end, so what SP wants is x + w
    ld   a,(hr_w)
    add  a,c
    ld   (hr_xw),a
    ld   a,(hr_y)
    ld   (hr_cy),a
    ld   a,(hr_pen)
    ld   d,a
    ld   e,a
    ld   ix,hr_ret

hr_row
    ld   a,(hr_cy)                  ; HL = LINETAB[y]
    ld   l,a
    ld   h,0
    add  hl,hl
    ld   bc,LINETAB
    add  hl,bc
    ld   c,(hl)
    inc  hl
    ld   h,(hl)
    ld   l,c
    ld   a,(hr_xw)                  ; ... + x + w
    add  a,l
    ld   l,a
    ld   a,h
    adc  a,0
    and  #3F                        ; LINETAB is written for #C000; the
hr_bh                               ; back buffer is the same offset at #80
    or   #C0
    ld   h,a
    ld   sp,hl
hr_jp
    jp   0                          ; patched -> HRPUSH + (HR_N - w/2)
hr_ret
    ld   hl,hr_cy
    inc  (hl)
    ld   hl,hr_rows
    dec  (hl)
    jp   nz,hr_row
    ld   sp,(hr_sp)
    ret


; ---------------------------------------------------------------------
;  hud_update -- the whole per-frame cost of the HUD.
;
;  IN   (plr_a) 0..71, and hud_setbuf called with this buffer.
;  OUT  this buffer's needle shows (plr_a).
;  Returns in 20 us when it already does, which is most frames.
; ---------------------------------------------------------------------
hud_update
    ld   hl,(hud_cp)
    ld   a,(plr_a)
    cp   (hl)
    ret  z                          ; the common case: nothing to do
    ld   (hu_a),a
    ld   a,(hl)
    cp   #FF                        ; is there a needle in this buffer?
    call nz,hud_erase               ; then take it down, from the record
    ld   a,(hu_a)
    ld   hl,(hud_cp)
    ld   (hl),a
    jp   hud_needle

; force a repaint even if the heading has not changed (after hud_static, or
; after anything else has scribbled on the dial)
hud_force
    ld   hl,(hud_cp)
    ld   (hl),#FF
    ret


; ---------------------------------------------------------------------
;  hud_needle -- A = heading 0..71 -> paint that needle, and RECORD where
;  each of its blocks went, so that hud_erase can take it down again
;  without recomputing anything.
;
;  HUDNDL holds headings 0..18 only; the dial is symmetric about both its
;  axes, so the other 54 are sign flips (genhud.py asserts that against the
;  direct trigonometry for all 72).  C keeps the two flip bits:
;
;      a in [ 0,18]  i = a       ( dx,  dy)      bits 00
;      a in [19,35]  i = 36 - a  ( dx, -dy)      bits 10
;      a in [36,54]  i = a - 36  (-dx, -dy)      bits 11
;      a in [55,71]  i = 72 - a  (-dx,  dy)      bits 01
;
;  Clobbers AF BC DE HL IX.  Does not touch SP.
; ---------------------------------------------------------------------
hud_needle
    ld   ix,(hud_rp)                ; where this buffer's record lives
    ld   hl,HUDDESC
    ld   (hn_dp),hl
    ld   c,0
    cp   19
    jr   c,hn_idx
    cp   36
    jr   c,hn_qy
    cp   55
    jr   c,hn_qxy
    ld   c,1                        ; 55..71: mirror in x
    neg
    add  a,72
    jr   hn_idx
hn_qy
    ld   c,2                        ; 19..35: mirror in y
    neg
    add  a,36
    jr   hn_idx
hn_qxy
    ld   c,3                        ; 36..54: turn 180 degrees
    sub  36
hn_idx
    ld   l,a
    ld   h,0
    add  hl,hl                      ; HUDNDL + a * (HUD_NDOT * 2)
    add  hl,hl
    add  hl,hl
    ld   de,HUDNDL
    add  hl,de
    ld   (hn_tp),hl
    ld   a,HUD_NDOT
    ld   (hn_dn),a

hn_dot
    ld   hl,(hn_tp)
    ld   a,(hl)                     ; dx, bytes from the dial centre
    inc  hl
    bit  0,c
    jr   z,hn_nox
    neg
hn_nox
    add  a,HUD_CXB-HUD_NW/2
    ld   b,a                        ; B = x, the block's left byte
    ld   a,(hl)                     ; dy, scanlines
    inc  hl
    ld   (hn_tp),hl
    bit  1,c
    jr   z,hn_noy
    neg
hn_noy
    add  a,HUD_CY
    ld   e,a                        ; E = the block's centre scanline
    ld   hl,(hn_dp)
    ld   a,(hl)                     ; its height, always odd
    inc  hl
    ld   (hn_h),a
    ld   d,a
    ld   a,(hl)
    inc  hl
    ld   (hn_dp),hl
    ld   (hn_pen),a
    dec  d                          ; top = centre - (h-1)/2
    srl  d
    ld   a,e
    sub  d
    call hn_blk
    ld   hl,hn_dn
    dec  (hl)
    jp   nz,hn_dot
    ret


; ---------------------------------------------------------------------
;  hn_blk -- A = top scanline, B = left byte, (hn_h) rows of (hn_pen),
;  HUD_NW = 2 bytes wide.  Writes the address it worked out to (IX) and
;  steps IX on: that record is the whole of hud_erase's input.
;  Preserves C.
; ---------------------------------------------------------------------
hn_blk
    ld   l,a
    ld   h,0
    add  hl,hl
    ld   de,LINETAB
    add  hl,de
    ld   e,(hl)
    inc  hl
    ld   d,(hl)
    ld   a,e
    add  a,b
    ld   l,a
    ld   a,d
    adc  a,0
    and  #3F
hn_bh
    or   #C0                        ; patched by hud_setbuf
    ld   h,a
    ld   (ix+0),l
    ld   (ix+1),h
    inc  ix
    inc  ix
    ld   a,(hn_pen)
    ld   e,a
    ld   a,(hn_h)
    ld   b,a
    ; fall through

; ---------------------------------------------------------------------
;  hn_rows -- HL = top left byte, B = rows, E = the byte to write.
;  Two bytes per row, HUD_NW wide.  Preserves C and IX.
; ---------------------------------------------------------------------
hn_rows
    ld   (hl),e
    inc  hl
    ld   (hl),e
    dec  hl
    ; next scanline.  Bits 3..5 of H are exactly (y & 7) -- the rest of the
    ; offset, row*80 + x, is always < #800 -- so if adding 8 clears them the
    ; scanline has left the character row: undo the carry it made into bit 6
    ; and step on by one row of 80 bytes instead.
    ld   a,h
    add  a,8
    ld   h,a
    and  #38
    jr   nz,hn_next
    ld   a,h
    sub  #40
    ld   h,a
    ld   a,l
    add  a,80
    ld   l,a
    jr   nc,hn_next
    inc  h
hn_next
    djnz hn_rows
    ret


; ---------------------------------------------------------------------
;  hud_erase -- repaint the needle that IS in this buffer in the dial's
;  own background, from the four addresses hud_needle recorded.
;
;  Erasing this way rather than by re-deriving the old heading is worth
;  ~450 us of the repaint: the addresses cost nothing to keep (8 bytes a
;  buffer) and the heading, the quadrant flips, the table walk and four
;  LINETAB lookups all disappear.  It is also strictly safer -- what comes
;  down is exactly what went up.
;
;  Unrolled because HUD_NDOT is 4 and the heights are constants; the
;  assert above is what makes that legal.
; ---------------------------------------------------------------------
hud_erase
    ld   ix,(hud_rp)
    ld   e,HUD_BG
    ld   l,(ix+0)
    ld   h,(ix+1)
    ld   b,HUD_H0
    call hn_rows
    ld   l,(ix+2)
    ld   h,(ix+3)
    ld   b,HUD_H1
    call hn_rows
    ld   l,(ix+4)
    ld   h,(ix+5)
    ld   b,HUD_H2
    call hn_rows
    ld   l,(ix+6)
    ld   h,(ix+7)
    ld   b,HUD_H3
    jp   hn_rows


; ------------------------------------------------------------- state ------
hud_cur     db #FF,#FF              ; heading drawn in #C000 / in #8000
hud_cp      dw hud_cur              ; -> the entry for the current buffer
hud_sp      dw 0
hu_a        db 0                    ; the heading being moved to

hst_p       dw 0                    ; walks HUDRECTS
hr_x        db 0
hr_y        db 0
hr_w        db 0
hr_h        db 0
hr_pen      db 0
hr_rows        db 0                    ; rows left
hr_cy       db 0                    ; row being painted
hr_xw       db 0                    ; x + w, where the backwards run starts
hr_sp       dw 0

hud_rp      dw hud_rows             ; -> the current buffer's record
hud_rows    defs HUD_NDOT*2*2       ; 4 block addresses, per buffer

hn_tp       dw 0                    ; walks HUDNDL
hn_dp       dw 0                    ; walks the descriptor (height, byte)
hn_dn       db 0                    ; blocks left
hn_h        db 0
hn_pen      db 0

; ---------------------------------------------------------------------
;  The unrolled PUSH block.  Entering at (HR_N - n) executes exactly n
;  pushes -- 2n bytes -- and then returns through IX.
; ---------------------------------------------------------------------
HRPUSH
    repeat HR_N
    push de
    rend
    jp   (ix)
