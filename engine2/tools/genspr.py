"""engine2/tools/genspr.py -- THE SPRITE SHEET, COMPILED.

    python3 engine2/tools/genspr.py     assets/sprites.png -> gen_spr.inc

THE ART IS A PNG NOW.  It used to be two hand-written rectangle lists in
this file, and they were good ones -- but a rectangle list is not a thing
anyone can draw, and every change to the monster meant editing offsets
and reading the ASCII preview to see what had happened.  The sheet is
painted in GIMP against assets/amaze-mode0.gpl and this file turns it
into the same records, cheaper: 4953.6 us against the hand art's 5459.2,
drawing the identical picture.

WHAT A RECORD IS, unchanged -- pip.asm's spr_draw walks these:

    db col, ncol, band0, band1, pen

  col          column PAIR offset from the sprite's centre, signed.  A
               pair is two bytes -- four mode-0 pixels.
  ncol         how many pairs WIDE.
  band0/band1  first and last BAND, inclusive.
  pen          the mode-0 solid byte, straight into hud_rect.

and the list ends with #80, which cannot be a signed pair offset.

WHY BANDS AND NOT ROWS.  The box's height is whatever the projection
says -- 28 rows at one cell, four at five -- so every y has to be scaled
by it, and that is a multiply.  Bands are the DISTINCT y edges, computed
once per draw into rowtab, and every record after that is two table
lookups.  sprpng.bands() finds them: a band is a maximal run of
IDENTICAL rows in the sheet, so the artist gets 128 rows to draw in and
the Z80 pays for the five or six the picture actually has.

WHY RECTANGLES AT ALL, MEASURED.  hud_rect costs 87 us a CALL and 63 us
a ROW, and a row is almost free to widen -- 0.5 us a byte a row:

    2 bytes x 28 rows   1850.7 us          10 bytes x 8 rows   718.4
    2 bytes x  8 rows    590.9             6 bytes x 8 rows    655.5
    2 bytes x  1 row     150.0             4 bytes x 8 rows    622.8

So a picture drawn one PAIR at a time pays 63 us a row for every column
it is wide.  The first version of the old file emitted one-pair records
and cost 12902.7 us for pip.asm's three drawers at one cell against a
C_PIP of 8200.  sprcover.py's objective is those two numbers and nothing
else -- see there.

TWO THINGS REFUSE ART RATHER THAN SHIP IT.  pip.asm's spr_rt holds
SPR_NB_MAX+1 scaled band edges, so a sprite with more distinct rows than
that is refused HERE -- naming the tile and the count -- rather than as
a rasm assert three tools downstream.  And the total cost is checked
against BUDGET below, because nothing else measures it: emu_holes.py
benches C_TAIL, C_HUD, C_HP, C_MSETUP and C_DOORACT on the booted disc
and does not touch C_PIPM or C_PIPP.

THE SEARCH IS ON A CLOCK, and that is the artist's protection too.  The
cover enumerates nb^2 * ncols^2 candidates per rectangle per pass, so a
twelve-band sprite is a hundred times the work of a four-band one; a
striped test sprite hung the build with no output at all.  A minimum
number of restarts always runs, so the answer never depends on how busy
the machine was, and the clock only stops the extras.  The count is
printed.

TRANSPARENCY IS THE ABSENCE OF A RECORD.  Index 16 in the sheet is not
drawn, so the floor shows through, and a silhouette is CHEAPER than the
block it replaces: hud_rect is charged per row DRAWN, and a shape with
its corners cut away draws fewer rows than its bounding box.

WIDENING THE MONSTER CHANGES THE GAME, not just the picture.  pip.asm
takes the aim cone from SPR_MON_HW, so a monster painted a pair wider is
a monster that is easier to shoot.  main() prints HW for exactly that
reason; it is the one number here that is not only cosmetic.

THE PENS ARE ONES ALREADY ON SCREEN, and world.py's PEN_INK is what says
which colour each is.  The monster is pen 13 -- BLACK, ink 0, the same
pen as the far ceiling -- so it reads as a silhouette against the olive
floor, and the pickup is pen 8, BRIGHT RED (ink 6), the colour the ammo
pips and the scanner are already drawn in.  (This file and pip.asm used
to call those two "mauve" and "orange"; they have not been either since
the palette moved.)
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import cpchw as cpc                                             # noqa: E402
import sprcover                                                 # noqa: E402
import sprpng                                                   # noqa: E402

SOLID = cpc.MODE0_SOLID

#  WHICH TILE IS WHICH, left to right in the sheet.  The asm names are
#  what pip.asm asks for, so adding a sprite is a tile plus a line here.
SPRITES = [("SPR_MON", "the monster"), ("SPR_PIP", "the pickup")]


def preview(rects, nb, lo, ncols):
    """-> the sprite as text, PAINTED FROM THE RECORDS in order.

    So the picture in the generated file is what the Z80 will draw and
    not a second copy of the intent that can drift from it.
    """
    g = sprpng.paint(rects, nb, ncols, lo)
    return ["".join("." if p is None else f"{p:X}" for p in row) for row in g]


def emit(name, what, rects, edges, nb, lo, ncols):
    assert edges[0] == 0 and edges[-1] == 256, f"{name}: bands must span the box"
    assert all(a < b for a, b in zip(edges, edges[1:])), f"{name}: not ascending"
    hw = max(max(-c, c + n - 1) for c, n, _a, _b, _p in rects)
    us = sprcover.cost(rects, edges)
    L = [f"; ---- {name}: {what}, {2 * hw + 1} pairs x {nb} bands, "
         f"{len(rects)} rectangles ----",
         f";      {us:.1f} us at a 28-row box, painted in this order.  The",
         ";      digits are PEN numbers; '.' is not drawn."]
    for r in preview(rects, nb, lo, ncols):
        L.append(f";     {r}")
    L.append(f"{name}_Y                      ; band top edges, 256ths of "
             f"the box height")
    L.append("    db " + ",".join(str(min(y, 255)) for y in edges[:-1])
             + ",255      ; ...the last is the foot")
    L.append(f"{name}_NB      equ {nb}")
    L.append(f"{name}_HW      equ {hw}"
             f"              ; half width in column PAIRS -- and pip.asm's"
             f" aim cone")
    L.append(f"{name}                        ; db col, ncol, band0, band1, pen")
    for (c, n, b0, b1, pen) in rects:
        L.append(f"    db {c:3d},{n:3d},{b0:3d},{b1:3d},#{SOLID[pen]:02X}"
                 f"      ; pen {pen}")
    L.append("    db #80                  ; end of list")
    L.append("")
    return L, us


HEAD = """; ---------------------------------------------------------------------
;  gen_spr.inc -- GENERATED from assets/sprites.png by genspr.py.
;  Do not edit.  Paint the PNG.
;
;  Lists of rectangles in the box's own coordinates -- see genspr.py for
;  the format and for why the vertical edges are BANDS rather than rows.
;  pip.asm's spr_draw walks these.
; ---------------------------------------------------------------------
"""


def _nb_max():
    """SPR_NB_MAX out of pip.asm.  Read, so it cannot drift."""
    for ln in open(os.path.join(_E2, "src", "pip.asm")):
        p = ln.split()
        if len(p) >= 3 and p[0] == "SPR_NB_MAX" and p[1] == "equ":
            return int(p[2])
    raise KeyError("SPR_NB_MAX is not an equ in pip.asm")


def build(path=None):
    """-> (lines, [(name, nrects, nb, hw, us)]).  Raises on a bad sheet."""
    ntile, px = sprpng.load(path)
    if ntile < len(SPRITES):
        raise ValueError(f"the sheet has {ntile} tiles and SPRITES names "
                         f"{len(SPRITES)}")
    L, info, report = [HEAD], [], []
    for n, (name, what) in enumerate(SPRITES):
        grid = sprpng.tile(px, n, report)
        bg, edges = sprpng.bands(grid)
        nb = len(bg)
        # THE ENGINE'S OWN LIMIT, READ AND NOT COPIED.  spr_draw scales the
        # band edges into spr_rt, which holds SPR_NB_MAX+1 of them, and
        # pip.asm asserts it -- but the assert fires in rasm, three tools
        # downstream of the person who painted the sprite, saying nothing
        # about which tile or which rows.  Say it here instead.
        if nb > _nb_max():
            raise ValueError(
                f"{name}: tile {n} has {nb} bands and spr_rt holds "
                f"{_nb_max()} (pip.asm's SPR_NB_MAX).  A band is a run of "
                f"IDENTICAL rows, so {nb} distinct rows is {nb} multiplies "
                f"a draw -- make the detail coarser vertically.")
        used = [x for x in range(sprpng.PAIRS)
                if any(row[x] is not None for row in bg)]
        if not used:
            raise ValueError(f"{name}: tile {n} is empty")
        lo, hi = min(used), max(used)
        centre = sprpng.PAIRS // 2
        tgt = [[row[x] for x in range(lo, hi + 1)] for row in bg]
        rects, tries = sprcover.cover(tgt, nb, hi - lo + 1, lo - centre,
                                      edges)
        # THE ONE CHECK THAT MATTERS.  Whatever the search did, this says
        # the records draw the sheet.  See sprcover.py.
        if sprpng.paint(rects, nb, hi - lo + 1, lo - centre) != tgt:
            raise AssertionError(f"{name}: the cover does not paint the sheet")
        lines, us = emit(name, what, rects, edges, nb, lo - centre,
                         hi - lo + 1)
        L += lines
        info.append((name, len(rects), nb, max(max(-c, c + n - 1)
                                               for c, n, _a, _b, _p in rects),
                     us, tries))
    return L, info, report


# WHAT THE ART IS ALLOWED TO COST, AND WHY THIS IS HERE.
#
# The sheet is painted by hand now, so the frame budget is one repaint
# away from being wrong -- and NOTHING ELSE MEASURES IT.  emu_holes.py
# benches C_TAIL, C_HUD, C_HP, C_MSETUP and C_DOORACT on the booted disc
# and does not touch C_PIPM or C_PIPP; those two are fitted offline in
# pacemodel.py.  So a bigger monster would sail through every gate in
# `make pace` and show up as a dropped period on a real CPC.
#
# This is the cheap guard and it is a MODEL, not a measurement: 87 us a
# hud_rect call plus 63 us a row, which is where those constants came
# from in the first place.  It fails the build rather than warning,
# because the thing it is protecting against is silent.
BUDGET = 4953.6         # us, the sheet the constants were fitted against
BUDGET_WHY = ("main3.asm's C_PIPP 6050 / C_PIPM 7100 were fitted with the "
              "sprites costing this much")


def main():
    L, info, report = build()
    out = os.path.join(_E2, "src", "gen_spr.inc")
    open(out, "w").write("\n".join(L) + "\n")
    # A PIXEL GROUP THAT WAS NOT ONE COLOUR IS SAID OUT LOUD.  A column
    # pair is four mode-0 pixels and the fill cannot place less; resolving
    # by majority is the only thing to do, and doing it silently is how a
    # sprite ends up not being the one that was painted.
    for (t, p, y, vals, best) in report[:12]:
        print(f"  ! tile {t} pair {p} row {y}: {vals} -> {best} (majority)")
    if len(report) > 12:
        print(f"  ! ...and {len(report) - 12} more mixed pixel groups")
    tot = 0.0
    for (name, nr, nb, hw, us, tries) in info:
        print(f"{name}: {nr} rectangles, {nb} bands, HW {hw} pairs, "
              f"{us:.1f} us ({tries} restarts)")
        tot += us
    print(f"total {tot:.1f} us at a 28-row box "
          f"-- pip.asm's C_PIPM / C_PIPP bound this")
    if tot > BUDGET + 0.05:
        print(f"\n*** THE SHEET COSTS {tot:.1f} us AND THE BUDGET IS "
              f"{BUDGET:.1f}.\n"
              f"    {BUDGET_WHY}.\n"
              f"    Nothing else measures this: emu_holes.py does not bench\n"
              f"    the sprite drawers.  Either paint it back under budget --\n"
              f"    fewer bands, or rectangles that span their whole width --\n"
              f"    or raise C_PIPM / C_PIPP in main3.asm, re-fit with\n"
              f"    emu_pacefit.py and re-run pacescan.py, and move BUDGET\n"
              f"    here to match.")
        return 1
    if tot < BUDGET - 0.05:
        print(f"    ...{BUDGET - tot:.1f} us under the {BUDGET:.1f} the "
              f"budget was fitted at.  Move BUDGET down in genspr.py to keep\n"
              f"    the guard tight, once C_PIPM / C_PIPP have been re-fitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
