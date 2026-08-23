; =====================================================================
;  engine2/src/bg.asm -- the background: ceiling and floor bands.
;
;  WHY THIS IS A RECTANGLE AND NOT A HORIZON POLYGON.  The player turns
;  freely but cannot pitch, and the camera sits exactly at wall
;  mid-height, so the horizon is the SAME scanline whatever the heading:
;  CYH.  Ceiling is therefore the solid rectangle [VP_Y, VP_Y+CYH) and
;  floor the solid rectangle [VP_Y+CYH, VP_Y+VP_H), both the full VP_BW
;  bytes wide.  No slope, no per-column work, no horizon table.
;
;  It is painted FIRST, before the quads, so it doubles as the buffer
;  clear -- every pixel of the viewport is written exactly once here and
;  the wall quads then overwrite whatever they cover.  That is why there
;  is no separate cls.
;
;  DEPTH BANDS.  A flat ceiling of one colour reads as a void, so each
;  half is optionally split in two: the scanline y maps to a ground
;  distance z = (FOCAL_V/2) / |y - CYH| (a point on the floor plane, half
;  a cell below the eye), so a horizontal split IS a depth split.  The
;  band edge sits at |y - CYH| = CYH/2, i.e. z = 2 cells.  Splitting
;  costs one extra list entry per half and nothing per scanline -- see
;  the measurement below -- so it is on by default.
;
;    BG_SEGS4  y 0..23 CEIL_NEAR, 24..47 CEIL_FAR,
;              y 48..71 FLOOR_FAR, 72..95 FLOOR_NEAR   (the default)
;    BG_SEGS2  one band each, for the measurement and for the flat look
;
;  THE FILL.  PUSH DE, two horizontally adjacent bytes for 4 us, is the
;  fastest store on the machine, so SP is the screen pointer and
;  interrupts must be off.  Two things make this cheaper than the shipped
;  span renderer's rect path:
;
;    * the run is VP_BW bytes for every line of every band -- a build-time
;      constant -- so the PUSH block is INLINED into the loop instead of
;      being entered through PUSHENT.  No `jp PUSHBLK`, no `jp (ix)` to
;      come back: 5 us off every scanline.
;    * the eight scanlines of a character row are unrolled, so the +&800
;      step is straight-line code and the loop test is paid once per ROW,
;      not per line.  That was worth another 740 us a frame, measured:
;      the rolled version of this same fill came out at 9956 us.
;
;  MEASURED, engine2/tools/emu_bg.py, cycle-accurate CPC 6128, interrupts
;  off, 16-bit counter, empty-loop overhead 15.00 us subtracted, method
;  calibrated to 100.08 us on 100 NOPs:
;
;      44 x 96 bytes, 2 bands        9216.2 us
;      44 x 96 bytes, 4 bands        9269.3 us   <- +53 us, 0.07% of the
;                                                   frame: the depth bands
;                                                   are free, keep them
;      theoretical floor (2 us/byte) 8448.0 us
;
;      48 x 128 bytes, 4 bands      13334.4 us  <- the bigger viewport, by
;                                                  editing vpcfg.inc and
;                                                  NOTHING else; 16.7% of
;                                                  the frame
;
;      40 x  96 bytes, 4 bands       8500.0 us  <- WHAT THIS BUILD NOW
;                                                  SHIPS.  vpcfg.inc moved
;                                                  to 40 wide after whole
;                                                  frames were measured
;                                                  (engine2/src/frame.asm);
;                                                  10.6% of the 80 ms frame
;
;  So 96.6 us per scanline, 2.194 us per byte, 9.7% over the PUSH DE
;  floor, and 11.6% of the 80 ms (4 vsync) frame budget.  Where the 9.7%
;  goes, per character row: 8 x (LD SP,HL 2 us) + 7 x (H step 4 us) +
;  (row step 8 us) + (DEC B / JP NZ 4 us) = 40 us on 720 us of PUSH, plus
;  26.5 us of setup per band and ~35 us of call/entry/exit.  Predicted
;  9261 us against 9269 measured.
;
;  IN   (bg_bufh)  #C0 or #80, the buffer to paint
;       (bg_list)  BG_SEGS4 or BG_SEGS2
;       bg_init    must have been called once, with bank 4 paged in, to
;                  copy BANDPEN into the lists (bg_fill itself never
;                  touches the table bank, so the caller may page it out)
;  OUT  the viewport rectangle painted, SP restored.
;  Clobbers AF BC DE HL IX.  Interrupts must be OFF.
; =====================================================================

; Needs from vpcfg.inc: VP_BW VP_H VP_Y VP_BOFF CYH
; Needs from tab_equ.inc: BANDPEN

BG_HALF     equ CYH/8                   ; ceiling char rows = floor char rows
BG_QTR      equ CYH/16                  ; rows above the z = 2 cell split

    assert CYH*2 == VP_H                ; no pitch: the horizon is CYH
    assert VP_BW == MAXPUSH*2           ; the inlined run is the full width
    ; The loop paints whole character rows, so the band edges -- and the
    ; top of the viewport -- must be multiples of 8 scanlines.  They are
    ; anyway: a mode 0 viewport that is not row aligned wastes the CRTC.
    assert (VP_Y&7) == 0
    assert (CYH&15) == 0                ; VP_H a multiple of 32 scanlines


bg_fill
    ld   (bg_spsav),sp
    ; HL = address ONE PAST the right end of scanline VP_Y's run; PUSH
    ; walks backwards, so this is what SP wants.
    ld   hl,VP_BOFF+VP_BW
    ld   a,(bg_bufh)
    add  a,h                    ; buffer base is &C000 or &8000, and the
    ld   h,a                    ; offset is under &4000, so OR would do
    ld   ix,(bg_list)

bg_seg
    ld   b,(ix+0)               ; CHARACTER ROWS in this band, 0 = end
    ld   a,b
    or   a
    jp   z,bg_done
    ld   a,(ix+1)               ; the band's solid mode-0 byte
    ld   d,a
    ld   e,a
    inc  ix
    inc  ix

bg_row
    repeat 7                    ; the first seven scanlines of the row:
    ld   sp,hl                  ;   2 us
    repeat MAXPUSH
    push de                     ;   4 us / 2 bytes -- the fill budget
    rend
    ld   a,h                    ;   4 us, +&800 = the next scanline inside
    add  a,8                    ;   this character row
    ld   h,a
    rend
    ld   sp,hl                  ; the eighth needs no +&800: the row step
    repeat MAXPUSH              ; below folds it in
    push de
    rend
    ld   a,l                    ; next character row is -&3800 + 80, and
    add  a,80                   ; -&3800 is &C800 in 16 bits
    ld   l,a
    ld   a,h
    adc  a,#C8
    ld   h,a
    dec  b
    jp   nz,bg_row
    jp   bg_seg

bg_done
    ld   sp,(bg_spsav)
    ret


; ---------------------------------------------------------------------
;  bg_init -- copy the four band pens out of BANDPEN into the lists.
;  Bank 4 must be paged at &4000.  Call once at startup.
; ---------------------------------------------------------------------
bg_init
    ld   hl,BANDPEN             ; CEIL_NEAR CEIL_FAR FLOOR_FAR FLOOR_NEAR
    ld   a,(hl)
    ld   (bg_s4+1),a            ; ceiling near
    ld   (bg_s2+1),a            ; the flat ceiling uses the near pen
    inc  hl
    ld   a,(hl)
    ld   (bg_s4+3),a            ; ceiling far
    inc  hl
    ld   a,(hl)
    ld   (bg_s4+5),a            ; floor far
    inc  hl
    ld   a,(hl)
    ld   (bg_s4+7),a            ; floor near
    ld   (bg_s2+3),a            ; the flat floor uses the near pen
    ret


; ------------------------------------------------------- band lists ------
;  db character rows (8 scanlines each), db solid byte ... db 0
BG_SEGS4    equ bg_s4
bg_s4       db BG_QTR,0
            db BG_HALF-BG_QTR,0
            db BG_HALF-BG_QTR,0
            db BG_QTR,0
            db 0

BG_SEGS2    equ bg_s2
bg_s2       db BG_HALF,0
            db BG_HALF,0
            db 0

bg_list     dw BG_SEGS4
bg_bufh     db #C0
bg_spsav    dw 0
