"""Produce the PNG set and sweep the state space for frame cost."""

import math
import os
import sys
import time

import world
import geom
import free
import fcost
import frender

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def baseline():
    """The SHIPPED engine, on the same cost model, for a like-for-like
    comparison.  cost.py has the occluder in; the shipped Z80 does not
    (README: removed on purpose to keep every frame the same length), so
    report both."""
    import cost
    import preview
    from geom import Rect

    grid, _, _ = world.load_maze()

    def cost_no_occ(x, y, facing, sub):
        faces, _occ = preview.build_facelist(grid, x, y, facing, sub, {})
        fill = geom.VP_H * geom.VP_BW
        rect_lines = geom.VP_H
        span_lines = 0
        for _k, g, _p, hclip in faces:
            if isinstance(g, Rect):
                h = g.h if hclip is None else hclip
                rect_lines += h
                fill += h * g.npush * 2
            else:
                span_lines += len(g.lines)
                fill += g.fill_bytes
        us = (fill // 2) * 4 + span_lines * 28 + rect_lines * 19
        return us, fill

    tot = w = 0.0
    n = 0
    wfill = 0
    for cy in range(world.MAZE_H):
        for cx in range(world.MAZE_W):
            if grid[cy][cx] != world.FLOOR:
                continue
            for f in range(4):
                for s in range(geom.SUBSTEPS):
                    us, fill = cost_no_occ(cx, cy, f, s)
                    ms = 4.1 + 1.27 * us / 1000.0
                    tot += ms
                    n += 1
                    if ms > w:
                        w, wfill = ms, fill
    print("=" * 118)
    print("BASELINE: the SHIPPED 4-facing / 8-substep engine, same cost model")
    print("=" * 118)
    print(f"  no occluder (what actually ships): mean {tot/n:5.1f} ms, "
          f"worst {w:5.1f} ms over {n} states  (worst fill {wfill} B)")
    avg, worst, n2, _over = cost.survey()
    print(f"  with occluder (cost.py default) : mean "
          f"{4.1+1.27*avg/1000:5.1f} ms, worst {4.1+1.27*worst[0]/1000:5.1f} ms")
    print()
    return tot / n, w


def line(c):
    return (f"faces={c['n_faces']:2d} cells={c['cells_visited']:3d} "
            f"fill={c['fill']:5d}B span={c['span_lines']:3d} "
            f"rect={c['rect_lines']:3d} | model={c['model_us']/1000:5.1f}ms "
            f"march={c['march_us']/1000:4.1f} proj={c['face_us']/1000:5.1f} "
            f"gen={c['gen_us']/1000:4.1f} | HW={c['hw_ms']:5.1f}ms "
            f"(split-opt {c['opt_hw_ms']:5.1f}, zero-overdraw "
            f"{c['ideal_ms']:5.1f}, overdraw x{c['overdraw']:.2f})")


def shots(grid):
    S = [
        ("01_corridor_0deg",   10.5, 13.5,  0),
        ("02_corridor_5deg",   10.5, 13.5,  1),
        ("03_corridor_15deg",  10.5, 13.5,  3),
        ("04_corridor_45deg",  10.5, 13.5,  9),
        ("05_between_cells",   11.97, 13.28, 0),
        ("06_corridor_180deg", 10.5, 13.5, 36),
        ("07_junction",         7.5,  7.5, 54),
        ("08_nose_to_wall",    10.5, 13.13, 63),
        ("09_open_room",        2.5,  1.5, 18),
    ]
    print("=" * 118)
    print("SHOTS")
    print("=" * 118)
    for name, x, y, a in S:
        fr = frender.render_png(grid, x, y, a, os.path.join(OUT, name + ".png"))
        c = fcost.count(fr)
        print(f"{name:20s} p=({x:5.2f},{y:5.2f}) h={a*5:3d}deg  {line(c)}")
    return [s[0] for s in S]


def sweep(grid, offs, astep, label):
    t0 = time.time()
    tot = 0.0
    n = 0
    worst = (0.0, None)
    best = (1e9, None)
    hist = {}
    over = 0
    wn = wo = 0.0
    accum = dict(n_faces=0, cells_visited=0, span_lines=0, rect_lines=0,
                 fill=0, opt_hw=0.0, ideal=0.0, overdraw=0.0,
                 net=0.0, optnet=0.0)
    for cy in range(world.MAZE_H):
        for cx in range(world.MAZE_W):
            if grid[cy][cx] != world.FLOOR:
                continue
            for ox, oy in offs:
                px, py = cx + ox, cy + oy
                for a in range(0, free.N_ANGLES, astep):
                    fr = free.build_frame(grid, px, py, a)
                    c = fcost.count(fr)
                    ms = c["hw_ms"]
                    tot += ms
                    n += 1
                    for k in ("n_faces", "cells_visited", "span_lines",
                              "rect_lines", "fill"):
                        accum[k] += c[k]
                    accum["opt_hw"] += c["opt_hw_ms"]
                    accum["ideal"] += c["ideal_ms"]
                    accum["overdraw"] += c["overdraw"]
                    accum["net"] += c["hw_ms_net"]
                    accum["optnet"] += c["opt_net_ms"]
                    wn = max(wn, c["hw_ms_net"])
                    wo = max(wo, c["opt_net_ms"])
                    if ms > 40.0:
                        over += 1
                    b = int(ms // 5) * 5
                    hist[b] = hist.get(b, 0) + 1
                    if ms > worst[0]:
                        worst = (ms, (px, py, a))
                    if ms < best[0]:
                        best = (ms, (px, py, a))
    print()
    print("=" * 118)
    print(f"SWEEP: {label}  ({n} states, {time.time()-t0:.0f}s)")
    print("=" * 118)
    print(f"  mean   HW frame  {tot/n:6.2f} ms      "
          f"(split-opt {accum['opt_hw']/n:6.2f} ms)")
    print(f"  best   HW frame  {best[0]:6.2f} ms  at {best[1]}")
    print(f"  worst  HW frame  {worst[0]:6.2f} ms  at {worst[1]}")
    print(f"  mean   zero-overdraw bound {accum['ideal']/n:6.2f} ms "
          f"(mean overdraw factor x{accum['overdraw']/n:.2f})")
    print(f"  states over 40 ms: {over}/{n} ({100*over/n:.1f}%)")
    print(f"  NET accounting (3.64 ms of the 4.1 ms constant is the shipped "
          f"engine's own view build, which the grid march replaces):")
    print(f"    mean {accum['net']/n:6.2f} ms  worst {wn:6.2f} ms   "
          f"| + trapezoid split-opt: mean {accum['optnet']/n:6.2f} ms  "
          f"worst {wo:6.2f} ms")
    print(f"  mean faces {accum['n_faces']/n:5.2f}   "
          f"mean cells marched {accum['cells_visited']/n:5.1f}   "
          f"mean span-lines {accum['span_lines']/n:6.1f}   "
          f"mean rect-lines {accum['rect_lines']/n:6.1f}   "
          f"mean fill {accum['fill']/n:6.0f} B")
    print("  histogram of HW frame time:")
    for b in sorted(hist):
        print(f"    {b:3d}-{b+5:3d} ms  {'#'*max(1, hist[b]*60//n):60s}"
              f" {hist[b]:6d} ({100*hist[b]/n:4.1f}%)")
    return worst


def sensitivity(grid, worst_state):
    print()
    print("=" * 118)
    print("SENSITIVITY to the NEW per-face / per-march assumptions")
    print("=" * 118)
    px, py, a = worst_state
    fr = free.build_frame(grid, px, py, a)
    base_face, base_march, base_gen = (fcost.US_FACE, fcost.US_MARCH_CELL,
                                       fcost.US_SPAN_GEN)
    print(f"  worst-case state {worst_state}")
    for uf in (200, 300, 500, 800, 1200):
        fcost.US_FACE = uf
        c = fcost.count(fr)
        print(f"    US_FACE={uf:5d}  ->  HW {c['hw_ms']:6.2f} ms   "
              f"(split-opt {c['opt_hw_ms']:6.2f} ms)")
    fcost.US_FACE = base_face
    for um in (20, 40, 60, 100):
        fcost.US_MARCH_CELL = um
        c = fcost.count(fr)
        print(f"    US_MARCH_CELL={um:4d} -> HW {c['hw_ms']:6.2f} ms")
    fcost.US_MARCH_CELL = base_march
    fcost.US_SPAN_GEN = base_gen


def floor_only_bound():
    """The irreducible cost: repaint the viewport once, nothing else."""
    fill = geom.VP_H * geom.VP_BW
    us = (fill // 2) * fcost.US_PER_PUSH + geom.VP_H * fcost.US_RECT_LINE
    print()
    print(f"IRREDUCIBLE: one full repaint of the {geom.VP_BW}x{geom.VP_H}-byte "
          f"viewport = {fill} B, {us} us model -> "
          f"{4.1 + 1.27*us/1000:.1f} ms HW, with ZERO geometry.")
    print(f"  half-FOV {free.HALF_FOV_DEG:.1f} deg (full FOV "
          f"{2*free.HALF_FOV_DEG:.1f} deg); one 5 deg step moves the vanishing "
          f"point {math.tan(math.radians(5))*geom.FOCAL:.1f} px = "
          f"{100*math.tan(math.radians(5))*geom.FOCAL/geom.VP_PW:.0f}% of the "
          f"viewport width.")


def main():
    grid, sx, sy = world.load_maze()
    floor_only_bound()
    print()
    baseline()
    names = shots(grid)

    offs = [(0.5, 0.5), (0.25, 0.5), (0.5, 0.25), (0.3, 0.7)]
    astep = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    worst_ms, worst_state = sweep(grid, offs, astep,
                                  f"{len(offs)} sub-positions/cell x "
                                  f"{free.N_ANGLES//astep} headings")

    print()
    fr = frender.render_png(grid, worst_state[0], worst_state[1],
                            worst_state[2], os.path.join(OUT, "10_worst.png"))
    c = fcost.count(fr)
    print(f"WORST view rendered to out/10_worst.png: p=({worst_state[0]:.2f},"
          f"{worst_state[1]:.2f}) h={worst_state[2]*5}deg")
    print("   " + line(c))
    sensitivity(grid, worst_state)
    return names


if __name__ == "__main__":
    main()
