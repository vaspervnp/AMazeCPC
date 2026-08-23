"""Largest viewport that fits the budget, WITH THE MEASURED GEOMETRY COST.

COPY of prototype/free-angle/vpsweep.py with three changes:

  1. it costs frames with engine2/tools/fcost_measured.py (the Z80 kernel as
     measured on the emulator) instead of the hand-estimated fcost.py;
  2. the FOV is held at 60 degrees, not 38 -- FOCAL_H = CX/tan(30) -- which
     is the decided target, and FOCAL_V = VP_H so a wall one cell away
     exactly fills the viewport height;
  3. the pass mark is 80 ms (4 vsync frames), the decided budget, and the
     target 48x128 bytes is in the sweep.

Every row is the full reachable state space of the shipped maze: every floor
cell x 4 sub-cell offsets x every 3rd heading.

    PYTHONPATH=tools:prototype/free-angle python3 engine2/tools/vpsweep_measured.py
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.join(_ROOT, "prototype", "free-angle"))

import geom                                                  # noqa: E402
import world                                                 # noqa: E402
import free                                                  # noqa: E402
import fcost_measured as fcost                               # noqa: E402
import fcost as fcost_est                                    # noqa: E402

FOV_DEG = 60.0
BUDGET_MS = 80.0
TAN_HALF = math.tan(math.radians(FOV_DEG / 2.0))


def set_viewport(bw, h):
    """bw viewport bytes wide, h scanlines tall, at the fixed 60 deg FOV."""
    geom.VP_BW = bw
    geom.VP_H = h
    geom.VP_PW = bw * 2
    geom.CX = float(bw)                 # half-byte units: CX = VP_PW/2 = bw
    geom.CY = h / 2.0
    geom.VP_BX = (80 - bw) // 2
    geom.VP_Y = (200 - h) // 2
    geom.FOCAL = float(h)
    free.set_focal(geom.CX / TAN_HALF, float(h))
    free.R_MAX = 6


def sweep(grid, offs, astep, cost):
    tot = worst = worst_opt = worst_net = 0.0
    tot_opt = 0.0
    n = over = 0
    argworst = None
    for cy in range(world.MAZE_H):
        for cx in range(world.MAZE_W):
            if grid[cy][cx] != world.FLOOR:
                continue
            for ox, oy in offs:
                for a in range(0, free.N_ANGLES, astep):
                    c = cost.count(free.build_frame(grid, cx + ox, cy + oy, a))
                    tot += c["hw_ms"]
                    tot_opt += c["opt_hw_ms"]
                    n += 1
                    if c["opt_hw_ms"] > BUDGET_MS:
                        over += 1
                    if c["opt_hw_ms"] > worst_opt:
                        argworst = (cx + ox, cy + oy, a, c)
                    worst = max(worst, c["hw_ms"])
                    worst_opt = max(worst_opt, c["opt_hw_ms"])
                    worst_net = max(worst_net, c["opt_net_ms"])
    return dict(mean=tot / n, mean_opt=tot_opt / n, worst=worst,
                worst_opt=worst_opt, worst_net=worst_net, over=over, n=n,
                argworst=argworst)


SIZES = ((48, 128), (44, 118), (40, 106), (36, 96), (32, 86), (28, 74),
         (24, 64), (20, 54), (16, 42), (12, 32))


def main():
    grid, _, _ = world.load_maze()
    offs = [(0.5, 0.5), (0.25, 0.5), (0.5, 0.25), (0.3, 0.7)]
    astep = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    print("Free-angle renderer vs viewport size, 60 deg FOV, aspect free")
    print("geometry cost = MEASURED Z80 kernel "
          "(%.0f + %.1f*cells + %.1f*faces us)"
          % (fcost.US_GEOM_FIXED, fcost.US_MARCH_CELL, fcost.US_FACE))
    print("budget %.0f ms = 4 vsync frames; 'opt' = wedge/body/wedge split"
          % BUDGET_MS)
    print()
    print("%9s %9s %8s %9s %10s %8s %s"
          % ("bytes", "pixels", "mean ms", "worst ms", "worst+opt",
             "over/n", "verdict"))
    print("-" * 86)
    best = None
    for bw, h in SIZES:
        set_viewport(bw, h)
        r = sweep(grid, offs, astep, fcost)
        ok = r["worst_opt"] <= BUDGET_MS
        if ok and best is None:
            best = (bw, h, r)
        v = ("FITS %.0f ms" % BUDGET_MS) if ok else "OVER BUDGET"
        v += "  (%.1f vsync frames worst)" % (r["worst_opt"] / 20.0)
        print("%4d x%-4d %4d x%-4d %8.1f %9.1f %10.1f %4d/%-5d %s"
              % (bw, h, bw * 2, h, r["mean_opt"], r["worst"], r["worst_opt"],
                 r["over"], r["n"], v))

    print()
    if best:
        bw, h, r = best
        c = r["argworst"][3]
        print("LARGEST VIEWPORT THAT FITS %.0f MS WORST CASE: %d x %d bytes "
              "= %d x %d pixels" % (BUDGET_MS, bw, h, bw * 2, h))
        print("   worst state (%.2f, %.2f) heading %d: %.1f ms  "
              "(geometry %.1f ms, fill %.1f ms)"
              % (r["argworst"][0], r["argworst"][1], r["argworst"][2],
                 c["opt_hw_ms"], c["new_us"] / 1000.0,
                 1.27 * c["opt_model_us"] / 1000.0))
    else:
        print("NOTHING IN THE SWEEP FITS %.0f MS." % BUDGET_MS)

    # ---- the target, side by side with the old estimate -------------------
    print()
    print("=== the decided target, 48x128 bytes, old estimate vs measured ===")
    set_viewport(48, 128)
    a = sweep(grid, offs, astep, fcost_est)
    b = sweep(grid, offs, astep, fcost)
    print("%-22s %10s %10s" % ("", "estimated", "measured"))
    for lbl, k in (("mean ms (opt)", "mean_opt"), ("worst ms (opt)",
                                                   "worst_opt"),
                   ("worst ms (net)", "worst_net")):
        print("%-22s %10.1f %10.1f" % (lbl, a[k], b[k]))
    print("%-22s %10d %10d" % ("states over 80 ms", a["over"], b["over"]))

    # ---- why shrinking barely helps --------------------------------------
    print()
    print("=== geometry vs fill, by viewport size ===")
    print("At a FIXED 60 deg FOV and a fixed 6-cell march radius the frustum")
    print("is the same shape at every size, so cells_visited and n_faces --")
    print("and therefore the whole geometry kernel -- do not change at all.")
    print("Shrinking the viewport only buys back fill time.")
    print("%9s %12s %12s %12s" % ("bytes", "geom ms", "fill ms", "worst ms"))
    for bw, h in SIZES:
        set_viewport(bw, h)
        wg = wf = 0.0
        best_tot = 0.0
        for cy in range(world.MAZE_H):
            for cx in range(world.MAZE_W):
                if grid[cy][cx] != world.FLOOR:
                    continue
                for ox, oy in offs:
                    for a2 in range(0, free.N_ANGLES, astep):
                        c = fcost.count(free.build_frame(grid, cx + ox,
                                                         cy + oy, a2))
                        if c["opt_hw_ms"] > best_tot:
                            best_tot = c["opt_hw_ms"]
                            wg = c["new_us"] / 1000.0
                            wf = 1.27 * c["opt_model_us"] / 1000.0 + 0.46
        print("%4d x%-4d %12.1f %12.1f %12.1f" % (bw, h, wg, wf, best_tot))

    # ---- best AREA at 60 deg, since geometry is size independent ---------
    print()
    print("=== worst-case ms over a (width, height) grid, 60 deg FOV ===")
    print("(the fill is the only term that moves, so pick the largest area "
          "whose worst case is under %.0f ms)" % BUDGET_MS)
    hs = (64, 80, 96, 112, 128)
    print("%6s" % "bw\\h" + "".join("%9d" % h for h in hs))
    fits = []
    for bw in (24, 28, 32, 36, 40, 44, 48):
        line = "%6d" % bw
        for h in hs:
            set_viewport(bw, h)
            r = sweep(grid, offs, astep * 2, fcost)
            line += "%9.1f" % r["worst_opt"]
            if r["worst_opt"] <= BUDGET_MS:
                fits.append((bw * h, bw, h, r["worst_opt"]))
        print(line)
    if fits:
        fits.sort()
        area, bw, h, w = fits[-1]
        print()
        print("LARGEST AREA UNDER %.0f MS: %d x %d bytes = %d x %d pixels "
              "(%d byte-cells, worst %.1f ms)"
              % (BUDGET_MS, bw, h, bw * 2, h, area, w))


if __name__ == "__main__":
    main()
