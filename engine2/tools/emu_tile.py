"""WHAT DOES A TILE BLIT COST?

Boots the real 6128, runs engine2/test/tst_tile.asm on it, and reports
microseconds per TILE and per screen byte for the "fake the C64's
character mode" architecture: precompiled 8x8-pixel tiles blitted into
the viewport.  Same method as emu_byte.py -- every number is a SLOPE
across two tile counts, so the counting loop, the CALL/RET and all
per-run setup cancel exactly.

    python3 engine2/tools/emu_tile.py
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
        ["rasm", "tst_tile.asm", "-o", "../build/tst_tile",
         "-s", "-os", "../build/tst_tile"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_tile.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_tile")):
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
        # the tile-id list: 16 distinct tiles, cycled, so the dispatch
        # really does land on a different 256-byte page every time
        self.c.write_ram(0x7500, bytes(i & 15 for i in range(256)))

    def s(self, n):
        return self.sym[n.upper()]

    def _cnt(self):
        return struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]

    def _probe(self, us):
        a = self._cnt()
        ticks = self.c.run_us(us)
        return ticks, (self._cnt() - a) & 0xFFFF

    def time(self, idx, ntiles=16, nbytes=44, nrows=8):
        self.c.run_us(2000)
        self.c.write_ram(0x8000, self.code)
        self.c.poke(self.s("NTILES"), ntiles)
        self.c.poke(self.s("NBYTES"), nbytes)
        self.c.poke(self.s("NROWS"), nrows)
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


E = dict(nop=0, empty=1, t4reg=2, t4brick=3, t4imm=4, t8reg=5, t8imm=6,
         t4disp=7, bandimm=8, bandreg=9, gen=10)


def main():
    rig = Rig()

    tnop = rig.time(E["nop"])
    tempty = rig.time(E["empty"])
    print(f"calibration: 100 NOPs = {tnop - tempty:8.3f} us "
          f"(must be 100.000)   loop+call+ret = {tempty:.3f} us")
    print()

    print("TILE BLITS -- slope across 8 and 24 tiles, so the whole")
    print("per-tile cost (blit + screen advance + loop) is in the number.")
    print()
    print(f"{'tile':46} {'us/tile':>9} {'bytes':>6} {'us/byte':>9}")
    print("-" * 76)

    out = {}
    for name, idx, w, note in (
            ("4x8 px, one held word (flat, no mortar)", "t4reg", 4, ""),
            ("4x8 px, two words + a mortar course", "t4brick", 4, ""),
            ("4x8 px, every byte an immediate", "t4imm", 4, ""),
            ("4x8 px, immediate, via id-list dispatch", "t4disp", 4, ""),
            ("16x8 px, two held words", "t8reg", 8, ""),
            ("16x8 px, every byte an immediate", "t8imm", 8, ""),
    ):
        t8 = rig.time(E[idx], ntiles=8)
        t24 = rig.time(E[idx], ntiles=24)
        per = (t24 - t8) / 16.0
        nb = w * 8
        out[idx] = per
        print(f"{name:46} {per:9.3f} {nb:6d} {per / nb:9.4f}")

    print()
    print(f"  dispatch overhead (t4disp - t4imm): "
          f"{out['t4disp'] - out['t4imm']:.3f} us per tile")

    print()
    print("ALIGNED BAND CONTROL -- 8 scanlines that never cross a")
    print("character row, so the per-scanline walk has no wrap test.")
    print()
    for name, idx in (("band, ld de,nn : push de", "bandimm"),
                      ("band, push de : push bc (4-byte repeat)", "bandreg")):
        # us/byte: slope across width.  nrows BANDS of 8 scanlines each,
        # so 24 more bytes per scanline is 24*8*nrows more bytes.
        nb = 8
        a = rig.time(E[idx], nbytes=20, nrows=nb)
        b = rig.time(E[idx], nbytes=44, nrows=nb)
        slope = (b - a) / (24.0 * 8 * nb)
        # us/scanline: slope across band count at a fixed width
        c = rig.time(E[idx], nbytes=44, nrows=4)
        d = rig.time(E[idx], nbytes=44, nrows=12)
        perline = (d - c) / 8.0 / 8.0
        fixed = perline - slope * 44
        print(f"  {name:42} {slope:7.4f} us/byte, "
              f"{fixed:6.3f} us fixed per scanline "
              f"-> {slope + fixed / 44:6.3f} us/byte at 44 wide")

    print()
    print("GENERATING the span code -- what tiles exist to avoid.")
    a = rig.time(E["gen"], nbytes=20, nrows=8)
    b = rig.time(E["gen"], nbytes=44, nrows=8)
    print(f"  copy precomputed words into the ld de,nn fields  "
          f"{(b - a) / (24.0 * 8):7.4f} us per screen byte")


if __name__ == "__main__":
    main()
