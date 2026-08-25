"""HOW MUCH OF A FRAME IS *NEAR* WALL, AND WHAT WOULD TEXTURING IT COST?

wallarea.py answered "how many viewport bytes are wall".  This answers the
question the hybrid LOD architecture hangs on:

    of the bytes the rasteriser writes in the worst frame, how many belong
    to faces at k <= KTEX -- the ones a texture would actually read on --
    and how many to faces further away, which stay flat?

Same state space as pacescan.py / wallarea.py: every position on the 24/256
movement lattice that passes game.asm's collision box, x 72 headings, i.e.
4 055 040 states.  For every state it accumulates, PER DEPTH k:

    b[k]   screen bytes WRITTEN (overdraw counted, like the machine)
    r[k]   runs (scanline fills)
    q[k]   quads
    bb[k]  bytes on BODY rows (constant span -> one generated block serves
           every row of the face)
    wf[k]  bytes on wedge rows whose LEFT edge is PINNED   -- a generated
    wm[k]  bytes on wedge rows whose LEFT edge MOVES       -- block is
    rm[k]  runs             ''            ''       MOVES     entered at a
           variable offset and always falls off its own end, so it can
           only follow a run whose LEFT edge is fixed; wm/rm rows need a
           patched stop.
    rows[k] scanline rows the face spans (what a vertical mortar strip
           would have to walk)

then prices a dozen whole-frame architectures with MEASURED microsecond
constants and reports the worst frame under each.

    python3 engine2/tools/lodscan.py [nstates|all] [jobs]
"""

import collections
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

_W = {}
KMAX = 8

# ---- MEASURED constants ------------------------------------------------
# emu_byte.py on the booted 6128 (slopes; 100 NOPs calibrate to 100.001 us)
US_FLAT = 2.000     # push de
US_IMM = 3.500      # ld de,nn : push de   (arbitrary span, generated block)
US_COL = 5.625      # ld (hl),a : add hl,de  unrolled x8, DOWN a column
C_LINE = 19.75      # per-scanline setup of a PUSH-block run
# raster.asm's own header, MEASURED
C_QUAD = 341.0      # per-quad setup
# project.asm's own header, MEASURED (run_proj_test.py / worst_proj.py)
C_PROJ = 321.0      # proj_pt, one endpoint
# derived: per near face, project 3 interior mortar lines (the face's own
# view-space endpoints bisect for free at t = 1/4, 1/2, 3/4) and lay the
# 22-unit block from a pattern buffer with pop hl : ld (nn),hl (4 us/byte,
# addresses are static so they bake) -- 3*321 + 22*8 = 1139, call it
C_GENV = 1150.0
# raster_joint as it stands (vpcfg.inc, MEASURED on the disc)
C_JOINT_NOW = 7189.0
# ...and folded into raster_quad's row loop, which is what vpcfg.inc says
# would fix it: ~28 us per joint row instead of 99, over ~70 rows.
# ESTIMATE, not a measurement.
C_JOINT_FOLD = 2000.0
C_STOP = 14.0       # patched stop on a moving-left-edge wedge row, est.

CHARGED_WORST = 104024.0        # pacescan.py, exhaustive, on the shipped build
BUDGET = 116736.0               # PACE_FRAMES 6
VSYNC_US = 19456.0              # of budget per vsync (116736/6)

KEYS = ("b", "r", "q", "bb", "wf", "wm", "rm", "rows")


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


def _state(px, py, a):
    """-> flat tuple of 8 per-k vectors, length 8*KMAX."""
    rm, c = _W["rm"], _W["cfg"]
    v = [[0] * KMAX for _ in KEYS]
    b, r, q, bb, wf, wm, rmv, rows = v
    for qd in _quads(px, py, a):
        k = min(qd[5], KMAX - 1)
        bhi, blo, hhi, hlo, bbc, bw, left_tall = rm.unpack(qd, c)
        runs = rm.raster_quad(qd, c)
        nbody = 0
        if bw:
            RC = c.CYH
            jlo = RC if hlo >= RC * 16 else (hlo >> 4)
            nbody = min(c.VP_H - 1, RC + jlo) - (RC - jlo) + 1
        q[k] += 1
        r[k] += len(runs)
        for i, (_row, _end, npush) in enumerate(runs):
            n = 2 * npush
            b[k] += n
            if i < nbody:
                bb[k] += n
            elif left_tall:          # run ends at the MOVING right edge,
                wf[k] += n           # left edge pinned at bhi -> free
            else:                    # run ends at the pinned right edge,
                wm[k] += n           # LEFT edge moves -> needs a stop
                rmv[k] += 1
        rows[k] += 2 * min(c.CYH, hhi >> 4)
    out = []
    for x in v:
        out.extend(x)
    return tuple(out)


# ---------------------------------------------------------------------
#  the cost functions -- all LINEAR in the per-k vectors, all in us,
#  all covering exactly what raster.asm covers today (per quad, per run,
#  per byte) so they can be calibrated against the charged worst frame.
# ---------------------------------------------------------------------
class V:
    """the 8 per-k vectors of one state, by name."""

    __slots__ = KEYS + ("t",)

    def __init__(self, t):
        self.t = t
        for i, kk in enumerate(KEYS):
            setattr(self, kk, t[i * KMAX:(i + 1) * KMAX])

    def s(self, name, lo=0, hi=KMAX):
        return sum(getattr(self, name)[lo:hi])


def base(v):
    return C_QUAD * v.s("q") + C_LINE * v.s("r")


def cost_today(v):
    return base(v) + US_FLAT * v.s("b")


def cost_all_imm(v):
    return base(v) + US_IMM * v.s("b")


def hybrid(v, ktex, stop=0.0, gen=0.0, joint=0.0):
    """near faces (k<=ktex) through a generated block, far faces flat."""
    near_b = v.s("b", 0, ktex + 1)
    return (base(v) + US_FLAT * (v.s("b") - near_b) + US_IMM * near_b
            + stop * v.s("rm", 0, ktex + 1)
            + (gen + joint) * v.s("q", 0, ktex + 1))


def hybridB(v, ktex):
    """only the BODY of a near face is generated; wedges stay flat."""
    body = v.s("bb", 0, ktex + 1)
    return base(v) + US_FLAT * (v.s("b") - body) + US_IMM * body


def strips(v, ktex, n):
    return (cost_today(v) + US_COL * n * v.s("rows", 0, ktex + 1))


def joints_only(v, ktex, per):
    return cost_today(v) + per * v.s("q", 0, ktex + 1)


COSTS = []
COSTS.append(("today: all flat PUSH  [SHIPPED]", cost_today))
COSTS.append(("all wall bytes generated-block, no LOD", cost_all_imm))
for kt in (1, 2, 3):
    COSTS.append((f"k<={kt} generated, stop free, no codegen",
                  lambda v, kt=kt: hybrid(v, kt)))
for kt in (1, 2, 3):
    COSTS.append((f"k<={kt} generated + stop + codegen  = VERT mortar",
                  lambda v, kt=kt: hybrid(v, kt, C_STOP, C_GENV)))
for kt in (1, 2, 3):
    COSTS.append((f"k<={kt} VERT mortar + FOLDED horiz joints (est)",
                  lambda v, kt=kt: hybrid(v, kt, C_STOP, C_GENV,
                                          C_JOINT_FOLD)))
COSTS.append(("k<=2 VERT mortar + horiz joints AS BUILT (7189/face)",
              lambda v: hybrid(v, 2, C_STOP, C_GENV, C_JOINT_NOW)))
COSTS.append(("k<=2 BODY only generated, wedges flat",
              lambda v: hybridB(v, 2)))
COSTS.append(("flat + 4 vertical mortar strips down each k<=2 face",
              lambda v: strips(v, 2, 4)))
COSTS.append(("flat + 8 vertical mortar strips down each k<=2 face",
              lambda v: strips(v, 2, 8)))
COSTS.append(("flat + FOLDED horiz joints only, k<=3 (est 2000/face)",
              lambda v: joints_only(v, 3, C_JOINT_FOLD)))
COSTS.append(("COURSES=1 EXACTLY AS IT STANDS (7189/face, k<=3)",
              lambda v: joints_only(v, 3, C_JOINT_NOW)))


def _chunk(args):
    lo, hi, step = args
    pos = _W["pos"]
    tot = 0
    sums = [0] * (8 * KMAX)
    peak = [0] * (8 * KMAX)
    worst = {}
    for i in range(lo, hi, step):
        px, py = pos[i]
        for a in range(72):
            t = _state(px, py, a)
            tot += 1
            for j, x in enumerate(t):
                sums[j] += x
                if x > peak[j]:
                    peak[j] = x
            v = V(t)
            for idx, (_name, fn) in enumerate(COSTS):
                us = fn(v)
                if idx not in worst or us > worst[idx][0]:
                    worst[idx] = (us, (px, py, a), t)
    return tot, sums, peak, worst


def main():
    import multiprocessing as mp
    arg = sys.argv[1] if len(sys.argv) > 1 else "20000"
    jobs = int(sys.argv[2]) if len(sys.argv) > 2 else (os.cpu_count() or 4)
    _init()
    pos = _W["pos"]
    c = _W["cfg"]
    npos = len(pos)
    step = 1 if arg == "all" else max(1, (npos * 72) // int(arg))
    print(f"viewport {c.VP_BW}x{c.VP_H} = {c.VP_BW*c.VP_H} bytes")
    print(f"{npos*72} states total; every {step}th position "
          f"= {len(range(0,npos,step))*72} states on {jobs} cores")
    bounds = [(i * npos // jobs, (i + 1) * npos // jobs, step)
              for i in range(jobs)]
    with mp.Pool(jobs, initializer=_init) as p:
        res = p.map(_chunk, bounds)

    tot = 0
    sums = [0] * (8 * KMAX)
    peak = [0] * (8 * KMAX)
    worst = {}
    for t, s, pk, w in res:
        tot += t
        for j in range(8 * KMAX):
            sums[j] += s[j]
            peak[j] = max(peak[j], pk[j])
        for idx, val in w.items():
            if idx not in worst or val[0] > worst[idx][0]:
                worst[idx] = val
    S = V(tuple(sums))
    P = V(tuple(peak))

    print(f"\nscanned {tot} states")
    print("\nMEAN per frame, BY DEPTH k  (the LOD question, in one table)")
    print(f"  {'k':>3} {'quads':>8} {'runs':>8} {'bytes':>9} {'%bytes':>7} "
          f"{'body':>8} {'wedge-fix':>9} {'wedge-mov':>9} {'rows':>7}")
    tb = S.s("b")
    for k in range(1, KMAX):
        if S.q[k] == 0:
            continue
        print(f"  {k:>3} {S.q[k]/tot:8.2f} {S.r[k]/tot:8.1f} "
              f"{S.b[k]/tot:9.1f} {100.0*S.b[k]/tb:7.1f} "
              f"{S.bb[k]/tot:8.1f} {S.wf[k]/tot:9.1f} {S.wm[k]/tot:9.1f} "
              f"{S.rows[k]/tot:7.1f}")
    print(f"  {'all':>3} {S.s('q')/tot:8.2f} {S.s('r')/tot:8.1f} "
          f"{tb/tot:9.1f} {100.0:7.1f} {S.s('bb')/tot:8.1f} "
          f"{S.s('wf')/tot:9.1f} {S.s('wm')/tot:9.1f} {S.s('rows')/tot:7.1f}")
    print("\n  cumulative share of written bytes at k <= KTEX:")
    run = 0
    for k in range(1, KMAX):
        run += S.b[k]
        print(f"    KTEX={k}: {100.0*run/tb:5.1f}%   "
              f"(mean {run/tot:7.1f} of {tb/tot:.1f} bytes/frame)")

    print("\nPEAKS (each its own state, not simultaneous)")
    for kk, lab in (("b", "bytes at k"), ("q", "quads at k"),
                    ("rows", "face rows at k")):
        print(f"  {lab:16} " + " ".join(
            f"k{k}={getattr(P, kk)[k]:5d}" for k in range(1, 5)))

    # ---- calibrate the whole-frame model against the charged worst -----
    tw = worst[0]
    rest = CHARGED_WORST - tw[0]
    print(f"\nFRAME MODEL   frame_us = {rest:.0f}"
          f" + {C_QUAD:.0f}/quad + {C_LINE}/run + us/byte"
          f"\n  {rest:.0f} us is everything this architecture does NOT "
          f"replace: bg_fill, march,\n  project_all, gun, HUD and the "
          f"pacing hooks.  It is SOLVED so that the model's\n  worst frame "
          f"under today's cost function is exactly the {CHARGED_WORST:.0f} us "
          f"pacescan.py\n  charges on the shipped build.")
    print(f"\n{'architecture':54} {'raster':>8} {'frame':>8} {'slack':>8} "
          f"{'vsync':>6} {'fps':>6}   worst state")
    print("-" * 128)
    for idx, (name, _fn) in enumerate(COSTS):
        us, st, t = worst[idx]
        frame = rest + us
        vs = max(1, math.ceil(frame / VSYNC_US))
        slack = vs * VSYNC_US - frame
        print(f"{name:54} {us/1000:8.2f} {frame/1000:8.2f} {slack/1000:8.2f} "
              f"{vs:6d} {1000.0/(vs*19.968):6.2f}   {st}")
    print(f"\n  budget {BUDGET:.0f} us = 6 vsyncs; one vsync = 19456 us of "
          f"budget = 19.968 ms of wall clock.\n  'slack' is how much of the "
          f"last vsync period is still free.")


if __name__ == "__main__":
    main()
