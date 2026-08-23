"""MEASURE the four chunks main3.asm's deliberate pad cuts a frame into.

    python3 engine2/tools/emu_chunk.py [n]

The pad (engine2/src/main3.asm, PACE_FRAMES = 4) puts a vsync wait after
each of

    chunk 1  bg_fill + march       chunk 3  raster, first half by area
    chunk 2  project_all           chunk 4  raster, the rest

and each wait advances the frame by exactly ONE 20 ms period only if the
chunk before it ran in under 20 ms.  So the question the pad lives or dies
by is not "how long is a frame" but "how often is the LONGEST CHUNK over
20000 us", and that is what this measures -- on the same rig, with the same
16-bit-counter protocol, as engine2/tools/emu_frame.py.

The raster halves are not measured separately (there is no harness entry
that draws half a quad list); raster is measured whole and the split is
reported as a bound, raster/2 <= worst half <= raster.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import emu_frame as ef                                       # noqa: E402

E_MARCH, E_PROJ = 0x801C, 0x8020
PERIOD_US = 20000.0


def chunks(rig, px, py, a):
    bg = rig.bench(ef.E_BG, px, py, a)
    mar = rig.bench(E_MARCH, px, py, a)
    prj = rig.bench(E_PROJ, px, py, a)
    ras = rig.bench(ef.E_RAST, px, py, a)
    return bg, mar, prj, ras


def report(rig, label, px, py, a):
    bg, mar, prj, ras = chunks(rig, px, py, a)
    c1 = bg + mar
    worst_half = max(ras / 2.0, ras - PERIOD_US) if ras else 0.0
    over = [n for n, v in (("1 bg+march", c1), ("2 project", prj),
                           ("3/4 raster half", ras / 2.0)) if v > PERIOD_US]
    print(f"{label:28s} bg {bg/1000:5.1f}  march {mar/1000:5.1f}"
          f"  proj {prj/1000:5.1f}  rast {ras/1000:5.1f}"
          f"  | c1 {c1/1000:5.1f}  c2 {prj/1000:5.1f}"
          f"  c3+c4 {ras/1000:5.1f}"
          f"  total {(c1+prj+ras)/1000:5.1f}"
          + ("   OVER: " + ",".join(over) if over else ""))
    return c1, prj, ras, worst_half


def main():
    rig = ef.Rig()
    rig.measure_overhead()
    print(f"loop overhead {rig.ovh:.2f} us\n")
    grid, solid = ef.load()
    for (label, px, py, a) in ef.scenarios(grid, solid):
        report(rig, label, px, py, a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
