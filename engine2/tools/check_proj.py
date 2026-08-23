"""Compare the fixed-point model (projmodel) against the float reference
(prototype/free-angle/free.py:project_face) over a spread of faces.

Reports the maximum screen-coordinate discrepancy in PIXELS: x in half-byte
units (= one mode-0 pixel), y in scanlines.
"""

import math
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.join(_ROOT, "prototype", "free-angle"))

import geom                                                # noqa: E402
import gentab                                              # noqa: E402
import projmodel as pm                                     # noqa: E402
import free                                                # noqa: E402

# Point the float reference at the engine2 viewport.  MUST come after
# `import free`, which calls geom.configure(0) and would undo it.
# The viewport comes from engine2/src/vpcfg.inc, via gentab -- NOT from a
# copy pasted here, which would silently disagree with the tables.
geom.VP_BX, geom.VP_BW = gentab.VP_BX, gentab.VP_BW
geom.VP_Y, geom.VP_H = gentab.VP_Y, gentab.VP_H
geom.VP_PW = gentab.VP_PW
geom.CX, geom.CY = gentab.CX, gentab.CY

geom.ZNEAR = 0.125
free.ZNEAR = 0.125
free.set_focal(pm.gentab.FOCAL_H, pm.gentab.FOCAL_V)


def ref(wx, wy, fd, px, py, ang):
    fwd, rgt = free.basis(ang)
    r = free.project_face(wx, wy, fd, px, py, fwd, rgt)
    if r is None:
        return None
    pts, _ = r
    # pts = [(xa,ytop_a),(xb,ytop_b),(xb,ybot_b),(xa,ybot_a)]
    return (pts[0][0], pts[0][1], pts[3][1], pts[1][0], pts[1][1], pts[2][1])


def got(wx, wy, fd, px, py, ang):
    fr = pm.Frame(px, py, ang)
    (ax, ay), (bx, by), _ = pm.face_endpoints(wx, wy, fd)
    i0, j0 = ax - fr.ipx, ay - fr.ipy
    i1, j1 = bx - fr.ipx, by - fr.ipy
    if max(abs(i0), abs(j0), abs(i1), abs(j1)) > 8:
        return "range"
    # FULL-PRECISION screen space: proj_face emits a byte-rounded record
    # (see projmodel.pack_quad) and the question here is the accuracy of
    # the projection itself, not of that rounding.
    r = pm.project_face_ij_screen(fr, i0, j0, i1, j1, fd)
    if r is None:
        return None
    return tuple(v / 16.0 for v in pm.screen_xy(r))


def main():
    rnd = random.Random(20260819)
    cases = []
    # A deterministic spread: every face direction, a range of depths and
    # lateral offsets, plus random ones.
    for fd in range(4):
        for f in (1, 2, 3, 5):
            for l in (-2, -1, 0, 1, 2):
                cases.append((l, -f, fd, 0.5, 0.5, 0))
                cases.append((l, -f, fd, 0.5, 0.5, 5))
    # Random faces inside the marcher's legal domain: the march is bounded by
    # R_MAX = 6 in L1, so a wall cell never sits further than 7 cells away and
    # z stays below the 8-cell end of HTAB/PROJ.
    n = 0
    while n < 20000:
        wx, wy = rnd.randint(-7, 7), rnd.randint(-7, 7)
        if abs(wx) + abs(wy) > 7:
            continue
        n += 1
        cases.append((wx, wy, rnd.randint(0, 3),
                      rnd.uniform(0.02, 0.98), rnd.uniform(0.02, 0.98),
                      rnd.randrange(72)))

    worst = {"x": (0.0, None), "y": (0.0, None),
             "xc": (0.0, None), "yc": (0.0, None)}
    nboth = ndisagree = 0
    for l, f, fd, px, py, ang in cases:
        wx, wy = l, f
        r = ref(wx, wy, fd, px, py, ang)
        g = got(wx, wy, fd, px, py, ang)
        if g == "range":
            continue
        if (r is None) != (g is None):
            ndisagree += 1
            continue
        if r is None:
            continue
        nboth += 1
        for k, idx, lo, hi in (("x", (0, 3), 0.0, 96.0),
                               ("y", (1, 2, 4, 5), 0.0, 128.0)):
            for i in idx:
                e = abs(r[i] - g[i])
                rec = (wx, wy, fd, px, py, ang, i, r[i], g[i])
                if e > worst[k][0]:
                    worst[k] = (e, rec)
                # what the rasteriser actually sees: everything outside the
                # viewport is clamped away before a single byte is written.
                ec = abs(min(max(r[i], lo), hi) - min(max(g[i], lo), hi))
                if ec > worst[k + "c"][0]:
                    worst[k + "c"] = (ec, rec)

    print(f"faces compared (both accepted): {nboth}")
    print(f"accept/reject disagreements  : {ndisagree}"
          f"   ({100.0*ndisagree/len(cases):.2f}% of cases)")
    for k, label in (("x", "screen x, raw            "),
                     ("xc", "screen x, clamped to view"),
                     ("y", "screen y, raw            "),
                     ("yc", "screen y, clamped to view")):
        e, w = worst[k]
        unit = "px (half-byte)" if k[0] == "x" else "scanlines"
        print(f"max err {label}: {e:7.3f} {unit}", end="")
        if w:
            print(f"   [wx={w[0]} wy={w[1]} dir={w[2]} p=({w[3]:.4f},"
                  f"{w[4]:.4f}) ang={w[5]} ref={w[7]:.2f} got={w[8]:.2f}]")
        else:
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
