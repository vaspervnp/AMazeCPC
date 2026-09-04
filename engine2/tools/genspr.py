"""engine2/tools/genspr.py -- THE MONSTER AND THE PICKUP, AS SHAPES.

    python3 engine2/tools/genspr.py     -> engine2/src/gen_spr.inc

Both of them used to be ONE SOLID RECTANGLE per column pair: pip.asm's
box_draw computed a top row and a bottom row and painted every pair of
the box between them in one colour.  That is why they read as blocks.

WHAT REPLACES IT IS THE HUD'S OWN IDIOM.  hud2.asm draws the whole
instrument panel out of a list of rectangles (HUDRECTS) because a PUSH
DE fill is the fastest store on the machine.  A sprite here is the same
list, back to front, in the box's OWN coordinates:

    db col, ncol, band0, band1, pen

  col          column PAIR offset from the sprite's centre, signed.  A
               pair is two bytes -- four mode-0 pixels.
  ncol         how many pairs WIDE, and this field is the whole design.
  band0/band1  first and last BAND, inclusive.  Bands are the horizontal
               slices below; band k spans rows rowtab[k]..rowtab[k+1]-1.
  pen          the mode-0 solid byte, straight into hud_rect.

and the list ends with #80, which cannot be a signed pair offset.

WHY `ncol` EXISTS, MEASURED.  hud_rect costs 87 us a CALL and 63 us a
ROW, and a row is almost free to widen -- 0.5 us a byte a row:

    2 bytes x 28 rows   1850.7 us          10 bytes x 8 rows   718.4
    2 bytes x  8 rows    590.9             6 bytes x 8 rows    655.5
    2 bytes x  1 row     150.0             4 bytes x 8 rows    622.8

So a picture drawn one PAIR at a time pays 63 us a row for every column
it is wide, and the same picture drawn as wide rectangles pays it once.
The first version of this file emitted one-pair records and cost 12902.7
us for pip.asm's three drawers at one cell, against a C_PIP of 8200 --
narrowing the monster from five pairs to three only brought it to 9705.0,
because the rows were never the problem.  Rectangles that span their
whole width cost about a third of that AND draw a bigger monster.

THE ART IS A RECTANGLE LIST AND NOT A GRID, for the same reason
HUDRECTS is: a grid has to be decomposed into rectangles and a greedy
decomposition of a face -- eyes inside a head -- gives back the one-pair
records this is trying to avoid.  Painter's order does it directly: the
head, then the eyes on top of it.  The ASCII preview in the generated
file is rendered FROM the rectangles, so it cannot drift from them.

WHY BANDS AND NOT ROWS.  The box's height is whatever the projection
says -- 28 rows at one cell, four at five -- so every y in the sprite has
to be scaled by it, and that is a multiply.  Bands are the DISTINCT y
edges, computed once per draw into rowtab, and every record after that is
two table lookups.  A 15-record monster costs 8 multiplies rather than
30.

TRANSPARENCY IS THE ABSENCE OF A RECORD.  There is no key colour and no
mask: a cell nothing covers is simply not drawn, so the floor shows
through it.  That also makes a silhouette CHEAPER than the block it
replaces -- hud_rect's cost is per row drawn, and a shape with its
corners cut away draws fewer rows than a full rectangle of the same
bounding box.

THE PENS ARE ONES ALREADY ON SCREEN.  pal.py hands out all sixteen and
this file asks for none of its own: the monster keeps its mauve (pen 13,
the one warm-dark colour nothing else uses), the pickup keeps the ammo
orange (pen 8) that the pips and the scanner are drawn in, and both take
bright white (15) for a highlight and black (0) for the parts that should
read as shadow against the olive floor.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import cpchw as cpc                                             # noqa: E402

SOLID = cpc.MODE0_SOLID

# pens, by the name pal.py gives them
DARK = 0                # black -- shadow against the olive floor
FLESH = 13              # mauve  -- pip.asm's MON_PEN
EYE = 15                # bright white
AMMO = 8                # orange -- pip.asm's PIP_PEN, and the HUD's
BAND = 15               # ...and the band around the canister

# ---------------------------------------------------------------------
#  THE MONSTER.  Three pairs across -- 12 mode-0 pixels -- and six bands
#  down, back to front.  Three pairs and not five because MON_HW is the
#  AIM CONE as well as the width (pip.asm), and widening the monster
#  would quietly make it easier to shoot.
#
#  Bands are not equal thickness: the head is a smaller share of a tall
#  monster than of a short one, which is what stops it reading as a totem
#  when it is close.
# ---------------------------------------------------------------------
MON_NB = 5
#  THE BANDS ARE THIN WHERE THE DETAIL IS, and that is a COST decision
#  rather than an aesthetic one.  A rectangle costs 87 us plus 63 us a
#  ROW -- measured -- so a two-pixel eye drawn across a band a third of
#  the monster tall costs as much as its whole head does.  The eye band
#  is 36/256 of the box and the legs 32; the head and the body, which are
#  three pairs wide and carry the shape, get the rest.
MON_Y = [0, 72, 108, 200, 224, 256]
MON_RECTS = [
    (-1, 3, 0, 1, "F"),         # the head, all three pairs
    (-1, 1, 1, 1, "E"),         # ...and an eye either side of it
    (+1, 1, 1, 1, "E"),
    (-1, 3, 2, 3, "F"),         # the body
    (-1, 1, 4, 4, "D"),         # legs, with the floor between them
    (+1, 1, 4, 4, "D"),
]

# ---------------------------------------------------------------------
PIP_NB = 5
PIP_Y = [0, 40, 100, 150, 214, 256]
PIP_RECTS = [
    (-1, 3, 1, 3, "A"),         # the body of it
    (0, 1, 0, 0, "B"),          # the cap catches the light
    (-1, 3, 2, 2, "B"),         # ...and a band round the middle
    (-1, 3, 4, 4, "D"),         # sitting in its own shadow
]

PEN_OF = {"D": DARK, "F": FLESH, "E": EYE, "A": AMMO, "B": BAND}


def preview(rects, nb):
    """-> the sprite as text, PAINTED FROM THE RECTANGLES in order.

    So the picture in the generated file is what the Z80 will draw, and
    not a second copy of the intent that can drift from it.
    """
    lo = min(c for c, _n, _a, _b, _p in rects)
    hi = max(c + n - 1 for c, n, _a, _b, _p in rects)
    grid = [["." for _ in range(lo, hi + 1)] for _ in range(nb)]
    for (c, n, b0, b1, ch) in rects:
        for b in range(b0, b1 + 1):
            for x in range(c, c + n):
                grid[b][x - lo] = ch
    return ["".join(r) for r in grid]


def emit(name, rects, ys, nb):
    assert len(ys) == nb + 1, f"{name}: {len(ys)} edges for {nb} bands"
    assert ys[0] == 0 and ys[-1] == 256, f"{name}: bands must span the box"
    assert all(a < b for a, b in zip(ys, ys[1:])), f"{name}: not ascending"
    for (c, n, b0, b1, ch) in rects:
        assert 0 <= b0 <= b1 < nb, f"{name}: band {b0}..{b1} outside 0..{nb-1}"
        assert n >= 1 and ch in PEN_OF, f"{name}: bad record {(c, n, ch)}"
    hw = max(max(-c, c + n - 1) for c, n, _a, _b, _p in rects)
    L = [f"; ---- {name}: {2 * hw + 1} pairs x {nb} bands, "
         f"{len(rects)} rectangles, painted in this order ----"]
    for r in preview(rects, nb):
        L.append(f";     {r}")
    L.append(f"{name}_Y                      ; band top edges, 256ths of "
             f"the box height")
    L.append("    db " + ",".join(str(min(y, 255)) for y in ys[:-1])
             + ",255      ; ...the last is the foot")
    L.append(f"{name}_NB      equ {nb}")
    L.append(f"{name}_HW      equ {hw}"
             f"              ; half width in column PAIRS")
    L.append(f"{name}                        ; db col, ncol, band0, band1, pen")
    for (c, n, b0, b1, ch) in rects:
        L.append(f"    db {c:3d},{n:3d},{b0:3d},{b1:3d},#{SOLID[PEN_OF[ch]]:02X}")
    L.append("    db #80                  ; end of list")
    L.append("")
    return L, rects


HEAD = """; ---------------------------------------------------------------------
;  gen_spr.inc -- GENERATED by engine2/tools/genspr.py.  Do not edit.
;
;  The monster and the pickup as lists of rectangles in the box's own
;  coordinates -- see genspr.py for the format and for why the vertical
;  edges are BANDS rather than rows.  pip.asm's spr_draw walks these.
; ---------------------------------------------------------------------
"""


def main():
    L = [HEAD]
    lm, rm_ = emit("SPR_MON", MON_RECTS, MON_Y, MON_NB)
    lp, rp = emit("SPR_PIP", PIP_RECTS, PIP_Y, PIP_NB)
    L += lm + lp
    out = os.path.join(_E2, "src", "gen_spr.inc")
    open(out, "w").write("\n".join(L) + "\n")
    nb = (len(rm_) + len(rp)) * 5 + (len(MON_Y) + len(PIP_Y)) + 2
    print(f"monster {len(rm_)} rectangles, {MON_NB} bands")
    print(f"pickup  {len(rp)} rectangles, {PIP_NB} bands")
    print(f"{nb} bytes of table; wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
