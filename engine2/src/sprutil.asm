; =====================================================================
;  engine2/src/sprutil.asm -- two of pip.asm's sprite helpers, and they
;  are HERE for one reason: rastcol.asm has an `align 256` in front of
;  COLBLK, and whatever sits in front of that align comes out of the
;  padding instead of out of game_end.
;
;  There were 40 bytes of pad left and the minimap needed 24 of them.
;  That is the whole story; the code is pip.asm's and belongs with it in
;  every other sense.  Moving DATA here is the usual move (gen_spr.inc
;  is a few lines above), but a routine works just as well as long as it
;  only reaches backwards -- these two read CNPAIR (gen_tex.inc, in
;  tab_equ.inc at the top of main3.asm) and rc_dn, which rastcol.asm
;  equs a page later and rasm resolves on its second pass.
;
;  IF THE PAD RUNS OUT, MOVE THEM BACK.  A block that OVERFLOWS the pad
;  is worse than one that never used it: it pushes COLBLK to the next
;  page and the new pad is bigger than the old one, which is how a
;  133-byte gen_spr.inc once cost 123 bytes instead of saving 104.
; =====================================================================
; --- A = a band index -> A = the viewport row it starts at.
spr_row
    push hl
    ld   l,a
    ld   h,0
    ld   de,spr_rt
    add  hl,de
    ld   a,(hl)
    pop  hl
    ret


; --- A = a column pair BIASED BY 4 -> carry set if the sprite is visible
;     there.  Reads (bx_bot), not the record's own foot: the cut is the
;     same question for every part of one sprite, because a row is a
;     depth and the sprite stands at one depth.
;
;     AND IT IS ALL OR NOTHING, NOT A CLIP.  Clipping the head to rc_dn is
;     right for a thing lying ON the floor and wrong for anything that
;     stands up: a monster NEARER than the wall reaches ABOVE the wall's
;     foot on screen, and cutting it there left a five-row stump at its
;     ankles.  The comparison is already the whole answer, because a row
;     IS a depth: the box's foot at or below the wall's foot means the box
;     is nearer, and a nearer box is drawn whole.
;
;     Preserves BC.  Clobbers AF DE HL.
spr_vis
    sub  4
    jr   c,sv_no                    ; off the left edge of the viewport
    cp   CNPAIR
    jr   nc,sv_no                   ; ...or the right
    ld   e,a
    ld   d,0
    ld   hl,rc_dn
    add  hl,de
    ld   a,(bx_bot)
    cp   (hl)
    jr   c,sv_no                    ; the wall's foot is BELOW the box's:
    scf                             ; the wall is nearer, so nothing here
    ret                             ; carry SET means visible
sv_no
    or   a
    ret
