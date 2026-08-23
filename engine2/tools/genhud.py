"""engine2/tools/genhud.py -- the HUD's geometry, precalculated.

    python3 engine2/tools/genhud.py            -> engine2/src/gen_hud.inc

Everything engine2/src/hud2.asm draws is DATA, generated here, so that the
same numbers can be replayed in Python by the verifier (engine2/tools/
emu_hud.py) and so that the whole HUD follows vpcfg.inc when the viewport
moves.  Two things come out:

  HUDRECTS   the static furniture, as (x, y, w, h, byte) rectangles, back
             to front.  Panels, the bevel around the viewport, the two
             readout wells, the compass dial (an ellipse, cut into bands of
             equal half-width so a 74-scanline circle is ~24 rectangles and
             not 74 one-line ones), its ticks and its hub.  hud2.asm's only
             drawing primitive is a PUSH DE rectangle, so this list IS the
             HUD.  Painted once into each buffer at startup.

  HUDNDL     the needle, for headings 0..18 only: 4 dots x (dx, dy), signed,
             dx in BYTES and dy in scanlines, relative to the dial centre.
             The other 54 headings are sign flips of these, which is exact
             because the dial is symmetric about both axes:

                 a in [ 0,18]  i = a       ( dx,  dy)
                 a in [19,35]  i = 36 - a  ( dx, -dy)
                 a in [36,54]  i = a - 36  (-dx, -dy)
                 a in [55,71]  i = 72 - a  (-dx,  dy)

             and it is asserted below against the direct computation for
             all 72 headings.  152 bytes instead of 576.

WHY THE NEEDLE IS FOUR BLOCKS AND NOT A LINE.  A drawn line has to be
erased, and erasing it costs as much as drawing it; the cheapest needle
that still resolves 5 degrees is a few 2-byte-wide blocks strung along the
heading, because then a repaint is ~14 scanline writes.  Two invariants
make that safe, and both are ASSERTED here rather than eyeballed:

  DISTINCT   the 72 needles are 72 different pictures.  With byte-granular
             x this is not free -- at 9 bytes of radius the tip moves 0.78
             bytes per 5-degree step, so adjacent tips often round to the
             same column -- and it is the inner dots, rounding differently,
             that separate them.  The assertion is on the whole 4-block
             picture, which is what the player actually sees.

  ERASABLE   every block of every heading lands on furniture that is
             DIAL_BG, so erasing by repainting the old needle in DIAL_BG
             restores the dial EXACTLY.  That is why the needle never
             reaches the rim, the ticks or the hub.

The pens come from engine2/tools/pal.py -- pen 14 (bright cyan) and 15
(bright white) are the two the palette reserves for the HUD; the panel
uses 11 (blue) and the needle's tail 9 (bright red), both of which the
viewport also uses, which costs nothing because the HUD and the viewport
never share a pixel.
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import cpchw as cpc                                             # noqa: E402
import gentab                                                   # noqa: E402
import pal                                                      # noqa: E402

def rnd(v):
    """Round half AWAY FROM ZERO, and do it symmetrically.

    Plain round() is not usable here.  The needle's four quadrants must be
    exact sign flips of one another -- that is what lets the file hold 19
    headings instead of 72 -- and both banker's rounding (round(4.5) = 4,
    round(5.5) = 6) and the 1-ulp asymmetry of sin(210 deg) against
    -sin(30 deg) break that on the .5 ties, which at radius 9 happen for
    real.  Quantising first makes the tie land on both sides at once.
    """
    v = round(v, 9)
    return int(math.floor(abs(v) + 0.5)) * (-1 if v < 0 else 1)


SCR_W, SCR_H = cpc.SCR_W_BYTES, cpc.SCR_H
VP_BX, VP_BW = gentab.VP_BX, gentab.VP_BW
VP_Y, VP_H = gentab.VP_Y, gentab.VP_H

# ---- pens (indices into pal.PEN_INK; solid mode-0 bytes are derived) ----
PANEL = pal.CEIL_NEAR               # 11, blue    -- the plate
LIGHT = pal.HUD_FRAME               # 6,  cyan    -- lit bevel edges
SHADOW = 0                          # black       -- shadowed bevel edges
MARK = pal.HUD_TEXT                 # 15, white   -- ticks that matter, hub
DIAL_BG = 0                         # black       -- inside the dial
NEEDLE = pal.HUD_TEXT               # 15, white   -- the needle's north arm
TAIL = 9                            # bright red  -- and its south tail
# LIGHT HAS BEEN PEN 14, THEN PEN 3, AND IS NOW PEN 6, and the HUD has not
# changed colour by one dot through any of it: all three were firmware ink
# 20, bright cyan.  It is on pen 6 now because pen 3 is a WALL step and the
# frame should not change meaning when the wall ramp is retuned; shortening
# that ramp to four blue steps is what freed pen 6.  See pal.MORTAR.
assert PANEL == 11 and pal.PEN_INK[LIGHT] == 20 and MARK == 15

SOLID = cpc.MODE0_SOLID

# ---- bevel ----
BEV_W = 2                           # side grooves, bytes
BEV_H = 2                           # rail lines, scanlines (two of them)

# ---- the dial ----
#  A mode-0 pixel is 0.025 of the screen width and a scanline 0.015 of its
#  height, so a CIRCLE has  ry = (0.025/0.015) * rx_pixels = 3.333 * rx_bytes.
ASPECT = 2.0 * (4.0 / (SCR_W * 2)) / (3.0 / SCR_H)   # 3.333 lines per BYTE
DIAL_RXB = 11                       # dial radius, bytes  (22 px)
DIAL_RY = rnd(DIAL_RXB * ASPECT)         # 37 scanlines
RIM_XB, RIM_Y = 1, 3                # rim thickness, bytes / scanlines
TICK_RXB = 13                       # tick ring radius, outside the dial
TICK_RY = rnd(TICK_RXB * ASPECT)         # 43
NDL_RXB = 9                         # needle tip radius, bytes
NDL_RY = rnd(NDL_RXB * ASPECT)           # 30

#  dot fraction of the tip radius, block height (ODD -- see the mirror), pen
NDL_DOTS = [(1.00, 5, NEEDLE),      # tip
            (0.72, 3, NEEDLE),
            (0.46, 3, NEEDLE),
            (-0.45, 3, TAIL)]       # the tail, pointing south
NDL_W = 2                           # every block is 2 bytes = 4 pixels wide

HUB_W, HUB_H = 2, 3

N_ANGLES = 72


# =====================================================================
#  the furniture
# =====================================================================
class Rects:
    """A checked rectangle list.  Every constraint hud2.asm relies on is
    enforced HERE, once, instead of being trusted 60 times below."""

    def __init__(self):
        self.r = []

    def add(self, x, y, w, h, pen):
        assert w > 0 and h > 0, f"empty rect {(x, y, w, h)}"
        assert w % 2 == 0, f"width must be even (PUSH DE writes 2): {w}"
        assert 0 <= x and x + w <= SCR_W, f"off screen in x: {(x, w)}"
        assert 0 <= y and y + h <= SCR_H, f"off screen in y: {(y, h)}"
        # The HUD may never touch the viewport: the renderer owns it and
        # does not clear it before drawing.
        assert not (x < VP_BX + VP_BW and x + w > VP_BX
                    and y < VP_Y + VP_H and y + h > VP_Y), \
            f"rect {(x, y, w, h)} overlaps the viewport"
        self.r.append((x, y, w, h, SOLID[pen]))

    def __len__(self):
        return len(self.r)


def ellipse_bands(rc, cxb, cy, rxb, ry, pen):
    """A filled ellipse as horizontal BANDS of constant half-width.

    x is symmetric about the BOUNDARY between bytes cxb-1 and cxb (so every
    band is an even number of bytes wide and no band needs an odd PUSH), y
    about the scanline cy.  Consecutive scanlines usually share a rounded
    half-width, so the 74-scanline dial comes out as ~24 rectangles.
    """
    hw = [rnd(rxb * math.sqrt(max(0.0, 1.0 - (dy / float(ry)) ** 2)))
          for dy in range(-ry, ry + 1)]
    i = 0
    while i < len(hw):
        j = i
        while j < len(hw) and hw[j] == hw[i]:
            j += 1
        if hw[i] > 0:
            rc.add(cxb - hw[i], cy - ry + i, 2 * hw[i], j - i, pen)
        i = j


def dial_centre():
    """Centre of the dial: middle of the panel below the viewport."""
    top = VP_Y + VP_H + 2 * BEV_H
    return SCR_W // 2, top + (SCR_H - top) // 2


def furniture():
    rc = Rects()
    cxb, cy = dial_centre()
    bot = VP_Y + VP_H                       # first scanline below the view

    # ---- the plates beside and below the viewport --------------------
    if VP_Y >= 2 * BEV_H:                   # only if the view is not flush
        rc.add(0, 0, SCR_W, VP_Y - 2 * BEV_H, PANEL)
        rc.add(0, VP_Y - 2 * BEV_H, SCR_W, BEV_H, SHADOW)
        rc.add(0, VP_Y - BEV_H, SCR_W, BEV_H, LIGHT)
    lw = VP_BX - BEV_W                      # left plate width
    rx = VP_BX + VP_BW + BEV_W              # right plate left edge
    rw = SCR_W - rx
    rc.add(0, VP_Y, lw, VP_H, PANEL)
    rc.add(rx, VP_Y, rw, VP_H, PANEL)
    rc.add(0, bot + 2 * BEV_H, SCR_W, SCR_H - bot - 2 * BEV_H, PANEL)

    # ---- the bevel: light from the top left, so the view is RECESSED --
    rc.add(VP_BX - BEV_W, VP_Y, BEV_W, VP_H, SHADOW)        # left  edge dark
    rc.add(VP_BX + VP_BW, VP_Y, BEV_W, VP_H, LIGHT)         # right edge lit
    rc.add(0, bot, SCR_W, BEV_H, LIGHT)                     # the rail under
    rc.add(0, bot + BEV_H, SCR_W, BEV_H, SHADOW)            # it, engraved

    # ---- readout slots, three each side of the dial ------------------
    #  Empty for now -- there is no score, no key ring and no health yet --
    #  but three bevelled slots read as an instrument panel where two big
    #  black rectangles read as a mistake, and they cost only startup time.
    ww, wh, gap = 22, 22, 5
    for wx in (2, SCR_W - 2 - ww):
        for k in range(3):
            wy = cy - (3 * wh + 2 * gap) // 2 + k * (wh + gap)
            rc.add(wx, wy, ww, wh, LIGHT)
            rc.add(wx + 1, wy + 2, ww - 2, wh - 4, SHADOW)

    # ---- the dial: a cyan disc with a black well cut out of it -------
    ellipse_bands(rc, cxb, cy, DIAL_RXB, DIAL_RY, LIGHT)
    ellipse_bands(rc, cxb, cy, DIAL_RXB - RIM_XB, DIAL_RY - RIM_Y, DIAL_BG)

    # ---- eight ticks on the ring outside it, north marked -----------
    for k in range(8):
        th = math.radians(45.0 * k)
        dx = rnd(TICK_RXB * math.sin(th))
        dy = rnd(-TICK_RY * math.cos(th))
        if k == 0:
            rc.add(cxb - 2 + dx, cy + dy - 2, 4, 5, MARK)
        else:
            rc.add(cxb - 1 + dx, cy + dy - 1, 2, 3, LIGHT)

    # ---- and the hub the needle turns about --------------------------
    rc.add(cxb - HUB_W // 2, cy - HUB_H // 2, HUB_W, HUB_H, MARK)
    return rc


def paint(rects):
    """Replay the rectangle list -> [200][80] of mode-0 bytes, None where
    nothing was painted.  This is the model emu_hud.py compares against."""
    grid = [[None] * SCR_W for _ in range(SCR_H)]
    for x, y, w, h, b in rects.r:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                grid[yy][xx] = b
    return grid


# =====================================================================
#  the needle
# =====================================================================
def dots(a):
    """Heading a (0..71) -> [(x_byte, y_top, h, pen)] straight from the
    trigonometry.  The asm derives the same thing from the quadrant table
    by sign flips; the two are asserted equal below."""
    cxb, cy = dial_centre()
    th = math.radians(360.0 / N_ANGLES * a)
    out = []
    for f, h, pen in NDL_DOTS:
        dx = rnd(NDL_RXB * f * math.sin(th))
        dy = rnd(-NDL_RY * f * math.cos(th))
        out.append((cxb - NDL_W // 2 + dx, cy + dy - (h - 1) // 2, h, pen))
    return out


def quadrant():
    """The 19 x 4 (dx, dy) pairs that go in the file."""
    cxb, cy = dial_centre()
    tab = []
    for a in range(19):
        for (x, y, h, _p) in dots(a):
            tab.append((x - (cxb - NDL_W // 2), y + (h - 1) // 2 - cy))
    return tab


def dots_from_quadrant(tab, a):
    """hud2.asm's own derivation, in Python, so the mirror rule is tested
    rather than assumed."""
    cxb, cy = dial_centre()
    if a <= 18:
        i, sx, sy = a, 1, 1
    elif a < 36:
        i, sx, sy = 36 - a, 1, -1
    elif a < 55:
        i, sx, sy = a - 36, -1, -1
    else:
        i, sx, sy = 72 - a, -1, 1
    out = []
    for d, (_f, h, pen) in enumerate(NDL_DOTS):
        dx, dy = tab[i * len(NDL_DOTS) + d]
        out.append((cxb - NDL_W // 2 + sx * dx, cy + sy * dy - (h - 1) // 2,
                    h, pen))
    return out


def cells(ds):
    """The needle as a set of (x, y) byte cells."""
    s = set()
    for (x, y, h, _p) in ds:
        for yy in range(y, y + h):
            for xx in range(x, x + NDL_W):
                s.add((xx, yy))
    return s


def check(rects, tab):
    """The two invariants the design rests on, plus the mirror rule."""
    grid = paint(rects)
    bg = SOLID[DIAL_BG]
    seen, bad = {}, []
    for a in range(N_ANGLES):
        direct, mirrored = dots(a), dots_from_quadrant(tab, a)
        if direct != mirrored:
            bad.append(f"heading {a}: mirror {mirrored} != direct {direct}")
        cs = cells(direct)
        for (x, y) in cs:
            if not (0 <= x < SCR_W and 0 <= y < SCR_H):
                bad.append(f"heading {a}: dot off screen at {(x, y)}")
            elif grid[y][x] != bg:
                bad.append(f"heading {a}: dot at {(x, y)} lands on "
                           f"&{grid[y][x]:02X}, not the dial background "
                           f"-- erasing it would damage the furniture")
        key = frozenset(cs)
        if key in seen:
            bad.append(f"heading {a} draws the same needle as {seen[key]}")
        seen[key] = a
    return bad


# =====================================================================
#  output
# =====================================================================
def write_inc(path, rects, tab):
    cxb, cy = dial_centre()
    L = []
    L.append("; Generated by engine2/tools/genhud.py -- do not edit.")
    L.append("; The HUD's furniture and its compass needle.  See that file")
    L.append("; for what every table means and what is asserted about it.")
    L.append("")
    L.append(f"HUD_NRECT    equ {len(rects)}   ; static furniture rectangles")
    L.append(f"HUD_CXB      equ {cxb}   ; dial centre: byte BOUNDARY x ...")
    L.append(f"HUD_CY       equ {cy}   ; ... and scanline y")
    L.append(f"HUD_NDOT     equ {len(NDL_DOTS)}   ; blocks in the needle")
    L.append(f"HUD_NW       equ {NDL_W}   ; every block is this many bytes")
    L.append("")
    L.append("; ---- static furniture: db x, y, w, h, byte ----")
    L.append("HUDRECTS")
    for (x, y, w, h, b) in rects.r:
        L.append(f"    db {x:3d},{y:4d},{w:3d},{h:4d},#{b:02X}")
    L.append("")
    L.append("; ---- needle: per-block height and pen ----")
    for d, (_f, h, _p) in enumerate(NDL_DOTS):
        L.append(f"HUD_H{d}       equ {h}   ; block {d} is this many scanlines")
    L.append(f"HUD_BG       equ #{SOLID[DIAL_BG]:02X}   "
             f"; ... and is erased with this byte")
    L.append("")
    L.append("HUDDESC      db " + ",".join(
        f"{h},#{SOLID[p]:02X}" for (_f, h, p) in NDL_DOTS))
    L.append("")
    L.append("; ---- needle, headings 0..18: db dx (bytes), dy (lines) ----")
    L.append("HUDNDL")
    for a in range(19):
        row = tab[a * len(NDL_DOTS):(a + 1) * len(NDL_DOTS)]
        L.append("    db " + ",".join(f"{dx:4d},{dy:4d}" for dx, dy in row)
                 + f"   ; heading {a}")
    L.append("")
    open(path, "w").write("\n".join(L) + "\n")


def build():
    rects = furniture()
    tab = quadrant()
    return rects, tab


def main():
    rects, tab = build()
    bad = check(rects, tab)
    for b in bad[:20]:
        print("FAIL:", b)
    cxb, cy = dial_centre()
    out = os.path.join(_E2, "src", "gen_hud.inc")
    write_inc(out, rects, tab)
    npix = sum(w * h for (_x, _y, w, h, _b) in rects.r)
    print(f"viewport {VP_BW}x{VP_H} bytes at ({VP_BX},{VP_Y}); "
          f"HUD = the rest of the screen")
    print(f"  furniture   {len(rects):3d} rectangles, {npix} byte-writes, "
          f"{len(rects)*5} bytes of table")
    print(f"  dial        centre ({cxb},{cy}) radius {DIAL_RXB} bytes x "
          f"{DIAL_RY} lines (aspect {ASPECT:.2f} -> round)")
    print(f"  needle      {len(NDL_DOTS)} blocks, tip radius {NDL_RXB} x "
          f"{NDL_RY}, {len(tab)*2} bytes of table")
    print(f"  72 headings all distinct, all on dial background: "
          f"{'NO -- see above' if bad else 'yes'}")
    print(f"wrote {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
