"""Re-express the MEASURED kernel cost in free.py's own counters.

engine2/tools/emu_kernel.py fits

    geometry_us = A + B * ref_cells + C * candidate_faces

where ref_cells / candidate_faces are the FIXED-POINT model's counters.
fcost.py multiplies free.py's counters instead, and the two differ a little
(the Z80 backface-culls during the march, free.py during projection; the Z80
frustum is 0.13% wider).  So refit the same measured microseconds against
free.py's cells_visited and n_candidates -- those are the numbers the
viewport sweep will actually feed in.
"""

import json
import os
import statistics
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.join(_ROOT, "prototype", "free-angle"))

import gentab                                                # noqa: E402
import geom                                                  # noqa: E402
import free                                                  # noqa: E402
import world                                                 # noqa: E402

# The viewport comes from engine2/src/vpcfg.inc, via gentab -- NOT from a
# copy pasted here, which would silently disagree with the tables.
geom.VP_BX, geom.VP_BW = gentab.VP_BX, gentab.VP_BW
geom.VP_Y, geom.VP_H = gentab.VP_Y, gentab.VP_H
geom.VP_PW = gentab.VP_PW
geom.CX, geom.CY = gentab.CX, gentab.CY

geom.ZNEAR = gentab.ZNEAR
free.ZNEAR = gentab.ZNEAR
free.set_focal(gentab.FOCAL_H, gentab.FOCAL_V)
free.R_MAX = 6


def lstsq(X, y):
    k = len(X[0])
    n = len(X)
    A = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(k)]
         for i in range(k)]
    b = [sum(X[r][i] * y[r] for r in range(n)) for i in range(k)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        b[i], b[p] = b[p], b[i]
        for r in range(i + 1, k):
            f = A[r][i] / A[i][i]
            for c in range(i, k):
                A[r][c] -= f * A[i][c]
            b[r] -= f * b[i]
    co = [0.0] * k
    for i in range(k - 1, -1, -1):
        co[i] = (b[i] - sum(A[i][j] * co[j] for j in range(i + 1, k))) / A[i][i]
    res = [y[r] - sum(X[r][i] * co[i] for i in range(k)) for r in range(n)]
    ybar = statistics.mean(y)
    r2 = 1 - sum(v * v for v in res) / sum((v - ybar) ** 2 for v in y)
    return co, (sum(v * v for v in res) / n) ** 0.5, r2, max(abs(v)
                                                             for v in res)


def main():
    j = json.load(open(os.path.join(_HERE, "..", "build",
                                    "kernel_timing.json")))
    grid, _, _ = world.load_maze()
    X, y, rows = [], [], []
    for d in j["sample"]:
        f = free.build_frame(grid, d["px"] / 256.0, d["py"] / 256.0, d["a"])
        X.append([1.0, float(f["cells_visited"]), float(f["n_candidates"])])
        y.append(d["total"])
        rows.append((f["cells_visited"], f["n_candidates"], f["n_faces"],
                     d["total"]))
    co, rms, r2, mx = lstsq(X, y)
    print("MEASURED Z80 geometry cost in free.py's own counters, %d states:"
          % len(y))
    print("  us = %.0f  +  %.1f * cells_visited  +  %.1f * n_candidates"
          % tuple(co))
    print("  R^2 %.4f   RMS residual %.0f us   worst residual %.0f us"
          % (r2, rms, mx))
    print("  mean measured %.0f us,  max measured %.0f us"
          % (statistics.mean(y), max(y)))

    # the same fit against n_faces (drawn), for the like-for-like comparison
    # with the old US_FACE = 500 estimate
    X2 = [[1.0, r[0] * 1.0, r[2] * 1.0] for r in rows]
    co2, rms2, r22, _ = lstsq(X2, y)
    print("\nsame data against n_FACES (drawn) instead of candidates:")
    print("  us = %.0f  +  %.1f * cells_visited  +  %.1f * n_faces"
          "   (R^2 %.4f, RMS %.0f)" % (co2[0], co2[1], co2[2], r22, rms2))
    print("\nfor reference, the hand estimate this replaces:")
    print("  us = 0    +  60.0 * cells_visited  +  500.0 * n_faces")
    print("  ratio measured/estimated, at the mean state:")
    mc = statistics.mean(r[0] for r in rows)
    mf = statistics.mean(r[2] for r in rows)
    est = 60 * mc + 500 * mf
    print("    mean cells_visited %.1f, n_faces %.1f, n_candidates %.1f"
          % (mc, mf, statistics.mean(r[1] for r in rows)))
    print("    estimated %.0f us   measured %.0f us   x%.1f"
          % (est, statistics.mean(y), statistics.mean(y) / est))
    json.dump(dict(coef_candidates=co, coef_faces=co2, r2=r2, rms=rms),
              open(os.path.join(_HERE, "..", "build", "kernel_fit_free.json"),
                   "w"), indent=1)


if __name__ == "__main__":
    main()
