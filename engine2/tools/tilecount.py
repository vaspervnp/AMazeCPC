"""HOW MANY DISTINCT 8x8 TILES DOES THE C64 PICTURE ACTUALLY NEED?

The "fake the C64's character mode" architecture precompiles a set of
8x8-pixel tiles and picks one per screen cell.  That is only cheaper than
computing pixels if the SET IS SMALL ENOUGH TO STORE.  This counts it,
exactly, off the real geometry: march + project every sampled player
state, render the reference wall texture PER PIXEL with perspective-
correct (u, v), cut the viewport into its 11 x 12 screen-aligned cells,
and count distinct 8x8 bitmaps.

The viewport is exactly 11 x 12 cells because vpcfg.inc has VP_BX 18,
VP_BW 44 (= 11 four-byte tiles), VP_Y 0 and VP_H 96 (= 12 character
rows), so a tile never straddles the Mode 0 interleave boundary.

    python3 engine2/tools/tilecount.py [nstates] [seed]
"""

import collections
import math
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import marchmodel as mm                                     # noqa: E402
import projmodel as pm                                      # noqa: E402
import pacescan                                             # noqa: E402

VP_PW = 88                      # viewport width, mode-0 pixels
VP_H = 96
CXH = 44.0                      # horizon centre, pixel units
CYH = 48.0
FOCAL_V = 96.0
FOCAL_H = pm.gentab.FOCAL_H if hasattr(pm.gentab, "FOCAL_H") else 76.210
ZNEAR = 0.125

TW = 8                          # tile width  in pixels
TH = 8                          # tile height in scanlines
NTX = VP_PW // TW               # 11
NTY = VP_H // TH                # 12


# ---------------------------------------------------------------------
#  THE REFERENCE TEXTURE.  Blue blocks, black mortar in BOTH axes, the
#  courses offset half a block so the blocks read as irregular -- which
#  is what the C64 screenshot shows.  One wall cell carries NC courses
#  and NB blocks per course; mortar is MW of a block wide.
# ---------------------------------------------------------------------
NC = int(os.environ.get("TC_NC", 4))    # courses per wall cell (vertical)
NB = int(os.environ.get("TC_NB", 4))    # blocks per course (horizontal)
MW = 0.10                       # mortar width, fraction of a block
MH = 0.10                       # mortar height, fraction of a course


MODE = "both"                   # both | horiz | vert


def mortar(u, v):
    """True where the texel is black mortar.  u, v in [0,1) over ONE cell."""
    cv = v * NC
    row = int(cv) % NC
    fv = cv - math.floor(cv)
    if MODE != "vert" and fv < MH:
        return True
    if MODE == "horiz":
        return False
    # every other course offset by half a block
    cu = u * NB + (0.5 if (row & 1) else 0.0)
    fu = cu - math.floor(cu)
    return fu < MW


# ---------------------------------------------------------------------
def quads_and_faces(solid, px, py, a):
    """-> list of (xa, za, xb, zb) view-space face endpoints, painter order."""
    r = mm.march(solid, px, py, a)
    ipx, ipy = px >> 8, py >> 8
    out = []
    for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
        (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
        q = pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
        if q is None:
            continue
        # view space is Q6.10 cells
        out.append((v[0] / 1024.0, v[1] / 1024.0,
                    v[2] / 1024.0, v[3] / 1024.0))
    return out


def render(faces, touched=None):
    """Per-pixel exact render.  -> buf[y][x] in {0 ceiling/floor,
    1 wall body, 2 mortar}.

    If `touched` is a list it is filled with one set of (tx,ty) cells per
    face -- the cells a PAINTER-ORDER tile renderer would have to blit,
    which is the number that matters because a tile blit cannot be
    clipped to a face edge: it always writes all 8x8 pixels."""
    buf = [[0] * VP_PW for _ in range(VP_H)]
    for (xa, za, xb, zb) in faces:            # painter order: back first
        cellset = set()
        if touched is not None:
            touched.append(cellset)
        dx, dz = xb - xa, zb - za
        for ix in range(VP_PW):
            s = ix + 0.5 - CXH
            den = FOCAL_H * dx - s * dz
            if den == 0.0:
                continue
            t = (s * za - FOCAL_H * xa) / den
            if t < 0.0 or t > 1.0:
                continue
            z = za + t * dz
            if z < ZNEAR:
                continue
            h = 0.5 * FOCAL_V / z             # half height, scanlines
            y0 = CYH - h
            y1 = CYH + h
            lo = max(0, int(math.floor(y0 + 0.5)))
            hi = min(VP_H, int(math.floor(y1 + 0.5)))
            inv = 1.0 / (2.0 * h)
            tx = ix // TW
            for iy in range(lo, hi):
                v = (iy + 0.5 - y0) * inv
                if v < 0.0 or v >= 1.0:
                    continue
                buf[iy][ix] = 2 if mortar(t, v) else 1
                cellset.add((tx, iy // TH))
    return buf


def codebytes(rows):
    """EXACT bytes of Z80 needed for one 4x8 tile compiled as code.

    Per row: `ld sp,hl` (1), then two pushes, then `add hl,bc` (1) --
    `jp (iy)` (2) on the last.  A push whose word is already in DE is one
    byte; otherwise `ld de,nn : push de` is four.  DE is tracked greedily,
    which is what a generator would do.  PUSH writes the RIGHT half of the
    row first, so the order is (g1, g0)."""
    n = 0
    de = None
    for i, (g0, g1) in enumerate(rows):
        n += 1
        for w in (g1, g0):
            if w == de:
                n += 1
            else:
                n += 4
                de = w
        n += 1 if i < 7 else 2
    return n


def cells(buf):
    """-> (full_wall_cells, edge_cells) as 64-bit keys.

    A cell is FULL if every one of its 64 pixels is wall; those are the
    ones a plain texture tile can serve.  A cell that mixes wall and
    background needs an EDGE tile, which carries the wall boundary as
    well as the texture."""
    full = []
    edge = []
    for ty in range(NTY):
        for tx in range(NTX):
            k = 0
            nw = 0
            rows = []
            for j in range(TH):
                row = buf[ty * TH + j]
                seg = row[tx * TW:tx * TW + TW]
                nw += sum(1 for p in seg if p)
                for p in seg:
                    k = (k << 2) | p
                rows.append((tuple(seg[0:4]), tuple(seg[4:8])))
            if nw == 0:
                continue
            (full if nw == 64 else edge).append((k, rows))
    return full, edge


def main():
    global MODE
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20260821
    if len(sys.argv) > 3:
        MODE = sys.argv[3]
    print(f"texture mode: {MODE}   ({NC} courses x {NB} blocks per wall cell)")
    solid, pos = pacescan.positions()
    rnd = random.Random(seed)
    states = [(px, py, rnd.randrange(72))
              for (px, py) in rnd.sample(pos, min(n, len(pos)))]

    fullset = set()
    edgeset = set()
    fullcnt = collections.Counter()
    fullsz = {}
    edgesz = {}
    nfull = nedge = 0
    worst = (0, None)
    wblit = (0, None)
    wcol = (0, None)
    totblit = 0
    totcol = 0
    curve = []
    for i, (px, py, a) in enumerate(states):
        faces = quads_and_faces(solid, px, py, a)
        touched = []
        buf = render(faces, touched)
        nb = sum(len(s) for s in touched)
        nc = sum(len({c[0] for c in s}) for s in touched)
        totblit += nb
        totcol += nc
        if nc > wcol[0]:
            wcol = (nc, (px, py, a))
        if nb > wblit[0]:
            wblit = (nb, (px, py, a, len(faces), nc))
        f, e = cells(buf)
        if len(f) + len(e) > worst[0]:
            worst = (len(f) + len(e), (px, py, a, len(f), len(e)))
        nfull += len(f)
        nedge += len(e)
        for k, rows in f:
            if k not in fullsz:
                fullsz[k] = codebytes(rows)
            fullset.add(k)
            fullcnt[k] += 1
        for k, rows in e:
            if k not in edgesz:
                edgesz[k] = codebytes(rows)
            edgeset.add(k)
        if (i + 1) in (1, 2, 5, 10, 20, 40, 60, 100, 150, 200, 300, 500):
            curve.append((i + 1, len(fullset), len(edgeset)))

    print(f"states rendered              {len(states)}")
    print(f"viewport cells per frame     {NTX} x {NTY} = {NTX * NTY}")
    print(f"wall cells seen              {nfull + nedge} "
          f"({nfull} full, {nedge} edge)")
    print(f"mean wall cells per frame    {(nfull + nedge) / len(states):.1f} "
          f"({nfull / len(states):.1f} full, {nedge / len(states):.1f} edge)")
    print(f"WORST wall cells in a frame  {worst[0]}  at {worst[1]}")
    print(f"mean TILE BLITS per frame    {totblit / len(states):.1f} "
          f"(painter order, one blit per face x cell)")
    print(f"WORST TILE BLITS in a frame  {wblit[0]}  at {wblit[1]}")
    print(f"mean face x tile-COLUMN pairs {totcol / len(states):.1f}   "
          f"WORST {wcol[0]} at {wcol[1]}")
    print()
    print(f"DISTINCT full-wall tiles     {len(fullset)}")
    print(f"DISTINCT edge tiles          {len(edgeset)}")
    print(f"DISTINCT total               {len(fullset) + len(edgeset)}")
    tb = sum(fullsz.values()) + sum(edgesz.values())
    nt = len(fullset) + len(edgeset)
    print(f"COMPILED TILE SET            {tb} bytes of Z80 "
          f"({tb / max(nt, 1):.1f} bytes/tile)")
    print(f"  against 49152 free bytes (banks 5,6,7): "
          f"{tb / 49152.0:.1f}x over")
    print()
    print("growth (states -> distinct full, distinct edge):")
    for k, a, b in curve:
        print(f"   {k:5d}  {a:7d}  {b:7d}")
    print()
    top = fullcnt.most_common(20)
    cov = sum(c for _k, c in top) / max(nfull, 1)
    print(f"the 20 commonest full tiles cover {cov * 100:.1f}% of full cells")
    for cut in (16, 32, 64, 128, 256, 512, 1024):
        c = sum(v for _k, v in fullcnt.most_common(cut))
        print(f"   the commonest {cut:5d} cover {c / max(nfull, 1) * 100:5.1f}%")


if __name__ == "__main__":
    main()
