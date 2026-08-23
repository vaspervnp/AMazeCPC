"""Independent ground truth: per-pixel-column DDA raycast.

The span renderer draws whole quads back-to-front.  A raycaster answers the
same question one column at a time and cannot get the ordering wrong, so
comparing the two localises painter errors, missing faces and quantisation
damage.  Any column where they disagree is an artefact of the span approach.
"""

import math

import geom
import world
import free
import frender


def cast(grid, px, py, fwd, rgt, t, doors, max_steps=64):
    """Ray p + s*(fwd + t*rgt).  -> (z, pen) of the first solid hit."""
    dx = fwd[0] + t * rgt[0]
    dy = fwd[1] + t * rgt[1]
    cx, cy = int(math.floor(px)), int(math.floor(py))
    stepx = 1 if dx > 0 else -1
    stepy = 1 if dy > 0 else -1
    tdx = abs(1.0 / dx) if dx else 1e30
    tdy = abs(1.0 / dy) if dy else 1e30
    sx = ((cx + 1 - px) / dx) if dx > 0 else ((cx - px) / dx if dx else 1e30)
    sy = ((cy + 1 - py) / dy) if dy > 0 else ((cy - py) / dy if dy else 1e30)
    for _ in range(max_steps):
        if sx < sy:
            s = sx
            sx += tdx
            cx += stepx
            ns = False              # crossed a vertical grid line -> E/W face
        else:
            s = sy
            sy += tdy
            cy += stepy
            ns = True               # crossed a horizontal line   -> N/S face
        c = world.cell_at(grid, cx, cy)
        solid = c == world.WALL or (c == world.DOOR
                                    and doors.get((cx, cy), 0) == 0)
        if solid:
            # s is measured along (fwd + t*rgt); its forward component is s.
            dist = s * math.hypot(dx, dy)
            depth = max(1, min(6, int(dist + 0.5)))
            return s, world.wall_pen(depth, ns, c == world.DOOR), ns
    return None, None, None


WALL_PENS = set(world.WALL_RAMP) | set(world.DOOR_RAMP)


def compare(grid, px, py, a_idx, doors=None):
    doors = doors or {}
    fwd, rgt = free.basis(a_idx)
    fr = free.build_frame(grid, px, py, a_idx, doors)
    buf = frender.new_frame()
    frender.draw(buf, fr)

    n_cols = geom.VP_PW
    ref = []
    for i in range(n_cols):
        t = (i + 0.5 - geom.CX) / geom.FOCAL
        ref.append(cast(grid, px, py, fwd, rgt, t, doors))

    bad_top = bad_pen = quant = struct = hole = 0
    worst_top = 0
    hist = {}
    for i in range(n_cols):
        z, pen, _ns = ref[i]
        col = [buf[geom.VP_Y + y][geom.VP_BX * 2 + i] for y in range(geom.VP_H)]
        rows = [y for y, p in enumerate(col) if p in WALL_PENS]
        if z is None or z > 6:
            continue
        s = geom.FOCAL / z
        ref_top = max(0, geom.CY - 0.5 * s)
        ref_bot = min(geom.VP_H, geom.CY + 0.5 * s)
        if not rows:
            if ref_bot - ref_top > 1:
                bad_top += 1
                hole += 1              # background visible where wall should be
                struct += 1
            continue
        dt = abs(rows[0] - ref_top)
        hist[min(9, int(dt))] = hist.get(min(9, int(dt)), 0) + 1
        if dt > 1.5:
            bad_top += 1
            worst_top = max(worst_top, dt)
            # Two quantisation mechanisms can explain a mismatch:
            #  (a) a silhouette edge within 2 columns  -> byte-granular x
            #  (b) a sloped top edge: the even-length rule pins the moving
            #      end of the run to a 2-BYTE (4 pixel) grid, so the edge
            #      staircases by 4*|dy/dx| scanlines
            near_edge = False
            for j in range(max(0, i - 2), min(n_cols, i + 3)):
                zj = ref[j][0]
                if zj is None or (z and abs(zj - z) > 0.25 * z):
                    near_edge = True
            slope = 0.0
            if 0 < i < n_cols - 1 and ref[i - 1][0] and ref[i + 1][0]:
                slope = abs(geom.FOCAL / ref[i + 1][0]
                            - geom.FOCAL / ref[i - 1][0]) / 4.0
            if near_edge or dt <= 2.0 * slope * 4.0 + 1.5:
                quant += 1
            else:
                struct += 1
        if rows:
            mid = col[(rows[0] + rows[-1]) // 2]
            if mid != pen:
                bad_pen += 1
    return dict(cols=n_cols, bad_top=bad_top, bad_pen=bad_pen,
                quant=quant, struct=struct, hole=hole, worst_top=worst_top,
                hist=hist)


def main():
    grid, _, _ = world.load_maze()
    tot = dict(cols=0, bad_top=0, bad_pen=0, quant=0, struct=0, hole=0)
    H = {}
    wt = 0
    n = 0
    views_with_hole = 0
    offs = [(0.5, 0.5), (0.25, 0.5), (0.5, 0.25), (0.3, 0.7), (0.8, 0.2)]
    for cy in range(world.MAZE_H):
        for cx in range(world.MAZE_W):
            if grid[cy][cx] != world.FLOOR:
                continue
            for ox, oy in offs:
                for a in range(0, free.N_ANGLES, 3):
                    r = compare(grid, cx + ox, cy + oy, a)
                    for k in tot:
                        tot[k] += r[k]
                    for k, v in r["hist"].items():
                        H[k] = H.get(k, 0) + v
                    wt = max(wt, r["worst_top"])
                    if r["hole"]:
                        views_with_hole += 1
                    n += 1
    c = tot["cols"]
    print(f"raycast cross-check over {n} views, {c} columns")
    print(f"  silhouette off by >1.5 px  : {tot['bad_top']} "
          f"({100*tot['bad_top']/c:.2f}%)  worst {wt:.0f} px")
    print(f"    ...attributable to byte/even-length quantisation at a "
          f"silhouette edge: {tot['quant']} ({100*tot['quant']/c:.2f}%)")
    print(f"    ...STRUCTURAL (painter order / missing face)        : "
          f"{tot['struct']} ({100*tot['struct']/c:.2f}%)")
    print(f"  columns where background shows through a wall: {tot['hole']} "
          f"({100*tot['hole']/c:.3f}%) in {views_with_hole}/{n} views")
    tc = sum(H.values())
    print("  silhouette error histogram (px, vs per-column raycast):")
    for k in sorted(H):
        lab = f"{k}-{k+1}" if k < 9 else "9+  "
        print(f"    {lab:>5s} px  {'#'*max(0, H[k]*50//tc):50s} "
              f"{H[k]:7d} ({100*H[k]/tc:5.2f}%)")
    print(f"  wrong wall PEN (flat per-face vs per-column ramp): "
          f"{tot['bad_pen']} ({100*tot['bad_pen']/c:.2f}%)")


if __name__ == "__main__":
    main()
