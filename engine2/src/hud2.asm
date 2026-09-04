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
;      hud_ammo      A = rounds left; bring this buffer's readout in line
;                    with it.  Same dirty rule, same two-buffer memory.
;      hud_scan      A = the packed bearing of the nearest ammo pickup;
;                    bring this buffer's direction pad in line with it.
;      hud_radar     the ammo blips on the dial, and one eighth of sweep.
;      hud_force     make the next hud_update repaint whatever happens.
;
;  hud_static, hud_update AND hud_ammo need BANK 4 PAGED AT #4000 (they read
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
; Needs from gen_hud.inc: HUDNDL HUDDESC HUD_H0..H3 HUD_BG
; ...and from gen_aux.inc: HUDRECTS HUD_NRECT AUXCFG -- RAM bank 6
;                         HUD_CXB HUD_CY HUD_NDOT HUD_NW
; Needs from march.asm:   plr_a          (the heading, 0..71)

    include "gen_hud.inc"
    include "gen_aux.inc"           ; RAM bank 6: HUDRECTS, HUD_NRECT, AUXCFG

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
    ld   bc,hud_am
    ld   ix,hud_rb
    cp   #C0
    jr   z,hs_front
    inc  hl                         ; the back buffer's heading ...
    ld   de,hud_rows+HUD_NDOT*2     ; ... and its block record
    inc  bc                         ; ... and its ammo count
    ld   ix,hud_rb+MAXAMMO          ; ... and its radar blips
hs_front
    ld   (hud_cp),hl
    ld   (hud_rp),de
    ld   (hud_amp),bc
    ld   hl,hud_sc-hud_am           ; the scanner's byte sits at the same
    add  hl,bc                      ; offset in its own pair, so it needs
    ld   (hud_scp),hl               ; no second branch
    ld   hl,hud_sw-hud_am           ; ...and so does the sweep's
    add  hl,bc
    ld   (hud_swp),hl
    ld   hl,hud_hp-hud_am           ; ...and the health bar's
    add  hl,bc
    ld   (hud_hpp),hl
    ld   (hud_rbp),ix               ; the blips are MAXAMMO bytes a buffer
    ld   hl,hud_mb-hud_am           ; ...and the monster's is one again,
    add  hl,bc                      ; so it rides the same offset
    ld   (hud_mbp),hl
    ret                             ; rather than one, so they get their
                                    ; own pointer, picked in the branch


; ---------------------------------------------------------------------
;  hud_static -- paint the furniture into the current buffer.
;
;  HUDRECTS is 71 rectangles of db x, y, w, h, byte, back to front, and
;  plates, the bevel around the viewport, six readout slots, then the dial
;  (an ellipse cut into bands of equal half-width, so 74 scanlines of
;  circle are 24 rectangles), its ticks and its hub.  Startup only --
;  19642 bytes in 897 scanlines, 101.5 ms a buffer.  That is 5.2 us a byte
;  against bg.asm's 2.2, because only 39.3 ms of it is PUSH DE and 62.2 ms
;  is per-row setup -- 69 us a row, mostly the LINETAB lookup, which a
;  22-byte average run cannot amortise the way a 40-byte one does.  It runs
;  twice, at startup, so it is left alone.
; ---------------------------------------------------------------------
;  THE TABLE IS IN RAM BANK 6 AND THE DRAWING NEEDS BANK 4.  355 bytes
;  of furniture used to sit in the code segment, which had 22 bytes left
;  in it -- see engine2/tools/genaux.py.  So each record is fetched with
;  bank 6 paged over &4000 and bank 4 is put straight back, because
;  hud_rect reads LINETAB out of bank 4 and would otherwise index into
;  the furniture table itself.
;
;  TWO OUTs A RECORD, 142 of them, against a routine that already costs
;  101 ms -- which is why this is a per-record fetch and not a copy to
;  scratch RAM.  A copy would need 355 contiguous free bytes below
;  &4000, and the whole reason this table moved is that there are none.
hud_static
    ld   hl,HUDRECTS
    ld   b,HUD_NRECT
hst_l
    ld   (hst_p),hl
    push bc                         ; B is the record count; the OUTs
    ld   bc,#7F00+AUXCFG            ; below need BC
    out  (c),c
    ld   hl,(hst_p)
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
    ld   bc,#7FC4                   ; ...and bank 4 back for LINETAB
    out  (c),c
    call hud_rect
    pop  bc
    ld   hl,(hst_p)
    ld   de,5
    add  hl,de
    djnz hst_l
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

; ---------------------------------------------------------------------
;  hud_ammo -- the six rounds, in the top-left readout slot.
;
;  IN   A = rounds remaining, 0..HUD_AMN
;  OUT  this buffer's readout shows it.
;  Returns in 20 us when it already does, which is nearly every frame.
;
;  THE SAME DIRTY RULE THE NEEDLE USES, and for the same reason: there
;  are TWO buffers, so a count remembered once would show a stale readout
;  on every other flip.  hud_am carries one byte per buffer and hud_amp
;  points at the current one, exactly as hud_cur / hud_cp do.
;
;  IT REPAINTS ALL SIX and does not try to touch only the pip that
;  changed.  It happens on the frames a round is spent or picked up and
;  on no others, and a "which one moved" test would cost more code than
;  the pixels it saves.
;
;  AND IT IS NOT CHEAP -- MEASURED 3811.1 us (emu_hud.py), against the
;  250 the comment here first guessed.  96 bytes of pips, but 48 ROWS of
;  two bytes each, and hud_rect pays a LINETAB lookup and a row setup
;  per row: the same 70 us a row that makes hud_static cost 100 ms.  A
;  2x8 rectangle is the worst shape hud_rect has.
;
;  SO IT CHARGES ITSELF, THE WAY door_act DOES, and only when it paints.
;  Folding 3.8 ms into C_HUD would spend it on EVERY frame for a readout
;  that changes on maybe one frame in fifty; cost_add leaves the
;  microseconds in the accumulator without testing or waiting, so the
;  overshoot lands on the frame that earned it -- see C_AMMO in main3.
;
;  Every coordinate comes from gen_hud.inc, which derives them from the
;  slot that holds them -- see genhud.ammo_slot().  There is no number
;  here that genhud does not own.
; ---------------------------------------------------------------------
hud_ammo
    ld   hl,(hud_amp)
    cp   (hl)
    ret  z                          ; the common case: nothing to do
    ld   (hl),a
    ld   b,HUD_AMN
    ld   c,a                        ; C = how many are still loaded
    ld   a,HUD_AMX
    ld   (hr_x),a
    ld   a,HUD_AMY
    ld   (hr_y),a
    ld   a,HUD_AMW
    ld   (hr_w),a
    ld   a,HUD_AMH
    ld   (hr_h),a
ha_pip
    ; `dec c / jr c` DOES NOT WORK HERE, and it is worth naming: DEC r
    ; leaves the CARRY FLAG ALONE on the Z80 -- only DEC of a 16-bit pair
    ; is flagless, but the 8-bit one is flagless in exactly the one flag
    ; a borrow would need.  The branch was therefore taken on whatever
    ; the `cp (hl)` at the top had left, and emu_hud.py's sequence caught
    ; it as one pip of six drawn spent on a full magazine.  Test for zero
    ; before decrementing instead.
    ld   a,c
    or   a
    ld   a,HUD_AMBG                 ; spent unless there is a round left
    jr   z,ha_pen
    dec  c
    ld   a,HUD_AMPEN
ha_pen
    ld   (hr_pen),a
    push bc
    call hud_rect
    pop  bc
    ld   a,(hr_x)                   ; ...and on to the next pip
    add  a,HUD_AMDX
    ld   (hr_x),a
    djnz ha_pip
    ifdef PACED
    ld   bc,C_AMMO
    call cost_add
    endif
    ret


; ---------------------------------------------------------------------
;  hud_health -- the player's hit points, in the bottom-left slot.
;
;  IN   A = (plr_hp), 0..HUD_HPN.  OUT  this buffer's bar shows it.
;  Clobbers AF BC DE HL.
;
;  TWO RECTANGLES, NOT HUD_HPN PIPS, and hud_rect's ~70 us a ROW is the
;  whole reason.  The ammo readout draws six pips of 8 rows = 48 rows and
;  costs 4000 us; this draws the health still in hand and the health
;  already lost as one rectangle each -- 16 rows -- and is charged C_HP.
;  Health changes far more often than the round count when a monster is
;  on you, so the cheap shape belongs here and not there.
;
;  THE SAME EARLY-OUT AS hud_ammo, and it is worth the two bytes a
;  buffer: the bar is repainted on the frames the count MOVES, which is
;  one frame in tens, and on every other frame this is a compare and a
;  ret.  hud_hp carries one byte per buffer and hud_hpp points at the
;  current one, exactly as hud_am / hud_amp do.
;
;  A WIDTH OF ZERO IS NOT DRAWN, WHICH IS WHY THE ORDER IS THIS WAY.
;  hud_rect returns on a zero height but a zero WIDTH would enter its
;  unrolled PUSH block at the wrong offset, so at full health the lost
;  rectangle must not run, and at zero health the kept one must not.
;  Both are tested, and each test is one OR.
; ---------------------------------------------------------------------
hud_health
    ld   hl,(hud_hpp)
    cp   (hl)
    ret  z                          ; the common case: nothing to do
    ld   (hl),a

    add  a,a                        ; hit points times HUD_HPSEG, which is
    add  a,a                        ; 4: two doublings, no multiply
    ld   d,a                        ; D = the kept width in bytes
    assert HUD_HPSEG == 4

    ld   a,HUD_HPY
    ld   (hr_y),a
    ld   a,HUD_HPH
    ld   (hr_h),a

    ld   a,HUD_HPX                  ; ---- the health still in hand
    ld   (hr_x),a
    ld   a,d
    or   a
    jr   z,hh_lost                  ; none left: do not draw a zero width
    ld   (hr_w),a
    ld   a,HUD_HPPEN
    ld   (hr_pen),a
    push de
    call hud_rect
    pop  de

hh_lost                             ; ---- and the health already lost
    ld   a,HUD_HPW
    sub  d
    jr   z,hh_done                  ; full: nothing to erase.  NOT `ret z`
    ld   (hr_w),a                   ; -- that path has already DRAWN, and
    ld   a,HUD_HPX                  ; returning from it would leave the
    add  a,d                        ; rectangle uncharged.  Every path
    ld   (hr_x),a                   ; that painted goes through hh_done.
    ld   a,HUD_HPBG
    ld   (hr_pen),a
    call hud_rect
hh_done
    ifdef PACED
    ld   bc,C_HP
    call cost_add
    endif
    ret


; ---------------------------------------------------------------------
;  hud_scan -- the ammo scanner's one lit bearing.
;
;  IN   A = (band << 4) | bearing, or #FF for "no pickup left on the map".
;       game.asm's ammo_scan packs it; genhud.py's scan_rects models it.
;  OUT  this buffer's pad shows it.
;
;  TWO RECTANGLES AT MOST, AND USUALLY ONE.  The eight unlit bearings and
;  the white hub are STATIC FURNITURE -- genhud.scan_furniture puts them
;  in HUDRECTS, so hud_static paints them once per buffer at startup and
;  this routine never draws a layout.  It lights the new cell and puts
;  the old one back to HUD_SCOFF, the same erase-then-draw the compass
;  needle does.  And when only the DISTANCE moved, the cell is the same
;  cell, so the erase is skipped and it is one rectangle: that is the
;  common case, because walking towards a pickup changes the band long
;  before it changes the bearing.
;
;  Same two-buffer dirty rule as the needle and the pips -- hud_sc holds
;  one byte per buffer and hud_scp points at the current one.  Returns in
;  a few us when the pad is already right, which is most frames.
;
;  Needs BANK 4 at #4000 and interrupts off, like everything that calls
;  hud_rect.
; ---------------------------------------------------------------------
hud_scan
    ld   hl,(hud_scp)
    cp   (hl)
    ret  z                          ; the common case: nothing to do
    ld   c,(hl)                     ; C = what is on the screen now
    ld   (hl),a
    ld   b,a                        ; B = what it should be

    ld   a,HUD_SCW                  ; every cell of the pad is the same
    ld   (hr_w),a                   ; size, so this is set once and not
    ld   a,HUD_SCH                  ; per rectangle
    ld   (hr_h),a

    ld   a,c                        ; ---- put the old bearing back, unless
    cp   #FF                        ;      the new one lights the same cell
    jr   z,hsc_draw
    xor  b
    and  #0F
    jr   z,hsc_draw
    ld   a,c
    call hsc_cell
    ld   a,HUD_SCOFF
    ld   (hr_pen),a
    push bc
    call hud_rect
    pop  bc

hsc_draw
    ld   a,b                        ; ---- and light the new one
    cp   #FF
    jr   z,hsc_done
    call hsc_cell
    ld   a,b
    rrca
    rrca
    rrca
    rrca
    and  7                          ; the distance band...
    ld   e,a
    ld   d,0
    ld   hl,SCANPEN                 ; ...picks the colour
    add  hl,de
    ld   a,(hl)
    ld   (hr_pen),a
    call hud_rect
hsc_done
    ifdef PACED
    ld   bc,C_SCAN
    call cost_add
    endif
    ret

; --- A = a packed bearing: aim hr_x / hr_y at its cell -----------
;     Clobbers AF DE HL.  B and C are the caller's and are left alone.
hsc_cell
    and  7
    add  a,a                        ; SCANPOS is two bytes an entry
    ld   e,a
    ld   d,0
    ld   hl,SCANPOS
    add  hl,de
    ld   a,(hl)
    ld   (hr_x),a
    inc  hl
    ld   a,(hl)
    ld   (hr_y),a
    ret


; ---------------------------------------------------------------------
;  hud_radar -- the ammo blips inside the dial, and the sweep round it.
;
;  IN   nothing; it reads game.asm's (ammo_blip), one packed
;       (band << 4) | WORLD SECTOR per pickup, #FF where there is none.
;  OUT  this buffer's dial agrees with it, and the sweep has moved on.
;
;  THE DIAL IS WORLD-REFERENCED, so the blips are too: a blip sits where
;  the needle would point if the player faced that pickup.  Line the two
;  up and walk.  Radius is distance -- the same three bands the readout
;  pips and the block on the floor use.
;
;  THE NEEDLE IS PUT BACK AFTERWARDS, and that is not belt and braces.
;  Both live on DIAL_BG and the needle spans every radius along its own
;  bearing, so a blip that moves off a square the needle is standing on
;  erases part of the needle when it paints DIAL_BG there.  Redrawing the
;  needle costs ~680 us and only happens on the frames a blip actually
;  moved; the alternative -- keeping them apart -- would mean giving up
;  either the three rings or the needle's reach.
;
;  THE SWEEP IS THE EIGHT TICKS THAT WERE ALREADY THERE, lit one at a
;  time, one eighth a frame.  It is OUTSIDE the rim, where neither the
;  needle nor a blip ever goes, so it needs no ordering at all -- two
;  rectangles a frame and no interaction.  Eighths rather than a drawn
;  arm because an arm is a line, and a line costs as much to erase as to
;  draw.
;
;  Needs BANK 4 at #4000 and interrupts off, like everything here.
; ---------------------------------------------------------------------
hud_radar
    ld   hl,ammo_blip
    ld   de,(hud_rbp)
    ld   b,MAXAMMO
    ld   c,0                        ; C = did anything move?
hr_bl
    ld   a,(de)
    cp   (hl)
    jr   z,hr_bnx
    ld   c,1
    push bc
    push de
    push hl
    ld   a,(de)                     ; take the old one down...
    ld   c,HUD_RADBG
    call hr_one
    pop  hl
    push hl
    ld   a,(hl)                     ; ...and put the new one up
    ld   c,HUD_RADPEN
    call hr_one
    pop  hl
    pop  de
    pop  bc
    ld   a,(hl)
    ld   (de),a
    ifdef PACED
    push bc                         ; ONE CHARGE PER BLIP THAT MOVED, not
    push de                         ; one for the whole routine: the
    push hl                         ; steady state is the sweep alone and
    ld   bc,C_BLIP                  ; charging the six-blip worst case on
    call cost_add                   ; every frame would throw 3300 us a
    pop  hl                         ; frame away -- which is exactly the
    pop  de                         ; mistake C_CFAR made
    pop  bc
    endif
hr_bnx
    inc  hl
    inc  de
    djnz hr_bl

    ; ---- AND THE MONSTER, LAST, so a monster standing on a pickup shows
    ;      as the monster -- which is the one worth knowing about.
    ;
    ;      IF ANY PICKUP MOVED, THE MONSTER IS PAINTED AGAIN WHERE IT
    ;      ALREADY IS.  A pickup erasing its old square to DIAL_BG wipes
    ;      the monster if the monster is standing there, and the
    ;      monster's remembered byte would say "already drawn" and leave
    ;      it wiped.
    ;
    ;      REPAINT, NOT FORGET.  Setting the remembered byte to #FF was
    ;      the first fix and it made things worse: #FF is also "nothing
    ;      was there", so the erase below had nothing to take down and
    ;      the OLD blip stayed on the dial for ever.  The remembered byte
    ;      is the only record of where the thing is; it has to survive.
    ld   a,c
    or   a
    jr   z,hr_monok
    ld   de,(hud_mbp)
    ld   a,(de)
    push bc
    ld   c,HUD_MONPEN
    call hr_one
    ifdef PACED
    ld   bc,C_BLIP                  ; one rectangle, and it is charged: it
    call cost_add                   ; is a whole rect nobody was billing,
    endif                           ; and the sum came out 100 us short
    pop  bc
hr_monok
    ld   hl,mon_blip
    ld   de,(hud_mbp)
    ld   a,(de)
    cp   (hl)
    jr   z,hr_nomon
    ld   c,1
    push bc
    push de
    push hl
    ld   a,(de)
    call hr_under                   ; ...to whatever is UNDER it
    call hr_one
    pop  hl
    push hl
    ld   a,(hl)
    ld   c,HUD_MONPEN
    call hr_one
    pop  hl
    pop  de
    pop  bc
    ld   a,(hl)
    ld   (de),a
    ifdef PACED
    push bc
    ld   bc,C_BLIP
    call cost_add
    pop  bc
    endif
hr_nomon

    ld   a,c
    or   a
    jr   z,hr_sweep
    ld   a,(plr_a)                  ; a blip erase can nick the needle
    call hud_needle
    ifdef PACED
    ld   bc,C_RNEEDLE
    call cost_add
    endif

hr_sweep
    ld   a,(hud_swa)                ; ...one eighth on, every frame
    inc  a
    and  HUD_NSECT-1
    ld   (hud_swa),a
    ld   hl,(hud_swp)
    cp   (hl)
    jr   z,hr_done                  ; this buffer already shows it
    ld   a,(hl)
    cp   #FF
    jr   z,hr_swnew
    ld   e,0                        ; put the old tick back to its own
    call hr_tick                    ; resting colour -- north's is not the
hr_swnew                            ; same size or pen as the other seven
    ld   a,(hud_swa)
    ld   hl,(hud_swp)
    ld   (hl),a
    ld   e,1
    call hr_tick
hr_done
    ifdef PACED
    ld   bc,C_SWEEP                 ; the sweep and the six-way compare,
    call cost_add                   ; which happen on every frame
    endif
    ret

; --- A = the monster's OLD blip: what does its square revert to?
;     -> C = the ammo pen if a pickup is standing on that same square,
;     the dial background if not.
;
;     WITHOUT THIS THE MONSTER ERASES THE PICKUP IT WAS STANDING ON.  The
;     square goes back to DIAL_BG, and the pickup's own remembered byte
;     still says "drawn", so nothing ever puts it back.  Caught by
;     emu_hud.py's radar sequence, which walks a monster onto a pickup's
;     square and off it again for exactly this reason.
;
;     Clobbers BC HL.  A is left alone -- hr_one wants it.
hr_under
    ld   c,HUD_RADBG
    cp   #FF
    ret  z                          ; nothing was there to erase
    ld   hl,ammo_blip
    ld   b,MAXAMMO
hu_l
    cp   (hl)
    jr   z,hu_hit
    inc  hl
    djnz hu_l
    ret
hu_hit
    ld   c,HUD_RADPEN
    ret


; --- A = a packed blip, C = the byte to paint it.  #FF draws nothing.
;     Clobbers AF BC DE HL.
hr_one
    cp   #FF
    ret  z
    ld   b,a
    and  7                          ; the sector...
    ld   e,a
    add  a,a
    add  a,e                        ; ...times three
    ld   e,a
    ld   a,b
    rrca
    rrca
    rrca
    rrca
    and  3                          ; ...plus the band
    add  a,e
    add  a,a                        ; two bytes an entry
    ld   e,a
    ld   d,0
    ld   hl,RADPOS
    add  hl,de
    ld   a,(hl)
    ld   (hr_x),a
    inc  hl
    ld   a,(hl)
    ld   (hr_y),a
    ld   a,HUD_RADW
    ld   (hr_w),a
    ld   a,HUD_RADH
    ld   (hr_h),a
    ld   a,c
    ld   (hr_pen),a
    jp   hud_rect

; --- A = a tick 0..7, E = 0 to rest it or 1 to light it -------------
;     Clobbers AF BC DE HL.
hr_tick
    ld   c,a
    add  a,a
    add  a,a
    add  a,c                        ; five bytes an entry
    ld   c,a
    ld   b,0
    ld   hl,TICKTAB
    add  hl,bc
    ld   a,(hl)
    ld   (hr_x),a
    inc  hl
    ld   a,(hl)
    ld   (hr_y),a
    inc  hl
    ld   a,(hl)
    ld   (hr_w),a
    inc  hl
    ld   a,(hl)
    ld   (hr_h),a
    inc  hl
    ld   a,e
    or   a
    ld   a,(hl)                     ; its resting byte...
    jr   z,hr_tpen
    ld   a,HUD_SWPEN                ; ...or lit
hr_tpen
    ld   (hr_pen),a
    jp   hud_rect


; force a repaint even if the heading has not changed (after hud_static, or
; after anything else has scribbled on the dial)
hud_force
    ld   hl,(hud_cp)
    ld   (hl),#FF
    ld   hl,(hud_amp)               ; hud_static repaints the slots too, so
    ld   (hl),#FF                   ; the readout in one and the scanner's
    ld   hl,(hud_scp)               ; lit bearing in the other are gone as
    ld   (hl),#FF                   ; well
    ld   hl,(hud_swp)               ; ...and so is the lit tick
    ld   (hl),#FF
    ld   hl,(hud_mbp)               ; ...and the monster's blip
    ld   (hl),#FF
    ld   hl,(hud_rbp)               ; ...and every ammo blip on the dial
    ld   b,MAXAMMO
hf_rb
    ld   (hl),#FF
    inc  hl
    djnz hf_rb
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
    ; ---- FETCH THE EIGHT BYTES OUT OF BANK 6, and page bank 4 straight
    ;      back.  The needle table is 152 bytes and the code segment had
    ;      none of them to spare -- see engine2/tools/genaux.py -- but
    ;      everything below this draws, and drawing reads LINETAB, which
    ;      is in bank 4 UNDERNEATH bank 6.  So the read and the drawing
    ;      cannot both have their bank paged in: the read wins, briefly,
    ;      and copies what it needs down.  HUD_NDOT * 2 bytes, once a
    ;      frame, against a hud_update measured at 1423 us.
    ld   bc,#7F00+AUXCFG
    out  (c),c
    ld   de,hn_dot4
    ld   bc,HUD_NDOT*2
    ldir
    ld   bc,#7FC4
    out  (c),c
    ld   hl,hn_dot4
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
hud_am      db #FF,#FF              ; ...and the ammo count each shows
hud_amp     dw hud_am               ; -> the entry for the current buffer
hud_sc      db #FF,#FF              ; ...and the scanner bearing each shows
hud_scp     dw hud_sc               ; -> the entry for the current buffer
hud_sw      db #FF,#FF              ; ...and which tick each has lit
hud_swp     dw hud_sw
hud_hp      db #FF,#FF              ; ...and the health bar each shows
hud_hpp     dw hud_hp
hud_swa     db 0                    ; the sweep's phase, 0..7.  ONE for both
                                    ; buffers: it is the clock, not a
                                    ; picture, and each buffer catches up
                                    ; the next time it is drawn into
hud_rb      ds MAXAMMO*2              ; the blips each buffer is showing
hud_rbp     dw hud_rb
hud_mb      db #FF,#FF              ; ...and the monster's, one a buffer
hud_mbp     dw hud_mb
; hud_sp IS GONE.  hud_static and hud_ammo each saved SP into it and
; restored it around their hud_rect calls -- and hud_rect already saves
; SP into its OWN hr_sp at entry (hud2.asm:hud_rect) and puts it back
; before every return, including the h == 0 early-out, which happens
; before SP has been touched at all.  The outer pair was doing nothing
; but costing 24 bytes of a body segment that has hit its ceiling ten
; times.  The header comment that said "hud_static saves and restores SP
; itself" was describing hr_sp all along.
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

hn_tp       dw 0                    ; walks hn_dot4
hn_dot4     ds HUD_NDOT*2           ; the heading's dots, copied down out
                                    ; of bank 6 -- see hud_needle
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


; ---------------------------------------------------------------------
;  THE ONE THING TYING A .asm CONSTANT TO A GENERATED .inc ONE.
;
;  genhud.py derives the health bar's width from its own HP_MAX and
;  hud_health draws HUD_HPSEG bytes per point; game.asm's PLR_HPMAX is what
;  the player actually has.  If those two ever disagree the bar either
;  leaves a segment permanently dark or runs past the slot that holds
;  it, and nothing else in the build would say a word.
;
;  It lives HERE and not beside PLR_HPMAX because rasm evaluates an assert
;  where it stands, and main3.asm includes game.asm before hud2.asm --
;  so at PLR_HPMAX's line HUD_HPN is not a symbol yet.  That is the same
;  trap the HUD_THI_* asserts fell into.
    assert PLR_HPMAX == HUD_HPN
    assert HUD_HPSEG * HUD_HPN == HUD_HPW
    assert (HUD_HPSEG & 1) == 0     ; hud_rect enters HRPUSH two bytes at
                                    ; a time, so every width it is handed
                                    ; must be even -- and the bar's width
                                    ; is HUD_HPSEG times a hit point
