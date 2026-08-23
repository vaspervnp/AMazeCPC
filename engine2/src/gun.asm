; =====================================================================
;  engine2/src/gun.asm -- the first-person weapon, and the walking bob.
;
;      gun_setbuf   A = #C0 / #80, the buffer the next gun_draw paints.
;                   Call it wherever frame_setbuf is called, same A.
;      gun_step     once a game frame: advance the bob.
;      gun_draw     once a game frame, AFTER the 3D view: blit the sprite.
;
;  NO CLEANUP, AND ONE CLIPPED EDGE.  bg_fill repaints every byte of the
;  viewport at the head of the next frame, so wherever the gun was is
;  already gone -- there is nothing to erase and no saved background.
;
;  THE SPRITE IS ANCHORED BELOW THE BOTTOM EDGE.  GUN_CUT scanlines of it
;  hang past VP_Y+VP_H at the centre of the bob and are simply not drawn.
;  That is the whole point: a weapon cut off by the bottom of the frame
;  reads as HELD, and one that sits fully inside it reads as floating,
;  which is what the previous placement did.  The vertical bob therefore
;  swings BOTH WAYS about that anchor, -GUN_BOBVA .. +GUN_BOBVA, instead
;  of the upward-only rise it was -- an upward-only bob makes the RESTING
;  pose the lowest one, so every step lifts the weapon.
;
;  SO THERE IS EXACTLY ONE CLIPPED EDGE, AND IT COSTS ONE COMPARE A BAND.
;  gd_rem carries the number of rows still above VP_Y+VP_H; each band
;  subtracts its own row count from it, draws whatever is left if that
;  goes negative, and returns.  It is NOT per-pixel clipping and there is
;  no test in the row loop at all.  Nothing else can clip:
;
;      left/right  the bob is +-GUN_BOBHA whole BYTES and the widest run
;                  stops well short of both edges
;      top         the highest the sprite ever sits leaves its last row
;                  exactly on the bottom edge, so its first row is
;                  GUN_H-1 above that and inside
;
;  gentab.py:self_check asserts all three at every phase, which is what
;  lets every row stay a plain byte copy.  That is also the entire reason
;  the art was designed as ONE CONTIGUOUS RUN PER SCANLINE.
;
;  VERIFIED, not asserted: engine2/tools/emu_gun.py boots the disc, poses
;  all 45 reachable bob offsets and compares the WHOLE VIEWPORT against
;  gunart.py's run list -- clipped to the viewport by the model too --
;  laid over the same frame drawn with gun_draw stubbed out.  That catches
;  a byte written outside the sprite as well as one missing inside it, and
;  in particular a row drawn BELOW the viewport, which would land in the
;  HUD.
;
;  ------------------------------------------------------------------
;  MEASURED on the booted disc, engine2/tools/emu_gun.py -- emu_pacefit's
;  protocol: a 16-bit counter with interrupts off, the same loop with the
;  CALL removed for the overhead, 100 NOPs calibrated to 99.99 us.
;
;      gun_draw   3425.5 - 4151.7 us over ALL 45 bob offsets; the WORST
;                 is the top of the bob, dy = +4, which is the one
;                 position that draws all GUN_H = 46 rows
;                 ...of which 2028.8 us is per-row stepping (44.1 us a
;                    scanline over 46) and 2122.9 us is the copy itself
;                    (5.01 us a byte over 424 -- LDI, see below)
;      gun_step   164.8 us walking, 42.0 us standing still
;
;  THE COST NOW DEPENDS ON THE BOB, which the old upward-only placement's
;  did not: rows drawn is GUN_ROWS0 + (gun_dy), i.e. 38 at the bottom of
;  the swing and 46 at the top, and that is a 726 us spread.  main3.asm's
;  C_GUN is charged against the TOP, because a cost constant in this
;  project is a one-sided upper bound and never an average -- and it had
;  to go from 3250 to 4500 to stay one.  The cost is FLAT in dx, exactly
;  as it was: the horizontal bob shifts the run, it does not change how
;  many rows there are or how many cross a character-row boundary, and
;  all five dx read the same microsecond at every dy.
;
;  THE BLIT IS PER ROW BUT ITS SETUP IS PER BAND.  46 independent
;  scanlines, each looking up LINETAB and its own run length, would be
;  half as much again in pure bookkeeping.  But the sprite is not 46
;  different runs: it is a few BANDS of consecutive rows that share the
;  same x0 and the same length (six of them, for this art).  gentab.py
;  derives the bands and gun_draw sets the copy up once per band; there
;  is then no LINETAB lookup after the first row at all, because DE walks
;  the screen with the SAME (y & 7) trick hud2.asm:hn_rows uses -- add 8
;  to the high byte, and if bits 3..5 fall out, undo the carry into bit 6
;  and step on by one row of 80 bytes.
;
;  LDI, AND WHAT IT IS AND IS NOT WORTH.  The block below is entered at
;  2*(GUN_MAXN - n) so it copies exactly n bytes; the entry is patched
;  once per band, not per row.  LDI decrements BC, so C is set to #FF
;  before every row -- the row counter lives in B and must not be
;  borrowed from.  It was chosen over LDIR on the estimate that LDI is
;  4 us a byte against LDIR's 6.  THAT ESTIMATE WAS WRONG: LDI MEASURES
;  5.03 us, and once the call and ret into the block are counted an LDIR
;  of the same run is about 70 us CHEAPER over the whole sprite as well
;  as 30 bytes smaller.  It is left as it is because the difference is
;  2% of a 3 ms blit against 25 ms of slack, and because swapping it
;  means moving the row counter out of B, which costs most of the 70 us
;  back -- but the next person to want bytes here should take them from
;  this block, and should measure rather than repeat the arithmetic.
;
;  WHY THE RUN POINTER NEVER MOVES BACKWARDS.  LDI advances both HL and
;  DE, so after a run DE sits one past the end of it.  The band record
;  carries (256 - n), which is added to E to put DE back at the start of
;  the run; the scanline step then moves it down.  Nothing is
;  recalculated and nothing is remembered but DE itself.
;
;  ------------------------------------------------------------------
;  THE BOB.  Two tables at mutually prime periods (GUN_BOBVN = 16 and
;  GUN_BOBHN = 23) give a Lissajous path that takes 368 frames -- about
;  44 s at 8.35 fps -- to repeat, and an 8-bit LFSR nudges the horizontal
;  phase by one or two extra steps every few frames so it never really
;  repeats at all.  Vertical is in SCANLINES, -GUN_BOBVA..+GUN_BOBVA
;  about the anchor; horizontal is in whole BYTES, +-GUN_BOBHA, which is
;  what keeps every row a byte copy.
;
;  THE VERTICAL TABLE IS A TRIANGLE AND HAS TO BE.  The smoothness rule
;  is that nothing moves more than one scanline in a frame, and swinging
;  2*GUN_BOBVA = 8 scanlines down and 8 back up inside GUN_BOBVN = 16
;  frames is 16 unit moves in 16 frames: every frame moves by exactly one
;  and there is no freedom left for a sine to shape.  Keeping the period
;  at 16 is what keeps it mutually prime with the horizontal 23, and the
;  horizontal has slack and stays a rounded sine.
;
;  THE OFFSETS ARE EASED, NOT ASSIGNED.  (gun_dx) and (gun_dy) move at
;  most ONE step per frame towards the table's value.  Both tables are
;  built to step by at most one anyway, so while the player walks the
;  ease is exact and free -- but it is what makes the LFSR nudge smooth
;  instead of a jump, and it is what walks the weapon back to the ANCHOR
;  when the player stops instead of snapping it there.  Note that rest is
;  now the MIDDLE of the travel, not the bottom of it, so stopping can
;  ease the weapon either up or down.
;
;  BOTH OFFSETS ARE UNSIGNED AND BOTH ARE BIASED.  (gun_dy) is
;  0..2*GUN_BOBVA with rest GUN_BOBVA; (gun_dx) is 0..2*GUN_BOBHA with
;  rest GUN_BOBHA.  BOBV and BOBH are stored biased in bank 4 for exactly
;  this reason, so one three-instruction ease serves both axes and the
;  blitter's `neg / add a,GUN_Y0` needs no sign handling.
; =====================================================================

; Needs from tab_equ.inc: LINETAB GUNBAND GUNPIX BOBV BOBH
;                         GUN_H GUN_WB GUN_X0F GUN_MAXN
;                         GUN_BOBVN GUN_BOBHN GUN_BOBVA GUN_BOBHA
;                         GUN_CUT GUN_ROWS0
; Needs from vpcfg.inc:   VP_BX VP_BW VP_Y VP_H
; Needs from game.asm:    plr_moving

GUN_XB      equ VP_BX+(VP_BW-GUN_WB)/2      ; sprite left byte, centred
GUN_Y0      equ VP_Y+VP_H-GUN_H+GUN_CUT+GUN_BOBVA
                                            ; top scanline at (gun_dy) = 0,
                                            ; i.e. the BOTTOM of the swing.
                                            ; The anchor -- the centre of
                                            ; the travel -- is GUN_BOBVA
                                            ; above this and hangs GUN_CUT
                                            ; scanlines below the viewport.
GUN_XC      equ GUN_XB-GUN_BOBHA+GUN_X0F    ; ...+ (gun_dx) + the first
                                            ; row's own x0 = column of the
                                            ; very first byte written

; ---------------------------------------------------------------------
;  THE FOUR THINGS THIS FILE ASSUMES ABOUT THE ART, ASSERTED.
;
;  Every one of them used to live in a comment.  The sprite has been 38,
;  46, 30 and 38 rows, and each change re-derives GUN_ROWS0, GUN_Y0, the
;  band list and the size of GUNPIX -- so the one thing that must never
;  be possible is the blitter and the drawing being from different
;  generations of that arithmetic.  GUN_SIG catches a stale DISC; these
;  catch a stale ASSEMBLY, which is the other half of the same fault and
;  the half no pixel diff can see, because a disc built from consistent
;  tables and inconsistent code is byte-for-byte self-consistent.
;
;  1. the bottom clamp counts rows, and GUN_ROWS0 is that count at the
;     bottom of the swing.  If it is not exactly H - CUT - BOBVA the
;     clamp stops the band walk early and the LAST bands -- the hand --
;     are never drawn at all, which is what a wrong height buys.
    assert GUN_ROWS0 == GUN_H-GUN_CUT-GUN_BOBVA
;  2. rows drawn at the TOP of the swing is GUN_ROWS0 + 2*GUN_BOBVA and
;     must not exceed the sprite, or the walk runs off the end of the
;     band list into whatever bank 4 has next.
    assert GUN_ROWS0+2*GUN_BOBVA <= GUN_H
;  3. ...and must be at least one row, or the first band returns.
    assert GUN_ROWS0 > 0
;  4. the sprite must always REACH the bottom edge -- that is the whole
;     anchor, and it is BOB_CUT >= BOB_VA.
    assert GUN_CUT >= GUN_BOBVA
;  5. the run pointer walks GUNPIX linearly across the whole sprite, so
;     the band list and the pixel table must be the same sprite.
    assert GUNPIX-GUNBAND == 5*GUN_NBAND+1
    assert BOBV-GUNPIX == GUN_PIXN
;  6. and the sprite must sit inside the viewport at every phase -- the
;     blitter has no side clip and no top clip at all.
    assert GUN_XB >= VP_BX+GUN_BOBHA
    assert GUN_XB+GUN_WB+GUN_BOBHA <= VP_BX+VP_BW
    assert GUN_Y0-2*GUN_BOBVA >= VP_Y
; ---------------------------------------------------------------------


; ---------------------------------------------------------------------
;  gun_setbuf -- A = #C0 (front) or #80 (back).
; ---------------------------------------------------------------------
gun_setbuf
    ld   (gd_bh+1),a
    ret


; ---------------------------------------------------------------------
;  gun_step -- one frame of bob.
;
;  Walking advances both phases by one and the LFSR sometimes adds one
;  more to the horizontal; standing still points both offsets at rest.
;  Either way the offsets only EASE, so nothing here can move the sprite
;  more than one scanline or one byte in a frame.
;  Clobbers AF BC DE HL.
; ---------------------------------------------------------------------
gun_step
    ld   a,(plr_moving)
    or   a
    jr   z,gu_rest

    ld   hl,gun_pv                  ; vertical phase, modulo GUN_BOBVN
    ld   b,GUN_BOBVN
    call gu_bump

    ld   a,(gun_lfsr)               ; x^8 + x^6 + x^5 + x^4 + 1, maximal
    srl  a                          ; length 255 -- it never reaches 0
    jr   nc,gu_nofb
    xor  #B8
gu_nofb
    ld   (gun_lfsr),a
    ld   c,a                        ; keep the new state for the nudge test

    ld   hl,gun_ph                  ; horizontal phase, modulo GUN_BOBHN
    ld   b,GUN_BOBHN
    call gu_bump
    ld   a,c
    and  3                          ; ...and a second (or third) step on
    jr   nz,gu_tgt                  ; roughly one frame in four
    call gu_bump
    bit  2,c
    call nz,gu_bump

gu_tgt
    ld   hl,BOBV                    ; targets := the two tables
    ld   a,(gun_pv)
    call gu_look
    ld   b,a
    ld   hl,BOBH
    ld   a,(gun_ph)
    call gu_look
    ld   c,a
    jr   gu_ease

gu_rest
    ld   b,GUN_BOBVA                ; rest: the ANCHOR, centred -- the
    ld   c,GUN_BOBHA                ; middle of both swings.  Both tables
                                    ; are biased, so neither centre is 0.

gu_ease
    ld   hl,gun_dy
    ld   a,b
    call gu_step1
    ld   hl,gun_dx
    ld   a,c
    ; fall through

; --- A = target, (HL) = current: move (HL) one step towards A ---------
gu_step1
    cp   (hl)
    ret  z
    jr   c,gu_down
    inc  (hl)
    ret
gu_down
    dec  (hl)
    ret

; --- (HL) = (HL) + 1 modulo B ----------------------------------------
gu_bump
    inc  (hl)
    ld   a,(hl)
    cp   b
    ret  c
    ld   (hl),0
    ret

; --- A = (HL + A) ----------------------------------------------------
gu_look
    add  a,l
    ld   l,a
    ld   a,h
    adc  a,0
    ld   h,a
    ld   a,(hl)
    ret


; ---------------------------------------------------------------------
;  gun_draw -- blit the sprite into the current buffer, on top of
;  whatever the 3D pass left there.
;
;  Bank 4 must be paged at #4000 (LINETAB and the four gun tables live
;  there).  Does not touch SP; interrupts may be on or off.
;  Clobbers AF BC DE HL IX.
; ---------------------------------------------------------------------
gun_draw
    ld   a,(gun_dy)                 ; --- THE BOTTOM CLAMP, set up once.
    add  a,GUN_ROWS0                ; rows from the top of the sprite to
    ld   (gd_rem+1),a               ; VP_Y+VP_H.  = GUN_H-GUN_CUT-GUN_BOBVA
                                    ; + the biased bob, so GUN_ROWS0 at the
                                    ; bottom of the swing up to GUN_H at the
                                    ; top.  The band walk below stops when
                                    ; it runs out; the rest of the sprite
                                    ; hangs below the viewport undrawn.

    ld   a,(gun_dy)                 ; --- DE = the first byte to write
    neg
    add  a,GUN_Y0                   ; biased, so this is never negative
    ld   l,a
    ld   h,0
    add  hl,hl
    ld   bc,LINETAB
    add  hl,bc
    ld   e,(hl)
    inc  hl
    ld   d,(hl)                     ; DE = LINETAB[y], written for #C000
    ld   a,(gun_dx)
    add  a,GUN_XC                   ; + the bob, the centring and x0
    add  a,e
    ld   e,a
    ld   a,d
    adc  a,0
    and  #3F
gd_bh
    or   #C0                        ; patched by gun_setbuf
    ld   d,a

    ld   hl,GUNPIX                  ; the runs, concatenated, top row first
    ld   ix,GUNBAND

gd_band
    ld   a,(ix+0)                   ; rows in this band; 0 ends the sprite
    or   a
    ret  z

    ; --- THE BOTTOM CLAMP.  ONE COMPARE, ONCE A BAND, and nothing at all
    ; in the row loop.  (gd_rem+1) is how many rows still fit above
    ; VP_Y+VP_H; take this band out of it, and if that goes negative draw
    ; only what is left and stop.  Rows are drawn strictly top to bottom
    ; and contiguously, so a band that does not fit is the last one --
    ; setting the remainder to 0 makes the next pass through here return.
    ; C is free: the row loop reloads it with #FF before every LDI run.
    ld   c,a                        ; C = rows this band wants
gd_rem
    ld   a,0                        ; patched: rows still inside the view
    sub  c
    jr   nc,gd_fits                 ; the whole band is above the edge
    add  a,c                        ; A = the remainder, < C
    ret  z                          ; ...and if it is none, we are done
    ld   c,a                        ; draw just those rows
    xor  a                          ; and none after this band
gd_fits
    ld   (gd_rem+1),a
    ld   a,c

    push af
    ld   a,(ix+2)                   ; 256 - n: undoes the LDI's advance
    ld   (gd_back+1),a
    push hl
    ld   l,(ix+1)                   ; 2*(GUN_MAXN - n): where to enter the
    ld   h,0                        ; unrolled block so it copies n bytes
    ld   bc,GUNLDI
    add  hl,bc
    ld   (gd_call+1),hl
    pop  hl
    pop  af
    ld   b,a                        ; B is the row counter from here on

gd_row
    ld   c,#FF                      ; LDI decrements BC; keep it off B
gd_call
    call 0                          ; patched -> GUNLDI + 2*(GUN_MAXN - n)
gd_back
    ld   a,0                        ; patched -> 256 - n
    add  a,e
    ld   e,a
    jr   c,gd_down
    dec  d
gd_down
    ld   a,d                        ; next scanline.  Bits 3..5 of the high
    add  a,8                        ; byte are exactly (y & 7); the rest of
    ld   d,a                        ; the offset, row*80 + x, is always
    and  #38                        ; under #800.  If adding 8 clears them
    jr   nz,gd_next                 ; the scanline has left the character
    ld   a,d                        ; row: undo the carry it made into bit
    sub  #40                        ; 6 and step on by one row of 80 bytes.
    ld   d,a
    ld   a,e
    add  a,80
    ld   e,a
    jr   nc,gd_next
    inc  d
gd_next
    djnz gd_row

    ld   c,(ix+3)                   ; the band's step in x0, signed, once
    ld   b,(ix+4)
    ex   de,hl
    add  hl,bc
    ex   de,hl
    ld   bc,5
    add  ix,bc
    jr   gd_band


; ---------------------------------------------------------------------
;  GUNLDI -- entering at 2*(GUN_MAXN - n) copies exactly n bytes and
;  returns.  MEASURED 5.03 us a byte; see the LDI note in the header for
;  why that is not the 4 it was chosen for.
; ---------------------------------------------------------------------
GUNLDI
    repeat GUN_MAXN
    ldi
    rend
    ret


; ------------------------------------------------------------- state ------
gun_dx      db GUN_BOBHA            ; 0..2*GUN_BOBHA, BIASED: rest is
                                    ; GUN_BOBHA, matching BOBH
gun_dy      db GUN_BOBVA            ; 0..2*GUN_BOBVA scanlines, BIASED the
                                    ; same way: rest is GUN_BOBVA, the
                                    ; anchor, and larger is HIGHER
gun_pv      db 0                    ; phase into BOBV
gun_ph      db 0                    ; phase into BOBH
gun_lfsr    db 1                    ; never 0, or it would stick there

; --- the generation stamp, and why two bytes here are worth it -------
;  gun_draw is verified by reading the ART out of gunart.py and the
;  PIXELS out of a booted disc, and nothing in that arrangement forces
;  the two to be the same generation.  They came apart: the art was
;  edited and `make gun` was run, which boots build/amaze.dsk and never
;  builds it, so the harness compared a new drawing against an old disc
;  and reported thousands of wrong bytes and a weapon with no hand --
;  every diff true, none of them a defect in this file.  A pixel diff
;  cannot tell a broken blitter from a stale disc.  GUN_SIG is an FNV
;  over the run list AND the geometry (H, the bob amplitudes, the cut,
;  the band count), gentab.py derives it from the art, and emu_gun.py
;  reads this word off the running machine and refuses to compare
;  anything until it matches.  The Makefile now also makes every target
;  that boots the disc build it first; this is the belt to that brace,
;  because the two files can be edited independently and a harness that
;  is run by hand does not go through the Makefile at all.
gun_stamp   dw GUN_SIG              ; NOT "gun_sig": rasm labels are case-
                                    ; insensitive and GUN_SIG is the equ
