"""Re-run prototype/free-angle's frame budget with the MEASURED per-face cost.

fcost.py's US_FACE = 500 us is a hand count whose single largest line item is
"2 perspective divides ... 2 x 135 = 270 us".  engine2/test/test_tables.py
measures that item on a cycle-accurate 6128:

    PROJ/HTAB  (16x16 quarter-square multiply)   573 us/endpoint  -> 1146/face
    PROJN/HTN  (normalised, one 8x8 multiply)    360 us/endpoint  ->  720/face

so the real per-face cost is  500 - 270 + measured, i.e. ~950 (fast) or
~1450 (exact) rather than 500.  This script reports what that does to the
worst reachable frame at the engine2 viewport (48x128 bytes, 60 deg FOV).

    PYTHONPATH=tools:prototype/free-angle python3 engine2/tools/budget.py
"""

import math
import sys

import geom
import world
import free
import fcost

VP_BX, VP_BW, VP_Y, VP_H = 16, 48, 0, 128
FOV_DEG = 60.0

US_FACE_REST = 500 - 270        # everything in the estimate BUT the divides
MEASURED = {
    "hand estimate (fcost.py as shipped)": 270,
    "measured PROJN/HTN, 1 x 8x8 mul": 720,
    "measured PROJ/HTAB, 1 x 16x16 mul": 1146,
}


def configure():
    geom.configure(0)
    geom.VP_BX, geom.VP_BW, geom.VP_Y, geom.VP_H = VP_BX, VP_BW, VP_Y, VP_H
    geom.VP_PW = VP_BW * 2
    geom.CX = geom.VP_PW / 2.0
    geom.CY = VP_H / 2.0
    fh = geom.CX / math.tan(math.radians(FOV_DEG / 2.0))
    free.set_focal(fh, float(VP_H))
    return fh


def sweep(grid, step=3):
    out = []
    for y in range(world.MAZE_H):
        for x in range(world.MAZE_W):
            if grid[y][x] != world.FLOOR:
                continue
            for fx, fy in ((0.5, 0.5), (0.25, 0.75), (0.75, 0.25)):
                for a in range(0, 72, step):
                    out.append(free.build_frame(grid, x + fx, y + fy, a))
    return out


def main():
    fh = configure()
    grid, _, _ = world.load_maze()
    frames = sweep(grid)
    print(f"viewport {VP_BW}x{VP_H} bytes, FOV {FOV_DEG:.0f} deg "
          f"(FOCAL_H {fh:.2f}), {len(frames)} reachable views sampled")
    print(f"worst view: {max(f['n_faces'] for f in frames)} faces, "
          f"{max(f['cells_visited'] for f in frames)} marched cells")
    print()
    print(f"{'projection cost per face':38s} {'US_FACE':>8s}"
          f" {'worst':>8s} {'w/ wedge split':>15s} {'frames':>7s}")
    for label, divide_us in MEASURED.items():
        fcost.US_FACE = US_FACE_REST + divide_us
        c = [fcost.count(f) for f in frames]
        worst = max(d["hw_ms_net"] for d in c)
        wopt = max(d["opt_net_ms"] for d in c)
        print(f"{label:38s} {fcost.US_FACE:8d}"
              f" {worst:7.1f}ms {wopt:14.1f}ms {math.ceil(wopt / 20):7d}")
    print()
    print("Budget is 4 vsync frames = 80.0 ms.  The frame is fill-dominated,")
    print("so a 2.7-4.2x error in the projection estimate costs ~8-13 ms of")
    print("the worst frame -- painful but not fatal, PROVIDED the wedge/body")
    print("split of the quad is implemented.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
