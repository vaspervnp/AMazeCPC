"""WHAT WOULD A FULL COLUMN RAYCASTER COST, ON THE REAL MAZE?

Replays a Wolfenstein-shaped renderer -- 44 rays, one DDA each, one
textured vertical strip each -- over EVERY state a player can stand in
(the 24/256 lattice x 72 headings that pacescan.py sweeps), and charges
it with the costs engine2/tools/emu_ray.py MEASURED on the booted 6128.

    python3 engine2/tools/raycost.py [nstates|all] [jobs]
"""

import collections
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

VP_BW = 44
VP_H = 96
FOCAL_V = 96
FOV = 60.0
NHEAD = 72

# ---- MEASURED on the booted 6128, engine2/tools/emu_ray.py -----------
RAY_FIXED = 666.24          # per ray: setup + 2 seed muls + post-hit block
RAY_CHEAP = 507.21          # ditto with mul8x8u seeds (8-bit deltaDist)
RAY_OPT   = 344.70          # ditto, quadrant hoisted, 8x8 texcol multiply
STEP_X = 25.155             # one DDA grid step, X branch
STEP_Y = 31.164             # one DDA grid step, Y branch
STRIP_FIX = 31.02           # per strip, POP-fed from a column cache
STRIP_B = 7.750
BAKED_FIX = 59.00           # per strip, screen addresses baked in code
BAKED_B = 6.500
TEX_FIX = 24.03             # per strip, true per-pixel fractional step
TEX_B = 13.624

# the strip has to start at an arbitrary scanline, so the unrolled block
# is entered at phase (ytop & 7); charge the entry arithmetic per strip
STRIP_PHASE = 20.0

# the parts of the frame the raycaster does NOT replace.  bg_fill, gun
# and hud are MEASURED; tail and door are main3.asm's own C_TAIL and
# C_DOORACT; ray_setup is the per-frame fan/fraction setup that replaces
# C_MSETUP (1550).
BG_FILL = 9215.8
GUN = 4400.0
HUD = 1400.0
TAIL = 1450.0
DOOR = 900.0
RAYSETUP = 500.0
KEEP = BG_FILL + GUN + HUD + TAIL + DOOR + RAYSETUP

BUDGET = 116736.0           # PACE_FRAMES 6
VSYNC = 19.968

_W = {}


def _init():
    import pacescan
    solid, pos = pacescan.positions()
    _W["solid"] = solid
    _W["pos"] = pos
    planelen = math.tan(math.radians(FOV / 2.0))
    fan = []
    for a in range(NHEAD):
        th = a * 2.0 * math.pi / NHEAD
        dx, dy = math.cos(th), math.sin(th)
        pxv, pyv = -dy * planelen, dx * planelen
        fan.append([(dx + (2.0 * (i + 0.5) / VP_BW - 1.0) * pxv,
                     dy + (2.0 * (i + 0.5) / VP_BW - 1.0) * pyv)
                    for i in range(VP_BW)])
    _W["fan"] = fan


def one(px, py, a):
    solid = _W["solid"]
    posx, posy = px / 256.0, py / 256.0
    sx_n = sy_n = 0
    nbytes = 0
    for (rx, ry) in _W["fan"][a]:
        mx, my = px >> 8, py >> 8
        ddx = 1e30 if rx == 0 else abs(1.0 / rx)
        ddy = 1e30 if ry == 0 else abs(1.0 / ry)
        if rx < 0:
            stx, sdx = -1, (posx - mx) * ddx
        else:
            stx, sdx = 1, (mx + 1.0 - posx) * ddx
        if ry < 0:
            sty, sdy = -1, (posy - my) * ddy
        else:
            sty, sdy = 1, (my + 1.0 - posy) * ddy
        side = 0
        n = 0
        while True:
            if sdx < sdy:
                sdx += ddx
                mx += stx
                side = 0
                sx_n += 1
            else:
                sdy += ddy
                my += sty
                side = 1
                sy_n += 1
            n += 1
            if not (0 <= mx < 16 and 0 <= my < 16) or n > 40:
                break
            if solid[my * 16 + mx]:
                break
        d = max(1e-6, (sdx - ddx) if side == 0 else (sdy - ddy))
        nbytes += min(VP_H, int(FOCAL_V / d))
    return sx_n, sy_n, nbytes


def cost(sx, sy, nb, rayfix, sfix, sbyte):
    return (VP_BW * rayfix + sx * STEP_X + sy * STEP_Y
            + VP_BW * (sfix + STRIP_PHASE) + nb * sbyte)


def _chunk(args):
    lo, hi, stride = args
    pos = _W["pos"]
    tot = 0
    acc = collections.Counter()
    best = {}
    hist = collections.defaultdict(collections.Counter)
    for k in range(lo, hi, stride):
        i, a = divmod(k, NHEAD)
        px, py = pos[i]
        sx, sy, nb = one(px, py, a)
        tot += 1
        acc["sx"] += sx
        acc["sy"] += sy
        acc["nb"] += nb
        v = {
            "naive": cost(sx, sy, nb, RAY_FIXED, TEX_FIX, TEX_B),
            "opt": cost(sx, sy, nb, RAY_OPT, TEX_FIX, TEX_B),
            "cache": cost(sx, sy, nb, RAY_OPT, STRIP_FIX, STRIP_B),
            "baked": cost(sx, sy, nb, RAY_OPT, BAKED_FIX, BAKED_B),
        }
        for kk, vv in v.items():
            acc[kk] += vv
            if vv > best.get(kk, (0, None))[0]:
                best[kk] = (vv, (px, py, a, sx, sy, nb))
            hist[kk][int(vv // 1000)] += 1
        if nb > best.get("nb", (0, None))[0]:
            best["nb"] = (nb, (px, py, a))
        st = sx + sy
        if st > best.get("st", (0, None))[0]:
            best["st"] = (st, (px, py, a))
    return tot, acc, best, hist


def main():
    n = sys.argv[1] if len(sys.argv) > 1 else "all"
    jobs = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    import multiprocessing as mpr
    _init()
    total = len(_W["pos"]) * NHEAD
    stride = 1 if n == "all" else max(1, total // int(n))
    per = total // jobs + 1
    chunks = [(j * per, min(total, (j + 1) * per), stride)
              for j in range(jobs)]
    with mpr.Pool(jobs, initializer=_init) as p:
        res = p.map(_chunk, chunks)
    tot = 0
    acc = collections.Counter()
    best = {}
    hist = collections.defaultdict(collections.Counter)
    for t, a, b, h in res:
        tot += t
        acc.update(a)
        for k, v in b.items():
            if v[0] > best.get(k, (0, None))[0]:
                best[k] = v
        for k, v in h.items():
            hist[k].update(v)

    print(f"state space {total}, scanned {tot} (stride {stride})")
    print(f"mean DDA steps  X {acc['sx']/tot:6.1f}  Y {acc['sy']/tot:6.1f}"
          f"  total {(acc['sx']+acc['sy'])/tot:6.1f}   (44 rays)")
    print(f"mean wall bytes {acc['nb']/tot:8.1f} of 4224 "
          f"({100*acc['nb']/tot/4224:.1f}% of the viewport)")
    print(f"worst wall bytes {best['nb'][0]} at {best['nb'][1]}")
    print(f"worst DDA steps  {best['st'][0]} at {best['st'][1]}")
    print()

    def pct(c):
        accn = 0
        out = {}
        for k in sorted(c):
            accn += c[k]
            for q in (50, 90, 99, 99.9, 100):
                if q not in out and accn >= tot * q / 100.0:
                    out[q] = k
        return out

    names = {
        "naive": "A. straight port : ray 666.2 us, strip 13.624 us/B",
        "opt": "B. optimised ray : ray 344.7 us, strip 13.624 us/B",
        "cache": "C. + column cache: ray 344.7 us, strip  7.750 us/B",
        "baked": "D. + baked addrs : ray 344.7 us, strip  6.500 us/B"}
    for k in ("naive", "opt", "cache", "baked"):
        w = best[k][0]
        whole = w + KEEP
        mean = acc[k] / tot + KEEP
        frames = math.ceil(whole / 1000.0 / VSYNC)
        print(f"{names[k]}")
        c = best[k][1]
        print(f"    render worst {w/1000:8.2f} ms   mean {acc[k]/tot/1000:7.2f} ms")
        print(f"      worst state (x={c[0]} y={c[1]} a={c[2]}): "
              f"{c[3]} X-steps {c[4]} Y-steps {c[5]} wall bytes")
        print(f"    WHOLE FRAME  worst {whole/1000:8.2f} ms  (+{KEEP/1000:.1f} ms kept)"
              f"   mean {mean/1000:7.2f} ms")
        print(f"    locked period {frames} vsyncs = {frames*VSYNC:7.2f} ms"
              f"  -> {1000/(frames*VSYNC):5.2f} fps")
        p = pct(hist[k])
        print("    render ms percentiles "
              + "  ".join(f"p{q}={v+0.5:.0f}" for q, v in p.items()))
        print()


if __name__ == "__main__":
    main()
