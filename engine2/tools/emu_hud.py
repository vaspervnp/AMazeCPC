"""Verify and MEASURE engine2/src/hud2.asm, the HUD.

    python3 engine2/tools/emu_hud.py

VERIFY, against engine2/tools/genhud.py's model of the same tables:

  furniture   the buffer is pre-poisoned, hud_static runs once, and all
              16384 bytes are compared.  Every rectangle must land exactly
              where the generator says, and every byte outside the HUD --
              above all, the whole VIEWPORT, which the renderer owns and
              never clears -- must still be poison.
  needle      all 72 headings are walked IN ORDER, as a turn does.  After
              each one the whole screen is compared again: the needle must
              be exactly right AND the previous one must have been erased
              back to the furniture, byte for byte.  That is the invariant
              the "erase by repainting the old heading in the dial's own
              background" trick lives or dies on.
  back buffer the same code writes #8000 by patching one immediate.  The
              harness lives at #8000, so the back buffer cannot be painted
              whole; instead a heading whose needle lands entirely above
              the harness is drawn there and checked, and then a second
              one, so both the draw and the erase are seen at #8000.

MEASURE with the usual protocol -- interrupts off, 16-bit counter, an
identical loop with the call removed for the overhead, and 100 NOPs to
prove the method reads 100.0 us.  Three numbers matter: hud_update when
the heading has not changed (every frame), hud_update when it has (every
frame the player is turning, which is most of them), and hud_static (once
per buffer at startup).
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

import gentab                                                  # noqa: E402
import genhud                                                  # noqa: E402
import cpchw as cpc                                            # noqa: E402
from cpc import CPC                                            # noqa: E402

BUILD = os.path.join(_E2, "build")
E_ONCE, E_UPD, E_SAME, E_TURN, E_TURNCTL, E_STATIC, E_EMPTY = (
    0x8000, 0x8004, 0x8008, 0x800C, 0x8010, 0x8014, 0x8018)
SCR = 0xC000
POISON = 0x5A
SCR_W, SCR_H = cpc.SCR_W_BYTES, cpc.SCR_H


def off(x, y):
    return (y & 7) * 0x800 + (y >> 3) * SCR_W + x


def build():
    genhud.main()
    blob, layout, _ = gentab.build()
    os.makedirs(BUILD, exist_ok=True)
    gentab.write_inc(os.path.join(BUILD, "tab_equ_test.inc"), blob, layout)
    r = subprocess.run(
        ["rasm", "tst_hud.asm", "-I", "../build", "-I", "../src",
         "-o", "../build/tst_hud", "-s", "-os", "../build/tst_hud"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_hud.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_hud")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    return blob, code, sym


# ---------------------------------------------------------------- model ----
RECTS, NDLTAB = genhud.build()
GRID = genhud.paint(RECTS)              # [200][80] of bytes, None = untouched


def want_image(heading=None):
    """-> {offset: byte} for everything the HUD should have painted."""
    img = {}
    for y in range(SCR_H):
        for x in range(SCR_W):
            b = GRID[y][x]
            if b is not None:
                img[off(x, y)] = b
    if heading is not None:
        for (x, y, h, pen) in genhud.dots(heading):
            for yy in range(y, y + h):
                for xx in range(x, x + genhud.NDL_W):
                    img[off(xx, yy)] = cpc.MODE0_SOLID[pen]
    return img


def needle_bytes(heading):
    """-> {offset: byte} for just the needle of `heading`."""
    out = {}
    for (x, y, h, pen) in genhud.dots(heading):
        for yy in range(y, y + h):
            for xx in range(x, x + genhud.NDL_W):
                out[off(xx, yy)] = cpc.MODE0_SOLID[pen]
    return out


class Rig:
    def __init__(self):
        self.tables, self.code, self.sym = build()
        self.c = CPC()
        self.c.run_frames(60)
        self.c.write_ram(gentab.BANK_BASE, self.tables)
        self.reload()

    def reload(self):
        self.c.write_ram(0x8000, self.code)

    def s(self, n):
        return self.sym[n.upper()]

    def run(self, entry, timeout=200):
        self.c.poke(self.s("DONE"), 0)
        self.c.set_pc(entry)
        for _ in range(timeout):
            self.c.run_frames(1)
            if self.c.peek(self.s("DONE")) == 0xFF:
                return
        raise RuntimeError(f"entry #{entry:04X} never finished")

    def once(self, heading, bufh=0xC0, poison=True):
        self.c.poke(self.s("BUFH"), bufh)
        self.c.poke(self.s("PLR_A"), heading)
        if poison:
            self.c.write_ram(SCR, bytes([POISON]) * 0x4000)
        self.run(E_ONCE)
        return self.c.read_ram(SCR, 0x4000)

    def upd(self, heading, bufh=0xC0):
        self.c.poke(self.s("BUFH"), bufh)
        self.c.poke(self.s("PLR_A"), heading)
        self.run(E_UPD)
        return self.c.read_ram(0x8000 if bufh == 0x80 else SCR, 0x4000)

    NTARGET = 4000

    def _run(self, entry, us):
        self.c.set_pc(entry)
        self.c.run_us(60000)                    # settle into the loop
        self.c.write_ram(self.s("COUNTER"), b"\x00\x00")
        ticks = self.c.run_us(us)
        n = struct.unpack("<H", self.c.read_ram(self.s("COUNTER"), 2))[0]
        return (ticks / 4.0) / n if n else None, n

    def bench(self, entry, target=None):
        """-> CPC microseconds per iteration, loop overhead NOT removed.

        Same reasoning as engine2/tools/emu_bg.py: probe with a short window,
        then size the real window for `target` iterations -- far from the
        16-bit counter's wrap, close enough to resolve a microsecond.
        """
        target = target or self.NTARGET
        t0, _n0 = self._run(entry, 200000)
        if t0 is None:
            raise RuntimeError("counter never advanced")
        t, n = self._run(entry, int(t0 * target))
        if not 0 < n <= 60000:
            raise RuntimeError(f"counter unusable: {n}")
        return t


# --------------------------------------------------------------- verify ----
def cmp_image(ram, img, what):
    bad = []
    for o in range(0x4000):
        exp = img.get(o, POISON)
        if ram[o] != exp:
            bad.append((o, ram[o], exp))
            if len(bad) > 8:
                break
    if bad:
        print(f"  {what}: WRONG, first {len(bad)}:")
        for o, got, exp in bad:
            print(f"    +&{o:04X} got &{got:02X} want &{exp:02X}")
    return len(bad)


def verify_static(rig):
    ram = rig.once(0)
    img = want_image(0)
    bad = cmp_image(ram, img, "furniture + needle")
    if not bad:
        vp = 0
        for y in range(gentab.VP_Y, gentab.VP_Y + gentab.VP_H):
            for x in range(gentab.VP_BX, gentab.VP_BX + gentab.VP_BW):
                if ram[off(x, y)] != POISON:
                    vp += 1
        print(f"  furniture: {len(img)} bytes exactly right, "
              f"{0x4000-len(img)} untouched, "
              f"viewport bytes damaged: {vp}")
        bad += vp
    return bad


def verify_turn(rig):
    """All 72 headings in sequence -- the erase path is what is on trial."""
    bad = 0
    for a in range(1, genhud.N_ANGLES + 1):
        h = a % genhud.N_ANGLES
        ram = rig.upd(h)
        n = cmp_image(ram, want_image(h), f"heading {h}")
        bad += n
        if n:
            break
    if not bad:
        print(f"  needle: 72 headings drawn in sequence, every one exact "
              f"and every erase clean")
    return bad


def verify_back(rig):
    """The #8000 path.  The harness is at #8000, so only headings whose
    needle lands clear of it can be drawn there -- but that is enough to
    see the patched buffer base actually work, draw and erase."""
    end = 0x8000 + len(rig.code) + 16
    safe = [a for a in range(genhud.N_ANGLES)
            if min(needle_bytes(a)) + 0x8000 > end]
    if len(safe) < 2:
        print("  back buffer: SKIPPED, no heading clears the harness")
        return 0
    a, b = safe[0], safe[1]
    rig.upd(a, bufh=0x80)
    ram = rig.upd(b, bufh=0x80)
    bad = []
    for o, want in needle_bytes(b).items():
        if ram[o] != want:
            bad.append((o, ram[o], want))
    bg = cpc.MODE0_SOLID[genhud.DIAL_BG]
    for o in needle_bytes(a):
        if o not in needle_bytes(b) and ram[o] != bg:
            bad.append((o, ram[o], bg))
    if bad:
        print(f"  back buffer: WRONG at {len(bad)} bytes, first "
              f"+&{bad[0][0]:04X} got &{bad[0][1]:02X} want &{bad[0][2]:02X}")
    else:
        print(f"  back buffer: headings {a} then {b} drawn and erased at "
              f"#8000 through the patched base, {len(needle_bytes(b))} "
              f"bytes exact")
    rig.reload()                        # the harness may have been scribbled
    return len(bad)


# -------------------------------------------------------------- measure ----
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
    rig.reload()
    return f - e


def measure(rig):
    ovh = rig.bench(E_EMPTY)
    print(f"  loop overhead {ovh:.2f} us (subtracted below)")
    same = rig.bench(E_SAME) - ovh
    turn = rig.bench(E_TURN, target=2000) - ovh
    ctl = rig.bench(E_TURNCTL) - ovh
    stat = rig.bench(E_STATIC, target=200) - ovh
    nb = sum(w * h for (_x, _y, w, h, _b) in RECTS.r)
    print()
    print(f"  hud_update, heading UNCHANGED   {same:8.2f} us   "
          f"{100.0*same/80000:5.3f}% of the 80 ms frame")
    print(f"  hud_update, heading CHANGED     {turn-ctl:8.2f} us   "
          f"{100.0*(turn-ctl)/80000:5.3f}% of the frame   "
          f"(erase + redraw, {4*2} blocks)")
    print(f"    the turn loop itself           {ctl:8.2f} us   "
          f"(subtracted: (plr_a) advance, not HUD)")
    nr = sum(h for (_x, _y, _w, h, _b) in RECTS.r)
    print(f"  hud_static, once per buffer     {stat:8.1f} us   "
          f"{stat/nb:5.3f} us/byte over {nb} bytes")
    print(f"    {len(RECTS.r)} rectangles, {nr} scanlines, "
          f"{nb/float(nr):.1f} bytes a scanline: {2.0*nb:.0f} us of PUSH DE "
          f"and {stat-2.0*nb:.0f} us of per-row setup ({(stat-2.0*nb)/nr:.0f} "
          f"us a row).  Narrow rows cannot amortise a LINETAB lookup, and "
          f"this runs twice, at startup, so it is left alone.")
    return same, turn - ctl, stat


def main():
    rig = Rig()
    print(f"\nHUD for a {gentab.VP_BW}x{gentab.VP_H} byte viewport at "
          f"({gentab.VP_BX},{gentab.VP_Y}); code+tables "
          f"{len(rig.code)} bytes")

    print("\n=== verify against the model ===")
    bad = verify_static(rig) + verify_turn(rig) + verify_back(rig)

    print("\n=== timing method calibration ===")
    calibrate(rig)

    print("\n=== measured ===")
    measure(rig)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
