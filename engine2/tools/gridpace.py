"""DOES THE HONEST GRID HOLD THE FRAME PERIOD?

pacemodel.py replays main3.asm's cost accumulator exactly, and pacescan.py
runs that replay over all 4055040 states a player can stand in -- including,
since pacemodel.joint_units, main3.asm's FLAT C_JOINT per jointed face.
(It did not always: for the whole of the COURSES 1 era pacemodel.units()
modelled a COURSES 0 disc, and every "locked" claim made from it was about
a build nobody had.)  What this file changes is not whether the joints are
charged but HOW, plus one thing the shipped rasteriser does not do at all:

    * the face's END COLUMNS, which are two substituted pushes per run,
      MEASURED at +2.000 us a scanline -- i.e. exactly C_QS 22 -> 24;
    * the COURSE JOINTS, charged PER MIRRORED ROW PAIR and per byte of
      face width instead of main3.asm's flat C_JOINT per face.

and then asks the only question that matters: how many states ask for
more waits than PACE_FRAMES has.

    python3 engine2/tools/gridpace.py [nstates|all] [jobs] [k=v ...]

    cjpair=  us per joint row PAIR          (0 turns the joints off)
    cjbyte=  us per byte of face width, for the joint's own pushes
    cqs=     C_QS, the per-scanline byte charge (22 shipped, 24 with edges)
    frames=  PACE_FRAMES to test
"""

import collections
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

CFG = dict(cjset=0, cjpair=0.0, cjbyte=0.0, cqs=22, cqw=0, frames=6,
           cquad=0, kmax=0)

_W = {}


def _init():
    import pacescan
    import pacemodel
    import rastermodel as rm
    solid, pos = pacescan.positions()
    _W["solid"] = solid
    _W["pos"] = pos
    _W["pm"] = pacemodel
    _W["rm"] = rm
    _W["cyh"] = rm.cfg().CYH


def joint_charge(q, cfg):
    """What ONE face's two course boundaries are charged.

    jpairs = j1e - j0 + 1 is the row-pair count raster_joint's loop runs,
    and it is two shifts and a DIV3 off the record's own hlo and hhi -- the
    same two numbers pace_quad already reads.  D is |bhi - blo|, which
    pace_quad has ALREADY computed.  So an honest per-pair charge costs the
    pacing code one 8x8 multiply it is already set up to do, and nothing
    else."""
    rm = _W["rm"]
    r = rm.joint_rows(q)
    if r is None:
        return 0
    j0, j1e, D, _N, _bA, _bB = r
    if not cfg["cjpair"]:
        return 0
    return int(cfg["cjset"] + cfg["cjpair"] * (j1e - j0 + 1)
               + cfg["cjbyte"] * D)


def state_units(px, py, a, cfg):
    import marchmodel as mm
    import projmodel as pm
    pmod = _W["pm"]
    solid, cyh = _W["solid"], _W["cyh"]
    nclip = [0]
    real = pm.lerp

    def counting(*args):
        nclip[0] += 1
        return real(*args)
    pm.lerp = counting
    try:
        r = mm.march(solid, px, py, a)
        ipx, ipy = px >> 8, py >> 8
        faces, quads = [], []
        for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
            (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
            nclip[0] = 0
            q = pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
            faces.append((q is not None, nclip[0]))
            if q is not None:
                quads.append(q + (door, k))
    finally:
        pm.lerp = real

    # pacemodel.units builds the whole frame; rebuild it here with the
    # quad charges recomputed at the new C_QS and each face's joints
    # appended as a UNIT OF THEIR OWN -- which is what main3.asm does, and
    # what keeps the largest atomic unit a quad OR its joints and never
    # their sum.
    u = [(0, pmod.C_BG, pmod.C_BG), (0, pmod.C_MSETUP, pmod.C_MSETUP)]
    u += [(0, pmod.C_CELL, pmod.C_CELL)] * r["visited"]
    u.append((2, 0, 0))
    for emitted, nc in faces:
        u.append((1, 0, (pmod.C_FACE if emitted else pmod.C_REJ)
                  + pmod.C_CLIP * nc))
    old, oldw = pmod.C_QS, pmod.C_QW
    pmod.C_QS = cfg["cqs"]
    if cfg["cqw"]:
        pmod.C_QW = cfg["cqw"]
    try:
        for q in quads:
            for cc in pmod.quad_units(q, cyh):
                u.append((0, cc, cc))
            jc = joint_charge(q, cfg)
            if jc:
                u.append((0, jc, jc))
    finally:
        pmod.C_QS, pmod.C_QW = old, oldw
    u.append((0, pmod.C_HUD, pmod.C_HUD))
    if pmod.GUN and pmod.GUN_CHARGED:
        u.append((0, pmod.C_GUN, pmod.C_GUN))
    return u


def _chunk(args):
    lo, hi, step, cfg = args
    CFG.update(cfg)
    if cfg["kmax"]:
        _W["rm"].JOINT_KMAX = cfg["kmax"]
    if cfg["cquad"]:
        _W["pm"].C_QUAD = cfg["cquad"]
    pos = _W["pos"]
    pmod = _W["pm"]
    hist = collections.Counter()
    worst = (0, None)
    biggest = (0, None)          # the largest ATOMIC unit anywhere
    over = []
    n = cfg["frames"]
    for i in range(lo, hi, step):
        px, py = pos[i]
        for a in range(72):
            u = state_units(px, py, a, cfg)
            b = max(c for (_k, _r, c) in u)
            if b > biggest[0]:
                biggest = (b, (px, py, a))
            waits, w, _acc = pmod.segments(u, n=n)
            tot = sum(c for (_k, _r, c) in u) + pmod.C_TAIL
            hist[waits] += 1
            if tot > worst[0]:
                worst = (tot, (px, py, a))
            if waits >= n and len(over) < 20:
                over.append((px, py, a))
    return hist, worst, biggest, over


def main():
    import multiprocessing as mp
    arg = sys.argv[1] if len(sys.argv) > 1 else "20000"
    jobs = int(sys.argv[2]) if len(sys.argv) > 2 else (os.cpu_count() or 4)
    for kv in sys.argv[3:]:
        k, v = kv.split("=")
        CFG[k] = float(v) if "." in v else int(v)
    _init()
    pos = _W["pos"]
    npos = len(pos)
    step = 1 if arg == "all" else max(1, (npos * 72) // int(arg))
    n = CFG["frames"]
    print(f"PACE_FRAMES {n} -> {n*19.968:.2f} ms, {1000/(n*19.968):.2f} fps; "
          f"budget {n*19456} us")
    print("cfg: " + "  ".join(f"{k}={v}" for k, v in CFG.items()))
    print(f"{len(range(0, npos, step))*72} states on {jobs} cores")

    bounds = [(i * npos // jobs, (i + 1) * npos // jobs, step, dict(CFG))
              for i in range(jobs)]
    with mp.Pool(jobs, initializer=_init) as p:
        res = p.map(_chunk, bounds)

    hist = collections.Counter()
    worst = (0, None)
    biggest = (0, None)
    over = []
    for h, w, b, o in res:
        hist.update(h)
        if w[0] > worst[0]:
            worst = w
        if b[0] > biggest[0]:
            biggest = b
        over += o
    tot = sum(hist.values())
    print(f"\nscanned {tot} states")
    for k in sorted(hist):
        print(f"  {k} waits: {hist[k]:8d}  {100.0*hist[k]/tot:6.3f}%")
    print(f"\n  worst CHARGED frame     {worst[0]:8d} us at {worst[1]}"
          f"   (budget {n*19456})")
    print(f"  largest ATOMIC unit     {biggest[0]:8d} us at {biggest[1]}"
          f"   (COST_THI 19456, vsync 19968)")
    bad = hist.get(n, 0)
    print(f"\n  states needing a {n}th wait (= a {n+1}th period): {bad}")
    if over:
        print("  e.g. " + ", ".join(map(str, over[:8])))


if __name__ == "__main__":
    main()
