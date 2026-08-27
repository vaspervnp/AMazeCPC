"""EXHAUSTIVE replay of the pacing rule over the WHOLE reachable state
space -- every open position on the 24/256 movement lattice, every heading.

    python3 engine2/tools/pacescan.py [jobs]

WHY EXHAUSTIVE AND NOT SAMPLED.  pacemodel.py replays a random sample,
which answers "what does a typical frame ask for".  That is not the
question the period turns on.  The period is decided by the states that
ask for ONE MORE WAIT THAN THE BUDGET HAS, and MEASURED here those are
three states in a million -- a 3000-state sample sees them with
probability 0.009, and a sample that misses them reports a clean sweep.
Every "locked" claim this project has had to withdraw was withdrawn
because a sampler did not visit the state that broke it.

There is no need to sample: the space is 4.05 million states, the replay
is ~11000 states a second per core, and sixteen cores finish it in under
a minute.  So this counts them all and prints, exactly:

    how many states in the whole space ask for k waits, for every k

and names every state that asks for more than PACE_FRAMES-1, which is
the set that would sit at PACE_FRAMES+1 periods on the disc.

THE REACHABILITY RULE IS game.asm's, not the sweep's circle.  coll_free
tests the 2x2 cell block the PRAD box touches, so it rejects a diagonal
whenever both overlaps are non-zero; emu_pace.reachable's circle test
keeps states the game cannot stand in (60120 positions against 56320).
Scanning the larger set would condemn a configuration for a state no
player can reach.
"""

import collections
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

PRAD = 64                       # game.asm's collision half-width, 8.8
NTOP = 40                       # worst-charged states kept, for benching
DOOR_SHUT = 2                   # SOLID's code for a shut door (game.asm)


def coll_free(solid, px, py):
    """game.asm:coll_free -- the 2x2 cell block the PRAD box touches, all
    of it clear of SOLID.  This is the movement rule itself, so the set it
    accepts is exactly the set a player can stand in."""
    x0, x1 = (px - PRAD) >> 8, (px + PRAD) >> 8
    y0, y1 = (py - PRAD) >> 8, (py + PRAD) >> 8
    for cy in (y0, y1):
        for cx in (x0, x1):
            if not (0 <= cx < 16 and 0 <= cy < 16) or solid[cy * 16 + cx]:
                return False
    return True


DOORMOV = 3                     # a door part way open (march.asm)

CONFIGS = ((0, "ALL SHUT -- the map as it loads"),
           (None, "ALL OPEN -- the flood sees through every doorway"),
           (DOORMOV, "ALL MOVING -- see-through AND still drawn"))


def open_doors(solid, code=0):
    """-> a copy of SOLID with every shut door (2) set to `code`.

    THE HEAVY CASE THE SWEEP NEVER SAW.  This file builds SOLID straight
    from the map, where every door reads 2 -- i.e. SHUT and opaque -- so
    for its whole life it swept only frames in which the flood stops at
    every doorway.  A door the player has opened is transparent, the
    flood pours through it into the next room, and the frame is much
    bigger: MEASURED exhaustively, cells popped 16 -> 36, quads 8 -> 14,
    and bucket 7 goes from 4.07% of states to 44.25%.  Those are the
    worst frames in the game and none of them was ever replayed.
    """
    return bytes(code if v == DOOR_SHUT else v for v in solid)


def positions(doors=0):
    """doors: 0 leaves them shut, None opens them, DOORMOV puts them
    part way -- which is the HEAVIEST of the three, because the flood
    goes through the doorway AND the door itself is still filed as a
    face.  Neither of the other two sweeps covers that."""
    import emu_frame as ef
    import emu_pace as ep
    _grid, solid = ef.load()
    if doors != 0:
        solid = open_doors(solid, 0 if doors is None else doors)
    offs = ep.lattice_offsets()
    out = []
    for cy in range(16):
        for cx in range(16):
            for ox in offs:
                for oy in offs:
                    px, py = (cx << 8) | ox, (cy << 8) | oy
                    if coll_free(solid, px, py):
                        out.append((px, py))
    return solid, out


_W = {}


def _init(ovr=None, doors=0):
    import pacemodel as pm
    import rastermodel as rm
    solid, _pos = positions(doors)
    # THE ONLY WAY THIS MODEL'S CONSTANTS EVER DIFFER FROM THE DISC'S.
    # pacemodel reads every C_* out of main3.asm on import; `sweep` below
    # needs to ask what a DIFFERENT C_QUAD would do without rebuilding
    # fourteen discs, so it passes the candidate in as an initargs dict.
    #
    # IT USED TO PASS IT THROUGH os.environ, AND THAT SILENTLY DID
    # NOTHING.  Python 3.14 starts pools with FORKSERVER on Linux, not
    # fork: the server process is created once, at the first Pool, and
    # every later worker is forked from THAT -- so it carries the
    # environment as it stood at the first Pool and never sees a later
    # change.  The sweep duly printed fourteen candidates with byte-
    # identical results, all of them the first candidate's.  initargs
    # travel with the task, so they do not care how the pool is started.
    for _n, _v in (ovr or {}).items():
        setattr(pm, _n, _v)
    _W["solid"] = solid
    _W["cyh"] = rm.cfg().CYH
    _W["pm"] = pm
    _W["_rm"] = rm
    pm._rm = rm
    _W["tail"] = (pm.C_TAIL + pm.C_SND + pm.C_DOORACT + pm.C_AMMO + pm.C_SCAN
              + pm.C_SWEEP + 8 * pm.C_BLIP + pm.C_RNEEDLE)


def _chunk(args):
    lo, hi, pos = args
    pm, solid, cyh, tail = _W["pm"], _W["solid"], _W["cyh"], _W["tail"]
    hist = collections.Counter()
    over, top = [], []
    worst = None
    for i in range(lo, hi):
        px, py = pos[i]
        for a in range(72):
            u = pm._state_units(solid, px, py, a, cyh)
            acc = 0
            for _ in range(3):              # settle the carry-over
                w, _wo, acc = pm.segments(u, acc, tail=tail, n=99)
            hist[w] += 1
            tot = sum(c for _, _, c in u)
            if worst is None or tot > worst[0]:
                worst = (tot, px, py, a)
            top.append((tot, px, py, a))
            if len(top) > 4000:
                top.sort(reverse=True)
                del top[NTOP:]
            if w >= pm.PACE_FRAMES:
                over.append((w, tot, px, py, a))
    top.sort(reverse=True)
    return hist, over, worst, top[:NTOP]


def sweep(jobs=None):
    """HOW BIG CAN pace_quad's CHARGE BE AND STILL LOCK?

    The two things wanted of C_QUAD / C_QS pull opposite ways.  Bigger is
    SAFER -- the charge has to dominate the real quad, and the real quad
    grows with the viewport width while C_QUAD does not.  Bigger is also
    SLOWER to pack: raise it far enough and the greedy rule asks for one
    more wait than the budget has, on a handful of states out of four
    million, and those states sit a whole period late.

    So the answer is not a fitted number, it is the LARGEST charge with
    zero over-budget states, and finding it needs the exhaustive count at
    each candidate -- which is a minute a candidate, not a rebuild.
    """
    import multiprocessing as mp
    import pacemodel as pm
    jobs = jobs or os.cpu_count()
    _solid, pos = positions()
    step = max(1, len(pos) // (jobs * 8))
    tasks = [(i, min(i + step, len(pos)), pos)
             for i in range(0, len(pos), step)]
    print(f"PACE_FRAMES {pm.PACE_FRAMES}  C_BG {pm.C_BG}  "
          f"COURSES {pm.COURSES}"
          + (f" (C_JOINT {pm.C_JOINT}, k<={pm.JOINT_KMAX})"
             if pm.COURSES else "")
          + f"  {len(pos)*72} states, exhaustive, per candidate\n")
    # ...with the two wait counts NAMED, not spelled 5 and 6: they are
    # PACE_FRAMES-1 (the last count that fits) and PACE_FRAMES (the first
    # that does not), and the literals were left behind at 6 when
    # PACE_FRAMES moved, so the columns were labelled for a budget the
    # scan was not using.
    print("  C_QUAD  C_QS" + ("%d waits" % (pm.PACE_FRAMES - 1)).rjust(11)
          + ("%d waits" % pm.PACE_FRAMES).rjust(13)
          + "   worst charge   LOCKED   NEEDS")
    best = None
    needs = {}
    for cq in (740, 780, 820, 860, 900, 920, 960):
        for cs in (22, 23):
            ovr = {"C_QUAD": cq, "C_QS": cs}
            hist = collections.Counter()
            over, worst = 0, 0
            with mp.Pool(jobs, initializer=_init, initargs=(ovr,)) as p:
                for h, o, w, _t in p.imap_unordered(_chunk, tasks):
                    hist.update(h)
                    over += len(o)
                    worst = max(worst, w[0] if w else 0)
            ok = over == 0
            # THE SMALLEST BUDGET THIS CANDIDATE WOULD LOCK AT, which is
            # free: `segments` is replayed UNCAPPED (n=99), so the wait
            # histogram does not depend on PACE_FRAMES at all, and the
            # worst state's wait count plus the drain IS the period the
            # disc would run.  Without this column the sweep can only say
            # "no" -- it answers "does the CURRENT budget hold" and leaves
            # "then what does" to another twenty-minute run per candidate.
            need = max(hist) + 1
            needs[(cq, cs)] = need
            print("  %6d  %4d  %9d  %11d   %12d   %s   %d"
                  % (cq, cs, hist[pm.PACE_FRAMES - 1], over, worst,
                     "yes" if ok else "NO ", need))
            if ok and (best is None or (cq, cs) > best):
                best = (cq, cs)
    print(f"\n  largest charge that still locks: C_QUAD {best[0]} "
          f"C_QS {best[1]}" if best else "\n  NOTHING LOCKS at PACE_FRAMES "
          f"{pm.PACE_FRAMES}")
    if not best:
        # ...so say what WOULD, rather than leaving the reader to re-run.
        fits = min(needs.values())
        big = max(k for k, v in needs.items() if v == fits)
        print(f"  the smallest budget any candidate locks at is "
              f"PACE_FRAMES {fits} ({fits*19.968:.2f} ms, "
              f"{1000/(fits*19.968):.2f} fps), and the largest charge that"
              f" locks there is C_QUAD {big[0]} C_QS {big[1]}")
    return 0 if best else 1


def main(jobs=None):
    """Sweep BOTH door configurations and fail if either misses.

    A door the player has opened is transparent to the march, so the
    flood pours through the doorway and the frame grows -- see
    open_doors().  Sweeping only the map's own SOLID, in which every
    door is shut, replays the LIGHT half of the game.
    """
    rc = 0
    for code, label in CONFIGS:
        print("\n" + "=" * 68)
        print("DOORS " + label)
        print("=" * 68)
        rc |= _main_one(jobs, code)
    return rc


def _main_one(jobs=None, doors=0):
    import multiprocessing as mp
    import pacemodel as pm
    jobs = jobs or os.cpu_count()
    solid, pos = positions(doors)
    print(f"PACE_FRAMES {pm.PACE_FRAMES}  C_BG {pm.C_BG}  "
          f"C_QUAD {pm.C_QUAD}/{pm.C_QS}/{pm.C_QW}  RQ_SPLIT {pm.RQ_SPLIT}")
    # ...AND WHICH WALLS.  This line did not say, and for the whole of the
    # COURSES 1 era it printed a flat-wall answer under a masonry build's
    # name -- see pacemodel.joint_units.  A report that does not name the
    # build it scanned cannot be caught being about the wrong one.
    print(f"COURSES {pm.COURSES}"
          + (f"  C_JOINT {pm.C_JOINT} per face, k<={pm.JOINT_KMAX}, "
             f"kind 0 only" if pm.COURSES else "  (flat walls)"))
    print(f"{len(pos)} standable positions (game.asm's box rule) x 72 "
          f"headings = {len(pos)*72} states -- ALL of them")
    step = max(1, len(pos) // (jobs * 8))
    tasks = [(i, min(i + step, len(pos)), pos)
             for i in range(0, len(pos), step)]
    hist = collections.Counter()
    over, tops = [], []
    with mp.Pool(jobs, initializer=_init, initargs=(None, doors)) as p:
        for h, o, _w, t in p.imap_unordered(_chunk, tasks):
            hist.update(h)
            over += o
            tops += t
    tops.sort(reverse=True)
    tops = tops[:NTOP]
    worst = tops[0][0]
    tot = sum(hist.values())
    print("\nwaits the accumulator asks for, EXHAUSTIVE:")
    for k in sorted(hist):
        print(f"   {k} waits  {hist[k]:9d}  {100.0*hist[k]/tot:9.5f}%"
              f"   -> {k+1} periods"
              + ("" if k < pm.PACE_FRAMES else "   <-- OVER BUDGET"))
    print(f"worst charged frame {worst} us against a budget of "
          f"{pm.PACE_FRAMES * pm.THRESH} us")
    # ...and NAME them, because the slack figure is about the worst frame
    # and a benchmark that samples the lattice will not contain it.  Feed
    # these to emu_pacefit.py, which measures what they really cost.
    print(f"the {len(tops)} most expensive states in the maze:")
    print("  " + " ".join(f"({px:04X},{py:04X})h{a}"
                          for _c, px, py, a in tops[:12]))
    import json
    json.dump([[c, px, py, a] for c, px, py, a in tops],
              open(os.path.join(os.path.dirname(_HERE), "build",
                                "pacescan_top_%s.json"
                                % {0: "shut", None: "open",
                                   DOORMOV: "moving"}[doors]), "w"))
    over.sort(reverse=True)
    print(f"\n{len(over)} states of {tot} would take "
          f"{pm.PACE_FRAMES+1} periods")
    for w, c, px, py, a in over[:40]:
        print(f"    (0x{px:04X}, 0x{py:04X}, {a}),   {w} waits, "
              f"charged {c} us")
    return 0 if not over else 1


if __name__ == "__main__":
    _a = sys.argv[1:]
    _j = int([x for x in _a if x.isdigit()][0]) if any(
        x.isdigit() for x in _a) else None
    raise SystemExit(sweep(_j) if "sweep" in _a else main(_j))
