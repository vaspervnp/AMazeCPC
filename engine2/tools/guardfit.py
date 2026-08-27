"""HOW MUCH GUARD FITS INSIDE SIX VSYNCS?  Exhaustive, over all 4055040.

    python3 engine2/tools/guardfit.py [C_QUAD ...]

The question the enemy phase has to answer BEFORE any Z80 is written is
not "is there slack" -- there is 21.4 ms of it -- it is "does one more
ATOMIC unit at the foot of the frame still pack".  main3.asm's greedy
rule takes a vsync wait whenever the next unit would not fit in what is
left of the current 19456 us interval, and PACE_FRAMES caps the waits at
six; a unit that is 20% of an interval can miss on the states whose last
interval is already nearly full, which is exactly what the 28x46 weapon
did (28 states of 4055040 at C_GUN 4500).

So this replays pacescan.py's rule with ONE EXTRA room-then-charge unit
of C_GUARD microseconds appended after gun_paced -- which is where the
enemy pass would go, after the walls and the weapon -- and reports the
largest C_GUARD with zero over-budget states.  It is the same
enumeration, the same constants read out of main3.asm, and the same
greedy; the only thing added is the unit.

The unit is charged as ONE, and that is the honest shape: every visible
guard is projected with bank 4 paged in and then ALL of them are blitted
with the sprite bank paged in, so the whole enemy pass is between two
bank switches and a vsync wait cannot fall inside it -- the same argument
that makes gun_draw one unit.
"""

import collections
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import pacescan                                             # noqa: E402

_W = {}


def _init(cguard, ovr=None):
    import pacemodel as pm
    import rastermodel as rm
    solid, _pos = pacescan.positions()
    for _n, _v in (ovr or {}).items():
        setattr(pm, _n, _v)
    # tail was C_TAIL + C_DOORACT by hand and went 2200 us light the day
    # sound landed.  This file FITS a constant against the head it
    # assumes, so a light head fits a C_GUARD that is too big to be safe.
    _W.update(solid=solid, cyh=rm.cfg().CYH, pm=pm, g=cguard,
              tail=pm.frame_head())
    pm._rm = rm


def _chunk(args):
    lo, hi, pos = args
    pm, solid, cyh, tail, g = (_W["pm"], _W["solid"], _W["cyh"],
                               _W["tail"], _W["g"])
    hist, over, worst = collections.Counter(), 0, 0
    for i in range(lo, hi):
        px, py = pos[i]
        for a in range(72):
            u = pm._state_units(solid, px, py, a, cyh)
            if g:
                u.append((0, g, g))         # the enemy pass, room then charge
            acc = 0
            for _ in range(3):
                w, _wo, acc = pm.segments(u, acc, tail=tail, n=99)
            hist[w] += 1
            worst = max(worst, sum(c for _, _, c in u))
            if w >= pm.PACE_FRAMES:
                over += 1
    return hist, over, worst


def run(cguard, ovr=None, jobs=None):
    import multiprocessing as mp
    jobs = jobs or os.cpu_count()
    _solid, pos = pacescan.positions()
    step = max(1, len(pos) // (jobs * 8))
    tasks = [(i, min(i + step, len(pos)), pos)
             for i in range(0, len(pos), step)]
    hist, over, worst = collections.Counter(), 0, 0
    with mp.Pool(jobs, initializer=_init,
                 initargs=(cguard, ovr)) as p:
        for h, o, w in p.imap_unordered(_chunk, tasks):
            hist.update(h)
            over += o
            worst = max(worst, w)
    return hist, over, worst


def main(argv):
    import pacemodel as pm
    quads = [int(v) for v in argv] or [pm.C_QUAD]
    print(f"PACE_FRAMES {pm.PACE_FRAMES}  C_GUN {pm.C_GUN}  "
          f"budget {pm.PACE_FRAMES * 19456} us, "
          f"{len(pacescan.positions()[1]) * 72} states, exhaustive")
    print("\n  C_QUAD  C_GUARD   6 waits   worst charge   LOCKED")
    for cq in quads:
        ovr = {"C_QUAD": cq}
        for g in (0, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 12000):
            _h, over, worst = run(g, ovr)
            print("  %6d  %7d  %8d   %12d   %s"
                  % (cq, g, over, worst, "yes" if over == 0 else "NO"))
            if over:
                break
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
