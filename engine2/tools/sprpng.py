"""engine2/tools/sprpng.py -- THE SPRITE SHEET, AND WHAT IT COSTS.

Shared by genspr.py (PNG -> rectangles) and by the --export bootstrap.
Kept apart from genspr.py so the FORMAT of the sheet is described once.

THE SHEET IS AN INDEXED PNG, AND IT HAS TO BE.  tools/world.py's sixteen
pens do not have sixteen distinct colours: pen 1 and pen 15 are both
firmware ink 26 (bright white), pen 0 and pen 13 are both ink 0 (black),
pen 5 and pen 12 are both ink 1.  An RGB sheet could not say which of a
pair the artist meant, so the sheet stores INDICES: the pixel value IS
the pen number the Z80 writes.  assets/amaze-mode0.gpl is that palette
for GIMP, in the same order, so the palette index in the editor and the
pen on the CPC are one number.

    index 0..15   the pens
    index 16      TRANSPARENT -- painted magenta so it is obvious, and
                  never drawn: it becomes the ABSENCE of a rectangle

GEOMETRY.  One tile per sprite, side by side, no gutter:

    PAIRS x PX  wide     7 column pairs, 4 mode-0 pixels each -> 28 px
    ROWS        tall     128

A COLUMN PAIR IS THE ENGINE'S UNIT, not a choice.  A rectangle record
carries `col` and `ncol` in PAIRS because hud_rect fills two bytes at a
time; four mode-0 pixels is the narrowest thing the sprite drawer can
place.  So the sheet is painted at mode-0 pixel resolution -- which is
what the artist expects -- and every group of PX pixels across must be
one colour.  A group that is not is REPORTED, with its coordinates, and
resolved by majority; it is not silently averaged.

WHY 128 ROWS.  The band edges are emitted in 256ths of the box height,
so a sheet of 128 rows lands every edge on an exact 2/256 -- and the
hand-built monster and pickup this replaced had edges at 72, 108, 200,
224 and 40, 100, 150, 214, every one of which is an exact multiple of 2.
The sheet can therefore reproduce the old art to the byte, which is how
the change was checked.

ROWS ARE NOT BANDS.  A band is a maximal run of IDENTICAL rows, found by
this file rather than declared: 128 rows of art become five or six bands
because that is how many distinct rows the picture has.  That matters
for cost -- see genspr.py, where a band is a multiply and a rectangle is
87 us.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import cpchw as cpc                                             # noqa: E402
import world                                                    # noqa: E402

PAIRS = 7                       # column pairs a tile, ODD so it has a centre
PX = 4                          # mode-0 pixels a column pair
ROWS = 128                      # rows a tile; see the note above
TILE_W = PAIRS * PX
CLEAR = 16                      # the transparent index
CLEAR_RGB = (0xFF, 0x00, 0xFF)  # ...painted magenta, so it cannot be missed

SHEET = os.path.join(_ROOT, "assets", "sprites.png")


def palette():
    """-> the 17 x 3 byte palette an indexed sheet must carry."""
    out = []
    for ink in world.PEN_INK:
        out += list(cpc.ink_rgb(ink))
    out += list(CLEAR_RGB)
    return out


def load(path=None):
    """-> {name: grid}, grid[row][pair] = pen or None, one entry a tile.

    Names come from the SPRITES manifest in genspr.py via `order`.
    """
    from PIL import Image
    img = Image.open(path or SHEET)
    if img.mode != "P":
        raise ValueError(
            f"{path or SHEET} is {img.mode}, not indexed.  The sheet stores "
            "PEN NUMBERS, not colours -- see sprpng.py.  In GIMP: "
            "Image > Mode > Indexed, 'Use custom palette', amaze-mode0, and "
            "turn OFF 'Remove unused colours'.")
    if img.height != ROWS:
        raise ValueError(f"{path or SHEET} is {img.height} rows, expected {ROWS}")
    if img.width % TILE_W:
        raise ValueError(f"{path or SHEET} is {img.width} px wide, and a tile "
                         f"is {TILE_W} -- {img.width % TILE_W} px left over")
    want = palette()
    got = list(img.getpalette() or [])[:len(want)]
    if got != want:
        raise ValueError(
            f"{path or SHEET} does not carry the game's palette.  GIMP drops "
            "duplicate colours unless 'Remove unused colours' is off, and "
            "this palette HAS duplicates -- pens 1 and 15 are both white.  "
            "Re-index from assets/amaze-mode0.gpl.")
    px = img.load()
    return img.width // TILE_W, px


def tile(px, n, report=None):
    """-> grid[row][pair] for tile n, pens or None, PX pixels to a pair.

    A group of PX pixels that is not one colour is resolved by MAJORITY
    and appended to `report` -- never silently averaged.  See the note in
    sprpng.py: the pair is the fill's unit and the artist cannot be shown
    a resolution the machine does not have.
    """
    grid = []
    for y in range(ROWS):
        row = []
        for p in range(PAIRS):
            x0 = n * TILE_W + p * PX
            vals = [px[x0 + i, y] for i in range(PX)]
            if len(set(vals)) != 1:
                best = max(set(vals), key=vals.count)
                if report is not None:
                    report.append((n, p, y, tuple(vals), best))
                v = best
            else:
                v = vals[0]
            if v > CLEAR:
                raise ValueError(f"tile {n} pair {p} row {y}: index {v} is "
                                 f"past the palette (0..{CLEAR})")
            row.append(None if v == CLEAR else v)
        grid.append(row)
    return grid


def bands(grid):
    """-> (bandgrid, edges).  A BAND IS A MAXIMAL RUN OF IDENTICAL ROWS.

    edges are in 256ths of the box height, which is what the Z80 scales:
    ROWS is 128 so every edge is an exact multiple of 2 and nothing is
    rounded.
    """
    bg, edge = [], [0]
    for y in range(ROWS):
        if bg and grid[y] == bg[-1]:
            continue
        bg.append(list(grid[y]))
        if y:
            edge.append(y * 256 // ROWS)
    edge.append(256)
    return bg, edge


def paint(rects, nb, ncols, lo):
    """Paint a rectangle list in order -> the grid it produces.

    THE CHECK THAT MAKES THE SEARCH IRRELEVANT.  sprcover's cover is a
    randomised hill-climb and could be replaced tomorrow; this is what
    says the answer is right, whatever found it.

    `lo` IS NOT OPTIONAL.  A record's `col` is signed and measured from
    the sprite's CENTRE, while the grid is indexed from 0 -- and Python
    indexes g[b][-1] as the last column without complaining, so getting
    this wrong paints a plausible picture in the wrong place.  There is
    one paint() in the repository for that reason; sprcover imports it.
    """
    g = [[None] * ncols for _ in range(nb)]
    for (c, n, b0, b1, pen) in rects:
        for b in range(b0, b1 + 1):
            for x in range(c - lo, c - lo + n):
                assert 0 <= x < ncols, f"column {x} outside 0..{ncols-1}"
                g[b][x] = pen
    return g
