"""What does a screen byte COST when you cannot PUSH it?

Boots the real 6128, runs engine2/test/tst_byte.asm on it, and reports
microseconds per screen byte for every way of placing one.  Each subject
is timed at two byte counts and the SLOPE is reported, so the counting
loop, the CALL/RET and all per-run setup cancel exactly.

    python3 engine2/tools/emu_byte.py
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
        ["rasm", "tst_byte.asm", "-o", "../build/tst_byte",
         "-s", "-os", "../build/tst_byte"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_byte.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_byte")):
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
        # a texture page and a linear source buffer; contents are
        # irrelevant to timing but must not be ROM
        self.c.write_ram(0x7000, bytes((i * 37) & 0xFF for i in range(256)))
        self.c.write_ram(0x7200, bytes((i * 91) & 0xFF for i in range(256)))
        # s_mortar reads ADDRESSES out of this table and writes to them,
        # so they have to be real screen bytes: a random table poked the
        # harness's own code and the run stopped meaning anything.
        pk = bytearray()
        for i in range(24):
            a = 0xC012 + 3 * i
            pk += bytes((a & 0xFF, a >> 8, 0x4C))
        self.c.write_ram(0x7400, bytes(pk))

    def s(self, n):
        return self.sym[n.upper()]

    def _cnt(self):
        return struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]

    def _probe(self, us):
        """DELTA of the counter across the window.

        The counter is NOT zeroed between windows.  cpc.write_ram into a
        page the running Z80 is also writing turned out to be dropped
        about half the time -- an e_empty that has to be 23.000 us came
        back 16.884 -- so nothing here writes RAM while the CPU runs."""
        a = self._cnt()
        ticks = self.c.run_us(us)
        return ticks, (self._cnt() - a) & 0xFFFF

    def time(self, idx, nbytes=44, nlines=32, nrows=12):
        """-> CPC microseconds per call of the subject, loop included.

        cpc_exec always runs exactly us*4 ticks, so the only error is the
        ragged end of the window: at most one iteration in n.  The window
        is sized for n around 12000, i.e. 1 part in 12000, and the loop
        runs with interrupts off so there is no jitter at all."""
        # set_pc lands mid-instruction, and several subjects PATCH THEIR
        # OWN JP, so a stray write from the instruction that was in flight
        # can leave a block entry point wrong for the rest of the session.
        # Let it finish, then restore the code image from disc.
        self.c.run_us(2000)
        self.c.write_ram(0x8000, self.code)
        self.c.poke(self.s("NBYTES"), nbytes)
        self.c.poke(self.s("NLINES"), nlines)
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


E = dict(nop=0, empty=1, push=2, across=3, ldi=4, ldir=5, popst=6,
         rowcopy=7, dnaive=8, dunroll=9, dfull=10, tex=11, texpop=12,
         texbc=13, mortar=14, push2=15, pushimm=16, colpush=17, colimm=18,
         colpair=19, colrun=20)


NL = 32                         # scanlines per timed run


def main():
    rig = Rig()

    tnop = rig.time(E["nop"])
    tempty = rig.time(E["empty"])
    print(f"calibration: 100 NOPs = {tnop - tempty:8.3f} us "
          f"(must be 100.000)   loop+call+ret = {tempty:.3f} us")
    print()

    rows = []

    def row(name, seq, t1, n1, t2, n2, note=""):
        slope = (t2 - t1) / (n2 - n1)
        rows.append((name, seq, slope, t2, n2, note))
        return slope

    # ---- ACROSS a scanline: 96 lines, 22 vs 44 bytes each --------------
    for name, idx, seq in (
            ("PUSH DE (constant fill)", "push", "push de"),
            ("PUSH DE / PUSH BC (4-byte pattern)", "push2",
             "push de : push bc   [8-pixel repeat, no reload]"),
            ("LD DE,nn / PUSH DE (any pattern)", "pushimm",
             "ld de,nn : push de  [pattern baked into generated code]"),
            ("LD (HL),A / INC L", "across", "ld (hl),a : inc l"),
            ("LDI unrolled", "ldi", "ldi"),
            ("LDIR", "ldir", "ldir  (one per scanline)"),
            ("LD A,(BC)/INC C/LD (HL),A/INC L", "rowcopy",
             "ld a,(bc) : inc c : ld (hl),a : inc l"),
    ):
        t22 = rig.time(E[idx], nbytes=22, nlines=NL)
        t44 = rig.time(E[idx], nbytes=44, nlines=NL)
        row(name, seq, t22, 22 * NL, t44, 44 * NL)

    # POP HL / LD (nn),HL -- one scanline's worth, repeated
    t22 = rig.time(E["popst"], nbytes=22, nlines=NL)
    t44 = rig.time(E["popst"], nbytes=44, nlines=NL)
    row("POP HL / LD (nn),HL", "pop hl : ld (nn),hl   [addr baked in code]",
        t22, 22 * NL, t44, 44 * NL)

    # ---- DOWN a column -------------------------------------------------
    t48 = rig.time(E["dnaive"], nbytes=48)
    t96 = rig.time(E["dnaive"], nbytes=96)
    row("DOWN naive, wrap tested per line",
        "ld (hl),a : dec c : jr z,wrap : add hl,de : djnz", t48, 48, t96, 96)

    t6 = rig.time(E["dunroll"], nrows=6)
    t12 = rig.time(E["dunroll"], nrows=12)
    row("DOWN unrolled x8, wrap hoisted",
        "ld (hl),a : add hl,de   x7, then add hl,bc : dec ixl : jr nz",
        t6, 48, t12, 96)

    tfull = rig.time(E["dfull"]) - tempty
    rows.append(("DOWN fully unrolled 96 lines", "no loop control at all",
                 tfull / 96.0, tfull, 96, "fixed length"))

    # ---- textured strips ----------------------------------------------
    t6 = rig.time(E["tex"], nrows=6)
    t12 = rig.time(E["tex"], nrows=12)
    row("TEXTURED strip, 16-bit frac step",
        "ld e,h : ld a,(de) : add hl,bc : exx : ld (hl),a : add hl,de : exx",
        t6, 48, t12, 96)

    t6 = rig.time(E["texpop"], nrows=6)
    t12 = rig.time(E["texpop"], nrows=12)
    row("PRECOMPUTED column, POP fed",
        "pop bc : ld (hl),c : add hl,de : ld (hl),b : add hl,de",
        t6, 48, t12, 96)

    t6 = rig.time(E["colpush"], nrows=6)
    t12 = rig.time(E["colpush"], nrows=12)
    row("COLUMN PAIR by PUSH, constant colour",
        "ld sp,hl : push de : add hl,bc   [2 bytes wide]",
        t6, 96, t12, 192)

    t6 = rig.time(E["colimm"], nrows=6)
    t12 = rig.time(E["colimm"], nrows=12)
    row("COLUMN PAIR by PUSH, baked per line",
        "ld sp,hl : ld de,nn : push de : add hl,bc   [2 bytes wide]",
        t6, 96, t12, 192)

    # THE COLUMN RENDERER'S CANDIDATE.  A textured pair of byte columns,
    # one sample feeding both, PUSH-fed down the interleave.  This is the
    # number the whole column architecture is costed on, so it is measured
    # against the two things that bound it: the same strip in a CONSTANT
    # colour (colpush, the floor -- no texture work at all) and the same
    # strip with the sample hoisted over two scanlines (colrun, what a 2x
    # magnified wall would pay).
    t6 = rig.time(E["colpair"], nrows=6)
    t12 = rig.time(E["colpair"], nrows=12)
    row("COLUMN PAIR by PUSH, TEXTURED",
        "ld e,h:ld a,(de):add hl,bc:exx:ld d,a:ld e,a:ld sp,hl:push de:"
        "add hl,bc:exx", t6, 96, t12, 192)

    t6 = rig.time(E["colrun"], nrows=6)
    t12 = rig.time(E["colrun"], nrows=12)
    row("COLUMN PAIR, TEXTURED, 2x magnified",
        "...the same with one sample per TWO scanlines", t6, 96, t12, 192)

    t6 = rig.time(E["texbc"], nrows=6)
    t12 = rig.time(E["texbc"], nrows=12)
    row("PRECOMPUTED column, LD A,(BC) fed",
        "ld a,(bc) : inc c : ld (hl),a : add hl,de", t6, 48, t12, 96)

    # ---- scattered pokes ------------------------------------------------
    t11 = rig.time(E["mortar"], nbytes=11, nlines=NL)
    t22 = rig.time(E["mortar"], nbytes=22, nlines=NL)
    row("SCATTERED poke, addr+colour from table",
        "ld e,(hl):inc l:ld d,(hl):inc l:ld a,(hl):inc l:ld (de),a",
        t11, 11 * NL, t22, 22 * NL)

    print(f"{'what':38} {'us/byte':>9}  {'run us':>9} {'bytes':>6}")
    print("-" * 78)
    for name, seq, slope, t, n, note in rows:
        print(f"{name:38} {slope:9.4f}  {t:9.1f} {n:6d}")
    print()
    for name, seq, slope, t, n, note in rows:
        print(f"  {name:38} {seq}")

    # ---- per-scanline setup cost ---------------------------------------
    print()
    print("per-scanline overhead (same byte count, 48 vs 96 lines):")
    for name, idx in (("PUSH DE", "push"), ("LD (HL),A across", "across"),
                      ("LDI", "ldi"), ("LDIR", "ldir"),
                      ("POP/LD (nn),HL", "popst")):
        a = rig.time(E[idx], nbytes=44, nlines=16)
        b = rig.time(E[idx], nbytes=44, nlines=48)
        print(f"  {name:24} {(b - a) / 32.0:7.3f} us per scanline "
              f"({(b - a) / 32.0 / 44:6.4f} us/byte at 44 wide)")


if __name__ == "__main__":
    main()
