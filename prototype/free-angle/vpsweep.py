"""What viewport size would a free-angle renderer actually fit into?

Scales the Mode 0 viewport keeping the 36:104 byte aspect (so the horizontal
FOV stays at 38 deg) and re-sweeps the maze.  Reports the largest viewport
whose WORST reachable state still fits 40 ms (2 frames at 50 Hz), which is
the criterion the shipped engine holds itself to.
"""

import geom
import world
import free
import fcost


def set_viewport(bw, h):
    geom.VP_BW = bw
    geom.VP_H = h
    geom.VP_PW = bw * 2
    geom.CX = bw
    geom.CY = h / 2.0
    geom.FOCAL = float(h)
    geom.VP_BX = (80 - bw) // 2
    geom.VP_Y = (200 - h) // 2
    free.KHALF = geom.CX / geom.FOCAL


def sweep(grid, offs, astep):
    tot = 0.0
    n = 0
    worst = 0.0
    worst_opt = 0.0
    worst_net = 0.0
    over = 0
    for cy in range(world.MAZE_H):
        for cx in range(world.MAZE_W):
            if grid[cy][cx] != world.FLOOR:
                continue
            for ox, oy in offs:
                for a in range(0, free.N_ANGLES, astep):
                    c = fcost.count(free.build_frame(grid, cx + ox, cy + oy, a))
                    tot += c["hw_ms"]
                    n += 1
                    if c["hw_ms"] > 40.0:
                        over += 1
                    worst = max(worst, c["hw_ms"])
                    worst_opt = max(worst_opt, c["opt_hw_ms"])
                    worst_net = max(worst_net, c["opt_net_ms"])
    return tot / n, worst, over, n, worst_opt, worst_net


def main():
    grid, _, _ = world.load_maze()
    offs = [(0.5, 0.5), (0.25, 0.5), (0.5, 0.25), (0.3, 0.7)]
    print("Free-angle renderer vs viewport size (aspect held, FOV held at "
          "38 deg)")
    print(f"{'bytes':>9s} {'pixels':>9s} {'mean ms':>8s} {'worst ms':>9s} "
          f"{'worst+opt':>10s} {'w+opt+net':>10s} {'verdict':>28s}")
    print("-" * 90)
    for bw, h in ((36, 104), (32, 92), (28, 80), (26, 76), (24, 70),
                  (22, 64), (20, 58), (18, 52), (16, 46)):
        set_viewport(bw, h)
        mean, worst, over, n, worst_opt, worst_net = sweep(grid, offs, 3)
        if worst_net <= 20:
            v = "fits 1 frame (50 fps)"
        elif worst_net <= 40:
            v = "fits 2 frames (25 fps)"
        elif worst_net <= 60:
            v = "needs 3 frames (16.7 fps)"
        else:
            v = "needs 4+ frames"
        print(f"{bw:>4d}x{h:<4d} {bw*2:>4d}x{h:<4d} {mean:>8.1f} "
              f"{worst:>9.1f} {worst_opt:>10.1f} {worst_net:>10.1f} "
              f"{v:>28s}")


if __name__ == "__main__":
    main()
