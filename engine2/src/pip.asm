; =====================================================================
;  engine2/src/pip.asm -- THE AMMO PICKUP, STANDING ON THE FLOOR.
;
;      pip_draw   once a game frame, AFTER raster_paced and before the
;                 weapon.  Draws the nearest live pickup as a block on
;                 the floor, or nothing.
;
;  WHY IT IS ONE COLUMN PAIR WIDE.  The renderer leaves behind exactly
;  the information this needs and no more: (rc_dn)+p is, after the wall
;  pass, ONE PAST the bottom screen row of the nearest wall at column
;  pair p -- which is the floor line at that pair.  Snapping the block to
;  a pair makes the occlusion test ONE COMPARE against ONE byte, instead
;  of a per-column clip against something the engine does not keep.
;
;  THE ONE PLACE IT IS NOT EXACT: both rc_dn and the box's foot row
;  saturate at the bottom of the viewport, so a box and a wall that are
;  BOTH within about a cell compare two clamps and the box loses.  The
;  player cannot stand inside a wall, so the case needs the box itself
;  to be a cell away and the wall no further -- and at that range the
;  box fills the screen anyway.
;
;  AND THE OCCLUSION IS EXACT, FOR FREE, BECAUSE A ROW IS A DEPTH.  The
;  camera sits at wall mid-height and cannot pitch, so the floor at
;  distance z projects to row CYH + 48/z -- the SAME formula as a wall's
;  half height (gentab.py's HTAB is round(196608/zq) for exactly this).
;  A wall in front of the pickup therefore has its foot BELOW the
;  pickup's block on screen, and rc_dn cuts the block away.  There is no
;  z-buffer here and none is needed.
;
;  IT IS DRAWN AFTER THE WALLS, NOT BEFORE.  Before would have been
;  simpler -- bg_fill, block, walls over the top -- but a wall FARTHER
;  than the pickup would then paint over it, because its band reaches
;  higher up the screen than the block does.  After the walls, with
;  rc_dn as the cut, is the only order that is right both ways round.
;
;  ONE THING IT GETS WRONG, AND IT IS WRITTEN DOWN RATHER THAN HIDDEN.
;  rastcol.asm's moving-door overlay RESETS rc_up/rc_dn on the pairs it
;  draws (rc_pairloop, "OVERLAY: forget what covered this pair") and then
;  re-grows them to the door's own rows.  So for the six frames a door is
;  in motion, a pickup behind it can show through it.  A shut door is
;  SOLID and covered correctly; an open one is gone.  Six frames of one
;  door is the whole of it, and the alternative -- drawing between the
;  two passes -- cannot work: proj_pt reads HTAB out of bank 4 and
;  raster_colframe has bank 5 paged over it from end to end.
;
;  Needs: march.asm (mv_x0 mv_z0 mv_sxi..mv_szj), project.asm (proj_pt),
;         rastcol.asm (rc_dn), hud2.asm (hud_rect), game.asm (as_*).
;  Bank 4 must be paged and interrupts off -- both true where main3.asm
;  calls it.
; =====================================================================

; HOW FAR IT IS WORTH DRAWING, in L1 cells.  Past this the block is one
; or two scanlines of a single pair -- a speck that reads as screen dirt
; rather than as an object -- and the HUD is the thing that finds a
; pickup at that range.  It also bounds the four repeated-add loops
; below to this many iterations each, which is what keeps them loops
; instead of multiplies.
PIP_MAX     equ 5
PIP_PEN     equ #03         ; pen 8, firmware ink 15: the orange the ammo
                            ; pips and the scanner already use, so the
                            ; thing on the floor and the readouts that
                            ; point at it are the same colour
PIP_HMAX    equ 12          ; ...nor grows past it, whatever the distance

; ---------------------------------------------------------------------
;  fx_draw -- THE SHOT: the flash at the muzzle and the mark where it
;  landed.  Once a game frame, after the world and before the weapon.
;
;  THE SHOT IS NOT TRACED, AND THIS IS THE HONEST VERSION OF THAT.  The
;  gun points down the middle of the screen, so whatever the renderer
;  just put in the middle column pair IS what a shot down the barrel
;  hits -- and the renderer has already left the answer behind: rc_dn at
;  the centre pair is the screen row of the nearest wall's foot there,
;  and (mon_bot) is the monster's foot row when it drew over that pair.
;  A row is a depth, so whichever is LOWER is nearer, and that decides
;  blood from stone.  No ray, no cells walked, no second march.
;
;  It is one frame stale -- game.asm fires before the frame is drawn --
;  which at five frames a second nobody can see.
;
;  Clobbers AF BC DE HL IX.
; ---------------------------------------------------------------------
FX_LIFE     equ 2           ; game frames the mark stays up
FX_BLOOD    equ #C3         ; pen 9, ink 6: bright red
FX_STONE    equ #3F         ; pen 14, ink 13: white-grey chips
FX_FLASH    equ #FC         ; pen 7, ink 24: bright yellow at the muzzle
FX_W        equ 4           ; the mark, bytes (even) and scanlines
FX_H        equ 4

fx_draw
    ld   a,(gun_recoil)             ; ---- THE MUZZLE FLASH, for as long as
    or   a                          ;      the recoil lasts, so the kick
    jr   z,fx_mark                  ;      and the flash are one event
    ld   a,GUN_XB+(GUN_WB-FX_W)/2
    ld   (hr_x),a
    ld   a,(gun_dy)                 ; the sprite rises with the bob and so
    ld   c,a                        ; must the flash: the top row is
    ld   a,GUN_Y0+GUN_BOBVA-FX_H    ; GUN_Y0 - (gun_dy - GUN_BOBVA)
    sub  c
    ld   (hr_y),a
    ld   a,FX_W
    ld   (hr_w),a
    ld   a,FX_H
    ld   (hr_h),a
    ld   a,FX_FLASH
    ld   (hr_pen),a
    call hud_rect

fx_mark
    ld   hl,fx_timer                ; ---- and the mark where it landed
    ld   a,(hl)
    or   a
    ret  z
    dec  (hl)
    ld   a,(fx_row)
    ld   (hr_y),a
    ld   a,VP_BX+VP_BW/2-FX_W/2
    ld   (hr_x),a
    ld   a,FX_W
    ld   (hr_w),a
    ld   a,FX_H
    ld   (hr_h),a
    ld   a,(fx_pen)
    ld   (hr_pen),a
    jp   hud_rect


; ---------------------------------------------------------------------
;  fx_fire -- called by game.asm on the frame a round is spent.  Reads
;  the LAST frame's rc_dn and (mon_bot) to decide what the shot hit.
;  Clobbers AF HL.
; ---------------------------------------------------------------------
fx_fire
    ld   a,FX_LIFE
    ld   (fx_timer),a

    ; ---- WHERE IT LANDS IS THE HORIZON, whatever it hit.  The barrel is
    ;      at eye height and points level, and the floor at distance z
    ;      projects to CYH + 48/z -- so a level shot lands at CYH itself,
    ;      at every range and against everything.  The first version put
    ;      the mark at the wall's FOOT, which is where the wall meets the
    ;      floor: too low to be a bullet hole, and squarely behind the
    ;      weapon sprite, which owns the bottom centre of the viewport.
    ld   a,CYH-FX_H/2
    ld   (fx_row),a

    ; ---- and WHAT it hit is one compare of two screen rows, because a
    ;      row is a depth: the monster's foot BELOW the wall's foot means
    ;      the monster is nearer.  mon_bot is 0 when it did not draw over
    ;      the centre pair at all, which loses that compare and gives
    ;      stone, as it should.
    ld   a,(rc_dn+CNPAIR/2)
    ld   hl,mon_bot
    cp   (hl)
    ld   a,FX_STONE
    jr   nc,fx_chip
    ld   a,FX_BLOOD
fx_chip
    ld   (fx_pen),a
    ret


; ---------------------------------------------------------------------
;  mon_draw -- THE MONSTER, standing where the map put it.
;
;  It does nothing but stand there.  That is the point: it is a target
;  with a known position and a known size, so the shot's impact effect
;  can be told apart from the wall's by looking at it.
;
;  Same path as the pickup -- box_draw below -- with three differences:
;  it is half a cell tall rather than a quarter (bx_sh 0), three column
;  pairs wide rather than one (bx_hw 1), and mauve.  Being wider is what
;  makes the per-pair cut earn its keep: standing at the edge of a
;  doorway it is behind the jamb on one pair and in the opening on the
;  next.
;
;  Clobbers AF BC DE HL IX.
; ---------------------------------------------------------------------
MON_PEN     equ #F3         ; pen 13, firmware ink 9 (mauve) -- the one
                            ; warm-dark colour nothing else on screen
                            ; uses, so it reads as flesh against the
                            ; blue walls and the olive floor
MON_MAX     equ 6           ; L1 cells: it is not drawn past this
MON_HMAX    equ 28          ; ...and no taller than this on screen
MON_HW      equ 1           ; half width in column PAIRS, so three pairs.
                            ; ONE CONSTANT, TWO READERS: it sets bx_hw
                            ; below AND it is the aim cone, because the
                            ; shot hits when the pairs this draws include
                            ; the crosshair's.  They were two literals and
                            ; the second one did not exist.

mon_draw
    xor  a
    ld   (mon_bot),a                ; nothing there unless it draws
    ld   a,(MONCELL)                ; where the map put it, y*16+x
    cp   #FF
    ret  z                          ; ...or nowhere, if the map has none
    and  #0F
    ld   e,a
    ld   a,(plr_x+1)
    ld   b,a
    ld   a,e
    sub  b
    ld   (bx_dx),a
    jr   nc,mn_xp
    neg
mn_xp
    ld   c,a                        ; C = |dx|, for the range guard
    ld   a,(MONCELL)
    rrca
    rrca
    rrca
    rrca
    and  #0F
    ld   e,a
    ld   a,(plr_y+1)
    ld   b,a
    ld   a,e
    sub  b
    ld   (bx_dy),a
    jr   nc,mn_yp
    neg
mn_yp
    add  a,c
    cp   MON_MAX+1
    ret  nc                         ; too far to be worth the projection
    ld   a,MON_PEN
    ld   (bx_pen),a
    xor  a
    ld   (bx_sh),a                  ; half a cell tall...
    ld   (bx_air),a                 ; ...standing on the floor...
    ld   a,MON_HW
    ld   (bx_hw),a                  ; ...and three pairs wide
    ld   a,MON_HMAX                 ; ...and capped, because hud_rect costs
    ld   (bx_hmax),a                ; ~70 us a ROW and an uncapped monster
                                    ; at one cell is 48 of them across
                                    ; three pairs: MEASURED 11691 us for
                                    ; the three world drawers together,
                                    ; 59% of a vsync period in ONE
                                    ; interval.  Capped it is a monster
                                    ; whose head is cut off when you walk
                                    ; into it, which is what walking into
                                    ; something looks like anyway.
    call box_draw

    ; ---- AND ONLY IF IT COVERS THE CROSSHAIR.  This used to copy
    ;      bx_bot unconditionally, which made the aim cone THE WHOLE
    ;      FIELD OF VIEW: box_draw writes bx_bot once for the box, not
    ;      once per pair, so "the monster drew" and "the monster drew
    ;      where the gun is pointing" were the same test.  MEASURED on
    ;      the booted disc, player four cells from the monster, all 72
    ;      headings: the shot read flesh on ten of the eleven headings
    ;      that had the monster anywhere on screen, including the two
    ;      where it was against the viewport edge.
    ;
    ;      It did not matter while the monster was a target that could
    ;      not be killed.  It matters the moment it has hit points,
    ;      because three rounds anywhere near it is not aiming.
    ;
    ;      THE TEST IS THE DRAWN PAIRS, not an angle.  box_draw puts the
    ;      box's centre pair in pip_p and paints pip_p-MON_HW..pip_p+MON_HW,
    ;      so the cone is exactly "one of those pairs is the middle one"
    ;      -- the pair fx_fire reads rc_dn at.  Three pairs of 22, and it
    ;      is the same three the player can see the monster standing in.
    ld   a,(bx_bot)
    or   a
    ret  z                          ; box_draw rejected it: mon_bot stays 0
    ld   a,(pip_p)
    sub  CNPAIR/2
    jr   nc,mn_cp
    neg
mn_cp
    cp   MON_HW+1
    ret  nc                         ; drawn, but not over the middle pair
    ld   a,(bx_bot)                 ; ...and leave its foot for fx_fire
    ld   (mon_bot),a
    ret


; ---------------------------------------------------------------------
;  pip_draw -- IN nothing.  Clobbers AF BC DE HL IX.
; ---------------------------------------------------------------------
pip_draw
    ld   a,(as_best)                ; game.asm's ammo_scan already picked
    cp   AMMO_NODIR                 ; the nearest live one and left its
    ret  z                          ; offset in cells behind it
    ld   a,(as_dist)
    cp   PIP_MAX+1
    ret  nc
    ld   a,(as_dx)
    ld   (bx_dx),a
    ld   a,(as_dy)
    ld   (bx_dy),a
    ld   a,PIP_PEN
    ld   (bx_pen),a
    ld   a,1                        ; a quarter of a cell tall...
    ld   (bx_sh),a
    ld   a,PIP_HMAX
    ld   (bx_hmax),a
    xor  a
    ld   (bx_hw),a                  ; ...one pair wide...
    ld   (bx_air),a                 ; ...and standing on the floor
    ; fall through

; ---------------------------------------------------------------------
;  box_draw -- AN UPRIGHT BOX AT A CELL, and the one drawing path every
;  world-space thing in this engine uses.
;
;  IN   (bx_dx)(bx_dy)  the cell offset from the player, signed
;       (bx_pen)        the byte to fill it with
;       (bx_sh)         height: the half height j shifted right by this,
;                       so 0 is half a cell tall, 1 a quarter, 2 an eighth
;       (bx_hw)         half width in column PAIRS: 0 draws one pair,
;                       1 draws three, 2 draws five
;       (bx_air)        0 stands it on the floor, 1 centres it on the
;                       horizon -- which is eye height, where a shot
;                       lands
;  Clobbers AF BC DE HL IX.
;
;  ONE PAIR AT A TIME, EACH CUT BY ITS OWN rc_dn.  A box three pairs wide
;  straddling a wall's edge is behind the wall on one pair and in front
;  on the next, and that is the case the per-pair cut exists for.
; ---------------------------------------------------------------------
box_draw
    ; ---- "IT DID NOT DRAW" HAS TO BE SAYABLE, AND IT WAS NOT.
    ;      There are five ret paths below -- the near plane, proj_pt's
    ;      overflow, and the two viewport edges -- and not one of them
    ;      wrote bx_bot, so a rejected box left the LAST box's foot
    ;      sitting there.  mon_draw copies bx_bot into mon_bot the
    ;      instant box_draw returns, and fx_fire reads mon_bot to decide
    ;      whether a shot hit flesh or stone.
    ;
    ;      So: turn your back on the monster and shoot a wall, and the
    ;      wall bled.  main3.asm calls pip_draw BEFORE mon_draw, so what
    ;      mon_bot actually held was the PICKUP's foot row.
    ;
    ;      MEASURED on the booted disc, player four cells east of the
    ;      monster, sweeping all 72 headings: mon_bot was non-zero on
    ;      72 of 72, and fx_pen read FX_BLOOD on 24 of them -- in three
    ;      disjoint arcs, including headings pointing away.  Poisoning
    ;      bx_bot with #AA and running one frame put #AA straight into
    ;      mon_bot, which is the whole bug in one byte.
    ;
    ;      Zeroing it here rather than in mon_draw because the contract
    ;      belongs to the drawer: every caller now gets 0 for "nothing
    ;      drawn", and bx_pair only ever runs on the success path, so
    ;      nothing downstream can see the zero.
    xor  a
    ld   (bx_bot),a

    ; ---- the box's centre, in the march's own view space ------------
    ;      mv_x0 / mv_z0 are the view coordinates of the PLAYER'S OWN
    ;      CELL CORNER and mv_sxi.. are the per-cell steps, so stepping
    ;      dx and dy times lands on the pickup's corner and half of each
    ;      step again lands on its centre.  The two axes are the same
    ;      arithmetic over consecutive words, so they are one routine
    ;      indexed by IX rather than two copies -- see pip_axis.
    ld   hl,(mv_x0)
    ld   ix,mv_sxi
    call pip_axis
    ld   (pip_xv),hl
    ld   hl,(mv_z0)
    ld   ix,mv_szi
    call pip_axis

    ; ---- THE NEAR PLANE, AND IT IS A REJECT, NOT A CLAMP.  proj_pt's
    ;      contract says z >= ZNEAR and it does not check: handed a
    ;      smaller one it CLAMPS, which turns a pickup behind the
    ;      player's shoulder into a bright block at the dead centre of
    ;      the horizon.  The face path rejects at project.asm:182 and so
    ;      does this.
    ;
    ;      AND IT HAS TO BE A SIGNED COMPARE, WHICH THIS WAS NOT.  It
    ;      read
    ;
    ;          ld de,ZNEAR_Q10 / or a / sbc hl,de / ret c
    ;
    ;      and `ret c` after SBC HL,DE tests the UNSIGNED borrow.  zv is
    ;      signed: something behind the player has zv negative, which as
    ;      an unsigned 16-bit number is enormous, so it does not borrow,
    ;      so it was NOT rejected -- it went on to proj_pt and got drawn.
    ;      The line above claiming this matches project.asm:182 was the
    ;      tell: that one negates the constant, adds, and tests the SIGN
    ;      bit (`ld a,h / and b / ret m`).  This did something else.
    ;
    ;      MEASURED, player four cells east of the monster, all 72
    ;      headings swept on the booted disc: fx_pen read FX_BLOOD in
    ;      THREE disjoint arcs -- 31..40, which is the monster, and
    ;      2..8 and 68..70, which are due east, facing directly away
    ;      from it.  Turn your back and shoot a wall, and the wall bled.
    ;
    ;      ADD HL,DE does not set S or Z on a Z80 -- only H, N and C --
    ;      which is why the sign has to be tested through A.
    ld   de,-ZNEAR_Q10
    push hl
    add  hl,de                      ; zv - ZNEAR
    ld   a,h
    pop  hl                         ; ...and zv back, flags untouched
    or   a
    ret  m                          ; negative: at or behind the near plane
    ex   de,hl                      ; DE = zv
    ld   hl,(pip_xv)
    call proj_pt                    ; -> HL = xs Q12.4, DE = hh Q12.4
    ret  c                          ; too far outside to be representable

    ld   (pip_hh),de

    ; ---- the column PAIR, and the guard is the viewport's own width.
    ;      xs is Q12.4 in mode-0 PIXELS from the left edge, so a pair --
    ;      two bytes, four pixels -- is 64 of them and the last valid xs
    ;      is XMAX_Q4-1.  Testing the HIGH BYTE against 6 instead lets
    ;      xs 1408..1535 through, which is pair 22 or 23: two bytes
    ;      written PAST the viewport, onto HUD furniture that is painted
    ;      once at boot and never repaired, and a read of rc_dn[22] --
    ;      which is not rc_dn at all but rastcol's rc_blo.
    bit  7,h
    ret  nz                         ; negative: off the left edge
    ld   de,XMAX_Q4
    push hl
    or   a
    sbc  hl,de
    pop  hl
    ret  nc                         ; >= XMAX_Q4: off the right edge
    add  hl,hl                      ; xs*4 -> the pair is the high byte
    add  hl,hl
    ld   a,h                        ; A = xs >> 6 = the pair, 0..21
    ld   (pip_p),a

    ; ---- the block: its foot is the floor at this depth, which is the
    ;      same row a wall's foot would be -- CYH + hh.  Its height is
    ;      half of that again, so it is a quarter of a cell tall and
    ;      shrinks with distance like everything else.
    ;      j = hh >> 4, AND IT IS A SIXTEEN-BIT SHIFT.  Doing it on the
    ;      low byte alone treats every hh of 256 or more as an overflow,
    ;      and hh is 16*(48/z): 256 is z = 3 CELLS.  That is not the
    ;      degenerate case, it is most of the range this draws in, and
    ;      it would have pinned every pickup nearer than three cells to
    ;      the bottom row at full height.
    ld   hl,(pip_hh)
    ld   b,4
pip_sh
    srl  h
    rr   l
    djnz pip_sh
    ld   a,h
    or   a
    jr   z,pip_gotj
    ld   l,VP_H-1-CYH               ; j >= 256: everything below clamps
pip_gotj
    ld   a,l
    ld   b,a                        ; B = j = hh >> 4, the half height

    ld   a,(bx_sh)                  ; ---- the box's own height, j >> bx_sh
    or   a
    jr   z,pip_gh
pip_shl
    srl  b
    dec  a
    jr   nz,pip_shl
pip_gh
    ld   a,(bx_air)                 ; ---- and where its FOOT sits: on the
    or   a                          ;      floor line, or half its height
    ld   a,l                        ;      below the horizon, which puts
    jr   z,pip_foot                 ;      its middle at eye level
    srl  a
    srl  a                          ; j >> 2 is a rough half of the box
    add  a,b
    srl  a
    jr   pip_bot
pip_foot
    ld   a,l
pip_bot
    add  a,CYH
    cp   VP_H
    jr   c,pip_botok
    ld   a,VP_H-1
pip_botok
    ld   c,a                        ; C = the block's bottom row
    ; NO MINIMUM.  There was a two-row floor here, and it was dead
    ; weight: PIP_MAX and MON_MAX already stop either box being drawn
    ; past five or six cells, where the height is still four rows, and
    ; hud_rect returns on a height of zero anyway.
    ld   a,b
    ld   e,a                        ; E, NOT C: C is holding the bottom
    ld   a,(bx_hmax)                ; row and the box is measured from it.
    cp   e                          ;
    jr   nc,pip_hi                  ; THE CAP IS THE CALLER'S, not one
    ld   e,a                        ; number for everything.  It was
pip_hi                              ; PIP_HMAX for both, which is a
    ld   a,e                        ; quarter of a cell -- so the monster,
    ld   b,a                        ; half a cell tall, came out a stub

    ; ---- THE BOX, UNCLIPPED, kept where every pair can read it.
    ;      Clipping the centre pair and then clipping the sides FROM THE
    ;      CENTRE'S RESULT shrinks the box a little more at every step,
    ;      which is what made the monster's flanks vanish.  The cut is
    ;      per pair against the same box.
    ld   a,c
    ld   (bx_bot),a                 ; the foot...
    ld   a,c
    sub  b
    inc  a
    ld   (bx_top),a                 ; ...and the head

    ld   a,2
    ld   (hr_w),a
    ld   a,(bx_pen)
    ld   (hr_pen),a

    ld   a,(pip_p)                  ; ---- the centre pair
    call bx_pair
    ld   a,(bx_hw)                  ; ---- and the ones either side
    or   a
    ret  z
    ld   b,a
    ld   a,(pip_p)
    ld   c,a
bx_side
    push bc
    ld   a,c
    sub  b
    call bx_pair                    ; ...to the left
    pop  bc
    push bc
    ld   a,c
    add  a,b
    call bx_pair                    ; ...and to the right
    pop  bc
    djnz bx_side
    ret

; --- A = a column pair: draw the box's slice of it, cut by rc_dn.
;     Reads (bx_top)(bx_bot), which no pair changes, so the cut is the
;     same question at every one of them.  Clobbers AF BC DE HL IX.
bx_pair
    cp   CNPAIR
    ret  nc                         ; off the viewport, either end
    push af
    ld   e,a
    ld   d,0
    ld   hl,rc_dn
    add  hl,de
    ld   a,(bx_bot)
    cp   (hl)
    jr   nc,bx_pvis
    pop  af
    ret                             ; wholly behind the wall at this pair
bx_pvis
    ; ---- AND IT IS ALL OR NOTHING, NOT A CLIP.  Clipping the head to
    ;      rc_dn is right for a thing lying ON the floor and wrong for
    ;      anything that stands up: a monster NEARER than the wall
    ;      reaches ABOVE the wall's foot on screen, and cutting it there
    ;      left a five-row stump at its ankles.
    ;
    ;      The comparison above is already the whole answer, because a
    ;      row IS a depth: the box's foot at or below the wall's foot
    ;      means the box is NEARER, and a nearer box is drawn whole.
    ;      Farther, and none of it is visible at this pair at all.
    ld   b,a                        ; B = the foot
    ld   a,(bx_top)
    ld   c,a
    pop  af
    add  a,a
    add  a,VP_BX
    ld   (hr_x),a
    ld   a,c
    add  a,VP_Y
    ld   (hr_y),a
    ld   a,b
    sub  c
    inc  a
    ld   (hr_h),a
    jp   hud_rect


; --- ONE VIEW AXIS.  IN HL = the seed at the player's cell corner,
;     IX -> that axis's (step in i, step in j).  OUT HL = the view
;     coordinate of the pickup's cell CENTRE.  Clobbers AF BC DE.
pip_axis
    ld   e,(ix+0)
    ld   d,(ix+1)
    ld   a,(bx_dx)
    call pip_mad
    ld   e,(ix+2)
    ld   d,(ix+3)
    ld   a,(bx_dy)
    call pip_mad
    push hl                         ; ...+ half a cell of each step, which
    ld   l,(ix+0)                   ; is what moves the corner to the
    ld   h,(ix+1)                   ; centre
    ld   e,(ix+2)
    ld   d,(ix+3)
    add  hl,de
    sra  h
    rr   l
    ex   de,hl
    pop  hl
    add  hl,de
    ret


; --- HL += DE * A, for a SIGNED A of small magnitude ------------------
;     |as_dx| + |as_dy| <= PIP_MAX, so this runs at most PIP_MAX times
;     across both calls of a pair.  A multiply would be bigger and, at
;     five iterations, not faster.
;     Clobbers AF B.
pip_mad
    or   a
    ret  z
    jp   m,pm_neg
    ld   b,a
pm_add
    add  hl,de
    djnz pm_add
    ret
pm_neg
    neg
    ld   b,a
pm_sub
    or   a
    sbc  hl,de
    djnz pm_sub
    ret


; ---- SCRATCH, IN THE GAP ABOVE THE DOOR TABLES ----------------------
;  Five bytes, and they are equs rather than db because the body segment
;  has none to spare: `assert game_end <= BUCK0` has fired ten times and
;  this feature landed it with single digits left.  #3DF0..#3DFF is the
;  hole between game.asm's door tables (which end at #3DEF) and
;  rastcol.asm's RC_COVER at #3E00.  Nothing here needs initialising --
;  every one is written before it is read, inside one call.
PIPVARS     equ #3DF0
pip_xv      equ PIPVARS+0
pip_hh      equ PIPVARS+2
pip_p       equ PIPVARS+4
bx_dx       equ PIPVARS+7       ; box_draw's arguments -- see its header
bx_dy       equ PIPVARS+8
bx_pen      equ PIPVARS+9
bx_sh       equ PIPVARS+10
bx_hw       equ PIPVARS+11
bx_air      equ PIPVARS+12
bx_hmax     equ PIPVARS+13   ; the tallest the box may be, scanlines
bx_top      equ PIPVARS+14   ; ...and the box itself, unclipped
bx_bot      equ PIPVARS+15

; THE SHOT'S OWN FOUR BYTES, above rastcol.asm's scratch.
;  The gap between the door tables and RC_COVER is full (see the assert
;  above) and the body has none to spare, so these go in the free RAM
;  between the end of RC_VARS and the CPU stack -- main3.asm's map lists
;  it as #3E9C-#3FEF.  Nothing initialises them: fx_timer is set by the
;  first fx_fire and read only after it, and mon_bot is written by
;  mon_draw every frame before fx_fire can look at it.
FXVARS      equ #3EA0
fx_timer    equ FXVARS+0
fx_row      equ FXVARS+1
fx_pen      equ FXVARS+2
mon_bot     equ FXVARS+3            ; the monster's foot row, or 0
    assert FXVARS >= RC_VARS+110    ; clear of the renderer's scratch...
    assert FXVARS+4 <= #3F00        ; ...and of emu_pacefit's harness
    assert PIPVARS >= DOORTAB+MAXDOORS*3
    assert PIPVARS+16 <= RC_COVER
