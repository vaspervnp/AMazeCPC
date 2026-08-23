"""HOW MANY TILE BLITS DOES THE WORST FRAME NEED?

Geometry only -- no texture, no bitmaps -- so it runs fast enough to
scan a large sample.  A painter-order tile renderer must blit one whole
8x8 cell for every (face, cell) pair the face touches, because a tile
blit cannot be clipped to a face edge: it always writes all 32 bytes.
That count, not the byte-coverage count wallarea.py reports, is what
multiplies the per-tile cost.

    python3 engine2/tools/tileblits.py [nstates|all] [jobs]
"""

import math
import multiprocessing as mp
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

VP_PW = 88
VP_H = 96
CXH = 44.0
CYH = 48.0
FOCAL_V = 96.0
ZNEAR = 0.125
TW = 8
TH = 8

_W = {}


def _init():
    import marchmodel as mm
    import projmodel as pm
    import pacescan
    solid, pos = pacescan.positions()
    _W["mm"] = mm
    _W["pm"] = pm
    _W["solid"] = solid
    _W["pos"] = pos
    _W["fh"] = float(pm.gentab.FOCAL_H)


def _one(px, py, a):
    mm, pm, solid, FH = _W["mm"], _W["pm"], _W["solid"], _W["fh"]
    r = mm.march(solid, px, py, a)
    ipx, ipy = px >> 8, py >> 8
    blits = 0
    cols = 0
    cov = set()
    nf = 0
    for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
        (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
        if pm.project_face(v[0], v[1], v[2], v[3],
                           ax - ipx, ay - ipy, fd) is None:
            continue
        nf += 1
        xa, za = v[0] / 1024.0, v[1] / 1024.0
        xb, zb = v[2] / 1024.0, v[3] / 1024.0
        dx, dz = xb - xa, zb - za
        seen = set()
        tcols = set()
        for ix in range(VP_PW):
            s = ix + 0.5 - CXH
            den = FH * dx - s * dz
            if den == 0.0:
                continue
            t = (s * za - FH * xa) / den
            if t < 0.0 or t > 1.0:
                continue
            z = za + t * dz
            if z < ZNEAR:
                continue
            h = 0.5 * FOCAL_V / z
            lo = max(0, int(math.floor(CYH - h + 0.5)))
            hi = min(VP_H, int(math.floor(CYH + h + 0.5)))
            if hi <= lo:
                continue
            tx = ix // TW
            tcols.add(tx)
            for ty in range(lo // TH, (hi - 1) // TH + 1):
                seen.add((tx, ty))
                cov.add((tx, ty))
        blits += len(seen)
        cols += len(tcols)
    return blits, cols, len(cov), nf


def _chunk(arg):
    lo, hi, step, seed = arg
    pos = _W["pos"]
    best = (0, None)
    bestc = (0, None)
    tot = totc = 0
    n = 0
    rnd = random.Random(seed)
    for i in range(lo, hi, step):
        px, py = pos[i]
        for a in range(72):
            if rnd.random() > _W["frac"]:
                continue
            b, c, cv, nf = _one(px, py, a)
            tot += b
            totc += c
            n += 1
            if b > best[0]:
                best = (b, (px, py, a, nf, c, cv))
            if c > bestc[0]:
                bestc = (c, (px, py, a, nf, b))
    return tot, totc, n, best, bestc


def _boot(frac):
    _init()
    _W["frac"] = frac


def main():
    n = sys.argv[1] if len(sys.argv) > 1 else "20000"
    jobs = int(sys.argv[2]) if len(sys.argv) > 2 else os.cpu_count()
    _init()
    pos = _W["pos"]
    total = len(pos) * 72
    frac = 1.0 if n == "all" else min(1.0, int(n) / total)
    print(f"{len(pos)} positions x 72 headings = {total} states; "
          f"sampling {frac * 100:.3f}%")

    step = 1
    bounds = []
    per = max(1, len(pos) // (jobs * 4))
    for lo in range(0, len(pos), per):
        bounds.append((lo, min(lo + per, len(pos)), step, 20260821 + lo))

    with mp.Pool(jobs, initializer=_boot, initargs=(frac,)) as p:
        res = p.map(_chunk, bounds)

    tot = sum(r[0] for r in res)
    totc = sum(r[1] for r in res)
    ns = sum(r[2] for r in res)
    best = max(r[3] for r in res)
    bestc = max(r[4] for r in res)
    print(f"states measured              {ns}")
    print(f"mean TILE BLITS per frame    {tot / max(ns, 1):.1f}")
    print(f"WORST TILE BLITS in a frame  {best[0]}  "
          f"at (px,py,a,faces,cols,cov) = {best[1]}")
    print(f"mean face x tile-COLUMN      {totc / max(ns, 1):.1f}")
    print(f"WORST face x tile-COLUMN     {bestc[0]}  at {bestc[1]}")


if __name__ == "__main__":
    main()
