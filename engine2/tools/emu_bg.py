"""Verify and MEASURE engine2/src/bg.asm, the ceiling/floor background.

    python3 engine2/tools/emu_bg.py

Two things happen here, in this order, because a wrong fill that is fast
is worth nothing:

  VERIFY  the buffer is pre-poisoned, bg_fill runs once, and every byte of
          the 200x80 screen is compared against the model: the viewport
          rectangle must hold exactly the band pens, and NOTHING outside
          it may have been touched.  Both band lists are checked.

  MEASURE the same 16-bit-counter protocol the kernel harness uses --
          interrupts off, a tight loop, an identical loop with the call
          removed for the overhead, and a 100-NOP loop to prove the method
          reads 100.0 us.  cpc.run_us() returns 4 MHz ticks and the gate
          array stretches every instruction to a whole microsecond, so
          ticks/4 is exactly the CPC microsecond count.
"""

import os
import struct
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import gentab                                                # noqa: E402
import cpchw as cpc                                          # noqa: E402
import pal                                                   # noqa: E402
from cpc import CPC                                          # noqa: E402

BUILD = os.path.join(_E2, "build")
E_ONCE, E_BG, E_EMPTY = 0x8000, 0x8004, 0x8008
SCR = 0xC000
POISON = 0x5A

VP_BX, VP_BW = gentab.VP_BX, gentab.VP_BW
VP_Y, VP_H = gentab.VP_Y, gentab.VP_H
CYH = int(gentab.CY)


def line_addr(y):
    return SCR + (y & 7) * 0x800 + (y >> 3) * 80


def bands(n):
    """-> [(first_y, n_lines, pen_byte)], the model of bg.asm's lists."""
    # The pens come from engine2/tools/pal.py, the same module gentab
    # builds BANDPEN from -- not from a second list kept in step by hand.
    solid = cpc.MODE0_SOLID
    cn, cf = solid[pal.CEIL_NEAR], solid[pal.CEIL_FAR]
    fn, ff = solid[pal.FLOOR_NEAR], solid[pal.FLOOR_FAR]
    q = (CYH // 16) * 8                 # bg.asm counts CHARACTER ROWS
    segs = ([(q, cn), (CYH - q, cf), (CYH - q, ff), (q, fn)] if n == 4
            else [(CYH, cn), (CYH, fn)])
    out, y = [], VP_Y
    for nl, pen in segs:
        out.append((y, nl, pen))
        y += nl
    assert y == VP_Y + VP_H
    return out


def build():
    blob, layout, _ = gentab.build()
    os.makedirs(BUILD, exist_ok=True)
    gentab.write_inc(os.path.join(BUILD, "tab_equ_test.inc"), blob, layout)
    r = subprocess.run(
        ["rasm", "tst_bg.asm", "-I", "../build", "-I", "../src",
         "-o", "../build/tst_bg", "-s", "-os", "../build/tst_bg"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_bg.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_bg")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    return blob, code, sym


class Rig:
    def __init__(self):
        self.tables, self.code, self.sym = build()
        self.c = CPC()
        self.c.run_frames(60)
        self.c.write_ram(gentab.BANK_BASE, self.tables)
        self.c.write_ram(0x8000, self.code)

    def s(self, n):
        return self.sym[n.upper()]

    def pick(self, nband):
        self.c.write_ram(self.s("BG_LIST"), struct.pack(
            "<H", self.s("BG_S4" if nband == 4 else "BG_S2")))

    def once(self, nband):
        self.pick(nband)
        self.c.write_ram(SCR, bytes([POISON]) * 0x4000)
        self.c.poke(self.s("DONE"), 0)
        self.c.set_pc(E_ONCE)
        for _ in range(60):
            self.c.run_frames(1)
            if self.c.peek(self.s("DONE")) == 0xFF:
                break
        else:
            raise RuntimeError("bg_fill never finished")
        return self.c.read_ram(SCR, 0x4000)

    NTARGET = 5000

    def _run(self, entry, us):
        self.c.set_pc(entry)
        self.c.run_us(60000)                    # settle into the loop
        self.c.write_ram(self.s("COUNTER"), b"\x00\x00")
        ticks = self.c.run_us(us)
        n = struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]
        return (ticks / 4.0) / n if n else None, n

    def bench(self, entry):
        """-> CPC microseconds per iteration (loop overhead NOT removed).

        The window is CHOSEN, not fixed, because a fixed one is wrong at
        both ends and silently so:

          too short  the counter only advances on COMPLETED iterations
                     and the run stops inside one, so the quantum of the
                     measurement is (one iteration / n).  bg_fill is ~9 ms;
                     at a 1.5 s window n = 162 and the quantum is 57 us --
                     wide enough to hide the whole 2-band vs 4-band
                     difference this tool exists to measure.
          too long   the counter is SIXTEEN BITS.  The empty control loop
                     is 15 us, so it wraps after 0.98 s and a 1.5 s window
                     reports 43.5 us instead of 14.9 us -- an overhead
                     nearly 3x too big, subtracted from everything.

        So: probe with a short window, then re-run with a window sized for
        NTARGET iterations, which is both far from the 65536 wrap and fine
        enough to resolve a few microseconds.
        """
        t0, n0 = self._run(entry, 200000)
        if t0 is None:
            raise RuntimeError("counter never advanced")
        t, n = self._run(entry, int(t0 * self.NTARGET))
        if not 0 < n <= 60000:
            raise RuntimeError(f"counter unusable: {n}")
        return t


def verify(rig, nband):
    ram = rig.once(nband)
    want = {}
    for y0, nl, pen in bands(nband):
        for y in range(y0, y0 + nl):
            for b in range(VP_BX, VP_BX + VP_BW):
                want[line_addr(y) + b - SCR] = pen
    bad = []
    for off in range(0x4000):
        exp = want.get(off, POISON)
        if ram[off] != exp:
            bad.append((off, ram[off], exp))
    if bad:
        print(f"  {nband} bands: {len(bad)} WRONG bytes, first 4:")
        for off, got, exp in bad[:4]:
            print(f"    &{SCR+off:04X} got &{got:02X} want &{exp:02X}")
    else:
        print(f"  {nband} bands: {len(want)} bytes painted exactly right, "
              f"{0x4000-len(want)} bytes outside the viewport untouched")
    return len(bad)


def calibrate(rig):
    src = os.path.join(BUILD, "cal.asm")
    open(src, "w").write(
        "    org #9000\n    jp cal_e\n    jp cal_n\n"
        "cal_e\n    di\n    ld sp,#7FF0\n    ld hl,0\n    ld (cnt),hl\n"
        "ce\n    ld hl,(cnt)\n    inc hl\n    ld (cnt),hl\n    jr ce\n"
        "cal_n\n    di\n    ld sp,#7FF0\n    ld hl,0\n    ld (cnt),hl\n"
        "cn\n    ld hl,(cnt)\n    inc hl\n    ld (cnt),hl\n"
        + "    nop\n" * 100 + "    jr cn\ncnt dw 0\n")
    subprocess.run(["rasm", "cal.asm", "-o", "cal", "-s", "-os", "cal"],
                   cwd=BUILD, capture_output=True, text=True, check=True)
    blob = open(os.path.join(BUILD, "cal.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "cal")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    rig.c.write_ram(0x9000, blob)

    def one(pc, us=400000):
        rig.c.set_pc(pc)
        rig.c.run_us(2000)
        rig.c.write_ram(sym["CNT"], b"\x00\x00")
        t = rig.c.run_us(us)
        n = struct.unpack("<H", rig.c.read_ram(sym["CNT"], 2))[0]
        return (t / 4.0) / n
    e, f = one(0x9000), one(0x9003)
    print(f"  empty loop {e:7.2f} us, +100 NOPs {f:7.2f} us, "
          f"difference {f-e:6.2f} us  (must be 100.00)")
    rig.c.write_ram(0x8000, rig.code)
    return f - e


def main():
    rig = Rig()
    print(f"background fill, viewport {VP_BW}x{VP_H} bytes at "
          f"({VP_BX},{VP_Y}), horizon at scanline {CYH}")

    print("\n=== verify against the model ===")
    bad = verify(rig, 2) + verify(rig, 4)

    print("\n=== timing method calibration ===")
    calibrate(rig)
    ovh = rig.bench(E_EMPTY)
    print(f"  loop overhead {ovh:.2f} us (subtracted below)")

    print("\n=== measured ===")
    floor = VP_H * VP_BW * 2.0
    for n in (2, 4):
        rig.pick(n)
        t = rig.bench(E_BG) - ovh
        print(f"  {n} bands  {t:8.1f} us   {t/(VP_H*VP_BW):5.3f} us/byte"
              f"   {100.0*t/floor-100:5.1f}% over the 2 us/byte floor"
              f"   {100.0*t/80000:5.1f}% of the 80 ms frame")
    print(f"  floor     {floor:8.1f} us   2.000 us/byte  "
          f"({VP_H*VP_BW} bytes at 2 us)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
