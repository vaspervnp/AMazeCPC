"""What does a TEXTURED span cost, and what does the texture SETUP cost?

Boots the real 6128, runs engine2/test/tst_m1.asm on it.  Every figure is
a SLOPE across two counts, so the counting loop, the CALL/RET and all
per-run setup cancel exactly -- except where a TOTAL is what is wanted
(the whole-face pair), which is reported as a total and labelled so.

    python3 engine2/tools/emu_m1.py
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
        ["rasm", "tst_m1.asm", "-o", "../build/tst_m1",
         "-s", "-os", "../build/tst_m1"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_m1.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_m1")):
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
        # SRC: the linear word buffer s_patchpop pops from
        self.c.write_ram(0x7200, bytes((i * 91) & 0xFF for i in range(256)))
        # JTAB: joint records (immediate address, AND mask, OR mask).  The
        # addresses MUST be real PUSHIMM immediates -- a random table pokes
        # the harness's own code and the run stops meaning anything.
        pi = self.sym["PUSHIMM"]
        jt = bytearray()
        for i in range(16):
            a = pi + 4 * (i % 22) + 1
            jt += bytes((a & 0xFF, a >> 8, 0xCC, 0x11))
        self.c.write_ram(0x7400, bytes(jt))
        # TTAB: t = p / (p + (Q-p)*R/256), one page per p, Q = 4.  Only
        # the CONTENTS are modelled here; the timing depends on nothing
        # but the table being real RAM at a page boundary.
        tt = bytearray()
        for p in (1, 2, 3):
            for r in range(256):
                den = p + (4 - p) * (r / 256.0)
                tt.append(max(0, min(255, int(round(256.0 * p / den)) - 1)))
        self.c.write_ram(0x7600, bytes(tt))

    def s(self, n):
        return self.sym[n.upper()]

    def _cnt(self):
        return struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]

    def _probe(self, us):
        a = self._cnt()
        ticks = self.c.run_us(us)
        return ticks, (self._cnt() - a) & 0xFFFF

    def time(self, idx, nbytes=44, nlines=96, nwords=22, njoint=4, nunit=8):
        # set_pc lands mid-instruction and every subject here PATCHES ITS
        # OWN JP, so settle, then restore the code image from disc.
        self.c.run_us(2000)
        self.c.write_ram(0x8000, self.code)
        self.c.poke(self.s("NBYTES"), nbytes)
        self.c.poke(self.s("NLINES"), nlines)
        self.c.poke(self.s("NWORDS"), nwords)
        self.c.poke(self.s("NJOINT"), njoint)
        self.c.poke(self.s("NUNIT"), nunit)
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


E = dict(nop=0, empty=1, patchimm=2, patchpop=3, joint=4, push12=5,
         pushimm=6, faceflat=7, facetex=8, jcol=9, jcol2=10)


def main():
    rig = Rig()
    tnop = rig.time(E["nop"])
    tempty = rig.time(E["empty"])
    print(f"calibration: 100 NOPs = {tnop - tempty:8.3f} us "
          f"(must be 100.000)   loop+call+ret = {tempty:.3f} us")

    print("\n--- the fill itself -------------------------------------")
    t22 = rig.time(E["pushimm"], nbytes=22, nlines=32)
    t44 = rig.time(E["pushimm"], nbytes=44, nlines=32)
    sl = (t44 - t22) / (44 * 32 - 22 * 32)
    print(f"  LD DE,nn / PUSH DE   {sl:7.4f} us/byte   (control: 3.5000)")

    n4 = rig.time(E["push12"], nunit=4)
    n8 = rig.time(E["push12"], nunit=8)
    sl12 = (n8 - n4) / ((8 - 4) * 12)
    print(f"  6 words + 2 EXX      {sl12:7.4f} us/byte   "
          f"12-byte PERIODIC pattern, no reload")

    print("\n--- the per-face texture SETUP --------------------------")
    a = rig.time(E["patchimm"], nwords=11)
    b = rig.time(E["patchimm"], nwords=22)
    slp = (b - a) / (22 - 11)
    print(f"  patch, constant word {slp:7.3f} us/word  "
          f"= {slp/2:5.3f} us/byte   ({slp*22:6.1f} us for a 44-byte face)")

    a = rig.time(E["patchpop"], nwords=11)
    b = rig.time(E["patchpop"], nwords=22)
    slq = (b - a) / (22 - 11)
    print(f"  patch, POP-fed       {slq:7.3f} us/word  "
          f"= {slq/2:5.3f} us/byte   ({slq*22:6.1f} us for a 44-byte face)")

    a = rig.time(E["joint"], njoint=4)
    b = rig.time(E["joint"], njoint=16)
    slj = (b - a) / (16 - 4)
    print(f"  one mortar pixel     {slj:7.3f} us/joint (read-modify-write "
          f"into one immediate)")

    a = rig.time(E["jcol"], njoint=1)
    b = rig.time(E["jcol"], njoint=3)
    slc = (b - a) / (3 - 1)
    print(f"  mortar COLUMN, all-in {slc:7.3f} us/joint (divide + multiply "
          f"+ mask + the RMW,")
    print(f"  {'':22s}{'':7s}  no tables: a one-sided upper bound)")
    print(f"  -> three interior joints on one face: {3*slc:6.1f} us")

    a = rig.time(E["jcol2"], njoint=1) - tempty
    b = rig.time(E["jcol2"], njoint=3) - tempty
    sl2 = (b - a) / (3 - 1)
    face2 = a - sl2                     # the once-per-face divide
    print(f"  TABLE-DRIVEN          {sl2:7.3f} us/joint  + {face2:6.1f} us "
          f"ONCE per face (the ratio divide)")
    print(f"  -> three interior joints on one face: {b:6.1f} us"
          f"   ({3*slc/b:4.1f}x better than no tables)")

    print("\n--- a WHOLE 44 x 96 wall-face body (totals, not slopes) --")
    ff = rig.time(E["faceflat"], nbytes=44, nlines=96) - tempty
    for nj in (0, 4, 8):
        ft = rig.time(E["facetex"], nbytes=44, nlines=96, njoint=nj) - tempty
        print(f"  flat {ff:9.1f} us   textured ({nj:2d} joints) {ft:9.1f} us"
              f"   +{ft-ff:8.1f} us  = x{ft/ff:5.3f}")

    print("\n--- and a far face, 6 bytes x 14 lines -------------------")
    ff = rig.time(E["faceflat"], nbytes=6, nlines=14) - tempty
    ft = rig.time(E["facetex"], nbytes=6, nlines=14, nwords=3,
                  njoint=4) - tempty
    print(f"  flat {ff:9.1f} us   textured {ft:9.1f} us   +{ft-ff:8.1f} us"
          f"  = x{ft/ff:5.3f}")


if __name__ == "__main__":
    main()
