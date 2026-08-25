"""HOW MANY VIEWPORT BYTES DOES THE WALL AREA ACTUALLY COVER?

Every "what would a textured renderer cost" estimate in this project has
so far been multiplied by 44*96 = 4224.  That is the whole viewport, and
the walls are not the whole viewport -- floor and ceiling are.  This
counts the real thing, off the real quad list: march + project for every
state a player can stand in (the same 24/256 lattice x 72 headings
pacescan.py sweeps), then rastermodel.raster_quad for the runs.

    python3 engine2/tools/wallarea.py [nstates|all] [jobs]

Reports, over the scanned states:
    painted   bytes the rasteriser WRITES (overdraw counted twice)
    covered   DISTINCT viewport bytes that end up wall (overdraw once)
    columns   distinct viewport BYTE COLUMNS any wall touches
"""

import collections
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

_W = {}


def _init():
    import pacescan
    import rastermodel as rm
    solid, pos = pacescan.positions()
    _W["solid"] = solid
    _W["pos"] = pos
    _W["rm"] = rm
    _W["cfg"] = rm.cfg()


def _quads(px, py, a):
    import marchmodel as mm
    import projmodel as pm
    solid = _W["solid"]
    r = mm.march(solid, px, py, a)
    ipx, ipy = px >> 8, py >> 8
    out = []
    for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
        (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
        q = pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
        if q is not None:
            out.append(q + (door, k))
    return out


def _one(px, py, a):
    rm, c = _W["rm"], _W["cfg"]
    painted = 0
    runs = 0
    cov = set()
    cols = set()
    nq = 0
    for q in _quads(px, py, a):
        nq += 1
        for (row, end, npush) in rm.raster_quad(q, c):
            n = 2 * npush
            painted += n
            runs += 1
            for b in range(end - n, end):
                cov.add(row * c.VP_BW + b)
                cols.add(b)
    return painted, len(cov), len(cols), nq, runs


def _chunk(args):
    lo, hi, step = args
    pos = _W["pos"]
    best = dict(painted=(0, None), covered=(0, None), cols=(0, None),
                nq=(0, None), runs=(0, None))
    hp = collections.Counter()
    hc = collections.Counter()
    tot = 0
    sp = sc = sr = 0
    for i in range(lo, hi, step):
        px, py = pos[i]
        for a in range(72):
            p, cv, cl, nq, runs = _one(px, py, a)
            tot += 1
            sp += p
            sc += cv
            sr += runs
            hp[p // 256] += 1
            hc[cv // 256] += 1
            for k, v in (("painted", p), ("covered", cv), ("cols", cl),
                         ("nq", nq), ("runs", runs)):
                if v > best[k][0]:
                    best[k] = (v, (px, py, a))
    return best, hp, hc, tot, (sp, sc, sr)


def main():
    import multiprocessing as mp
    arg = sys.argv[1] if len(sys.argv) > 1 else "20000"
    jobs = int(sys.argv[2]) if len(sys.argv) > 2 else (os.cpu_count() or 4)
    _init()
    pos = _W["pos"]
    c = _W["cfg"]
    npos = len(pos)
    if arg == "all":
        step = 1
    else:
        want = int(arg)
        step = max(1, (npos * 72) // want)
    scanned_pos = len(range(0, npos, step))
    print(f"viewport {c.VP_BW}x{c.VP_H} = {c.VP_BW * c.VP_H} bytes")
    print(f"{npos} standable positions x 72 headings = {npos * 72} states; "
          f"scanning every {step}th position = {scanned_pos * 72} states "
          f"on {jobs} cores")

    bounds = [(i * npos // jobs, (i + 1) * npos // jobs, step)
              for i in range(jobs)]
    with mp.Pool(jobs, initializer=_init) as p:
        res = p.map(_chunk, bounds)

    best = dict(painted=(0, None), covered=(0, None), cols=(0, None),
                nq=(0, None), runs=(0, None))
    hp, hc = collections.Counter(), collections.Counter()
    tot = 0
    sums = [0, 0, 0]
    for b, a, cc, t, sm in res:
        for j in range(3):
            sums[j] += sm[j]
        for k in best:
            if b[k][0] > best[k][0]:
                best[k] = b[k]
        hp.update(a)
        hc.update(cc)
        tot += t

    area = c.VP_BW * c.VP_H
    print(f"\nscanned {tot} states")
    for k, label in (("painted", "bytes WRITTEN by the rasteriser"),
                     ("covered", "DISTINCT viewport bytes that are wall"),
                     ("cols", "distinct byte columns touched"),
                     ("nq", "quads in the frame"),
                     ("runs", "runs (= scanline fills) in the frame")):
        v, st = best[k]
        extra = f"  = {100.0 * v / area:5.1f}% of the viewport" \
            if k in ("painted", "covered") else ""
        print(f"  worst {label:38} {v:6d}{extra}   at {st}")

    def pct(h, q):
        tot_ = sum(h.values())
        run = 0
        for k in sorted(h):
            run += h[k]
            if run >= tot_ * q:
                return k * 256
        return 0

    print(f"\n  mean painted {sums[0]/tot:7.1f}   mean covered {sums[1]/tot:7.1f}"
          f"   mean runs {sums[2]/tot:6.1f}")
    print("\n  painted-byte percentiles: "
          + "  ".join(f"p{q*100:g}={pct(hp, q)}"
                      for q in (0.5, 0.9, 0.99, 0.999)))
    print("  covered-byte percentiles: "
          + "  ".join(f"p{q*100:g}={pct(hc, q)}"
                      for q in (0.5, 0.9, 0.99, 0.999)))


if __name__ == "__main__":
    main()
