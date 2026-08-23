"""Free-position / free-angle ("Wolfenstein-like") renderer for the AMazeCPC
world, producing exactly the same primitive the Z80 consumes: horizontal
PUSH DE runs with a byte-granular start and an EVEN byte length.

Differences from the shipped engine, and why they matter:

  * The player is at an arbitrary (x, y) float and an arbitrary one of 72
    headings (5 degree steps).  Nothing about a face's screen shape is a
    function of a small finite state any more, so NOTHING can be
    precalculated: every face must be transformed, clipped, divided and
    rasterised at runtime.
  * A face is a screen-space RECTANGLE only when its plane is perpendicular
    to the view direction, i.e. only at headings that are multiples of 90
    degrees (4 of the 72).  At every other heading every face is a trapezoid
    and costs the 28 us/scanline "span-line" rate instead of 19 us/scanline.

Conventions
  maze coords: x to the right, y DOWNWARD (row index), cell size 1.0
  heading h (deg): forward = (cos h, sin h);  right = (-sin h, cos h)
    so h=0 faces east(+x), h=90 faces south(+y).
  view space: z = forward component (depth), xv = right component (lateral)
"""

import math

import geom
import world
from geom import Rect, Spans

# ---------------------------------------------------------------- setup ----
geom.configure(0)                       # Mode 0 viewport: 36x104 bytes

N_ANGLES = 72                           # 5 degree increments
DEG_STEP = 360.0 / N_ANGLES

# Half-width of the frustum in world units per unit of depth.
# Horizontal and vertical focal lengths are separate.  FOCAL_V sets how tall a
# wall is (FOCAL_V = VP_H makes a wall one cell away exactly fill the view);
# FOCAL_H sets the horizontal field of view independently.  Wolfenstein wants a
# wide FOV without short walls, and a Mode 0 pixel is 1.67x wider than tall
# anyway, so tying the two together would be the wrong constraint.
FOCAL_H = geom.FOCAL
FOCAL_V = geom.FOCAL


def set_focal(fh, fv):
    global FOCAL_H, FOCAL_V, KHALF, HALF_FOV_DEG
    FOCAL_H, FOCAL_V = float(fh), float(fv)
    KHALF = geom.CX / FOCAL_H
    HALF_FOV_DEG = math.degrees(math.atan(KHALF))


KHALF = geom.CX / geom.FOCAL
HALF_FOV_DEG = math.degrees(math.atan(KHALF))

ZNEAR = geom.ZNEAR                      # 0.08
R_MAX = 6                               # march radius, cells (L1)

NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3
# (dx, dy) of the neighbour the face looks into, and the face's normal
_FACE = {
    NORTH: (0, -1),
    EAST:  (+1, 0),
    SOUTH: (0, +1),
    WEST:  (-1, 0),
}


def basis(a_idx):
    r = math.radians((a_idx % N_ANGLES) * DEG_STEP)
    c, s = math.cos(r), math.sin(r)
    return (c, s), (-s, c)              # forward, right


def to_view(wx, wy, px, py, fwd, rgt):
    dx, dy = wx - px, wy - py
    return (dx * rgt[0] + dy * rgt[1],   # xv (lateral)
            dx * fwd[0] + dy * fwd[1])   # z  (depth)


def is_open(grid, x, y, doors):
    c = world.cell_at(grid, x, y)
    if c == world.WALL:
        return False
    if c == world.DOOR:
        return doors.get((x, y), 0) > 0
    return True


# ------------------------------------------------------------ frustum ------
# Half-space tests, positive = inside.
def _inside(xv, z, plane):
    if plane == 0:
        return z - ZNEAR
    if plane == 1:
        return KHALF * z - xv           # right plane
    return xv + KHALF * z               # left plane


def clip_segment(a, b):
    """Clip a view-space segment (xv, z) to near + left + right planes.
    -> (a, b) or None."""
    for plane in (0, 1, 2):
        da = _inside(a[0], a[1], plane)
        db = _inside(b[0], b[1], plane)
        if da < 0 and db < 0:
            return None
        if da < 0 or db < 0:
            t = da / (da - db)
            m = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            if da < 0:
                a = m
            else:
                b = m
    return a, b


def cell_in_frustum(cx, cy, px, py, fwd, rgt):
    """Conservative: reject only if all four corners are outside one plane."""
    v = [to_view(cx + i, cy + j, px, py, fwd, rgt)
         for i, j in ((0, 0), (1, 0), (0, 1), (1, 1))]
    for plane in (0, 1, 2):
        if all(_inside(x, z, plane) < 0 for x, z in v):
            return False
    return True


# ------------------------------------------------------------ marching -----

def march(grid, px, py, a_idx, doors):
    """Flood through open cells inside the frustum.

    -> (open_cells set, faces list, cells_visited count)

    Front-to-back is NOT used for the flood; see build_frame for the painter
    ordering of the faces themselves.
    """
    fwd, rgt = basis(a_idx)
    pcx, pcy = int(math.floor(px)), int(math.floor(py))

    seen = set()
    visited = 0
    stack = [(pcx, pcy)]
    pushed = {(pcx, pcy)}
    while stack:
        cx, cy = stack.pop()
        visited += 1
        if abs(cx - pcx) + abs(cy - pcy) > R_MAX:
            continue
        if (cx, cy) != (pcx, pcy):
            if not is_open(grid, cx, cy, doors):
                continue
            if not cell_in_frustum(cx, cy, px, py, fwd, rgt):
                continue
        seen.add((cx, cy))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (cx + dx, cy + dy)
            if n not in pushed:
                pushed.add(n)
                stack.append(n)

    # Every grid edge between a visible open cell and a solid cell is a
    # candidate wall segment.
    faces = []
    for (cx, cy) in seen:
        for d, (dx, dy) in _FACE.items():
            wx, wy = cx + dx, cy + dy
            cell = world.cell_at(grid, wx, wy)
            if cell == world.FLOOR:
                continue
            if cell == world.DOOR and doors.get((wx, wy), 0) > 0:
                continue
            # The face of the SOLID cell that looks back at the open cell.
            face_dir = (d + 2) % 4
            faces.append((wx, wy, face_dir, cell == world.DOOR))
    return seen, faces, visited


def face_endpoints(wx, wy, face_dir):
    """World endpoints of the wall face, and its outward normal."""
    if face_dir == NORTH:                       # y = wy, normal (0,-1)
        return (wx, wy), (wx + 1, wy), (0, -1)
    if face_dir == SOUTH:                       # y = wy+1
        return (wx, wy + 1), (wx + 1, wy + 1), (0, 1)
    if face_dir == WEST:                        # x = wx
        return (wx, wy), (wx, wy + 1), (-1, 0)
    return (wx + 1, wy), (wx + 1, wy + 1), (1, 0)   # EAST


# --------------------------------------------------------- projection ------

def project_face(wx, wy, face_dir, px, py, fwd, rgt):
    """-> (quad points in viewport pixels, z of midpoint) or None."""
    (ax, ay), (bx, by), n = face_endpoints(wx, wy, face_dir)
    # backface cull: player must be on the outward side of the plane
    if (px - ax) * n[0] + (py - ay) * n[1] <= 0.0:
        return None

    a = to_view(ax, ay, px, py, fwd, rgt)
    b = to_view(bx, by, px, py, fwd, rgt)
    cl = clip_segment(a, b)
    if cl is None:
        return None
    a, b = cl

    sa = FOCAL_V / a[1]
    sb = FOCAL_V / b[1]
    hxa = FOCAL_H / a[1]
    hxb = FOCAL_H / b[1]
    xa = geom.CX + a[0] * hxa
    xb = geom.CX + b[0] * hxb
    # Order by PROJECTED x, not by view-space lateral x: for a wall seen
    # nearly edge-on the NEAR endpoint projects further out than the far one.
    if xa > xb:
        a, b = b, a
        sa, sb = sb, sa
        hxa, hxb = hxb, hxa
        xa, xb = xb, xa
    if xb - xa < 1e-6:
        return None
    pts = [(xa, geom.CY - 0.5 * sa),
           (xb, geom.CY - 0.5 * sb),
           (xb, geom.CY + 0.5 * sb),
           (xa, geom.CY + 0.5 * sa)]

    # Shading depth: EUCLIDEAN distance to the midpoint of the VISIBLE
    # (clipped) part of the face.  Deliberately not the view-space depth z --
    # z of a wall running away from you changes fast as the frustum edge
    # slides along it, so the whole face changes ramp step when you merely
    # turn on the spot.  Radial distance is rotation invariant.
    # On Z80 the octagonal approximation max + 0.5*min is ~20 us, 4% error.
    dist = math.hypot(0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))
    return pts, dist


def rasterise(pts):
    """Same quantiser and Rect/Spans classification as tools/geom.py."""
    return geom._rasterise(pts)


# ------------------------------------------------------------- frame -------

BAND_Z = 2.5            # depth where the near/far floor+ceiling bands meet


def background_bands():
    """4 full-width bands, exactly like the shipped engine.  The horizon is
    always at CY because the camera is at wall mid-height."""
    top, bot = geom.VP_Y, geom.VP_Y + geom.VP_H
    mid = geom.VP_Y + geom.VP_H // 2
    d = int(round(0.5 * FOCAL_V / BAND_Z))
    yc = max(top, mid - d)
    yf = min(bot, mid + d)
    return [(top, yc, world.CEIL_NEAR),
            (yc, mid, world.CEIL_FAR),
            (mid, yf, world.FLOOR_FAR),
            (yf, bot, world.FLOOR_NEAR)]


def build_frame(grid, px, py, a_idx, doors=None):
    """-> dict with the draw list and the raw counters."""
    doors = doors or {}
    fwd, rgt = basis(a_idx)
    seen, cand, visited = march(grid, px, py, a_idx, doors)
    pcx, pcy = int(math.floor(px)), int(math.floor(py))

    drawn = []
    for wx, wy, fd, is_door in cand:
        r = project_face(wx, wy, fd, px, py, fwd, rgt)
        if r is None:
            continue
        pts, dist = r
        g = rasterise(pts)
        if g is None:
            continue
        # Ramp index matched to the shipped engine: a front face of forward
        # cell f sits at distance f-0.5 and uses ramp index f, so
        # index = int(dist + 0.5).
        depth = max(1, min(6, int(dist + 0.5)))
        ns = fd in (NORTH, SOUTH)       # N/S one ramp step darker than E/W
        pen = world.wall_pen(depth, ns, is_door)
        # painter key: L1 cell distance.  For an axis-aligned uniform grid
        # this is an EXACT back-to-front order (see notes in the report).
        key = abs(wx - pcx) + abs(wy - pcy)
        drawn.append((key, g, pen))

    drawn.sort(key=lambda t: -t[0])     # back to front

    return {
        "bands": background_bands(),
        "faces": [(g, pen) for _, g, pen in drawn],
        "cells_visited": visited,
        "cells_seen": len(seen),
        "n_faces": len(drawn),
        "n_candidates": len(cand),
    }
