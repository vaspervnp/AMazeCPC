"""SAMPLE THE PROGRAM COUNTER while the column renderer runs, and say
where the microseconds actually are.

    python3 engine2/tools/pcprof.py [nstates]

WHY THIS EXISTS.  Twice now a saving has been estimated from reading the
code and been wrong by a large factor -- most recently a level-of-detail
path costed at 22.6% of the rasteriser that measured 2.9%, because the
per-pair setup it removed turned out to be 258 us of a 1800 us pair and
the other 1540 was somewhere else entirely.  "Somewhere else" is not a
place you can optimise.  This finds it.

METHOD.  Run one whole raster_colframe with the emulator stepping in
small slices, sample the PC after each, and bucket the samples by the
nearest preceding symbol.  A sample is worth the time the slice took, so
the histogram is in microseconds and not in visits -- a two-instruction
loop entered ten thousand times and a long straight run both show up at
their true cost.

The symbols come from the harness's own .sym file, so the buckets are
whatever rastcol.asm calls things; no address is written down here.
"""

import os
import sys
import collections

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                                "AMazeCPC", "tools"))


def symbolise(sym):
    """-> a sorted [(addr, name)] for bisecting a PC onto a symbol."""
    out = sorted((a, n) for n, a in sym.items())
    return [a for a, _ in out], [n for _, n in out]


def profile(nstates=6, slice_us=2, seed=99):
    import bisect
    import emu_rcol as E

    rig = E.Rig(paced=False)
    addrs, names = symbolise(rig.sym)
    hist = collections.Counter()
    total = 0.0

    for px, py, a, qs in E._states(nstates, seed):
        rig.c.write_ram(E.FRONT, rig.blank)
        rig.poke_quads(qs)
        rig.c.poke(rig.s("DONE"), 0)
        rig.c.set_pc(E.E_MANY)
        for _ in range(400000):
            t = rig.c.run_us(slice_us)
            us = t / 4.0
            pc = rig.c.pc
            i = bisect.bisect_right(addrs, pc) - 1
            if i >= 0:
                hist[names[i]] += us
                total += us
            if rig.c.peek(rig.s("DONE")) == 0xFF:
                break

    # ---- GROUP, because the flat list is thirty symbols of 1-3% and
    #      the question is which PHASE to attack, not which label.
    FILL = ("COLBLK", "COLTAIL", "RC_TAILEND", "RC_BTAIL", "RC_BGO10",
            "RC_BLKEND", "RC_GO")
    BAND = ("RC_BAND", "RC_BUF")
    EDGE = ("RC_EDGE", "RC_EBUF", "RC_NOUP", "RC_NODN", "RC_EDONE",
            "RC_ETROWS", "RC_ETSML", "RC_ETBIG", "RC_ET1OK", "RC_EU1",
            "RC_EUGO", "RC_ED1", "RC_NOEDGE")
    HARNESS = ("RI_L", "RASTER_INIT", "SETUP", "ROMOFF", "E_MANY",
               "E_SPIN", "RASTER_SETBUF", "RS_L")
    grp = collections.Counter()
    for n, us in hist.items():
        if n in FILL:
            grp["fill (COLBLK/COLTAIL)"] += us
        elif n in BAND:
            grp["band setup"] += us
        elif n in EDGE:
            grp["edge runs"] += us
        elif n in HARNESS:
            grp["harness (not the renderer)"] += us
        else:
            grp["per-pair / per-face SETUP"] += us
    eng = total - grp["harness (not the renderer)"]
    print(f"\n{nstates} states, {slice_us} us slices, "
          f"{total:.0f} us sampled, {eng:.0f} us in the renderer\n")
    print("%-30s %10s %8s" % ("phase", "us", "of render"))
    for k, v in grp.most_common():
        if k.startswith("harness"):
            continue
        print("%-30s %10.0f %7.1f%%" % (k, v, 100.0 * v / eng))
    print("%-30s %10.0f" % ("(harness, excluded)",
                            grp["harness (not the renderer)"]))
    print()

    print(f"{nstates} states, {slice_us} us slices, "
          f"{total:.0f} us of samples\n")
    print("%-14s %10s %7s" % ("symbol", "us", "share"))
    shown = 0.0
    for name, us in hist.most_common(24):
        print("%-14s %10.0f %6.1f%%" % (name, us, 100.0 * us / total))
        shown += us
    print("%-14s %10.0f %6.1f%%" % ("(rest)", total - shown,
                                    100.0 * (total - shown) / total))
    return hist


if __name__ == "__main__":
    _a = [x for x in sys.argv[1:] if x.isdigit()]
    profile(int(_a[0]) if _a else 6)
