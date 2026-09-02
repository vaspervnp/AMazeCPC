; =====================================================================
;  engine2/src/menu.asm -- THE TITLE SCREEN.
;
;      menu_show   paint it, wait for SPACE, return.  Once, before the
;                  game loop; it never runs again.
;
;  It is the only text this engine draws.  Everything else on screen is
;  a rectangle -- the HUD's furniture, the readouts, the world -- and a
;  rectangle cannot spell REVIVE8BIT, so this brings a font with it.
;  engine2/tools/genmenu.py owns the glyphs, the words and the colours;
;  there is not a coordinate or a character in this file.
;
;  THE BLIT IS A NIBBLE LOOKUP AND NOTHING ELSE.  A glyph is four pixels
;  wide, which is one nibble of font and two bytes of screen, so a row is
;  one table read and two stores.  The table is per PEN, generated, so
;  mode 0's scrambled bit layout is answered in Python once instead of by
;  a shift-and-mask loop here.  Six rows a glyph, three bytes of pitch --
;  four of ink and two of gap -- and every glyph starts on a byte, which
;  is why there is no shifted path at all.
;
;  NO DOUBLE BUFFER.  The game flips two 16K buffers; the menu is one
;  still picture and paints the front one only.  main3.asm clears both
;  before calling this, so the buffer the game starts drawing into is
;  black rather than half a title screen.
;
;  Needs BANK 4 PAGED (LINETAB) and interrupts off, like every other
;  thing here that puts SP on the screen -- except that this one does
;  not: it writes with LD (HL),A, because 118 characters once is not
;  worth the PUSH DE machinery or the SP discipline that comes with it.
; =====================================================================

MN_KEY      equ 5           ; KEYS row 5, bit 7: SPACE.  The same byte
MN_KBIT     equ 7           ; game.asm reads -- see scan_keys.

; ---------------------------------------------------------------------
;  menu_show -- IN nothing.  Clobbers everything.
; ---------------------------------------------------------------------
; WHERE THE BLOCK IS COPIED TO, and why it is safe.  main3.asm calls
; menu_show BEFORE maze_unpack, march_init and game_init, so SOLID,
; MARK and the quad list are all still uninitialised -- 960 bytes of RAM
; that nothing has a claim on yet and everything overwrites the moment
; the game starts.  The menu borrows the front of it and never touches
; it again.
MENUBUF     equ SOLID
    assert MN_BLOB <= QUADS+NQUAD*QRECSZ-MENUBUF

MNPENS      equ MENUBUF+MN_O_PENS
MNFONT      equ MENUBUF+MN_O_FONT
MNTEXT      equ MENUBUF+MN_O_TEXT
MNDEAD      equ MENUBUF+MN_O_DEAD
MNWIN       equ MENUBUF+MN_O_WIN

; ---------------------------------------------------------------------
;  TWO SCREENS, ONE BLITTER.  genmenu.py emits the words as a list of
;  (row, x, pen, len, indices...) records ended by a zero length, and
;  which list this walks is one `ld ix`.  So the death screen costs a
;  second list in the generator, four bytes of terminator, and the three
;  instructions below -- against a copy of everything from here down.
;
;  menu_show   the title, at startup
;  menu_dead   the one after the last hit point.  main3.asm restarts the
;              world after it, because MENUBUF equ SOLID: painting either
;              screen DESTROYS THE MAP, so there is no resuming from one.
;              That is not a limitation being worked around, it is why
;              the death screen restarts rather than continues.
; ---------------------------------------------------------------------
menu_win
    ld   hl,MNWIN
    jr   mn_at
menu_dead
    ld   hl,MNDEAD
    jr   mn_at
menu_show
    ld   hl,MNTEXT
mn_at
    ld   (mn_list),hl
    ; ---- FETCH IT OUT OF BANK 5 FIRST.  The font, the colour tables and
    ;      the words are 568 bytes that are read once and never again, so
    ;      they live in the renderer's table bank rather than in a code
    ;      segment that has hit its ceiling thirteen times.  Bank 5 goes
    ;      over &4000 for exactly one LDIR -- and LINETAB, which the blit
    ;      below needs, is in bank 4 underneath it, which is why this is
    ;      a copy and not a read in place.
    ld   bc,#7F00+TEXCFG
    out  (c),c
    ld   hl,MENUTB
    ld   de,MENUBUF
    ld   bc,MN_BLOB
    ldir
    ld   bc,#7FC4
    out  (c),c

    ld   hl,SCR_FRONT               ; the picture goes in the buffer that
    call clear_16k                  ; is on display, and only that one

    ld   ix,(mn_list)
mn_next
    ld   a,(ix+3)                   ; the length: 0 ends the list
    or   a
    jr   z,mn_wait
    ld   (mn_n),a

    ld   a,(ix+2)                   ; ---- this line's pen table
    add  a,a
    ld   e,a
    ld   d,0
    ld   hl,MNPENS
    add  hl,de
    ld   a,(hl)
    inc  hl
    ld   h,(hl)
    ld   l,a
    ld   (mn_pen),hl

    ld   a,(ix+1)                   ; ---- and where it starts
    ld   (mn_x),a
    ld   a,(ix+0)
    ld   (mn_y),a

    push ix
    pop  hl
    ld   de,4
    add  hl,de                      ; HL -> the glyph indices
mn_char
    ld   a,(hl)                     ; ---- one glyph
    cp   MN_GSCORE                  ; ...or THE SCORE, a hole genmenu.py
    jr   nz,mn_nsc                  ; left at 255 -- one past every real
    ld   a,(scr_g)                  ; glyph index, so it costs no font.
mn_nsc                              ; NOT `mn_g0`: rasm's labels are CASE
                                    ; INSENSITIVE and MN_G0 is the equ
                                    ; beside it -- the same trap MON_HPMAX
                                    ; and mon_hp document in game.asm
    push hl
    call mn_glyph
    pop  hl
    inc  hl
    ld   a,(mn_x)                   ; ...and on to the next column
    add  a,MN_PITCH
    ld   (mn_x),a
    ld   a,(mn_n)
    dec  a
    ld   (mn_n),a
    jr   nz,mn_char

    push hl                         ; HL is one past the line's last index,
    pop  ix                         ; which is where the next record starts
    jr   mn_next

    ; ---- AND WAIT FOR THE PRESS EDGE, not the level.  A player who
    ;      held SPACE to get here would otherwise start the game and open
    ;      the door in front of them in the same breath: game.asm's
    ;      door_act is a press edge too, and it would see the same key
    ;      still down on the first frame.
mn_wait
    call scan_keys
    ld   a,(KEYS+MN_KEY)
    bit  MN_KBIT,a
    jr   z,mn_wait                  ; still down from before -- wait it out
mn_down
    call scan_keys
    ld   a,(KEYS+MN_KEY)
    bit  MN_KBIT,a
    jr   nz,mn_down
    ret


; ---------------------------------------------------------------------
;  mn_glyph -- A = a glyph index.  Draws it at (mn_x, mn_y) in (mn_pen).
;  Clobbers AF BC DE HL.
; ---------------------------------------------------------------------
mn_glyph
    ld   l,a                        ; MNFONT + index * MN_GH, and MN_GH is
    ld   h,0                        ; 6, so it is (i*2 + i*4)
    add  hl,hl
    ld   e,l
    ld   d,h
    add  hl,hl
    add  hl,de
    ld   de,MNFONT
    add  hl,de
    ld   (mn_gp),hl

    ld   a,(mn_y)
    ld   (mn_row),a
    ld   b,MN_GH
mn_grow
    push bc
    ld   a,(mn_row)                 ; ---- HL = LINETAB[row] + x
    ld   l,a
    ld   h,0
    add  hl,hl
    ld   bc,LINETAB
    add  hl,bc
    ld   c,(hl)
    inc  hl
    ld   h,(hl)
    ld   l,c
    ld   a,(mn_x)
    add  a,l
    ld   l,a
    ld   a,h
    adc  a,0
    and  #3F                        ; LINETAB is written for #C000 and the
    or   SCR_FRONT/256              ; menu only ever paints there
    ld   h,a
    ex   de,hl                      ; DE -> the screen

    ld   hl,(mn_gp)                 ; ---- the row's nibble -> two bytes
    ld   a,(hl)
    inc  hl
    ld   (mn_gp),hl
    add  a,a
    ld   c,a
    ld   b,0
    ld   hl,(mn_pen)
    add  hl,bc
    ld   a,(hl)
    ld   (de),a
    inc  de
    inc  hl
    ld   a,(hl)
    ld   (de),a

    ld   hl,mn_row
    inc  (hl)
    pop  bc
    djnz mn_grow
    ret


mn_x        db 0
mn_y        db 0
mn_n        db 0
mn_row      db 0
mn_gp       dw 0
mn_pen      dw 0
mn_list     dw MNTEXT           ; which word list to paint -- see mn_at

; THE SCORE, AND IT IS A GLYPH INDEX AND NOT A NUMBER.  game.asm INCs it
; -- once a pickup, once for the monster -- and mn_char draws it, so the
; conversion from a count to a character is done by STARTING the count at
; MN_G0 and never doing it at all.  CHARSET is sorted, so '0'..'9' are
; contiguous and an INC is legal; genmenu.py emits MN_G0 so the two
; cannot drift.
scr_g       db MN_G0
