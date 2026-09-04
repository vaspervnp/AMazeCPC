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

HUD_NDOT = 4        # blocks in the needle; genaux.py reads this name


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


MM_N = 16               # the maze is 16x16 cells
MM_CH = 2               # scanlines a cell.  IT WAS 4, and 4 cost 14800 us
                        # to paint against a budget with 18178 spare --
                        # see C_MMAP.  Two scanlines is the same 16x16
                        # map at half the fill, and the well holds it
                        # with room over.  A byte is 2 mode-0 pixels
                        # across, so a cell is a wide-ish rectangle
MM_SEEN = pal.HUD_FRAME     # the cyan the instrument frames are drawn in
MM_PLR = pal.HUD_TEXT       # ...and white for where you are standing


def map_slot():
    """-> (x, y, w, h) of the map itself, CENTRED in the right-hand well.

    Derived from the same slot arithmetic that draws the well, so moving
    the slots moves the map with them -- the rule every other readout in
    this file follows.
    """
    _cxb, cy = dial_centre()
    ww, wh, gap = 22, 22, 5
    wx = SCR_W - 2 - ww
    wy = cy - (3 * wh + 2 * gap) // 2
    iw, ih = ww - 2, 3 * wh + 2 * gap - 4          # the inner well
    w, h = MM_N, MM_N * MM_CH
    assert w <= iw, f"map is {w} bytes wide, the well holds {iw}"
    assert h <= ih, f"map is {h} lines tall, the well holds {ih}"
    return wx + 1 + (iw - w) // 2, wy + 2 + (ih - h) // 2, w, h


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
    for k in range(3):                      # ---- the LEFT column: ammo,
        wy = cy - (3 * wh + 2 * gap) // 2 + k * (wh + gap)   # scanner, health
        rc.add(2, wy, ww, wh, LIGHT)
        rc.add(3, wy + 2, ww - 2, wh - 4, SHADOW)
    # ---- and the RIGHT column is ONE well now: the map.
    #  It was three empty slots -- "three bevelled slots read as an
    #  instrument panel where two big black rectangles read as a
    #  mistake", which was true while there was nothing to put in them.
    #  There is now.  One well the height of all three, because a map cut
    #  into three strips is not a map.
    mx, my, mh = SCR_W - 2 - ww, cy - (3 * wh + 2 * gap) // 2, 3 * wh + 2 * gap
    rc.add(mx, my, ww, mh, LIGHT)
    rc.add(mx + 1, my + 2, ww - 2, mh - 4, SHADOW)

    scan_furniture(rc)                  # the ammo scanner's resting pad

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
def ammo_slot():
    """-> (x, y, w, h, dx, n) for the six ammo pips.

    DERIVED FROM THE SLOT THAT HOLDS THEM, not written down: the readout
    lives in the inner well of the TOP-LEFT bevelled slot, whose geometry
    is the ww/wh/gap arithmetic in furniture() above.  Move the slots and
    the pips follow; hud2.asm carries no coordinate of its own.

    Every width is EVEN, which hud_rect requires -- its unrolled PUSH
    block is entered in units of two bytes.
    """
    ww, wh, gap = 22, 22, 5
    _cxb, cy = dial_centre()
    wx = 2                                  # the LEFT column of slots
    wy = cy - (3 * wh + 2 * gap) // 2       # ...and the TOP one of three
    ix, iy, iw, ih = wx + 1, wy + 2, ww - 2, wh - 4      # the inner well
    n, w = 6, 2
    dx = 3                                  # 2 bytes of pip, 1 of gap
    span = (n - 1) * dx + w
    assert span <= iw, (span, iw)
    h = 8
    return ix + (iw - span) // 2, iy + (ih - h) // 2, w, h, dx, n


def ammo_rects(n):
    """-> [(x, y, w, h, byte)] the readout showing `n` rounds.

    THE MODEL OF hud_ammo, and the only one: emu_hud.py compares the
    bytes hud_ammo writes against exactly this.  Spent pips are drawn in
    the slot's own SHADOW colour rather than skipped, because the count
    goes down as well as up and a skipped pip would leave the last one
    on screen for ever.
    """
    x, y, w, h, dx, cnt = ammo_slot()
    out = []
    for i in range(cnt):
        pen = pal.HUD_AMMO if i < n else SHADOW
        out.append((x + i * dx, y, w, h, SOLID[pen]))
    return out


# =====================================================================
#  THE AMMO SCANNER -- a 3x3 direction pad in the MIDDLE-LEFT slot.
#
#  The pips above it say how many rounds are left; this says where the
#  next box of them is.  Eight outer cells are the eight bearings
#  RELATIVE TO THE PLAYER'S HEADING -- top-centre is straight ahead and
#  they run clockwise -- and the hub is the player.
#
#  THE EIGHT UNLIT CELLS ARE FURNITURE, and that is what makes the whole
#  thing cheap.  They go in with the rest of the static rectangles at
#  startup, so hud_scan never draws a layout: it paints ONE cell in the
#  distance colour and paints the previous one back to SCAN_OFF, exactly
#  the way the compass needle erases itself.  A pad drawn from scratch
#  every time the bearing moved would be nine rectangles instead of two.
#
#  Everything below is derived from the slot, like ammo_slot() above.
SCAN_OFF = PANEL                    # 11, blue  -- an unlit bearing
SCAN_HUB = MARK                     # 15, white -- the player, at the hub

#  Relative octant -> which of the nine cells lights.  0 is dead ahead and
#  they run CLOCKWISE, which on a map drawn with +x right and +y down is
#  the direction game.asm's turn_right takes plr_a (STEPTAB is
#  (cos 5a, sin 5a), so a = 18 is +y, i.e. east turns to south).
SCAN_CELL = [(1, 0),        # 0  ahead
             (2, 0),        # 1  ahead-right
             (2, 1),        # 2  right
             (2, 2),        # 3  behind-right
             (1, 2),        # 4  behind
             (0, 2),        # 5  behind-left
             (0, 1),        # 6  left
             (0, 0)]        # 7  ahead-left
SCAN_HUBCELL = (1, 1)


#  ---- THE HEALTH BAR, in the BOTTOM-LEFT slot ------------------------
#  A BAR AND NOT PIPS, and that is a budget decision, not a taste one.
#  hud_rect costs ~70 us a ROW, so a readout's cost is (rectangles x
#  rows), not (rectangles).  Six ammo pips of 8 rows are 48 rows and
#  C_AMMO is 4000 us; a bar is TWO rectangles of the same 8 rows, 16
#  rows, and MEASURED it charges C_HP.  Health changes far more often
#  than the round count when a monster is on you, so the cheap shape is
#  the one that belongs here.
#
#  It draws in FX_BLOOD's own red, which ties the bar to the mark the
#  shot leaves in flesh -- the one other place in the game that colour
#  means damage.
HP_PEN = 9                          # bright red, ink 6 -- as FX_BLOOD
HP_MAX = 5                          # segments, and so the player's hit
                                    # points: game.asm asserts they agree


def health_slot():
    """-> (x, y, w, h, seg) for the health bar.

    DERIVED FROM THE SLOT, like ammo_slot() and scan_slot(): the inner
    well of the BOTTOM-LEFT bevelled slot.  `seg` is the width of one hit
    point in bytes, and it is even, because hud_rect's unrolled PUSH
    block is entered in units of two bytes -- so a bar drawn at any
    health is an even width and needs no odd path.
    """
    ww, wh, gap = 22, 22, 5
    _cxb, cy = dial_centre()
    wx = 2                                      # the LEFT column...
    wy = cy - (3 * wh + 2 * gap) // 2 + 2 * (wh + gap)   # ...BOTTOM slot
    ix, iy, iw, ih = wx + 1, wy + 2, ww - 2, wh - 4      # the inner well
    seg = (iw // HP_MAX) & ~1                   # even bytes per hit point
    assert seg >= 2, (seg, iw)
    w, h = seg * HP_MAX, 8
    assert w <= iw and h <= ih, (w, h, iw, ih)
    return ix + (iw - w) // 2, iy + (ih - h) // 2, w, h, seg


def scan_slot():
    """-> (x0, y0, bw, bh, sx, sy) for the 3x3 pad.

    bw is EVEN because hud_rect's unrolled PUSH block is entered in units
    of two bytes; the asserts below are what keep it so.
    """
    ww, wh, gap = 22, 22, 5
    _cxb, cy = dial_centre()
    wx = 2                                  # the LEFT column of slots...
    wy = cy - (3 * wh + 2 * gap) // 2 + (wh + gap)      # ...MIDDLE of three
    ix, iy, iw, ih = wx + 1, wy + 2, ww - 2, wh - 4     # the inner well
    bw, bh, pad = 6, 5, 1
    sx, sy = bw + pad, bh + pad
    assert 3 * bw + 2 * pad == iw, (bw, iw)
    assert 3 * bh + 2 * pad <= ih, (bh, ih)
    assert bw % 2 == 0, bw
    return ix, iy + (ih - (3 * bh + 2 * pad)) // 2, bw, bh, sx, sy


def scan_xy(col, row):
    x0, y0, _bw, _bh, sx, sy = scan_slot()
    return x0 + col * sx, y0 + row * sy


def scan_furniture(rc):
    """The pad's resting state: eight blue bearings and a white hub."""
    _x0, _y0, bw, bh, _sx, _sy = scan_slot()
    for (col, row) in SCAN_CELL:
        x, y = scan_xy(col, row)
        rc.add(x, y, bw, bh, SCAN_OFF)
    x, y = scan_xy(*SCAN_HUBCELL)
    rc.add(x, y, bw, bh, SCAN_HUB)


def scan_rects(state, prev=None):
    """-> [(x, y, w, h, byte)] the pad AFTER hud_scan has drawn `state`.

    THE MODEL OF hud_scan, and the only one -- emu_hud.py compares the
    bytes it writes against exactly this.  `state` is the packed byte the
    game hands over: (band << 4) | octant, or 0xFF for "no pickup left".
    `prev` is what was on screen before, because hud_scan restores that
    cell and nothing else: the eight unlit cells are furniture and it
    must not be repainting them.
    """
    _x0, _y0, bw, bh, _sx, _sy = scan_slot()
    out = []
    if prev is not None and prev != 0xFF and prev != state:
        if state == 0xFF or (state & 15) != (prev & 15):
            x, y = scan_xy(*SCAN_CELL[prev & 7])
            out.append((x, y, bw, bh, SOLID[SCAN_OFF]))
    if state != 0xFF:
        x, y = scan_xy(*SCAN_CELL[state & 7])
        out.append((x, y, bw, bh, SOLID[pal.HUD_SCAN[(state >> 4) & 3]]))
    return out


# =====================================================================
#  THE RADAR -- ammo blips inside the dial, and a sweep round its ticks.
#
#  THE DIAL IS ALREADY A COMPASS ROSE, so the blips use its own mapping:
#  dots(a) puts heading a at angle 5a with 0 straight up, and a world
#  SECTOR o is heading 9o (72 headings over 8 sectors), so a blip for
#  sector o goes at 45o degrees -- exactly where the needle points when
#  the player faces it.  Line the needle up with a blip and walk.
#
#  RADIUS IS DISTANCE.  Three rings, near / mid / far, the same three
#  bands game.asm's ammo_scan already sorts pickups into for the pad and
#  the floor block.  So a blip on the inner ring is in this room.
#
#  THE SWEEP IS THE EIGHT TICKS THAT ARE ALREADY THERE, lit one at a
#  time.  It costs two rectangles a frame and -- this is the point -- it
#  lives OUTSIDE the rim, where the needle and the blips never go, so
#  none of the three can erase another.  Inside the dial that is not
#  free: the needle spans every radius along its own bearing, so it and
#  the blips do collide, and hud_radar deals with that by ordering the
#  repaints rather than by pretending they cannot.
RADAR_R = [3, 6, 9]                 # blip radii in BYTES: near, mid, far
RADAR_W, RADAR_H = 2, 3             # ...and the block, like a needle dot
RADAR_PEN = pal.HUD_AMMO            # the ammo orange, as everywhere else
MON_PEN = 13                        # mauve -- THE SAME PEN THE MONSTER IS
                                    # DRAWN IN, so the blip and the thing
                                    # it stands for are one colour.  It is
                                    # also none of the three the dial
                                    # already spends: white needle, red
                                    # tail, orange ammo.
SWEEP_PEN = 7                       # bright yellow: the lit tick


def radar_pos(sector, band):
    """-> (x, y) of the blip block for a world sector and distance band."""
    cxb, cy = dial_centre()
    th = math.radians(45.0 * sector)
    r = RADAR_R[band]
    dx = rnd(r * math.sin(th))
    dy = rnd(-r * ASPECT * math.cos(th))
    return cxb - RADAR_W // 2 + dx, cy + dy - (RADAR_H - 1) // 2


def tick_rects():
    """-> [(x, y, w, h, byte)] the eight ticks, exactly as furniture()
    draws them.  The sweep lights one and puts the last one back, so it
    needs their geometry AND their resting colour -- and north's tick is
    a different size and a different pen from the other seven."""
    cxb, cy = dial_centre()
    out = []
    for k in range(8):
        th = math.radians(45.0 * k)
        dx = rnd(TICK_RXB * math.sin(th))
        dy = rnd(-TICK_RY * math.cos(th))
        if k == 0:
            out.append((cxb - 2 + dx, cy + dy - 2, 4, 5, SOLID[MARK]))
        else:
            out.append((cxb - 1 + dx, cy + dy - 1, 2, 3, SOLID[LIGHT]))
    return out


def radar_check():
    """Every blip lands on DIAL_BG, so erasing one restores the dial.

    The same invariant the needle has (see the header), and for the same
    reason -- a blip that overlapped the rim or the hub could not be
    taken back.  Asserted at generation time over all 24 positions.
    """
    grid = paint(furniture())
    bg = SOLID[DIAL_BG]
    bad = []
    for o in range(8):
        for b in range(3):
            x, y = radar_pos(o, b)
            for yy in range(y, y + RADAR_H):
                for xx in range(x, x + RADAR_W):
                    if grid[yy][xx] != bg:
                        bad.append((o, b, xx, yy, grid[yy][xx]))
    assert not bad, f"blips off the dial background: {bad[:4]}"
    return len(bad) == 0


def radar_cells(blips, mon=0xFF, under=None):
    """-> [(x, y, w, h, byte or None)] every one of the 24 blip squares.

    THE WHOLE RING SET, not just the ones a blip is on: the thing that
    goes wrong with an erase is that it puts the wrong colour back, or
    puts it back somewhere else, and only checking the squares that
    SHOULD be lit cannot see either.

    AN UNLIT SQUARE IS NOT NECESSARILY BLACK, and assuming it was is the
    first thing this model got wrong.  The needle spans every radius
    along its own bearing, so at heading 0 its second dot sits exactly on
    the sector-0 middle-ring square -- hud_radar draws the needle back
    over the blips for precisely that reason.

    AND IT IS NOT ONE COLOUR EITHER, which is the second thing it got
    wrong: the needle dot is three scanlines and the ring square is
    three, offset by one, so the square is needle on two rows and dial
    background on the third.  An unlit square therefore comes back as
    None -- "whatever the dial has here" -- and the caller compares it
    against the dial it painted for itself, byte by byte.
    """
    lit = {}
    for b in blips:
        if b != 0xFF:
            lit[(b & 7, (b >> 4) & 3)] = SOLID[RADAR_PEN]
    # THE MONSTER GOES ON LAST, so a monster sharing a square with a
    # pickup shows as the monster -- which is the one you want to know
    # about.  hud_radar draws them in that order for the same reason.
    if mon != 0xFF:
        lit[(mon & 7, (mon >> 4) & 3)] = SOLID[MON_PEN]
    out = []
    for o in range(8):
        for band in range(3):
            x, y = radar_pos(o, band)
            out.append((x, y, RADAR_W, RADAR_H, lit.get((o, band))))
    return out


def sweep_cells(lit):
    """-> the eight ticks, with tick `lit` in the sweep colour."""
    out = []
    for k, (x, y, w, h, b) in enumerate(tick_rects()):
        out.append((x, y, w, h, SOLID[SWEEP_PEN] if k == lit else b))
    return out


def scan_pad(state):
    """-> [(x, y, w, h, byte)] the WHOLE pad as it should look.

    scan_rects() above is what hud_scan is allowed to WRITE; this is what
    the nine cells must READ BACK as afterwards.  Checking the whole pad
    rather than just the two rectangles is what catches an erase that
    puts the wrong colour back, or one that lands on the hub.
    """
    _x0, _y0, bw, bh, _sx, _sy = scan_slot()
    out = []
    for i, (col, row) in enumerate(SCAN_CELL):
        x, y = scan_xy(col, row)
        pen = SCAN_OFF
        if state != 0xFF and (state & 7) == i:
            pen = pal.HUD_SCAN[(state >> 4) & 3]
        out.append((x, y, bw, bh, SOLID[pen]))
    x, y = scan_xy(*SCAN_HUBCELL)
    out.append((x, y, bw, bh, SOLID[SCAN_HUB]))
    return out


def write_inc(path, rects, tab):
    radar_check()               # every blip must land on DIAL_BG
    cxb, cy = dial_centre()
    L = []
    L.append("; Generated by engine2/tools/genhud.py -- do not edit.")
    L.append("; The HUD's furniture and its compass needle.  See that file")
    L.append("; for what every table means and what is asserted about it.")
    L.append("")
    L.append(f"HUD_CXB      equ {cxb}   ; dial centre: byte BOUNDARY x ...")
    L.append(f"HUD_CY       equ {cy}   ; ... and scanline y")
    L.append(f"HUD_NDOT     equ {len(NDL_DOTS)}   ; blocks in the needle")
    # ---- THE MAP, in the right-hand well ----------------------------
    #  ONE BYTE A CELL, and that is why hud2.asm has a blitter of its own
    #  rather than calling hud_rect: hud_rect fills in two-byte units --
    #  genhud.py asserts every width it is given is even, because the fill
    #  is an unrolled run of PUSH DE -- so the narrowest cell it can draw
    #  is two bytes, and sixteen of those is 32 bytes against the 20 the
    #  well has.  A byte a cell fits, and a straight write is cheaper than
    #  a rectangle call anyway at this size.
    #
    #  IT FITS, SO IT DOES NOT SCROLL.  The window is asserted to hold the
    #  whole map below; a map that outgrows the well trips the assert
    #  rather than silently showing a corner of itself.
    mmx, mmy, mmw, mmh = map_slot()
    L.append(f"HUD_MMX      equ {mmx}   ; the map, byte x ...")
    L.append(f"HUD_MMY      equ {mmy}   ; ... and scanline y")
    L.append(f"HUD_MMCH     equ {MM_CH}   ; scanlines a cell")
    L.append(f"HUD_MMN      equ {MM_N}   ; cells a side")
    L.append(f"HUD_MMSEEN   equ #{SOLID[MM_SEEN]:02X}   "
             f"; a cell the flood has reached")
    L.append(f"HUD_MMPLR    equ #{SOLID[MM_PLR]:02X}   ; ... and the one you are in")
    L.append(f"HUD_MMBG     equ #{SOLID[SHADOW]:02X}   ; ... and one it has not")
    del mmw, mmh
    L.append(f"HUD_NW       equ {NDL_W}   ; every block is this many bytes")

    # ---- THE AMMO READOUT, in the top-left slot ----------------------
    #  Six pips in the slot's inner well.  The geometry is DERIVED from
    #  the same numbers that drew the slot -- ammo_slot() below -- so a
    #  slot that moves takes its pips with it, and hud2.asm never has a
    #  coordinate of its own.  Every width is EVEN because hud_rect's
    #  unrolled PUSH block is entered in units of two bytes.
    ax, ay, aw, ah, adx, an = ammo_slot()
    L.append("")
    L.append(f"HUD_AMX      equ {ax}   ; first ammo pip, byte x")
    L.append(f"HUD_AMY      equ {ay}   ; ... and scanline y")
    L.append(f"HUD_AMW      equ {aw}   ; pip width in BYTES (even)")
    L.append(f"HUD_AMH      equ {ah}   ; ... and height in scanlines")
    L.append(f"HUD_AMDX     equ {adx}   ; byte pitch from one pip to the next")
    L.append(f"HUD_AMN      equ {an}   ; how many rounds the readout shows")
    # ...as BYTES and not pens: hud_rect pushes the byte straight to the
    # screen, and Rects.add is the only thing that maps one to the other.
    L.append(f"HUD_AMPEN    equ #{SOLID[pal.HUD_AMMO]:02X}   "
             f"; a round the player still has")
    L.append(f"HUD_AMBG     equ #{SOLID[SHADOW]:02X}   "
             f"; ... and one already fired")

    # ---- THE HEALTH BAR, in the bottom-left slot ---------------------
    hx, hy, hw, hh, hseg = health_slot()
    L.append("")
    L.append(f"HUD_HPX      equ {hx}   ; health bar, byte x")
    L.append(f"HUD_HPY      equ {hy}   ; ... and scanline y")
    L.append(f"HUD_HPW      equ {hw}   ; full width, BYTES (even)")
    L.append(f"HUD_HPH      equ {hh}   ; ... and height in scanlines")
    L.append(f"HUD_HPSEG    equ {hseg}   ; bytes of bar per hit point (even)")
    L.append(f"HUD_HPN      equ {HP_MAX}   ; hit points the bar shows")
    L.append(f"HUD_HPPEN    equ #{SOLID[HP_PEN]:02X}   "
             f"; health still in hand -- FX_BLOOD's own red")
    L.append(f"HUD_HPBG     equ #{SOLID[SHADOW]:02X}   "
             f"; ... and health already lost")

    # ---- THE AMMO SCANNER, in the middle-left slot -------------------
    #  A 3x3 direction pad.  hud2.asm is handed a packed byte -- see
    #  scan_rects() -- and needs three things from here: how big a cell
    #  is, where each of the eight bearings is, and what to paint.  The
    #  eight positions are a TABLE rather than a base and a pitch,
    #  because the mapping from bearing to cell is not a straight line:
    #  it walks a ring, and a ring is not arithmetic hud2.asm should be
    #  doing.
    sx0, sy0, sbw, sbh, _ssx, _ssy = scan_slot()
    L.append("")
    L.append(f"HUD_SCW      equ {sbw}   ; a scanner cell, bytes (even)")
    L.append(f"HUD_SCH      equ {sbh}   ; ... and scanlines")
    L.append(f"HUD_SCOFF    equ #{SOLID[SCAN_OFF]:02X}   "
             f"; an unlit bearing -- what hud_scan restores")
    L.append(f"HUD_SCN      equ {len(SCAN_CELL)}   ; bearings on the pad")
    L.append("SCANPEN                     ; by distance band: near, mid, far")
    L.append("    db " + ",".join("#%02X" % SOLID[p] for p in pal.HUD_SCAN))
    L.append("SCANPOS                     ; by RELATIVE bearing: 0 is dead")
    L.append("                            ; ahead, then clockwise")
    for i, (col, row) in enumerate(SCAN_CELL):
        x, y = scan_xy(col, row)
        L.append("    db %3d,%4d   ; %d" % (x, y, i))
    assert sx0 == scan_xy(0, 0)[0] and sy0 == scan_xy(0, 0)[1]


    # ---- THE RADAR, on the dial ---------------------------------------
    #  Blips by (sector, band) and the eight ticks the sweep lights.  The
    #  tick table carries each tick's RESTING colour as well as its box,
    #  because north's is a different size and a different pen from the
    #  other seven and the sweep has to put back exactly what it found.
    L.append("")
    L.append(f"HUD_RADW     equ {RADAR_W}   ; a blip block, bytes (even)")
    L.append(f"HUD_RADH     equ {RADAR_H}   ; ... and scanlines")
    L.append(f"HUD_RADPEN   equ #{SOLID[RADAR_PEN]:02X}   "
             f"; the ammo orange, as on the floor and in the pips")
    L.append(f"HUD_RADBG    equ #{SOLID[DIAL_BG]:02X}   "
             f"; ...and what erasing one puts back")
    L.append(f"HUD_MONPEN   equ #{SOLID[MON_PEN]:02X}   "
             f"; ...and a monster, in the pen it is drawn in")
    L.append(f"HUD_SWPEN    equ #{SOLID[SWEEP_PEN]:02X}   "
             f"; the lit tick")
    L.append(f"HUD_NSECT    equ 8   ; sectors round the dial")
    L.append("RADPOS                      ; db x, y -- by sector*3 + band,")
    L.append("                            ; band 0 near (inner ring)")
    for o in range(8):
        row = []
        for b in range(3):
            x, y = radar_pos(o, b)
            row.append(f"{x:3d},{y:4d}")
        L.append("    db " + ", ".join(row) + f"   ; sector {o}")
    L.append("TICKTAB                     ; db x, y, w, h, resting byte")
    for (x, y, w, h, b) in tick_rects():
        L.append(f"    db {x:3d},{y:4d},{w:3d},{h:3d},#{b:02X}")

    L.append("")
    # ---- THE FURNITURE IS NOT HERE ANY MORE.  It was 71 records of five
    #      bytes emitted straight into the code segment, and the code
    #      segment had 22 bytes left.  engine2/tools/genaux.py puts the
    #      same records in RAM bank 6 and gen_aux.inc names them, so
    #      HUDRECTS and HUD_NRECT come from there now -- read genaux.py
    #      for why bank 6 exists and what else may go in it.  This file
    #      still OWNS the geometry; it just no longer owns the storage.
    L.append("; ---- static furniture: see gen_aux.inc, RAM bank 6 ----")
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
    # ---- THE NEEDLE TABLE IS NOT HERE EITHER.  Like the furniture, it
    #      is in RAM bank 6 now -- engine2/tools/genaux.py -- because the
    #      code segment ran out.  This file still derives it and asserts
    #      it; genaux.py stores it.
    L.append("; ---- needle table: see gen_aux.inc, RAM bank 6 ----")
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
