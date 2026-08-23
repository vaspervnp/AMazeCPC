"""Time proj_face over the WORST frames the marcher can actually produce.

Sweeps every floor position x heading of the real maze with the float
reference to find the frames with the most candidate faces, then runs those
exact face lists through the Z80 on the emulator and reports the measured
geometry cost of the whole frame.
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import run_proj_test as R                                   # noqa: E402
import projmodel as pm                                      # noqa: E402
from run_proj_test import free, gentab                      # noqa: E402
import world                                                # noqa: E402


def sweep(grid, step=2):
    out = []
    for y in range(world.MAZE_H):
        for x in range(world.MAZE_W):
            if world.cell_at(grid, x, y) != world.FLOOR:
                continue
            for fx, fy in ((0.5, 0.5), (0.25, 0.75), (0.75, 0.25)):
                px, py = x + fx, y + fy
                for a in range(0, 72, step):
                    f = free.build_frame(grid, px, py, a)
                    out.append((f["n_candidates"], f["n_faces"],
                                f["cells_visited"], px, py, a))
    out.sort(reverse=True)
    return out


def main():
    tables, code, sym = R.build()
    m = R.Machine(tables, code, sym)
    grid, _, _ = world.load_maze()
    t_empty, _ = m.time_loop("TM_EMPTY", 200000)

    worst = sweep(grid)
    print(f"swept {len(worst)} (position, heading) frames of the real maze")
    print(f"worst candidate count {worst[0][0]}, "
          f"worst drawn {max(w[1] for w in worst)}, "
          f"worst cells visited {max(w[2] for w in worst)}")
    print()
    print(f"  {'player':24s} {'cand':>5s} {'drawn':>6s} {'us/face':>9s} "
          f"{'proj_face ms':>13s}")

    m.c.poke(sym["N_FACES"], 1)
    tb0, _ = m.time_loop("TM_BATCH0", 200000)
    harness = tb0 - t_empty

    rows = []
    for nc, nf, ncell, px, py, ang in worst[:10]:
        ipx, ipy = int(math.floor(px)), int(math.floor(py))
        fx = int(round((px - ipx) * 256)) & 0xFF
        fy = int(round((py - ipy) * 256)) & 0xFF
        _, cand, _ = free.march(grid, px, py, ang, {})
        recs = []
        for wx, wy, fd, _d in cand:
            a = R.lattice(wx - ipx, wy - ipy, fd)
            if max(abs(v) for v in a) > 8:
                continue
            recs.append(a + (fd,))
        if not recs:
            continue
        m.set_player(fx, fy, ang)
        m.c.write_ram(sym["IN_BUF"],
                      b"".join(bytes(v & 0xFF for v in r) for r in recs))
        m.c.poke(sym["N_FACES"], len(recs))
        t, n = m.time_loop("TM_BATCH", 200000)
        per = t - t_empty - harness
        rows.append((len(recs), nf, per))
        print(f"  ({px:5.2f},{py:5.2f}) a={ang:2d}   {len(recs):5d} {nf:6d} "
              f"{per:9.1f} {per*len(recs)/1000:13.2f}")

    setup, _ = m.time_loop("TM_SETUP", 400000)
    setup -= t_empty
    tot = max(c * p for c, f, p in rows)
    print()
    print(f"  proj_setup, once per frame            : {setup:8.1f} us")
    print(f"  WORST measured proj_face total        : {tot:8.1f} us")
    print(f"  worst geometry kernel per frame       : "
          f"{(tot+setup)/1000:8.2f} ms  ({(tot+setup)/20000*100:.0f}% of one"
          f" 20 ms vsync frame)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
