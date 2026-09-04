"""Worst case the kernel can be given: an OPEN ROOM.

The shipped maze (tools/world.py) is a one-cell-wide labyrinth -- it has no
cell whose 3x3 neighbourhood is open, so `emu_kernel.py time` can never
report an "open room" row.  This script patches a synthetic map into the
harness's MAZEDATA and measures the kernel there, which bounds what any
future level design can cost.

    python3 engine2/tools/emu_room.py

TWO ROWS A MAP, AND THAT IS THE POINT OF THE FILE.  It used to print one,
at the state with the most CANDIDATE faces, tie-broken by the flood's own
reference-cell count -- which is the right question for the march and the
wrong one for the projector.  In hall9 that state projects ZERO quads
while states projecting SIX exist in the same room, so the `faces us`
column was timing a projector that had been handed nothing and the TOTAL
bounded neither half.  Both projmodel entry points agree the zero is
arithmetically right; it was the CHOICE OF STATE that was not a bound.

So each map is measured twice: once where the flood is worst, which is
what march_setup and the cell loop cost, and once where the most faces
actually reach the screen, which is what project_all costs.  The bound a
level designer wants is the larger of the two totals.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import emu_kernel as EK                                      # noqa: E402
import marchmodel as mm                                      # noqa: E402
import projmodel as pm                                       # noqa: E402


def make(kind):
    """-> 256-byte SOLID (1 = wall, 0 = open)."""
    g = bytearray(1 for _ in range(256))
    if kind == "hall5":
        box = range(5, 10)
    elif kind == "hall9":
        box = range(3, 12)
    else:                                   # everything open but the border
        box = range(1, 15)
    for y in box:
        for x in box:
            g[y * 16 + x] = 0
    return bytes(g)


def main():
    rig = EK.Rig()
    calib = EK.calibrate(rig)
    print("  (calibration residual %.2f us)" % (calib - 100.0))
    ovh = rig.bench(EK.E_EMPTY, 0x0880, 0x0880, 0)
    print("\nloop overhead %.1f us\n" % ovh)

    print("%-10s %-8s %-10s %6s %5s %5s %6s %10s %10s %10s"
          % ("map", "worst", "state", "refcel", "pop", "cand", "quads",
             "march us", "faces us", "TOTAL us"))
    for kind, cells in (("hall5", range(5, 10)), ("hall9", range(3, 12)),
                        ("openfield", range(1, 15))):
        solid = make(kind)
        rig.c.write_ram(rig.s("MAZEDATA"), solid)
        march_best = proj_best = None
        for cx in cells:
            for cy in cells:
                for a in range(0, 72, 2):
                    px, py = (cx << 8) | 128, (cy << 8) | 128
                    r = mm.march(solid, px, py, a)
                    ref = mm.march(solid, px, py, a,
                                   push_opaque=True)["visited"]
                    nq = quads(r, px, py, a)
                    mkey = (len(r["faces"]), ref)
                    if march_best is None or mkey > march_best[0]:
                        march_best = (mkey, px, py, a, r, ref, nq)
                    if proj_best is None or nq > proj_best[6]:
                        proj_best = ((len(r["faces"]), ref), px, py, a,
                                     r, ref, nq)
        for why, pick in (("flood", march_best), ("project", proj_best)):
            (nf, _), px, py, a, r, ref, nq = pick
            row(rig, ovh, kind, why, px, py, a, r, ref, nf, nq)


def quads(r, px, py, a):
    """How many of the marched faces actually reach the screen."""
    fr = pm.Frame(px / 256.0, py / 256.0, a)
    n = 0
    for wx, wy, fd, door, k in r["faces"]:
        (ax, ay), (bx, by), _ = pm.face_endpoints(wx, wy, fd)
        if pm.project_face_ij(fr, ax - fr.ipx, ay - fr.ipy,
                              bx - fr.ipx, by - fr.ipy, fd) is not None:
            n += 1
    return n


def row(rig, ovh, kind, why, px, py, a, r, ref, nf, nq):
    t = rig.bench(EK.E_ALL, px, py, a, us=2000000) - ovh
    tm = rig.bench(EK.E_MARCH, px, py, a, us=2000000) - ovh
    ts = rig.bench(EK.E_SETUP, px, py, a) - ovh
    print("%-10s %-8s %-10s %6d %5d %5d %6d %10.0f %10.0f %10.0f"
          % (kind, why, f"({px>>8},{py>>8})a{a}", ref, r["visited"], nf, nq,
             tm, t - tm - ts, t))
    if r["faces"] and rig.c.peek(rig.s("M_DROPPED")):
        print("   NOTE: faces dropped, a bucket overflowed")


if __name__ == "__main__":
    main()
