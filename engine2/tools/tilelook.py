"""DOES THE FAKE-CHARACTER-MODE TILE PICTURE HOLD STILL?

Renders the same reference masonry texture two ways off the REAL march +
project output:

  EXACT   per-pixel perspective (u,v), per-pixel wall half-height h.
          This is what the C64 reference looks like; it is the target.

  TILE    the proposal's dispatch key: ONE h per 8-pixel tile column
          (Bresenham gives the vertical scale per tile column), and u
          linear between the perspective-correct u0,u1 at the tile
          column's two edges.  Whole 8x8 cells, screen-aligned grid,
          painter order, no clipping of a blit to a face edge.

then walks the player the way game.asm walks him -- 24/256 of a cell per
frame, 5 degrees per turn frame -- and asks how much of the picture
changes for reasons that are NOT the motion.

    python3 engine2/tools/tilelook.py static [n]
    python3 engine2/tools/tilelook.py motion [n]
    python3 engine2/tools/tilelook.py stairs [n]
"""

import math
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import tilecount as tc                                        # noqa: E402
import pacescan                                               # noqa: E402

VP_PW, VP_H = tc.VP_PW, tc.VP_H
CXH, CYH, FOCAL_V, FOCAL_H = tc.CXH, tc.CYH, tc.FOCAL_V, tc.FOCAL_H
ZNEAR = tc.ZNEAR
TW, TH, NTX, NTY = tc.TW, tc.TH, tc.NTX, tc.NTY


# ------------------------------------------------------------------ exact
def render_exact(faces):
    return tc.render(faces)


# ------------------------------------------------------------------- tile
def face_col(xa, za, xb, zb, s):
    """-> (t, z) at screen offset s from the centre, or None."""
    dx, dz = xb - xa, zb - za
    den = FOCAL_H * dx - s * dz
    if den == 0.0:
        return None
    t = (s * za - FOCAL_H * xa) / den
    if t < 0.0 or t > 1.0:
        return None
    z = za + t * dz
    if z < ZNEAR:
        return None
    return t, z


def render_tile(faces, cellerr=None):
    """The proposal's renderer, with an INFINITE tile set (so no memory
    truncation and no id quantisation) AND every generosity available:
    the tile column's h and its two u endpoints are taken over the part
    of the column that is ACTUALLY ON THE FACE, and nothing is painted
    off the face.  That is strictly better than the proposal's stated
    key, which samples at the tile column's own edges.

    The only approximations left are the two the 8x8 tile forces:
    h constant across the 8-pixel column, and u linear across it."""
    buf = [[0] * VP_PW for _ in range(VP_H)]
    for (xa, za, xb, zb) in faces:
        for tx in range(NTX):
            xl, xr = tx * TW, tx * TW + TW
            on = [ix for ix in range(xl, xr)
                  if face_col(xa, za, xb, zb, ix + 0.5 - CXH)]
            if not on:
                continue
            sl, sr = on[0], on[-1]
            a = face_col(xa, za, xb, zb, sl + 0.5 - CXH)
            b = face_col(xa, za, xb, zb, sr + 0.5 - CXH)
            c = face_col(xa, za, xb, zb, (sl + sr) * 0.5 + 0.5 - CXH)
            if c is None:
                c = a
            u0, u1 = a[0], b[0]
            h = 0.5 * FOCAL_V / c[1]
            y0 = CYH - h
            y1 = CYH + h
            lo = max(0, int(math.floor(y0 + 0.5)))
            hi = min(VP_H, int(math.floor(y1 + 0.5)))
            inv = 1.0 / (2.0 * h)
            span = max(sr - sl, 1)
            for ix in on:
                u = u0 + (ix - sl) / span * (u1 - u0)
                if u < 0.0 or u >= 1.0:
                    continue
                for iy in range(lo, hi):
                    v = (iy + 0.5 - y0) * inv
                    if v < 0.0 or v >= 1.0:
                        continue
                    buf[iy][ix] = 2 if tc.mortar(u, v) else 1
    return buf


def render_tile_exactedge(faces):
    """As render_tile, but the wall SILHOUETTE is per-pixel exact -- i.e.
    pretend the edge tiles carry the true sloped boundary, which is what
    tilecount.py's 4857 edge tiles actually are.  Only the TEXTURE is
    tile-quantised: v from the column's single h, u linear across it.
    This isolates the texture defect from the silhouette defect."""
    buf = [[0] * VP_PW for _ in range(VP_H)]
    for (xa, za, xb, zb) in faces:
        for tx in range(NTX):
            xl, xr = tx * TW, tx * TW + TW
            cols = []
            for ix in range(xl, xr):
                c = face_col(xa, za, xb, zb, ix + 0.5 - CXH)
                if c:
                    cols.append((ix, c))
            if not cols:
                continue
            sl, sr = cols[0][0], cols[-1][0]
            u0 = cols[0][1][0]
            u1 = cols[-1][1][0]
            zc = cols[len(cols) // 2][1][1]
            hq = 0.5 * FOCAL_V / zc            # the TILE's single h
            y0q = CYH - hq
            invq = 1.0 / (2.0 * hq)
            span = max(sr - sl, 1)
            for ix, (t, z) in cols:
                u = u0 + (ix - sl) / span * (u1 - u0)
                if u < 0.0 or u >= 1.0:
                    continue
                h = 0.5 * FOCAL_V / z          # TRUE h, for the edge only
                lo = max(0, int(math.floor(CYH - h + 0.5)))
                hi = min(VP_H, int(math.floor(CYH + h + 0.5)))
                for iy in range(lo, hi):
                    v = (iy + 0.5 - y0q) * invq
                    if v < 0.0:
                        v = 0.0
                    elif v >= 1.0:
                        v = 0.9999999
                    buf[iy][ix] = 2 if tc.mortar(u, v) else 1
    return buf


def diff(a, b):
    n = 0
    for y in range(VP_H):
        ra, rb = a[y], b[y]
        for x in range(VP_PW):
            if ra[x] != rb[x]:
                n += 1
    return n


def changed(a, b):
    """set of pixels that differ, as a flat frozenset of indices"""
    s = set()
    for y in range(VP_H):
        ra, rb = a[y], b[y]
        for x in range(VP_PW):
            if ra[x] != rb[x]:
                s.add(y * VP_PW + x)
    return s


def wallpix(a):
    return sum(1 for y in range(VP_H) for x in range(VP_PW) if a[y][x])


# --------------------------------------------------------------- movement
def steptab(a):
    """game.asm STEPTAB: int() of 24*cos/sin at 5-degree steps."""
    STEP = 24
    dx = int(STEP * math.cos(a * 5.0 * math.pi / 180.0))
    dy = int(STEP * math.sin(a * 5.0 * math.pi / 180.0))
    return dx, dy


def walk(solid, px, py, a, n):
    """n forward steps, stopping at a wall.  -> list of (px,py,a)"""
    out = [(px, py, a)]
    for _ in range(n):
        dx, dy = steptab(a)
        nx, ny = px + dx, py + dy
        if not pacescan.coll_free(solid, nx, py):
            nx = px
        if not pacescan.coll_free(solid, nx, ny):
            ny = py
        if (nx, ny) == (px, py):
            break
        px, py = nx, ny
        out.append((px, py, a))
    return out


def turn(px, py, a, n):
    return [(px, py, (a + i) % 72) for i in range(n)]


# ------------------------------------------------------------------ tasks
def task_static(n):
    solid, pos = pacescan.positions()
    rnd = random.Random(20260821)
    tot_e = tot_t = tot_d = tot_w = 0
    worst = (0.0, None)
    for _ in range(n):
        px, py = rnd.choice(pos)
        a = rnd.randrange(72)
        faces = tc.quads_and_faces(solid, px, py, a)
        e = render_exact(faces)
        t = render_tile(faces)
        w = wallpix(e)
        d = diff(e, t)
        tot_w += w
        tot_d += d
        tot_e += sum(1 for y in range(VP_H) for x in range(VP_PW)
                     if e[y][x] == 2)
        tot_t += sum(1 for y in range(VP_H) for x in range(VP_PW)
                     if t[y][x] == 2)
        if w and d / w > worst[0]:
            worst = (d / w, (px, py, a, d, w))
    print(f"states                       {n}")
    print(f"wall pixels (exact)          {tot_w}")
    print(f"pixels TILE gets wrong       {tot_d}  "
          f"= {tot_d / max(tot_w,1)*100:.1f}% of wall area")
    print(f"mortar pixels exact / tile   {tot_e} / {tot_t}")
    print(f"WORST state                  {worst[0]*100:.1f}%  at {worst[1]}")


def task_motion(n):
    """The number that matters.  For each consecutive pair of frames,
    how many pixels change in EXACT (that is honest motion) and how many
    change in TILE.  The excess is texture that is moving when the wall
    it is painted on is not."""
    solid, pos = pacescan.positions()
    rnd = random.Random(20260821)
    rows = []
    for kind in ("walk", "turn"):
        te = tt = 0
        tsp = 0
        pairs = 0
        worst = (0, None)
        for _ in range(n):
            px, py = rnd.choice(pos)
            a = rnd.randrange(72)
            seq = walk(solid, px, py, a, 8) if kind == "walk" \
                else turn(px, py, a, 8)
            pe = pt = None
            for (qx, qy, qa) in seq:
                faces = tc.quads_and_faces(solid, qx, qy, qa)
                e = render_exact(faces)
                t = render_tile(faces)
                if pe is not None:
                    ce = changed(pe, e)
                    ct = changed(pt, t)
                    te += len(ce)
                    tt += len(ct)
                    sp = len(ct - ce)
                    tsp += sp
                    pairs += 1
                    if sp > worst[0]:
                        worst = (sp, (qx, qy, qa))
                pe, pt = e, t
        print(f"--- {kind} ({pairs} frame pairs, 8-frame sequences)")
        print(f"  pixels changing per frame, EXACT   {te/pairs:8.1f}")
        print(f"  pixels changing per frame, TILE    {tt/pairs:8.1f}"
              f"   ({tt/max(te,1):.2f}x)")
        print(f"  TILE-only changes (crawl) per frame{tsp/pairs:8.1f}"
              f"   = {tsp/max(tt,1)*100:.0f}% of all TILE change")
        print(f"  worst frame pair                   {worst[0]} px at {worst[1]}")
        rows.append((kind, te / pairs, tt / pairs, tsp / pairs))
    return rows


def task_stairs(n):
    """How big is the silhouette staircase?  For every face, walk the
    per-tile-column h and report the jump in the wall's top edge between
    adjacent tile columns -- that is the riser of the staircase the tile
    renderer draws where the true edge is a straight converging line.
    Compare with the current renderer, which quantises per BYTE = 2 px."""
    solid, pos = pacescan.positions()
    rnd = random.Random(20260821)
    hist = {}
    hist2 = {}
    worst = (0, None)
    tot = tot2 = 0
    cnt = cnt2 = 0
    for _ in range(n):
        px, py = rnd.choice(pos)
        a = rnd.randrange(72)
        faces = tc.quads_and_faces(solid, px, py, a)
        for (xa, za, xb, zb) in faces:
            prev = prev2 = None
            for tx in range(NTX):
                c = face_col(xa, za, xb, zb, (tx * TW + TW * 0.5) - CXH)
                y = None if c is None else CYH - 0.5 * FOCAL_V / c[1]
                if y is not None and prev is not None:
                    d = int(round(abs(y - prev)))
                    hist[d] = hist.get(d, 0) + 1
                    tot += d
                    cnt += 1
                    if d > worst[0]:
                        worst = (d, (px, py, a))
                prev = y
            for bx in range(VP_PW // 2):
                c = face_col(xa, za, xb, zb, (bx * 2 + 1.0) - CXH)
                y = None if c is None else CYH - 0.5 * FOCAL_V / c[1]
                if y is not None and prev2 is not None:
                    d = int(round(abs(y - prev2)))
                    hist2[d] = hist2.get(d, 0) + 1
                    tot2 += d
                    cnt2 += 1
                prev2 = y
    print(f"TILE  (8-px columns): mean riser {tot/max(cnt,1):.2f} px, "
          f"worst {worst[0]} px at {worst[1]}")
    print("   riser histogram", dict(sorted(hist.items())[:14]))
    print(f"TODAY (2-px columns): mean riser {tot2/max(cnt2,1):.2f} px")
    print("   riser histogram", dict(sorted(hist2.items())[:14]))


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "static"
    nn = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    {"static": task_static, "motion": task_motion,
     "stairs": task_stairs}[what](nn)
