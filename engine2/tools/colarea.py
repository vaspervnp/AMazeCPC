"""WHAT DOES THE COLUMN RENDERER COST, OVER EVERY STATE A PLAYER CAN REACH?

engine2/tools/wallarea.py asks this of the span renderer -- how many bytes
does it WRITE, how many scanline runs does it set up.  This asks it of
engine2/tools/colmodel.py: how many column PAIRS survive the front-to-back
done-flag, and how many bytes those pairs paint.

    python3 engine2/tools/colarea.py [nstates|all] [jobs]

The two are directly comparable because both walk the same quad lists off
the same march and projector, over the same 24/256 movement lattice x 72
headings pacescan.py sweeps, and both are costed with per-byte and
per-setup numbers MEASURED on a booted 6128 by emu_byte.py.

    span   2.000 us/byte written  +  19.75 us per scanline run
    column 10.125 us/byte written +  C_SETUP us per column pair

The span renderer's per-byte cost is the PUSH DE floor and cannot be
beaten; the column renderer's is five times it, because SP has to be
reloaded every scanline and the texture has to be sampled and stepped.
What column order gets back is the OVERDRAW (a pair is finished the moment
a face covers it floor to ceiling) and the per-scanline setup.  This
counts which way that trade actually falls.
"""

import collections
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# MEASURED, engine2/tools/emu_byte.py, slope over 96 and 192 bytes with the
# 100-NOP calibration exact to 100.001 us.  See colmodel.py's header for
# the decomposition of the 20.25 us a scanline of a pair costs.
US_BYTE_COL = 10.125
US_BYTE_SPAN = 2.000
US_RUN_SPAN = 19.75

# The per-pair setup is not measured yet -- the routine does not exist --
# so this is the INSTRUCTION-COUNT estimate that the asm has to beat:
# the u divide (4 restoring steps), the CTAB lookup, the h Bresenham, the
# screen address, and the done-flag test.  emu_rast.py replaces it with a
# measurement the moment raster_col is built.
US_PAIR_SETUP = 150.0

_W = {}


def _init():
    import pacescan
    import rastermodel as rm
    import colmodel
    solid, pos = pacescan.positions()
    _W["solid"] = solid
    _W["pos"] = pos
    _W["rm"] = rm
    _W["cm"] = colmodel
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
            out.append(q + (1 if door else 0, k))
    return out


def _one(px, py, a):
    """-> (col_bytes, col_pairs, span_bytes, span_runs, nq).

    The column walk is colmodel's own -- the same generator render() uses,
    so what is counted here is what the Z80 will be asked to draw and not
    an idealisation of it.
    """
    rm, cm, c = _W["rm"], _W["cm"], _W["cfg"]
    quads = _quads(px, py, a)
    cover = cm.new_cover(c)
    cbytes = cpairs = 0
    for q in reversed(quads):            # painter order backwards = near first
        for (_p, _u, _j, _r0, _r1, _s, bands, _st,
             edges, _r0t, _r1t) in cm.face_columns(q, c, cover):
            for b0, b1, _ix in bands:
                cpairs += 1
                cbytes += 2 * (b1 - b0 + 1)
            for e0, e1, _ix, _o in edges:
                cbytes += e1 - e0 + 1
    sbytes = sruns = 0
    for q in quads:
        for (_row, _end, npush) in rm.raster_quad(q, c):
            sbytes += 2 * npush
            sruns += 1
    return cbytes, cpairs, sbytes, sruns, len(quads)


def _cost_col(cbytes, cpairs):
    return cbytes * US_BYTE_COL + cpairs * US_PAIR_SETUP


def _cost_span(sbytes, sruns):
    return sbytes * US_BYTE_SPAN + sruns * US_RUN_SPAN


def _chunk(args):
    lo, hi, step = args
    pos = _W["pos"]
    best = {k: (0, None) for k in
            ("cbytes", "cpairs", "sbytes", "sruns", "ccost", "scost", "nq")}
    hist = collections.Counter()
    tot = 0
    sums = collections.Counter()
    for i in range(lo, hi, step):
        px, py = pos[i]
        for a in range(72):
            cb, cp, sb, sr, nq = _one(px, py, a)
            cc, sc = _cost_col(cb, cp), _cost_span(sb, sr)
            tot += 1
            for k, v in (("cbytes", cb), ("cpairs", cp), ("sbytes", sb),
                         ("sruns", sr), ("ccost", cc), ("scost", sc),
                         ("nq", nq)):
                sums[k] += v
                if v > best[k][0]:
                    best[k] = (v, (px, py, a))
            hist[int(cc) // 1000] += 1
    return best, hist, tot, sums


def main():
    import multiprocessing as mp
    arg = sys.argv[1] if len(sys.argv) > 1 else "20000"
    jobs = int(sys.argv[2]) if len(sys.argv) > 2 else (os.cpu_count() or 4)
    _init()
    pos = _W["pos"]
    c = _W["cfg"]
    npos = len(pos)
    step = 1 if arg == "all" else max(1, (npos * 72) // int(arg))
    scanned = len(range(0, npos, step)) * 72
    print(f"viewport {c.VP_BW}x{c.VP_H} = {c.VP_BW * c.VP_H} bytes, "
          f"{c.VP_BW // 2} column pairs")
    print(f"{npos} standable positions x 72 headings = {npos * 72} states; "
          f"scanning every {step}th position = {scanned} states on {jobs} "
          f"cores")
    print(f"costs: column {US_BYTE_COL} us/byte + {US_PAIR_SETUP} us/pair "
          f"(setup ESTIMATED)   span {US_BYTE_SPAN} us/byte + "
          f"{US_RUN_SPAN} us/run")

    bounds = [(i * npos // jobs, (i + 1) * npos // jobs, step)
              for i in range(jobs)]
    with mp.Pool(jobs, initializer=_init) as p:
        res = p.map(_chunk, bounds)

    best = {k: (0, None) for k in
            ("cbytes", "cpairs", "sbytes", "sruns", "ccost", "scost", "nq")}
    hist = collections.Counter()
    tot = 0
    sums = collections.Counter()
    for b, h, t, s in res:
        for k in best:
            if b[k][0] > best[k][0]:
                best[k] = b[k]
        hist.update(h)
        sums.update(s)
        tot += t

    area = c.VP_BW * c.VP_H
    print(f"\nscanned {tot} states\n")
    print("  %-42s %8s   %s" % ("worst over the scan", "value", "state"))
    for k, label in (
            ("nq", "quads in the frame"),
            ("sbytes", "SPAN   bytes written (overdraw counted)"),
            ("sruns", "SPAN   scanline runs"),
            ("scost", "SPAN   us"),
            ("cbytes", "COLUMN bytes written"),
            ("cpairs", "COLUMN pairs set up"),
            ("ccost", "COLUMN us")):
        v, st = best[k]
        extra = ""
        if k in ("sbytes", "cbytes"):
            extra = f"  = {100.0 * v / area:5.1f}% of the viewport"
        print("  %-42s %8.0f%s   at %s" % (label, v, extra, st))

    print("\n  means over the scan:")
    print("    span   %7.0f bytes  %6.1f runs   %8.1f us"
          % (sums["sbytes"] / tot, sums["sruns"] / tot, sums["scost"] / tot))
    print("    column %7.0f bytes  %6.1f pairs  %8.1f us"
          % (sums["cbytes"] / tot, sums["cpairs"] / tot, sums["ccost"] / tot))
    print("    ratio  column / span = %.2fx mean, %.2fx worst"
          % (sums["ccost"] / max(1.0, sums["scost"]),
             best["ccost"][0] / max(1.0, best["scost"][0])))


if __name__ == "__main__":
    main()
