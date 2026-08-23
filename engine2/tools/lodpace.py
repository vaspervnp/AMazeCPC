"""WHAT DOES THE HYBRID LOD TEXTURE DO TO THE FRAME PERIOD?

lodscan.py prices the wall fill with a linear model.  This runs the REAL
question through the REAL instrument: pacemodel.py's cost accumulator,
replayed over all 4 055 040 states by pacescan.py's machinery, with
raster_quad's charge changed to what a generated (textured) PUSH block
would cost on faces at k <= KTEX.

Two things only this can answer, and both of them decide the architecture:

  1. THE LARGEST ATOMIC UNIT.  RQ_SPLIT is 0, so a whole quad is ONE unit
     the accumulator cannot yield inside.  A near quad charged at 3.5
     us/byte instead of 2.0 is 1.75x on its byte term, and if that unit
     passes THRESH = 19456 us the frame stops fitting in whole vsync
     periods however much total slack there is.
  2. HOW MANY STATES OUT OF FOUR MILLION ask for one more wait than the
     budget has.  That is a three-in-a-million question in this project's
     history and sampling has already got it wrong twice.

    python3 engine2/tools/lodpace.py [KTEX] [C_GENV] [C_JOINTC] [jobs]

KTEX     texture faces at k <= this (0 = nothing, the shipped build)
C_GENV   us charged per textured face for building its block
C_JOINTC us charged per textured face for the horizontal course joints
"""

import collections
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import pacescan                                             # noqa: E402


def quad_units_tex(q, cyh=None):
    """pacemodel.quad_units with a per-depth byte rate.

    RQ_SPLIT 0 branch only -- which is the shipped build.  The charge is
    raster.asm's own: C_QUAD once, then per scanline C_QS plus the run's
    bytes, plus C_QW for each wedge row PAIR's Bresenham.  The only change
    is that a face at k <= KTEX pays US_IMM per byte instead of US_FLAT,
    and carries a fixed per-face charge for generating its block.
    """
    import pacemodel as pm
    import rastermodel as _rm
    cyh = cyh or _rm.cfg().CYH
    blo, bhi, hlo, hhi, _kind, k = q
    bw = abs(bhi - blo)
    jlo = cyh if hlo >= cyh * 16 else (hlo >> 4)
    jhi = min(cyh, hhi >> 4)
    tex = k <= pm.KTEX
    # us per scanline of run: 2.0 us/byte flat, 3.5 us/byte generated.
    # Round UP -- the model's rule is est >= actual for every unit.
    per = math.ceil(3.5 * bw) if tex else 2 * bw
    fixed = (pm.C_GENV + pm.C_JOINTC) if tex else 0
    return [pm.C_QUAD + fixed + (jlo + jhi) * (pm.C_QS + per)
            + pm.C_QW * (jhi - jlo)]


def quad_units_tex_split(q, cyh=None):
    """the same for RQ_SPLIT 1 -- raster.asm's mid-quad yield.

    The point of asking is that RQ_SPLIT 0 makes a whole quad ONE unit,
    and a textured near quad is 1.75x on its byte term.  If that unit
    approaches THRESH the greedy packer cannot fill around it and states
    start asking for an extra wait even though the frame TOTAL still fits.
    Chunking is the standing fix; it costs C_CHUNK per chunk.
    """
    import pacemodel as pm
    import rastermodel as _rm
    sh = _rm.quad_shape(q)
    tex = q[5] <= pm.KTEX
    per = 7 if tex else 4              # us per PUSH unit = 2 bytes
    u = [pm.C_QSET + ((pm.C_GENV + pm.C_JOINTC) if tex else 0)]
    n, bpl = sh["bh"], pm.C_BLINE + per * sh["npush"]
    while n > 0:
        k = min(pm.RQ_BCH, n)
        n -= k
        u.append(pm.C_CHUNK + (0 if k == pm.RQ_BCH else pm.C_PMUL) + k * bpl)
    pre, i = sh["wpre"], 0
    while i < len(pre):
        k = min(pm.RQ_WCH, len(pre) - i)
        u.append(pm.C_CHUNK + (0 if k == pm.RQ_WCH else pm.C_PMUL)
                 + k * (pm.C_WPAIR + per * pre[i]) + pm.C_WSTEP * pre[i])
        i += k
    return u


def quad_units_tex_mixed(q, cyh=None):
    """THE ONE THAT MATTERS.  A textured quad is CHUNKED, a flat quad is
    not.

    RQ_SPLIT is all-or-nothing today and turning it on costs C_CHUNK = 300
    us on EVERY quad in the frame -- 19.5 ms of charge on the worst frame,
    which by itself breaks the 6-period lock (see the RQ_SPLIT 1 baseline).
    But only the TEXTURED quads have an atomic-unit problem: they are the
    ones whose byte term went up 1.75x and which carry the per-face
    codegen.  So chunk those and leave the rest on raster.asm's cheap
    single-unit path.  raster.asm already contains both loops (RQ_PACED);
    this makes the choice per quad instead of per build.
    """
    import pacemodel as pm
    if q[5] > pm.KTEX:
        return quad_units_tex(q, cyh)          # flat: one unit, as today
    return quad_units_tex_split(q, cyh)        # textured: chunked


def _chunk(args):
    """pacescan._chunk, plus the worst ATOMIC UNIT and worst INTERVAL."""
    lo, hi, pos = args
    W = pacescan._W
    pm, solid, cyh, tail = W["pm"], W["solid"], W["cyh"], W["tail"]
    hist = collections.Counter()
    over, top = [], []
    worst = (0, 0, 0, 0)
    wunit = (0, 0, 0, 0)
    wint = (0, 0, 0, 0)
    for i in range(lo, hi):
        px, py = pos[i]
        for a in range(72):
            u = pm._state_units(solid, px, py, a, cyh)
            acc = 0
            for _ in range(3):
                w, wo, acc = pm.segments(u, acc, tail=tail, n=99)
            hist[w] += 1
            tot = sum(c for _, _, c in u)
            mx = max(c for _, _, c in u)
            if tot > worst[0]:
                worst = (tot, px, py, a)
            if mx > wunit[0]:
                wunit = (mx, px, py, a)
            if wo > wint[0]:
                wint = (wo, px, py, a)
            top.append((tot, px, py, a))
            if len(top) > 4000:
                top.sort(reverse=True)
                del top[pacescan.NTOP:]
            if w >= pm.PACE_FRAMES:
                over.append((w, tot, px, py, a))
    top.sort(reverse=True)
    return hist, over, worst, top[:pacescan.NTOP], wunit, wint


def run(ktex, cgen, cjoint, jobs, pace_frames=6, quiet=False, split=0):
    import multiprocessing as mp
    import pacemodel as pm
    _solid, pos = pacescan.positions()
    ovr = {"KTEX": ktex, "C_GENV": cgen, "C_JOINTC": cjoint,
           "PACE_FRAMES": pace_frames}
    if split == 2:                      # chunk ONLY the textured quads
        ovr["RQ_SPLIT"] = 0             # (pace_quad's flat path stays)
        ovr["quad_units"] = quad_units_tex_mixed
    elif split:
        ovr["RQ_SPLIT"] = 1
        if ktex >= 0:
            ovr["quad_units"] = quad_units_tex_split
    elif ktex >= 0:
        ovr["quad_units"] = quad_units_tex
    step = max(1, len(pos) // (jobs * 8))
    tasks = [(i, min(i + step, len(pos)), pos)
             for i in range(0, len(pos), step)]
    hist = collections.Counter()
    over, tops = [], []
    wunit = wint = (0, 0, 0, 0)
    with mp.Pool(jobs, initializer=pacescan._init, initargs=(ovr,)) as p:
        for h, o, _w, t, mu, mi in p.imap_unordered(_chunk, tasks):
            hist.update(h)
            over += o
            tops += t
            if mu[0] > wunit[0]:
                wunit = mu
            if mi[0] > wint[0]:
                wint = mi
    tops.sort(reverse=True)
    worst = tops[0][0]
    tot = sum(hist.values())
    budget = pace_frames * pm.THRESH
    nover = len(over)
    if not quiet:
        print("\nwaits the accumulator asks for, EXHAUSTIVE:")
        for k in sorted(hist):
            print(f"   {k} waits  {hist[k]:9d}  {100.0*hist[k]/tot:9.5f}%"
                  f"   -> {k+1} periods"
                  + ("" if k < pace_frames else "   <-- OVER BUDGET"))
        print(f"worst charged frame  {worst} us of a {budget} us budget "
              f"({pace_frames} vsyncs)")
        print(f"worst ATOMIC unit    {wunit[0]} us   (THRESH "
              f"{pm.THRESH}) at (0x{wunit[1]:04X},0x{wunit[2]:04X}) "
              f"h{wunit[3]}"
              + ("   <-- BIGGER THAN ONE PERIOD" if wunit[0] >= pm.THRESH
                 else ""))
        print(f"worst INTERVAL est   {wint[0]} us   at "
              f"(0x{wint[1]:04X},0x{wint[2]:04X}) h{wint[3]}")
        print(f"{nover} of {tot} states need {pace_frames+1} periods")
        for w, c, px, py, a in sorted(over, reverse=True)[:6]:
            print(f"    (0x{px:04X},0x{py:04X},{a})  {w} waits, {c} us")
    return dict(worst=worst, over=nover, unit=wunit, interval=wint,
                budget=budget, tot=tot, hist=hist)


def main():
    a = [x for x in sys.argv[1:]]
    ktex = int(a[0]) if len(a) > 0 else 2
    cgen = int(a[1]) if len(a) > 1 else 1150
    cjoint = int(a[2]) if len(a) > 2 else 0
    jobs = int(a[3]) if len(a) > 3 else (os.cpu_count() or 4)
    import pacemodel as pm
    print(f"KTEX {ktex}  C_GENV {cgen}  C_JOINTC {cjoint}  "
          f"C_QUAD {pm.C_QUAD}/{pm.C_QS}/{pm.C_QW}  RQ_SPLIT {pm.RQ_SPLIT}")
    assert pm.RQ_SPLIT == 0, "this models the RQ_SPLIT 0 (shipped) charge"
    for pf in (6, 7):
        print(f"\n===== PACE_FRAMES {pf} "
              f"({pf*19.968:.2f} ms, {1000/(pf*19.968):.2f} fps) =====")
        r = run(ktex, cgen, cjoint, jobs, pf)
        if r["over"] == 0:
            print(f"  LOCKED at {pf} periods = {1000/(pf*19.968):.2f} fps")
            break


if __name__ == "__main__":
    main()
