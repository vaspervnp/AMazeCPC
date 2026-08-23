"""MEASURE the frame period of the BOOTED disc over a state set that is
CHOSEN, not merely sampled -- and report the whole distribution.

    python3 engine2/tools/emu_pace3.py [nrandom] [nworst] [nwalk]

emu_pace.py samples the 24/256 lattice uniformly, which is the right thing
when nothing is known about where the failures are.  Something IS known
here: engine2/tools/pacemodel.py replays the accumulator's own rule
offline and can therefore NAME the states whose charge asks for the most
vsync waits, and those are the only ones that can push a frame into an
extra period.  A uniform sample of 1400 out of 4328640 reachable states
finds a 0.1% failure set with probability ~0.8 per run and can easily
report a clean 100.00% while the defect is sitting there.

So this harness measures, for whatever PACE_FRAMES and viewport the source
is currently set to:

    the model's WORST states by wait count, exhaustively over the top tier
    + states reached by HOLDING KEYS from random starts
    + a uniform sample of the 24/256 lattice x 72 headings
    + every state named in emu_pace.py's OUTLIERS / OFFGRID / SPILL

and prints the FULL histogram of measured periods -- every distinct raw
reading, bucketed by vsync count -- plus, per class, how many states were
off PACE_FRAMES.  "Locked" means one bucket and it is PACE_FRAMES.
"""

import collections
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import emu_pace as ep                                          # noqa: E402

VSYNC_MS = ep.VSYNC_MS


def scan_worst(nkeep=40):
    """The states pacescan.py's EXHAUSTIVE pass named, if it has been run.

    model_worst below scans 20000 states out of 4055040, and main3.asm's
    PACING note records what that costs: benched at the 40 heaviest states
    a SAMPLED replay can find, the disc read 90.63 ms, against 99.50 at the
    40 pacescan.py names -- the sample understates the worst frame by 7.6
    ms, because the worst frame in a four-million-state space is not in a
    twenty-thousand-state sample of it.

    So the sweep measures BOTH lists and reports them as separate classes.
    This one is the exhaustive answer and is the one that matters; it is
    just a file, written by `pacescan.py`, so re-run that after any change
    to a C_* or to the viewport and this list follows.
    """
    import json
    p = os.path.join(os.path.dirname(_HERE), "build", "pacescan_top.json")
    if not os.path.exists(p):
        return []
    return [(px, py, a) for _c, px, py, a in json.load(open(p))][:nkeep]


def model_worst(nkeep=60, nscan=20000, seed=4711):
    """The states the OFFLINE replay says ask for the most waits.

    Returns (states, histogram of waits over the scan).  The replay uses
    the same C_* constants the Z80 does and charges them in the same
    order, so the wait count it reports is the one the machine will take
    -- this is a search, not an estimate, and every state it hands back is
    then MEASURED on the disc like any other.
    """
    import pacemodel as pm
    import emu_frame as ef
    import rastermodel as rm
    grid, solid = ef.load()
    cyh = rm.cfg().CYH
    offs = ep.lattice_offsets()
    pool = []
    for (cx, cy) in ef.floors(grid):
        for ox in offs:
            for oy in offs:
                px, py = (cx << 8) | ox, (cy << 8) | oy
                if ef.reachable(solid, px, py, 64):
                    pool.append((px, py))
    rnd = random.Random(seed)
    hist = collections.Counter()
    scored = []
    tail = pm.C_TAIL + pm.C_DOORACT      # the pessimistic frame: SPACE held
    for _ in range(nscan):
        px, py = rnd.choice(pool)
        a = rnd.randrange(72)
        u = pm._state_units(solid, px, py, a, cyh)
        acc = 0
        for _ in range(3):               # settle the carry-over
            waits, _w, acc = pm.segments(u, acc, tail=tail, n=99)
        hist[waits] += 1
        scored.append((waits, sum(c for _, _, c in u), px, py, a))
    scored.sort(reverse=True)
    return [(px, py, a) for _w, _c, px, py, a in scored[:nkeep]], hist, scored


def sweep(nrandom=900, nworst=60, nwalk=90, nscan=20000, seed=8191):
    import pacemodel as pm
    print(f"PACE_FRAMES {ep.PACE_N}   viewport {_vp()}"
          + (f"   COURSES 1, C_JOINT {pm.C_JOINT} per face k<={pm.JOINT_KMAX}"
             if pm.COURSES else "   COURSES 0 (flat walls)"))
    print(f"offline replay: scanning {nscan} states for the worst packers")
    worst, whist, scored = model_worst(nworst, nscan)
    tot = sum(whist.values())
    print("  waits the accumulator asks for (uncapped, offline):")
    for k in sorted(whist):
        print(f"     {k}  {whist[k]:6d}  {100.0*whist[k]/tot:6.3f}%"
              f"   -> {k+1} periods")
    need = max(whist)
    print(f"  worst offline: {need} waits = {need+1} periods; "
          f"PACE_FRAMES is {ep.PACE_N}"
          + ("  OK" if need < ep.PACE_N else "  <-- OVER BUDGET"))
    print(f"  worst charged frame {scored[0][1]} us against a budget of "
          f"{ep.PACE_N * pm.THRESH} us\n")

    g = ep.Rig()
    rnd = random.Random(seed)
    offs = ep.lattice_offsets()
    pool = [((cx << 8) | ox, (cy << 8) | oy, a)
            for cy in range(16) for cx in range(16)
            for ox in offs for oy in offs for a in range(72)
            if ep.reachable(g.solid, (cx << 8) | ox, (cy << 8) | oy)]
    named = ([((cx << 8) | 128, (cy << 8) | 128, a)
              for cx, cy, a in ep.OUTLIERS]
             + list(ep.OFFGRID) + list(ep.SPILL))
    walked = g.walked(nwalk)
    sampled = rnd.sample(pool, min(nrandom, len(pool)))
    scanned = scan_worst()
    if not scanned:
        print("  NO engine2/build/pacescan_top.json -- the exhaustive worst"
              " states are NOT being measured.  Run pacescan.py first.")
    classes = [("scan-worst", scanned), ("model-worst", worst),
               ("named", named), ("walked", walked), ("sampled", sampled)]
    classes = [(n, s) for n, s in classes if s]
    ntot = sum(len(s) for _n, s in classes)
    print(f"MEASURING {ntot} states on the booted disc, "
          f"period sampled at 250 us and NOT rounded")

    hist = collections.Counter()
    perclass = {}
    bad = []
    for cname, sts in classes:
        ch, nbad = collections.Counter(), 0
        for px, py, a in sts:
            g.place(px, py, a)
            per = g.periods()
            if not per:
                continue
            for p in per:
                hist[round(p, 1)] += 1
                ch[round(p / VSYNC_MS)] += 1
            ok = (all(abs(p / VSYNC_MS - round(p / VSYNC_MS)) < 0.06
                      for p in per)
                  and max(per) - min(per) < 0.6
                  and all(round(p / VSYNC_MS) == ep.PACE_N for p in per))
            if not ok:
                nbad += 1
                bad.append((cname, px, py, a, per))
        perclass[cname] = (len(sts), ch, nbad)
        print(f"  {cname:12s} {len(sts):5d} states  "
              + "  ".join(f"{v}v x{c}" for v, c in sorted(ch.items()))
              + (f"   {nbad} OFF {ep.PACE_N}" if nbad else "   all on pace"))

    n = sum(hist.values())
    print(f"\n=== PERIOD, {n} game frames, FULL distribution")
    vs = collections.defaultdict(list)
    for p, c in hist.items():
        vs[int(round(p / VSYNC_MS))] += [p] * c
    for v in sorted(vs):
        raw = vs[v]
        fps = f"{1000.0/(v*VSYNC_MS):5.2f} fps" if v else "  -- fps"
        print(f"    {v} vsyncs = {v*VSYNC_MS:6.2f} ms = "
              f"{fps}   {len(raw):6d}  "
              f"{100.0*len(raw)/n:7.3f}%   (raw {min(raw):.1f}..{max(raw):.1f})")
    locked = len(vs) == 1 and sorted(vs)[0] == ep.PACE_N and not bad
    print(f"\n    LOCKED: {locked}")
    if bad:
        print(f"    {len(bad)} states off {ep.PACE_N} vsyncs:")
        for cname, px, py, a, per in bad[:24]:
            print(f"      {cname:12s} (0x{px:04X}, 0x{py:04X}, {a}),   "
                  f"{sorted(set(round(p,1) for p in per))} ms")
    return 0 if locked else 1


def _vp():
    import gentab
    v = gentab.load_vpcfg()
    return f"{v['VP_BW']}x{v['VP_H']} bytes at ({v['VP_BX']},{v['VP_Y']})"


if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:]]
    raise SystemExit(sweep(*(a + [900, 60, 90][len(a):])))
