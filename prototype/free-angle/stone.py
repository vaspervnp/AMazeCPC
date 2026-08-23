"""Preview: what would large square stone blocks look like on the walls?

Draws each wall face twice -- once whole in a dark "mortar" pen, then each
stone inset by a margin on top -- which is exactly how it would work on the
Z80, because the gap between two filled quads IS the mortar line.

Two decompositions, with very different costs on real hardware:

  COURSES (horizontal joints)  a wall face split into N bands stacked
      vertically.  At any fixed screen x the projection of wall height is
      LINEAR, so a course boundary is just a linear interpolation between the
      face's own top and bottom edge y values.  The rasteriser already walks
      scanlines, so this is nearly free.

  BLOCKS (vertical joints)  splitting each course along the wall as well.
      A vertical line on a vertical wall projects to a vertical screen line,
      so the joint sits at a FIXED screen x for the whole face -- but every
      horizontal run then has to be split there, and that is per scanline,
      which is where the money goes.

    python3 stone.py            # both, side by side
"""

import math
import os
import sys

import geom
import world
import free
import frender
import vpsweep

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# Pen assignments for the stone look.  Mortar is one ramp step darker than the
# darkest stone at that depth, so joints read as recessed at every distance.
N_COURSES = 3          # stone rows per wall cell
N_BLOCKS = 2           # stones across per wall cell
MARGIN_X = 1           # mortar half-width, in bytes
MARGIN_Y = 1           # mortar half-height, in scanlines


def sub_quad(wx, wy, fd, px, py, fwd, rgt, t0, t1, v0, v1):
    """Project the patch of a wall face between wall parameters t0..t1
    (along the wall) and v0..v1 (up it).  Returns quad points or None."""
    (ax, ay), (bx, by), n = free.face_endpoints(wx, wy, fd)
    if (px - ax) * n[0] + (py - ay) * n[1] <= 0.0:
        return None                                   # backface

    # Sub-segment endpoints in world space, then into view space.
    p0 = (ax + (bx - ax) * t0, ay + (by - ay) * t0)
    p1 = (ax + (bx - ax) * t1, ay + (by - ay) * t1)
    a = free.to_view(p0[0], p0[1], px, py, fwd, rgt)
    b = free.to_view(p1[0], p1[1], px, py, fwd, rgt)
    cl = free.clip_segment(a, b)
    if cl is None:
        return None
    a, b = cl

    sa = free.FOCAL_V / a[1]
    sb = free.FOCAL_V / b[1]
    xa = geom.CX + a[0] * (free.FOCAL_H / a[1])
    xb = geom.CX + b[0] * (free.FOCAL_H / b[1])
    if xa > xb:
        a, b = b, a
        sa, sb = sb, sa
        xa, xb = xb, xa
    if xb - xa < 1e-6:
        return None

    # Wall height v maps LINEARLY to screen y at a fixed x, so a course
    # boundary is a straight interpolation of the face's own edges.
    def ys(s, v):
        return geom.CY - (v - 0.5) * s

    dist = math.hypot(0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))
    return [(xa, ys(sa, v1)), (xb, ys(sb, v1)),
            (xb, ys(sb, v0)), (xa, ys(sa, v0))], dist


def render(grid, px, py, a_idx, blocks=True):
    buf = frender.new_frame()
    for y0, y1, pen in free.background_bands():
        for y in range(y0, y1):
            frender._row(buf, y, geom.VP_BX, geom.VP_BW // 2, pen)

    fwd, rgt = free.basis(a_idx)
    seen, cand, visited = free.march(grid, px, py, a_idx, {})
    pcx, pcy = int(math.floor(px)), int(math.floor(py))

    faces = []
    for wx, wy, fd, is_door in cand:
        faces.append((abs(wx - pcx) + abs(wy - pcy), wx, wy, fd, is_door))
    faces.sort(key=lambda t: -t[0])            # back to front

    nb = N_BLOCKS if blocks else 1
    for _key, wx, wy, fd, is_door in faces:
        whole = sub_quad(wx, wy, fd, px, py, fwd, rgt, 0.0, 1.0, 0.0, 1.0)
        if whole is None:
            continue
        pts, dist = whole
        depth = max(1, min(6, int(dist + 0.5)))
        ns = fd in (free.NORTH, free.SOUTH)
        stone = world.wall_pen(depth, ns, is_door)
        mortar = world.wall_pen(min(6, depth + 2), ns, is_door)

        g = free.rasterise(pts)                # the whole face, in mortar
        if g is not None:
            _blit(buf, g, mortar)

        for c in range(N_COURSES):             # then each stone on top
            v0 = c / N_COURSES
            v1 = (c + 1) / N_COURSES
            for k in range(nb):
                t0 = k / nb
                t1 = (k + 1) / nb
                sq = sub_quad(wx, wy, fd, px, py, fwd, rgt, t0, t1, v0, v1)
                if sq is None:
                    continue
                spts, _ = sq
                inset = inset_quad(spts)
                if inset is None:
                    continue
                gi = free.rasterise(inset)
                if gi is not None:
                    _blit(buf, gi, stone)
    return buf


def _blit(buf, g, pen):
    from geom import Rect
    if isinstance(g, Rect):
        for i in range(g.h):
            frender._row(buf, g.y0 + i, g.xb, g.npush, pen)
    else:
        for i, (xb, n) in enumerate(g.lines):
            frender._row(buf, g.y0 + i, xb, n, pen)


def inset_quad(pts):
    """Shrink a quad by the mortar margin; None if nothing survives."""
    (x0, yt0), (x1, yt1), (x1b, yb1), (x0b, yb0) = pts
    x0 += MARGIN_X
    x1 -= MARGIN_X
    if x1 - x0 < 0.5:
        return None
    return [(x0, yt0 + MARGIN_Y), (x1, yt1 + MARGIN_Y),
            (x1, yb1 - MARGIN_Y), (x0, yb0 - MARGIN_Y)]


def main():
    os.makedirs(OUT, exist_ok=True)
    grid, _, _ = world.load_maze()
    vpsweep.set_viewport(44, 96)
    free.set_focal(geom.CX / math.tan(math.radians(30)), 96)

    shots = [
        ("corridor", 5.5, 13.5, 0),
        ("turn10", 5.5, 13.5, 2),
        ("angled", 5.5, 13.5, 5),
        ("junction", 7.5, 7.5, 18),
    ]
    for name, x, y, a in shots:
        for tag, blocks in (("flat", None), ("courses", False), ("stone", True)):
            p = os.path.join(OUT, f"stone_{name}_{tag}.png")
            if tag == "flat":
                frender.render_png(grid, x, y, a, p, sx=6, sy=5)
                continue
            buf = render(grid, x, y, a, blocks=blocks)
            frender.crop_viewport(buf, 6, 5).save(p)
        print("wrote", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
