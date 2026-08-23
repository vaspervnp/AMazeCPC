"""What does a geometrically honest GRID cost, on the booted 6128?

Runs engine2/test/tst_grid.asm on a cycle-accurate CPC and reports, as
SLOPES across two sizes (so the loop, the CALL/RET and all per-run setup
cancel exactly):

    PUSH IY vs PUSH DE          the price of substituting one push at
                                each end of a run to draw the face's
                                END COLUMNS
    body scanline, plain        raster.asm:rq_bline verbatim
    body scanline + end columns the same run, same push count
    joint row PAIR, as shipped  raster_joint's second pass
    joint row PAIR, folded      accumulator and both screen pointers in
                                registers, address stepped not looked up
    joint row PAIR, math only   the span arithmetic with no screen at all

    python3 engine2/tools/emu_grid.py
"""

import os
import struct
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

from cpc import CPC                                         # noqa: E402

BUILD = os.path.join(_E2, "build")


def build():
    r = subprocess.run(
        ["rasm", "tst_grid.asm", "-o", "../build/tst_grid",
         "-s", "-os", "../build/tst_grid"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_grid.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_grid")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    return code, sym


class Rig:
    def __init__(self):
        self.code, self.sym = build()
        self.c = CPC()
        self.c.run_frames(60)
        self.c.write_ram(0x8000, self.code)

    def s(self, n):
        return self.sym[n.upper()]

    def _cnt(self):
        return struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]

    def _probe(self, us):
        a = self._cnt()
        ticks = self.c.run_us(us)
        return ticks, (self._cnt() - a) & 0xFFFF

    def time(self, idx, nbytes=44, nlines=32, npairs=16):
        # set_pc lands mid-instruction and several subjects patch their own
        # JP, so restore the code image before every measurement.
        self.c.run_us(2000)
        self.c.write_ram(0x8000, self.code)
        self.c.poke(self.s("NBYTES"), nbytes)
        self.c.poke(self.s("NLINES"), nlines)
        self.c.poke(self.s("NPAIRS"), npairs)
        self.c.set_pc(0x8000 + 4 * idx)
        self.c.run_us(50000)
        ticks, n = self._probe(200000)
        if n == 0:
            ticks, n = self._probe(4000000)
        per = (ticks / 4.0) / max(n, 1)
        us = max(200000, min(200000000, int(per * 12000)))
        ticks, n = self._probe(us)
        if not 1000 < n < 60000:
            raise RuntimeError(f"counter unusable: {n} (us={us})")
        return (ticks / 4.0) / n


E = dict(nop=0, empty=1, bline=2, bedge=3, pushiy=4,
         jorig=5, jfold=6, jfold1=7, jmath=8, jtrue=9)


def main():
    rig = Rig()
    tnop = rig.time(E["nop"])
    tempty = rig.time(E["empty"])
    print(f"calibration: 100 NOPs = {tnop - tempty:8.3f} us "
          f"(must be 100.000)   loop+call+ret = {tempty:.3f} us")
    print()

    # ---- 1. what does one PUSH cost, DE against IY -----------------------
    print("PER PUSH (slope over byte count, 32 scanlines):")
    out = {}
    for name, idx in (("PUSH DE", "bline"), ("PUSH IY", "pushiy")):
        t22 = rig.time(E[idx], nbytes=22, nlines=32)
        t44 = rig.time(E[idx], nbytes=44, nlines=32)
        per_byte = (t44 - t22) / (22 * 32)
        out[name] = per_byte
        print(f"  {name:28} {per_byte:7.4f} us/byte = "
              f"{2*per_byte:7.4f} us per push")
    print(f"  -> the DD/FD prefix costs {2*(out['PUSH IY']-out['PUSH DE']):.4f}"
          f" us per push")
    print()

    # ---- 2. one body scanline, with and without the end columns ----------
    print("PER BODY SCANLINE (slope over line count, 44 bytes):")
    for name, idx in (("rq_bline verbatim", "bline"),
                      ("+ both END COLUMNS", "bedge"),
                      ("+ joint folded ALL the way", "jtrue")):
        a = rig.time(E[idx], nbytes=44, nlines=16)
        b = rig.time(E[idx], nbytes=44, nlines=48)
        per = (b - a) / 32.0
        out[name] = per
        print(f"  {name:28} {per:7.3f} us/scanline   "
              f"(44-byte line = {a/16:7.2f} us)")
    print(f"  -> the two vertical end columns cost "
          f"{out['+ both END COLUMNS'] - out['rq_bline verbatim']:.3f}"
          f" us per scanline")
    jt = out['+ joint folded ALL the way'] - out['rq_bline verbatim']
    print(f"  -> a fully folded joint scanline costs {jt:.3f} us on top,"
          f"  = {2*jt:.1f} us per mirrored PAIR")
    print()

    # ---- 3. one course-joint row PAIR ------------------------------------
    print("PER COURSE-JOINT ROW PAIR (slope over pair count):")
    for name, idx in (("raster_joint, as shipped", "jorig"),
                      ("FOLDED, 0 edge steps", "jfold"),
                      ("FOLDED, 1 edge step/row", "jfold1"),
                      ("span arithmetic ONLY", "jmath")):
        a = rig.time(E[idx], npairs=8)
        b = rig.time(E[idx], npairs=24)
        per = (b - a) / 16.0
        out[name] = per
        print(f"  {name:28} {per:7.3f} us/pair")
    print(f"  -> folding saves "
          f"{out['raster_joint, as shipped'] - out['FOLDED, 0 edge steps']:.1f}"
          f" us/pair, "
          f"{100*(1 - out['FOLDED, 0 edge steps']/out['raster_joint, as shipped']):.0f}%")
    print(f"  -> of the folded pair, "
          f"{100*out['span arithmetic ONLY']/out['FOLDED, 0 edge steps']:.0f}%"
          f" is arithmetic that no folding can remove")
    print(f"  -> one Bresenham edge step costs "
          f"{out['FOLDED, 1 edge step/row'] - out['FOLDED, 0 edge steps']:.2f}"
          f" us per pair")


if __name__ == "__main__":
    main()
