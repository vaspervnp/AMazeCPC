"""What does a FULL COLUMN RAYCASTER cost on the real 6128?

Boots the machine, runs engine2/test/tst_ray.asm on it, and reports the
per-piece microsecond costs of the Wolfenstein-shaped renderer:
per-ray setup, per-DDA-step, per-column post-hit, and the two textured
strip inner loops.  Every number is a SLOPE across two parameter values,
so the counting loop, the CALL/RET and all per-run setup cancel.

    python3 engine2/tools/emu_ray.py
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
ORG = 0x4000


def build():
    r = subprocess.run(
        ["rasm", "tst_ray.asm", "-I", "../src", "-o", "../build/tst_ray",
         "-s", "-os", "../build/tst_ray"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_ray.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_ray")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    return code, sym


class Rig:
    def __init__(self):
        self.code, self.sym = build()
        self.c = CPC()
        self.c.run_frames(60)
        self.c.write_ram(ORG, self.code)
        # texture page, cache page, and the three lookup tables the
        # post-hit block reads.  Contents are irrelevant to timing but
        # must be real RAM and must not send anything out of range.
        self.c.write_ram(0x7000, bytes(256))                # MAP
        self.c.write_ram(0x7200, bytes((i * 37) & 0xFF for i in range(256)))
        self.c.write_ram(0x7700, bytes((i * 91) & 0xFF for i in range(256)))
        # HTAB: projected height Q12.4, so that h lands in 1..96
        lo = bytearray(256)
        hi = bytearray(256)
        for zq in range(256):
            d = max(1, zq)
            hv = min(0x7FF, (96 * 16 * 4) // d)
            lo[zq] = hv & 0xFF
            hi[zq] = hv >> 8
        self.c.write_ram(0x7300, bytes(lo))
        self.c.write_ram(0x7400, bytes(hi))
        self.c.write_ram(0x7500, bytes(range(256)))         # TEXSTEP/STARTOF
        # LINETAB: 96 word screen addresses, mode-0 interleave
        lt = bytearray()
        for y in range(128):
            a = 0xC000 + (y & 7) * 0x800 + (y >> 3) * 80
            lt += struct.pack("<H", a)
        self.c.write_ram(0x7600, bytes(lt))

    def s(self, n):
        return self.sym[n.upper()]

    def _cnt(self):
        return struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]

    def _probe(self, us):
        a = self._cnt()
        ticks = self.c.run_us(us)
        return ticks, (self._cnt() - a) & 0xFFFF

    def time(self, idx, nsteps=8, nrows=8):
        # the subjects patch their own immediates; restore the image
        self.c.run_us(2000)
        self.c.write_ram(ORG, self.code)
        self.c.poke(self.s("NSTEPS"), nsteps)
        self.c.poke(self.s("NROWS"), nrows)
        self.c.set_pc(ORG + 0x2000 + 4 * idx)
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


E = dict(nop=0, empty=1, mul8=2, mul16=3, recip=4, ray=5, post=6,
         strip=7, stex=8, raycheap=9, baked=10, rayy=11, rayopt=12, post8=13)


def main():
    rig = Rig()
    tnop = rig.time(E["nop"])
    tempty = rig.time(E["empty"])
    print(f"calibration: 100 NOPs = {tnop - tempty:.3f} us "
          f"(loop control {tempty:.3f} us)")
    print()

    def sub(name, **kw):
        return rig.time(E[name], **kw) - tempty

    for n in ("mul8", "mul16", "recip", "post", "post8"):
        print(f"{name_of(n):38s} {sub(n):9.3f} us")
    print()

    for n in ("ray", "raycheap", "rayy", "rayopt"):
        a = sub(n, nsteps=2)
        b = sub(n, nsteps=14)
        slope = (b - a) / 12.0
        fixed = a - 2 * slope
        print(f"{name_of(n):38s} total@2 {a:8.3f}  total@14 {b:8.3f}")
        print(f"{'':38s} per DDA step {slope:7.3f} us"
              f"   per-ray fixed {fixed:8.3f} us")
    print()

    for n in ("strip", "baked", "stex"):
        a = sub(n, nrows=2)
        b = sub(n, nrows=10)
        slope = (b - a) / (8 * 8.0)
        fixed = a - 16 * slope
        print(f"{name_of(n):38s} {slope:7.3f} us/byte "
              f"  per-strip fixed {fixed:8.3f} us")


def name_of(n):
    return {
        "mul8": "mul8x8u (quarter squares)",
        "mul16": "mul16x8u",
        "recip": "recip_zv",
        "post": "post-hit column block",
        "ray": "ray, mul16x8u seeds",
        "raycheap": "ray, mul8x8u seeds",
        "rayy": "ray, Y-axis steps only",
        "rayopt": "ray, fully optimised",
        "post8": "post-hit block, 8x8 texcol mul",
        "strip": "strip, POP-fed from column cache",
        "stex": "strip, per-pixel fractional step",
        "baked": "strip, POP-fed, screen addrs baked",
    }[n]


if __name__ == "__main__":
    main()
