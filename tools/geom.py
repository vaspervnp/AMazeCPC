"""Projection and rasterisation for the precalculated span lists.

The world is a unit grid.  The player stands at the centre of a cell looking
along +Z, and can only face the four cardinal directions -- so the *shape* of
every wall face depends solely on where the cell sits in the view frustum
(lateral offset `l`, forward offset `f`) and on how far the player has walked
into the current cell (`substep`).  That is a small, finite set, which is the
whole reason the span lists can be precalculated.

Two face kinds are emitted:

  FRONT  the -Z face of a cell -- always a screen-space rectangle, so it
         collapses to a single (y0, height, x_end, npush) record.
  SIDE   a face parallel to the view axis -- a trapezoid, so it needs a real
         per-scanline span list.

Everything is clipped to the viewport at generation time; nothing off-screen
ever reaches the Z80.
"""

from dataclasses import dataclass

# ------------------------------------------------------------- viewport ----
# Geometry is measured in half-byte units, which makes it mode independent:
# a CPC scanline is 80 bytes wide in every mode, and only the number of
# pixels packed into a byte changes.  Mode 0 gets a small window with a HUD
# around it; Mode 2 takes the whole screen and dithers for depth.

MODE = 0
VP_BX = 22          # left edge, in bytes
VP_BW = 36          # width, in bytes
VP_Y = 8            # top scanline
VP_H = 104          # height in scanlines
VP_PW = VP_BW * 2   # viewport width, in half-byte units
CX = VP_PW / 2.0
CY = VP_H / 2.0
FOCAL = 104.0       # = VP_H: a wall one cell away fills the view
GAMMA = 1.0         # <1 would compress depth; free, since we precalculate
ZNEAR = 0.08        # anything closer is clipped away

F_MAX = 5           # forward cells 0..F_MAX
L_MAX = 3           # lateral cells -L_MAX..+L_MAX
SUBSTEPS = 8        # motion sub-positions per cell


def configure(mode):
    """Point the projection at the target screen mode."""
    global MODE, VP_BX, VP_BW, VP_Y, VP_H, VP_PW, CX, CY, FOCAL, F_MAX
    global SUBSTEPS
    MODE = mode
    if mode == 0:
        VP_BX, VP_BW, VP_Y, VP_H, F_MAX = 22, 36, 8, 104, 5
        SUBSTEPS = 8
    else:
        VP_BX, VP_BW, VP_Y, VP_H, F_MAX = 0, 80, 0, 200, 4
        # A full-screen repaint costs ~32 us/frame of pure fill, so Mode 2
        # locks to 100 ms rather than 40 ms.  Halving the sub-steps keeps the
        # same number of distinct positions per SECOND -- so it looks no less
        # smooth -- while crossing a cell in 0.4 s instead of 0.8 s.
        SUBSTEPS = 4
    VP_PW = VP_BW * 2
    CX = VP_PW / 2.0
    CY = VP_H / 2.0
    FOCAL = float(VP_H)

FRONT, SIDE = 0, 1


def substep_offset(s):
    """Player's offset from their cell centre along the view axis, in cells."""
    return (s / SUBSTEPS) - 0.5


def scale(z):
    """Screen pixels per world unit at depth z."""
    return FOCAL / (z ** GAMMA)


def project(wx, wy, z):
    """World (lateral, height, depth) -> viewport-local pixel (x, y).

    `wy` is 0 at the floor and 1 at the ceiling; the camera sits at 0.5.
    """
    s = scale(z)
    return (CX + wx * s, CY - (wy - 0.5) * s)


# ---------------------------------------------------------- rasterising ----

def raster_convex(pts):
    """Scanline-rasterise a convex polygon given as viewport-local pixel points.

    Yields (y, xl, xr) with y an integer scanline and xl/xr floats, sampling
    each scanline at its centre.  Nothing outside the viewport is yielded.
    """
    ys = [p[1] for p in pts]
    y_lo = max(0, int(min(ys)))
    y_hi = min(VP_H, int(max(ys)) + 1)

    n = len(pts)
    for y in range(y_lo, y_hi):
        yc = y + 0.5
        xs = []
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if y0 == y1:
                continue
            if (y0 <= yc < y1) or (y1 <= yc < y0):
                t = (yc - y0) / (y1 - y0)
                xs.append(x0 + t * (x1 - x0))
        if len(xs) < 2:
            continue
        yield y, min(xs), max(xs)


def quantise(xl, xr):
    """Pixel range -> (start_byte, npush) within the viewport, or None.

    PUSH DE writes two bytes at a time and both carry the same colour, so the
    start byte may be odd; only the *length* has to be even.
    """
    b0 = int(round(xl / 2.0))
    b1 = int(round(xr / 2.0))
    b0 = max(0, min(VP_BW, b0))
    b1 = max(0, min(VP_BW, b1))
    n = b1 - b0
    if n <= 0:
        return None
    if n & 1:                       # round the length to even
        if b1 < VP_BW:
            b1 += 1
        elif b0 > 0:
            b0 -= 1
        else:
            return None
        n = b1 - b0
    return b0, n // 2


# ------------------------------------------------------------- faces ------

@dataclass
class Rect:
    """A constant-width span repeated over a contiguous run of scanlines."""
    y0: int             # absolute scanline
    h: int
    xb: int             # absolute start byte column
    npush: int

    @property
    def fill_bytes(self):
        return self.h * self.npush * 2


@dataclass
class Spans:
    """One (start_byte, npush) pair per scanline, from y0 downwards."""
    y0: int
    lines: list         # [(xb, npush), ...]

    @property
    def fill_bytes(self):
        return sum(n * 2 for _, n in self.lines)


def _rasterise(pts):
    """Rasterise a polygon into a Rect if it is one, else a Spans list."""
    rows = []
    for y, xl, xr in raster_convex(pts):
        q = quantise(xl, xr)
        if q is None:
            if rows:                # left the polygon; convex so we are done
                break
            continue
        rows.append((y, q[0], q[1]))
    if not rows:
        return None

    y0 = rows[0][0]
    # Rasterising a convex shape can only yield contiguous scanlines; assert it
    # so a geometry bug cannot silently produce a misaligned span list.
    assert [r[0] for r in rows] == list(range(y0, y0 + len(rows))), \
        "non-contiguous scanlines in face"

    body = [(xb, n) for _, xb, n in rows]
    if len(set(body)) == 1:
        xb, n = body[0]
        return Rect(VP_Y + y0, len(body), VP_BX + xb, n)
    return Spans(VP_Y + y0, [(VP_BX + xb, n) for xb, n in body])


def front_face(l, f, off):
    """The -Z face of cell (l, f).  Rectangular in screen space."""
    z = f - 0.5 - off
    if z < ZNEAR:
        return None
    x0, y_top = project(l - 0.5, 1.0, z)
    x1, y_bot = project(l + 0.5, 0.0, z)
    return _rasterise([(x0, y_top), (x1, y_top), (x1, y_bot), (x0, y_bot)])


def side_face(l, f, off):
    """The inward-facing side of cell (l, f) -- a trapezoid.

    Cells to the right of the axis show their left face and vice versa; a cell
    on the axis shows neither, being exactly edge-on.
    """
    if l == 0:
        return None
    xw = l - 0.5 if l > 0 else l + 0.5

    za = f - 0.5 - off          # near edge
    zb = f + 0.5 - off          # far edge
    za = max(za, ZNEAR)
    if zb <= ZNEAR:
        return None

    xa, ya_top = project(xw, 1.0, za)
    _, ya_bot = project(xw, 0.0, za)
    xb, yb_top = project(xw, 1.0, zb)
    _, yb_bot = project(xw, 0.0, zb)

    return _rasterise([(xa, ya_top), (xb, yb_top), (xb, yb_bot), (xa, ya_bot)])


def horizon_y(f, off, ceiling):
    """Absolute scanline where the floor/ceiling meets the far face of cell f.

    Used to band the floor and ceiling for depth cueing -- cheap extra rects.
    """
    z = f + 0.5 - off
    if z < ZNEAR:
        return None
    _, y = project(0.0, 1.0 if ceiling else 0.0, z)
    return VP_Y + max(0, min(VP_H, int(round(y))))


def slots():
    """Every (kind, l, f) face slot in the frustum, in painter's order.

    Far cells first, and within a depth the outermost laterals first, so an
    inner cell's front face correctly covers the side face of the cell beyond
    it.  A cell's own side is drawn before its front, the front being nearer.
    """
    out = []
    for f in range(F_MAX, -1, -1):
        for l in sorted(range(-L_MAX, L_MAX + 1), key=lambda v: (-abs(v), v)):
            out.append((SIDE, l, f))
            out.append((FRONT, l, f))
    return out
