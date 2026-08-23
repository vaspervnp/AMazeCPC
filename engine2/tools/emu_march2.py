"""MEASURE the marcher alone: per-frame setup cost and cost per marched cell.

    python3 engine2/tools/emu_march2.py [nsample]

Same timing protocol as emu_kernel.py (16-bit counter, interrupts off, empty
loop subtracted, method calibrated against a 100-NOP loop).  Reports

    march_us = A + B * ref_cells       (least squares over sampled states)

where ref_cells is free.py's cells_visited -- the SAME denominator
engine2/src/march.asm's header uses, so before/after numbers compare directly.
A is also measured directly by benching march_setup on its own (#8018).
"""

import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import emu_kernel as EK                                        # noqa: E402
import marchmodel as mm                                        # noqa: E402
import world                                                   # noqa: E402

E_MSETUP = 0x8018


def lsq2(data):
    """march_us ~ A + B*ref_cells + C*candidate_faces."""
    X = [[1.0, float(d[0]), float(d[2])] for d in data]
    y = [d[3] for d in data]
    n = len(data)
    A = [[sum(X[k][i] * X[k][j] for k in range(n)) for j in range(3)]
         for i in range(3)]
    b = [sum(X[k][i] * y[k] for k in range(n)) for i in range(3)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        b[i], b[p] = b[p], b[i]
        for r in range(i + 1, 3):
            f = A[r][i] / A[i][i]
            for c in range(i, 3):
                A[r][c] -= f * A[i][c]
            b[r] -= f * b[i]
    co = [0.0] * 3
    for i in (2, 1, 0):
        co[i] = (b[i] - sum(A[i][j] * co[j] for j in range(i + 1, 3))) / A[i][i]
    res = [y[k] - sum(X[k][i] * co[i] for i in range(3)) for k in range(n)]
    return co, (sum(r * r for r in res) / n) ** 0.5


def main(nsample=60, seed=99):
    grid, _, _ = world.load_maze()
    solid = mm.solid_from_grid(grid)
    rig = EK.Rig()
    calib = EK.calibrate(rig)
    ovh = rig.bench(EK.E_EMPTY, 0x0A80, 0x0D80, 0)
    print("loop overhead %.2f us   (100-NOP calibration %.2f)" % (ovh, calib))

    floors = [(x, y) for y in range(16) for x in range(16)
              if grid[y][x] == world.FLOOR]
    rows = []
    for x, y in floors:
        for fx, fy in EK.VP_OFFS:
            px, py = (x << 8) | fx, (y << 8) | fy
            for a in range(72):
                ref = mm.march(solid, px, py, a, push_opaque=True)["visited"]
                r = mm.march(solid, px, py, a)
                rows.append((px, py, a, ref, r["visited"], len(r["faces"])))
    rnd = random.Random(seed)
    pick = rnd.sample(rows, nsample)
    pick.append(max(rows, key=lambda r: r[3]))
    pick.append(max(rows, key=lambda r: r[5]))

    data = []
    for px, py, a, ref, pop, nf in pick:
        t = rig.bench(EK.E_MARCH, px, py, a, us=1200000) - ovh
        data.append((ref, pop, nf, t))
    sm = rig.bench(E_MSETUP, *pick[0][:3], us=1200000) - ovh
    sm2 = rig.bench(E_MSETUP, *pick[-1][:3], us=1200000) - ovh

    n = len(data)
    sx = sum(d[0] for d in data)
    sy = sum(d[3] for d in data)
    sxx = sum(d[0] * d[0] for d in data)
    sxy = sum(d[0] * d[3] for d in data)
    b = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    a0 = (sy - b * sx) / n
    res = [d[3] - (a0 + b * d[0]) for d in data]
    rms = (sum(r * r for r in res) / n) ** 0.5
    co2, rms2 = lsq2(data)

    print("\n=== march, %d states ===" % n)
    print("  march_setup measured directly : %.0f / %.0f us" % (sm, sm2))
    print("  march_us = %.0f + %.1f * ref_cells   (RMS %.0f us)"
          % (a0, b, rms))
    print("  mean march %.0f us over %.2f ref cells"
          % (sy / n, sx / n))
    worst = max(data, key=lambda d: d[3])
    print("  worst sampled: %d ref cells, %d faces, %.0f us"
          % (worst[0], worst[2], worst[3]))
    print("  march_us = %.0f + %.1f * ref_cells + %.1f * faces  (RMS %.0f us)"
          % (co2[0], co2[1], co2[2], rms2))
    return dict(setup=sm, per_cell=b, const=a0, rms=rms)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
