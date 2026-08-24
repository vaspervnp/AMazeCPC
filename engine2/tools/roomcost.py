"""WHAT THE ROOM SIZE COSTS THE MARCH, over every state a player can stand in.

    python3 engine2/tools/roomcost.py [jobs]

tools/world.py's room size is bounded by W + H <= R_MAX + 1, and R_MAX is
what the flood pays for: its area grows as the square of the radius, every
popped cell is charged C_CELL, and every filed face becomes a quad the
rasteriser has to draw.  So enlarging a room is a PACING change wearing a
level-design hat, and this is the measurement that prices it.

It reports, exhaustively over the same reachable set pacescan.py sweeps:

    cells popped         -> C_CELL, and march.asm's own loop
    faces filed          -> C_FACE / C_REJ, and the quads that follow
    the FARTHEST bucket  -> how many face buckets march.asm needs
    the deepest flood    -> how big MSTKTOP-MSTKBOT has to be

The last two are the ones that are not about time at all: overrun the
bucket count and faces are dropped, overrun the flood stack and it writes
into the buckets themselves.  Both are sized here rather than guessed.
"""

import collections
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                                "AMazeCPC", "tools"))

_W = {}


def _init():
    import marchmodel as mm
    import pacescan as ps
    _W["mm"] = mm
    _W["solid"], _W["pos"] = ps.positions()


def _chunk(args):
    lo, hi, pos = args
    mm, solid = _W["mm"], _W["solid"]
    cells = collections.Counter()
    faces = collections.Counter()
    far = collections.Counter()
    depth = collections.Counter()
    worst = (0, None)
    for i in range(lo, hi):
        px, py = pos[i]
        for a in range(mm.N_ANGLES):
            r = mm.march(solid, px, py, a)
            cells[r["visited"]] += 1
            faces[len(r["faces"])] += 1
            depth[r["maxdepth"]] += 1
            k = max((f[4] for f in r["faces"]), default=0)
            far[k] += 1
            if r["visited"] > worst[0]:
                worst = (r["visited"], (px, py, a))
    return cells, faces, far, depth, worst


def main(jobs=None):
    import multiprocessing as mp
    import marchmodel as mm
    import pacescan as ps
    jobs = jobs or os.cpu_count()
    _init()
    pos = _W["pos"]
    print(f"R_MAX {mm.R_MAX} -> faces filed at L1 1..{mm.R_MAX + 1}, "
          f"so rooms are bounded by W + H <= {mm.R_MAX + 1}")
    print(f"{len(pos)} standable positions x {mm.N_ANGLES} headings = "
          f"{len(pos) * mm.N_ANGLES} states -- ALL of them")
    step = max(1, len(pos) // (jobs * 8))
    tasks = [(i, min(i + step, len(pos)), pos)
             for i in range(0, len(pos), step)]
    cells = collections.Counter()
    faces = collections.Counter()
    far = collections.Counter()
    depth = collections.Counter()
    worst = (0, None)
    with mp.Pool(jobs, initializer=_init) as p:
        for c, f, k, d, w in p.imap_unordered(_chunk, tasks):
            cells.update(c)
            faces.update(f)
            far.update(k)
            depth.update(d)
            worst = max(worst, w)

    def show(name, hist, tail=4):
        tot = sum(hist.values())
        ks = sorted(hist)
        body = "  ".join(f"{k}:{100.0 * hist[k] / tot:.2f}%" for k in ks[-tail:])
        print(f"  {name:22s} max {ks[-1]:4d}   (top {tail}: {body})")

    print("\nexhaustive:")
    show("cells popped", cells)
    show("faces filed", faces)
    show("farthest bucket k", far)
    show("flood stack depth", depth)
    import pacemodel as P
    print(f"\n  worst march {worst[0]} cells at {worst[1]}"
          f"  = {worst[0] * P.C_CELL} us at C_CELL {P.C_CELL}")
    kmax = max(far)
    dmax = max(depth)
    print(f"\n  march.asm needs buckets k = 1..{kmax}"
          f"  ({kmax} pages from BUCKETS)")
    print(f"  march.asm needs a flood stack of at least {dmax} entries"
          f" x 10 = {dmax * 10} bytes")
    return 0


if __name__ == "__main__":
    _a = [x for x in sys.argv[1:] if x.isdigit()]
    raise SystemExit(main(int(_a[0]) if _a else None))
