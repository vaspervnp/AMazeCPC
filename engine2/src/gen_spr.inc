; ---------------------------------------------------------------------
;  gen_spr.inc -- GENERATED from assets/sprites.png by genspr.py.
;  Do not edit.  Paint the PNG.
;
;  Lists of rectangles in the box's own coordinates -- see genspr.py for
;  the format and for why the vertical edges are BANDS rather than rows.
;  pip.asm's spr_draw walks these.
; ---------------------------------------------------------------------

; ---- SPR_MON: the monster, 3 pairs x 4 bands, 6 rectangles ----
;      2754.6 us at a 28-row box, painted in this order.  The
;      digits are PEN numbers; '.' is not drawn.
;     DDD
;     FDF
;     DDD
;     0.0
SPR_MON_Y                      ; band top edges, 256ths of the box height
    db 0,72,108,224,255      ; ...the last is the foot
SPR_MON_NB      equ 4
SPR_MON_HW      equ 1              ; half width in column PAIRS -- and pip.asm's aim cone
SPR_MON                        ; db col, ncol, band0, band1, pen
    db  -1,  3,  0,  0,#F3      ; pen 13
    db  -1,  3,  1,  1,#FF      ; pen 15
    db  -1,  1,  3,  3,#00      ; pen 0
    db   1,  1,  3,  3,#00      ; pen 0
    db  -1,  3,  2,  2,#F3      ; pen 13
    db   0,  1,  1,  1,#F3      ; pen 13
    db #80                  ; end of list

; ---- SPR_PIP: the pickup, 3 pairs x 5 bands, 5 rectangles ----
;      2199.0 us at a 28-row box, painted in this order.  The
;      digits are PEN numbers; '.' is not drawn.
;     .F.
;     888
;     FFF
;     888
;     000
SPR_PIP_Y                      ; band top edges, 256ths of the box height
    db 0,40,100,150,214,255      ; ...the last is the foot
SPR_PIP_NB      equ 5
SPR_PIP_HW      equ 1              ; half width in column PAIRS -- and pip.asm's aim cone
SPR_PIP                        ; db col, ncol, band0, band1, pen
    db   0,  1,  0,  0,#FF      ; pen 15
    db  -1,  3,  2,  2,#FF      ; pen 15
    db  -1,  3,  1,  1,#03      ; pen 8
    db  -1,  3,  3,  3,#03      ; pen 8
    db  -1,  3,  4,  4,#00      ; pen 0
    db #80                  ; end of list

