"""Bit-exact Python model of engine2/src/march.asm -- INCREMENTAL VIEW SPACE.

This is the SPEC the Z80 implements: every arithmetic step here is one the
Z80 performs, in the same order, with the same truncation.  Two things are
checked against it:

  * the float reference (prototype/free-angle/free.py) -- how often, if ever,
    fixed point changes a visibility decision  (engine2/tools/check_model.py);
  * the assembled Z80 routine running on the emulator -- must be identical,
    every state, no exceptions  (engine2/tools/emu_march.py, emu_kernel.py).

FIXED POINT
  player position   px, py   unsigned 16-bit 8.8   (high byte = cell 0..15)
  everything else   signed 16-bit Q6.10, 1024 = one cell -- the SAME VIEW
                    fixed point engine2/tools/gentab.py gives the projector,
                    so a face endpoint leaves the march ready to project.

WHY THERE IS NOT ONE MULTIPLY IN THE MARCHING LOOP
  View-space coordinates of a grid corner are AFFINE in the grid indices:

      xv(i,j) = i*rgtx + j*rgty - xv0        xv0 = (fx*rgtx + fy*rgty) >> 8
      zv(i,j) = i*fwdx + j*fwdy - z0         z0  = (fx*fwdx + fy*fwdy) >> 8

  so stepping i -> i+1 ADDS the per-frame constant (rgtx, fwdx) and j -> j+1
  adds (rgty, fwdy).  The two frustum half-planes are affine in (i,j) for the
  same reason:

      L = xv + KHALF*zv >= 0      inside the left plane
      R = KHALF*zv - xv >= 0      inside the right plane

  with steps dLi = rgtx + KHALF*fwdx, dLj = rgty + KHALF*fwdy,
             dRi = KHALF*fwdx - rgtx, dRj = KHALF*fwdy - rgty
  which are pure functions of the heading, so they come out of a ROM table
  (LRSTEP here, MARCHTAB in gen_slopes.inc) rounded ONCE.

  The flood therefore carries (xv, zv, L, R) on its stack and updates them
  with four 16-bit ADDs per cell step.  Four multiplies at the top of the
  frame seed the player's own cell corner; after that the march does not
  multiply and does not build a single table.

  A cell is culled iff ALL FOUR of its corners fall outside one plane, i.e.
  iff the maximum over the corners is negative.  Each plane function is a
  sum of an i-term and a j-term, so that maximum is the value at the
  reference corner plus max(0, step_i) + max(0, step_j) -- per-frame
  constants, which are FOLDED INTO THE SEED.  The whole cull is then three
  sign tests on carried values:

      L < 0             cull            (left plane)
      R < 0             cull            (right plane)
      zv + CZ < 0       cull            (near plane, CZ folds ZNEAR in)

  Backface culling stays free: the face of a wall cell that looks back at
  open cell (cx, cy) is visible iff the player is on the open side of that
  cell's own integer boundary -- a compare of the player's cell coordinate.

  Painter order stays free: the sort key is the L1 cell distance of the wall
  cell, an integer 1..7, so faces are bucket-sorted as they are produced.

CONSERVATISM (why SLACK exists)
  Q6.10 is one bit coarser than the 7.9 slope tables this replaces, so the
  seed carries SLACK = 8 (0.008 cell) of deliberate widening on all three
  planes.  Without it a cell sitting EXACTLY on a plane -- which happens
  at grid-aligned sub-positions on round headings, where free.py's float
  test returns exactly 0.0 and keeps the cell -- can round to "outside",
  and because the flood prunes there, a whole corridor behind it
  disappears.  Swept over 37392 states against free.py:

      SLACK   states with a MISSING drawn face   states with an extra cell
        0                85  (0.23%)                     26
        4                 0                            890
        8                 0                            937   <- shipped
       32                 0                           2166

  8 costs 0.003 extra cells and 0.003 extra faces per frame on average
  and leaves the fixed-point march a strict superset of the float one.
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import gentab                                                  # noqa: E402

N_ANGLES = 72
KHALF = math.tan(math.radians(30.0))        # CX / FOCAL_H, 60 degree FOV
ZNEAR = 0.08                                # free.py's march near plane
R_MAX = 6                                   # faces are filed at L1 1..R_MAX+1;
                                            # what a room costs, and why 4x4
                                            # fits inside this, is measured by
                                            # engine2/tools/roomcost.py and
                                            # written up in tools/world.py
VBITS = 10                                  # view fixed point, Q6.10
VONE = 1 << VBITS
ZNEAR_M = int(round(ZNEAR * VONE))          # 82
SLACK = 8                                   # frustum widening, Q6.10; see above
FBITS = VBITS                               # kept for check_model's banner

MAZE_W = MAZE_H = 16

# cell codes in the SOLID array
OPEN, WALL, DOORC = 0, 1, 2                 # DOORC = closed door (solid)
DOORMOV = 3                                 # ...and one part way through its
                                            # run: SEE-THROUGH, so the flood
                                            # goes past it and the room beyond
                                            # is marched, but still FILED as a
                                            # face so the door is drawn, and
                                            # still non-zero so coll_free keeps
                                            # the player out.  march.asm reads
                                            # it as (cell-1) < 2 == opaque.


def opaque(cell):
    """march.asm's own test, `dec a / cp 2 / jr c`: a cell stops the
    flood iff it is WALL or a SHUT door.  DOORMOV does not."""
    return cell in (WALL, DOORC)

# face directions: outward normal of the face
NORTH, EAST, SOUTH, WEST = 0, 1, 2, 3


def set_fbits(n):
    """Precision sweeps are gone: the march now shares the projector's Q6.10."""
    if n != VBITS:
        raise ValueError("the march is Q6.10 by construction")


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def _rnd(v):
    return int(math.floor(v + 0.5))


# --------------------------------------------------- per-heading constants --
def basis_table():
    """[72][4] rgtx rgty fwdx fwdy, Q6.10 -- gentab's BASIS, verbatim."""
    b = gentab.t_basis()
    return [[s16(v) for v in b[4 * a:4 * a + 4]] for a in range(N_ANGLES)]


def lrstep_table():
    """[72][4] dLi dLj dRi dRj, Q6.10 -- one rounding each, from the BASIS
    integers so the L/R recurrence stays consistent with the xv/zv one."""
    out = []
    for rgtx, rgty, fwdx, fwdy in BASIS:
        kx, ky = KHALF * fwdx, KHALF * fwdy
        out.append([s16(rgtx + _rnd(kx)), s16(rgty + _rnd(ky)),
                    s16(_rnd(kx) - rgtx), s16(_rnd(ky) - rgty)])
    return out


BASIS = basis_table()
LRSTEP = lrstep_table()


def mulf(v, f):
    """(v * f) >> 8, v signed, f = 0..255 -- exactly project.asm's ps_mulf:
    the magnitude is shifted, so the result truncates TOWARDS ZERO."""
    p = (abs(v) * f) >> 8
    return -p if v < 0 else p


def kq(v):
    """KHALF * v by three arithmetic shifts: 1/2 + 1/16 + 1/64 = 0.578125.

    Used ONCE per frame, to seed L and R; the per-step constants are the
    exactly-rounded ROM ones, so this 0.13% error never accumulates.
    """
    return s16((v >> 1) + (v >> 4) + (v >> 6))


class Seed:
    """Everything march_setup computes before the flood starts."""

    def __init__(self, px_fx, py_fx, a_idx):
        a = a_idx % N_ANGLES
        self.rgtx, self.rgty, self.fwdx, self.fwdy = BASIS[a]
        self.dLi, self.dLj, self.dRi, self.dRj = LRSTEP[a]
        fx, fy = px_fx & 0xFF, py_fx & 0xFF
        xv0 = s16(mulf(self.rgtx, fx) + mulf(self.rgty, fy))
        z0 = s16(mulf(self.fwdx, fx) + mulf(self.fwdy, fy))
        self.xv = s16(-xv0)                 # view coords of corner (pcx, pcy)
        self.zv = s16(-z0)
        q = kq(self.zv)
        self.L = s16(self.xv + q + max(0, self.dLi) + max(0, self.dLj) + SLACK)
        self.R = s16(q - self.xv + max(0, self.dRi) + max(0, self.dRj) + SLACK)
        self.CZ = s16(max(0, self.fwdx) + max(0, self.fwdy) - ZNEAR_M + SLACK)


# ------------------------------------------------------------- marching ----
def march(solid, px_fx, py_fx, a_idx, push_opaque=False):
    """-> dict(visited, seen, faces, fviews, buckets)

    push_opaque=True reproduces free.py's traversal exactly, including its
    cells_visited counter.  The Z80 uses False: an opaque neighbour is
    marked but never pushed, since popping it only to reject it costs time
    and cannot change the seen set or the face list.  Both settings must
    produce identical `seen` and `faces` -- check_model.py asserts it.

    faces are (wx, wy, dir, is_door, key) already backface-culled, and
    `buckets[k]` is the painter-order group at L1 distance k (drawn 7 -> 1).
    fviews[n] is the VIEW-SPACE record the Z80 files for faces[n]:
    (xa, za, xb, zb) Q6.10, endpoint A first, ready for the projector.
    """
    s = Seed(px_fx, py_fx, a_idx)
    pcx, pcy = px_fx >> 8, py_fx >> 8

    mark = bytearray(256)
    stack = [(pcx, pcy, s.xv, s.zv, s.L, s.R)]
    mark[pcy * 16 + pcx] = 1
    visited = 0
    seen = []
    # ONE BUCKET PER L1 DISTANCE 0..R_MAX+1, sized from R_MAX rather than
    # written down: march.asm's bucket PAGES are sized from the same
    # number through gen_march.py, and a model carrying its own copy of a
    # bound is how the map and the machine come to disagree about how far
    # the world reaches.
    nb = R_MAX + 2
    buckets = [[] for _ in range(nb)]
    views = [[] for _ in range(nb)]
    # ...and the DEEPEST the flood stack ever gets.  march.asm's stack is
    # a fixed MSTKTOP-MSTKBOT and overrunning it writes straight into the
    # face buckets, which is the worst class of bug this engine has had.
    # Reporting the bound lets the asm be sized from a measurement rather
    # than from the area of the L1 ball, which is wildly pessimistic.
    maxdepth = 1

    while stack:
        maxdepth = max(maxdepth, len(stack))
        cx, cy, xv, zv, L, R = stack.pop()
        visited += 1
        if abs(cx - pcx) + abs(cy - pcy) > R_MAX:
            continue
        if (cx, cy) != (pcx, pcy):
            if opaque(solid[cy * 16 + cx]):
                continue
            if L < 0:                       # left plane
                continue
            if R < 0:                       # right plane
                continue
            if s16(zv + s.CZ) < 0:          # near plane
                continue
        seen.append((cx, cy))

        # the cell's four corners, in view space.  c[0] = (cx, cy) itself.
        c = ((xv, zv),
             (s16(xv + s.rgtx), s16(zv + s.fwdx)),                  # +i
             (s16(xv + s.rgty), s16(zv + s.fwdy)),                  # +j
             (s16(xv + s.rgtx + s.rgty), s16(zv + s.fwdx + s.fwdy)))

        # faces of this open cell's solid neighbours, backface-culled.
        # dx,dy = neighbour offset; the face is the neighbour's side that
        # looks back at us; ea,eb index the corner pair that face_endpoints()
        # names A and B.
        for dx, dy, fdir, ea, eb in ((0, -1, SOUTH, 0, 1), (0, 1, NORTH, 2, 3),
                                     (-1, 0, EAST, 0, 2), (1, 0, WEST, 1, 3)):
            wx, wy = cx + dx, cy + dy
            cell = solid[wy * 16 + wx]
            if cell == OPEN:
                continue
            if fdir == SOUTH:                       # plane y = cy, need py > cy
                if py_fx <= (cy << 8):
                    continue
            elif fdir == NORTH:                     # plane y = cy+1, py < cy+1
                if py_fx >= ((cy + 1) << 8):
                    continue
            elif fdir == EAST:                      # plane x = cx, px > cx
                if px_fx <= (cx << 8):
                    continue
            else:                                   # WEST, plane x = cx+1
                if px_fx >= ((cx + 1) << 8):
                    continue
            key = abs(wx - pcx) + abs(wy - pcy)
            # 2 SHUT and 3 MOVING are both doors -- march.asm's
            # `cp 2 / jr c` says wall below 2, door at or above it --
            # and MOVING carries bit 1 as well, which is what makes
            # rastcol.asm draw it last and on top of the room behind it.
            buckets[key].append((wx, wy, fdir,
                                 3 if cell == DOORMOV
                                 else (1 if cell == DOORC else 0)))
            views[key].append(c[ea] + c[eb])

        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            i = (cy + dy) * 16 + (cx + dx)
            if mark[i]:
                continue
            mark[i] = 1
            if not push_opaque and opaque(solid[i]):
                continue
            if dx:
                st = (s.rgtx, s.fwdx, s.dLi, s.dRi) if dx > 0 else \
                     (-s.rgtx, -s.fwdx, -s.dLi, -s.dRi)
            else:
                st = (s.rgty, s.fwdy, s.dLj, s.dRj) if dy > 0 else \
                     (-s.rgty, -s.fwdy, -s.dLj, -s.dRj)
            stack.append((cx + dx, cy + dy, s16(xv + st[0]), s16(zv + st[1]),
                          s16(L + st[2]), s16(R + st[3])))

    faces = []
    fviews = []
    # BACK TO FRONT, and the far end is R_MAX+1 rather than a written-down
    # 7.  Leaving it at 7 while R_MAX grew would silently drop the whole
    # farthest bucket -- the walls that the bigger rooms exist to show.
    for k in range(R_MAX + 1, 0, -1):
        for f, v in zip(buckets[k], views[k]):
            faces.append(f + (k,))
            fviews.append(v)
    return {"visited": visited, "seen": seen, "faces": faces,
            "fviews": fviews, "buckets": buckets, "maxdepth": maxdepth}


def solid_from_grid(grid, doors=None):
    """world.py grid -> the 256-byte SOLID array the Z80 reads."""
    doors = doors or {}
    a = bytearray(256)
    for y in range(16):
        for x in range(16):
            c = grid[y][x]
            if c == 1:
                a[y * 16 + x] = WALL
            elif c == 2:
                a[y * 16 + x] = OPEN if doors.get((x, y), 0) > 0 else DOORC
            else:
                a[y * 16 + x] = OPEN
    return a
