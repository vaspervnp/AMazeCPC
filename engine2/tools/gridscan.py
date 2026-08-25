"""WHAT DOES THE HONEST GRID COST, PER FRAME, OVER THE REAL STATE SPACE?

wallarea.py counts the bytes a frame paints.  This counts the things the
GRID architecture is charged for on top of that:

    runs          scanline fills (each one gets two vertical edge pushes)
    body/wedge    scanlines and bytes, the four regressors raster.asm's
                  own timing fit uses
    D             wedge Bresenham edge steps
    jpairs        course-joint mirrored row PAIRS  (the joint's row loop
                  runs once per pair and paints two scanlines)
    jrows         joint SCANLINES  (= len(joint_runs))
    jpush         joint PUSHes -- the mortar pixels themselves

and then prices a whole frame with MEASURED constants, so the answer is
in milliseconds and not in counts.

    python3 engine2/tools/gridscan.py [nstates|all] [jobs]
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


KEYS = ("nq", "runs", "bl", "bb", "wl", "wb", "D", "jfaces", "jpairs",
        "jrows", "jpush", "jextra", "painted")


def _one(px, py, a):
    rm, c = _W["rm"], _W["cfg"]
    t = dict.fromkeys(KEYS, 0)
    for q in _quads(px, py, a):
        t["nq"] += 1
        bl, bb, wl, wb = rm.counts(q, c)
        t["bl"] += bl
        t["bb"] += bb
        t["wl"] += wl
        t["wb"] += wb
        t["runs"] += bl + wl
        t["painted"] += bb + wb
        t["D"] += rm.quad_shape(q, c)["D"]
        jr = rm.joint_runs(q, c)
        t["jrows"] += len(jr)
        t["jpush"] += sum(n for (_r, _e, n) in jr)
        t["jextra"] += sum(n - 1 for (_r, _e, n) in jr)
        rr = rm.joint_rows(q, c)
        if rr is not None:
            j0, j1e, _D, _N, _bA, _bB = rr
            t["jfaces"] += 1
            t["jpairs"] += j1e - j0 + 1
    return t


# ---- MEASURED per-unit costs.  Everything here is filled in by
#      emu_grid.py and this file only multiplies.  The defaults are
#      raster.asm's own measured fit; the grid terms are overridden from
#      the command line so the two never drift.
COST = dict(
    qset=426.0,         # per quad, nothing drawn
    bline=18.78,        # body scanline, fixed
    bbyte=1.976,        # ...per byte
    wline=59.05,        # wedge scanline, fixed
    wbyte=1.760,
    wstep=19.27,        # per Bresenham edge step
    edge=0.0,           # per RUN, for the two vertical end columns
    jpair=0.0,          # per joint mirrored PAIR, ONE push on each row
    jpush=0.0,          # per EXTRA joint push beyond that first one
    jflat=0.0,          # main3.asm's C_JOINT, charged per JOINTED FACE
    rest=9215.8 + 12000 + 28000 + 3400 + 1450,   # bg+march+project+gun+hud
)


def price(t, cost=None):
    c = cost or COST
    r = (c["qset"] * t["nq"]
         + c["bline"] * t["bl"] + c["bbyte"] * t["bb"]
         + c["wline"] * t["wl"] + c["wbyte"] * t["wb"]
         + c["wstep"] * t["D"]
         + c["edge"] * t["runs"])
    j = (c["jpair"] * t["jpairs"] + c["jpush"] * t["jextra"]
         + c["jflat"] * t["jfaces"])
    return r, j


def _chunk(args):
    # The cost table travels in the ARGUMENT, not in the module global.
    # Python 3.14 starts pool workers with forkserver on Linux, which
    # re-imports this module in the child -- so anything main() poked
    # into COST is gone by the time _chunk runs there, and the scan
    # silently prices everything at the defaults.
    lo, hi, step, cost = args
    COST.update(cost)
    pos = _W["pos"]
    best = {k: (0, None) for k in KEYS}
    best["raster"] = (0.0, None)
    best["frame"] = (0.0, None)
    tot = 0
    sums = collections.Counter()
    hist = collections.Counter()
    for i in range(lo, hi, step):
        px, py = pos[i]
        for a in range(72):
            t = _one(px, py, a)
            tot += 1
            for k in KEYS:
                sums[k] += t[k]
                if t[k] > best[k][0]:
                    best[k] = (t[k], (px, py, a))
            r, j = price(t)
            if r + j > best["raster"][0]:
                best["raster"] = (r + j, (px, py, a))
            f = r + j + COST["rest"]
            if f > best["frame"][0]:
                best["frame"] = (f, (px, py, a))
            hist[int(f // 1000)] += 1
    return best, tot, sums, hist


def main():
    import multiprocessing as mp
    arg = sys.argv[1] if len(sys.argv) > 1 else "20000"
    jobs = int(sys.argv[2]) if len(sys.argv) > 2 else (os.cpu_count() or 4)
    for kv in sys.argv[3:]:
        k, v = kv.split("=")
        COST[k] = float(v)
    _init()
    pos = _W["pos"]
    c = _W["cfg"]
    npos = len(pos)
    step = 1 if arg == "all" else max(1, (npos * 72) // int(arg))
    print(f"viewport {c.VP_BW}x{c.VP_H}, COURSES={c.COURSES}")
    print(f"{npos*72} states; every {step}th position -> "
          f"{len(range(0, npos, step))*72} states on {jobs} cores")
    print("costs: " + "  ".join(f"{k}={v:g}" for k, v in COST.items()))

    bounds = [(i * npos // jobs, (i + 1) * npos // jobs, step, dict(COST))
              for i in range(jobs)]
    with mp.Pool(jobs, initializer=_init) as p:
        res = p.map(_chunk, bounds)

    best = {k: (0, None) for k in KEYS}
    best["raster"] = (0.0, None)
    best["frame"] = (0.0, None)
    tot = 0
    sums = collections.Counter()
    hist = collections.Counter()
    for b, t, s, h in res:
        tot += t
        sums.update(s)
        hist.update(h)
        for k in best:
            if b[k][0] > best[k][0]:
                best[k] = b[k]

    print(f"\nscanned {tot} states\n")
    print(f"  {'':10} {'worst':>10} {'mean':>10}   at")
    for k in KEYS:
        print(f"  {k:10} {best[k][0]:10d} {sums[k]/tot:10.1f}   {best[k][1]}")
    for k in ("raster", "frame"):
        print(f"  {k:10} {best[k][0]/1000.0:10.2f} ms"
              f"{'':11}{best[k][1]}")

    def pct(q):
        run = 0
        for k in sorted(hist):
            run += hist[k]
            if run >= tot * q:
                return k
        return 0
    print("\n  whole-frame ms percentiles: "
          + "  ".join(f"p{q*100:g}={pct(q)}"
                      for q in (0.5, 0.9, 0.99, 0.999, 1.0)))


if __name__ == "__main__":
    main()
