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


def _init(level=0):
    import marchmodel as mm
    import pacescan as ps
    # THE LEVEL TRAVELS IN initargs, and it has to: select_level() rebinds
    # module globals in world, and a forkserver worker inherits none of
    # them.  See the same note in pacescan._init.
    ps.world.select_level(level)
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


def main(jobs=None, level=0):
    import multiprocessing as mp
    import marchmodel as mm
    import pacescan as ps
    jobs = jobs or os.cpu_count()
    _init(level)
    pos = _W["pos"]
    print(f"\n==== LEVEL {level} " + "=" * 52)
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
    with mp.Pool(jobs, initializer=_init, initargs=(level,)) as p:
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
    # ...AND SAY WHETHER IT FITS.  These two were printed and read by a
    # human, which is fine for one map and no use at all once a level is
    # something a designer adds: overrun the bucket count and faces are
    # DROPPED, overrun the flood stack and it writes into the buckets.
    # Both limits come out of the source, so neither can go stale here.
    kfit, dfit = _bucket_pages(), _stack_entries()
    ok = kmax <= kfit and dmax <= dfit
    print(f"  buckets k max {kmax} of {kfit} pages, flood depth {dmax} of "
          f"{dfit} entries -> {'FITS' if ok else 'OVERRUNS -- see march.asm'}")
    return 0 if ok else 1


def _equ(name, path):
    """One equ out of an asm source, hex or decimal."""
    for ln in open(os.path.join(_HERE, "..", "src", path)):
        p = ln.split()
        if len(p) >= 3 and p[0] == name and p[1] in ("equ", "EQU"):
            v = p[2]
            return int(v[1:], 16) if v.startswith("#") else int(v)
    raise KeyError(f"{name} not in {path}")


def _bucket_pages():
    """BUCKETS runs to MSTKBOT, one page a bucket -- see march.asm."""
    return (_equ("MSTKBOT", "march.asm") - _equ("BUCKETS", "march.asm")) // 256


def _stack_entries():
    """The flood stack is MSTKBOT..MSTKTOP, 10 bytes an entry."""
    return (_equ("MSTKTOP", "march.asm") - _equ("MSTKBOT", "march.asm")) // 10


def all_levels(jobs=None):
    import genaux
    rc = 0
    for lv in range(genaux.nlevel()):
        rc |= main(jobs, lv)
    print("\nALL LEVELS: " + ("FITS" if not rc else "ONE OR MORE OVERRUN"))
    return rc


if __name__ == "__main__":
    _a = [x for x in sys.argv[1:] if x.isdigit()]
    _lv = [int(x[2:]) for x in sys.argv[1:]
           if x.startswith("lv") and x[2:].isdigit()]
    _j = int(_a[0]) if _a else None
    raise SystemExit(main(_j, _lv[0]) if _lv else all_levels(_j))
