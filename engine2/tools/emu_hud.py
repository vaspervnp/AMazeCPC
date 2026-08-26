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
E_AMMO, E_AMMOB = 0x801C, 0x8020
E_SCAN, E_SCANB = 0x8024, 0x8028
E_RADAR = 0x802C
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

    def ammo(self, n, bufh=0xC0):
        self.c.poke(self.s("BUFH"), bufh)
        self.c.poke(self.s("AMMON"), n)
        self.run(E_AMMO)
        return self.c.read_ram(0x8000 if bufh == 0x80 else SCR, 0x4000)

    def scan(self, state, bufh=0xC0):
        self.c.poke(self.s("BUFH"), bufh)
        self.c.poke(self.s("SCANN"), state)
        self.run(E_SCAN)
        return self.c.read_ram(0x8000 if bufh == 0x80 else SCR, 0x4000)

    def radar(self, blips, mon=0xFF, bufh=0xC0):
        self.c.poke(self.s("BUFH"), bufh)
        self.c.write_ram(self.s("AMMO_BLIP"), bytes(blips))
        self.c.poke(self.s("MON_BLIP"), mon)
        self.run(E_RADAR)
        return self.c.read_ram(0x8000 if bufh == 0x80 else SCR, 0x4000)

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


def verify_ammo(rig):
    """Every count from a full magazine down to empty and back up.

    IN SEQUENCE, and that is the point: hud_ammo remembers what it last
    drew per buffer and returns without touching the screen when the
    count has not moved, so a test that set each count from a clean
    screen would never exercise the memo or the repaint of a pip that
    has to go OUT again.  Here 6->5 has to blank one and 0->6 has to
    bring all six back.
    """
    rig.once(0)                             # furniture, and hud_force with it
    bad = 0
    counts = list(range(genhud.ammo_slot()[5], -1, -1)) + [genhud.ammo_slot()[5]]
    for n in counts:
        ram = rig.ammo(n)
        want = {}
        for (x, y, w, h, b) in genhud.ammo_rects(n):
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    want[off(xx, yy)] = b
        wrong = [(o, ram[o], b) for o, b in want.items() if ram[o] != b]
        if wrong:
            o, got, exp = wrong[0]
            print(f"  ammo {n}: WRONG at {len(wrong)} bytes, first "
                  f"+&{o:04X} got &{got:02X} want &{exp:02X}")
            bad += len(wrong)
            break
        # ...and nothing OUTSIDE the pips moved: the furniture is still
        # exactly what hud_static left, everywhere.
        img = want_image(0)
        spill = [o for o, b in img.items() if o not in want and ram[o] != b]
        if spill:
            print(f"  ammo {n}: SPILLED onto {len(spill)} furniture bytes, "
                  f"first +&{spill[0]:04X}")
            bad += len(spill)
            break
    if not bad:
        print(f"  ammo: {len(counts)} counts drawn in sequence "
              f"({genhud.ammo_slot()[5]} down to 0 and back), every pip exact, "
              f"no byte outside the readout touched")
    # A REPEAT MUST BE A NO-OP.  Poison the readout behind hud_ammo's back
    # and ask for the count it already thinks is on screen: if it repaints,
    # the memo is not doing its job and C_AMMO -- 3.8 ms, charged by
    # hud_ammo itself -- is being spent on every frame instead of the few
    # a round moves on.
    x, y, w, h, dx, n = genhud.ammo_slot()
    for yy in range(y, y + h):
        for xx in range(x, x + (n - 1) * dx + w):
            rig.c.poke(SCR + off(xx, yy), POISON)
    ram = rig.ammo(n)
    kept = sum(1 for yy in range(y, y + h)
               for xx in range(x, x + (n - 1) * dx + w)
               if ram[off(xx, yy)] == POISON)
    if kept != h * ((n - 1) * dx + w):
        print(f"  ammo: the unchanged-count early-out REPAINTED "
              f"({kept} of {h*((n-1)*dx+w)} poisoned bytes survived)")
        bad += 1
    else:
        print(f"  ammo: an unchanged count writes nothing at all "
              f"({kept} poisoned bytes survive)")
    return bad


def verify_scan(rig):
    """Every bearing and every distance band, in sequence.

    THE WHOLE PAD IS CHECKED, not just the two rectangles hud_scan is
    allowed to write.  genhud.scan_pad() says what all nine cells must
    read back as, so an erase that puts the wrong colour back, or one
    that lands on the hub, or a bearing that indexes SCANPOS off by one,
    all show up as a wrong cell rather than as nothing.

    IN SEQUENCE, because the erase is the half that has state: hud_scan
    only knows which cell to put back from the byte it remembered, so a
    test that reset the pad between states would never exercise it.
    """
    rig.once(0)                             # furniture, hud_force with it
    bad = 0
    # every bearing at every band, then a lap of bands on one bearing,
    # then out to nothing and back -- 0xFF is "no pickup left".
    states = ([b * 16 + o for o in range(8) for b in range(3)]
              + [0x00, 0x10, 0x20, 0x10, 0x00]
              + [0xFF, 0x03, 0xFF, 0x25])
    for st in states:
        ram = rig.scan(st)
        want = {}
        for (x, y, w, h, b) in genhud.scan_pad(st):
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    want[off(xx, yy)] = b
        wrong = [(o, ram[o], b) for o, b in want.items() if ram[o] != b]
        if wrong:
            o, got, exp = wrong[0]
            print(f"  scan #{st:02X}: WRONG at {len(wrong)} of {len(want)} "
                  f"pad bytes, first +&{o:04X} got &{got:02X} want &{exp:02X}")
            bad += len(wrong)
            break
        img = want_image(0)                 # ...and nothing outside the pad
        spill = [o for o, b in img.items() if o not in want and ram[o] != b]
        if spill:
            print(f"  scan #{st:02X}: SPILLED onto {len(spill)} bytes, "
                  f"first +&{spill[0]:04X}")
            bad += len(spill)
            break
    if not bad:
        print(f"  scanner: {len(states)} bearings and bands drawn in "
              f"sequence, all nine pad cells exact every time, no byte "
              f"outside the pad touched")

    # AND THE EARLY-OUT.  Poison the pad behind hud_scan's back and ask
    # for the state it already believes is on screen.
    x0, y0, bw, bh, sx, sy = genhud.scan_slot()
    cells = [genhud.scan_xy(c, r) for (c, r) in
             genhud.SCAN_CELL + [genhud.SCAN_HUBCELL]]
    n = 0
    for (x, y) in cells:
        for yy in range(y, y + bh):
            for xx in range(x, x + bw):
                rig.c.poke(SCR + off(xx, yy), POISON)
                n += 1
    ram = rig.scan(states[-1])
    kept = sum(1 for (x, y) in cells for yy in range(y, y + bh)
               for xx in range(x, x + bw) if ram[off(xx, yy)] == POISON)
    if kept != n:
        print(f"  scanner: the unchanged-bearing early-out REPAINTED "
              f"({kept} of {n} poisoned bytes survived)")
        bad += 1
    else:
        print(f"  scanner: an unchanged bearing writes nothing at all "
              f"({kept} poisoned bytes survive)")
    return bad


def verify_radar(rig):
    """The dial's blips and its sweep, over a sequence of blip sets.

    IN SEQUENCE, like everything else here, because the erase is the half
    with state: hud_radar only knows which square to put back from the
    byte it remembered, and it draws nothing at all when the set has not
    moved.  The sweep advances one tick a call whatever happens, so this
    also walks it right round the dial twice.

    ALL 24 BLIP SQUARES ARE CHECKED EVERY TIME, not just the lit ones --
    see genhud.radar_cells.  So is every one of the eight ticks, which is
    what catches a sweep that lights the right one and forgets to put the
    last one back in ITS OWN colour: north's tick is a different size and
    a different pen from the other seven.
    """
    rig.once(0)                             # furniture, and hud_force
    bad = 0
    N = 6
    #  (ammo blips, monster blip).  The last two pairs are the ones that
    #  matter: a monster ON a pickup's square must show as the MONSTER,
    #  and a monster that leaves must put the dial back -- including when
    #  a pickup is underneath it, which is the case a naive erase to
    #  DIAL_BG gets wrong.
    sets = [
        ([0xFF] * N, 0xFF),                 # nothing on the map
        ([0x16] + [0xFF] * (N - 1), 0xFF),  # one pickup, mid ring
        ([0x16, 0x27] + [0xFF] * (N - 2), 0x04),
        ([0x00, 0x11, 0x22, 0x03, 0x14, 0x25], 0x12),
        ([0x20, 0x21, 0x22, 0x23, 0x24, 0x25], 0x26),   # all six + monster
        ([0x00] * N, 0x00),                 # monster ON a pickup
        ([0x00] * N, 0xFF),                 # ...and off it again
        ([0xFF] * N, 0x05),                 # monster alone
        ([0x27, 0xFF, 0x16, 0xFF, 0x05, 0xFF], 0xFF),
    ]
    # the sweep starts wherever hud_static left it; track it the way the
    # asm does -- one on, modulo eight, per call.
    lit = rig.c.peek(rig.s("HUD_SWA"))
    # THE DIAL IS THREE LAYERS AND THE ORDER IS THE POINT: furniture,
    # then the blips, then the NEEDLE ON TOP.  hud_radar redraws the
    # needle after any blip moves -- see the note there -- so a blip and
    # the needle can want the same square and the needle wins.  Modelling
    # it as "blip square = blip colour" fails on the outer ring straight
    # ahead, where the needle's tip is; modelling an unlit square as
    # black fails one row lower.  Both happened.
    for st, mon in sets:
        lit = (lit + 1) % 8
        ram = rig.radar(st, mon)
        grid = genhud.paint(genhud.furniture())        # layer 1
        for (x, y, w, h, b) in genhud.radar_cells(st, mon):  # layer 2
            if b is None:
                continue
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    grid[yy][xx] = b
        for (x, y, h, pen) in genhud.dots(0):           # layer 3, on top
            for yy in range(y, y + h):
                for xx in range(x, x + genhud.NDL_W):
                    grid[yy][xx] = genhud.SOLID[pen]
        want = {}
        for (x, y, w, h, _b) in (genhud.radar_cells(st, mon)
                                 + genhud.sweep_cells(lit)):
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    want[off(xx, yy)] = grid[yy][xx]
        for (x, y, w, h, b) in genhud.sweep_cells(lit):  # the lit tick is
            for yy in range(y, y + h):                   # not furniture
                for xx in range(x, x + w):
                    want[off(xx, yy)] = b
        wrong = [(o, ram[o], b) for o, b in want.items() if ram[o] != b]
        if wrong:
            o, got, exp = wrong[0]
            print(f"  radar {[hex(v) for v in st]} mon {hex(mon)}: "
                  f"WRONG at {len(wrong)} of "
                  f"{len(want)}, first +&{o:04X} got &{got:02X} want &{exp:02X}")
            bad += len(wrong)
            break
    if not bad:
        print(f"  radar: {len(sets)} blip sets drawn in sequence -- pickups "
              f"and the monster, including a monster standing on a pickup "
              f"-- all 24 ring squares and all 8 ticks exact every time")
    return bad


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
    ammo = rig.bench(E_AMMOB) - ovh
    scan = rig.bench(E_SCANB) - ovh
    nb = sum(w * h for (_x, _y, w, h, _b) in RECTS.r)
    print()
    print(f"  hud_update, heading UNCHANGED   {same:8.2f} us   "
          f"{100.0*same/80000:5.3f}% of the 80 ms frame")
    print(f"  hud_update, heading CHANGED     {turn-ctl:8.2f} us   "
          f"{100.0*(turn-ctl)/80000:5.3f}% of the frame   "
          f"(erase + redraw, {4*2} blocks)")
    print(f"    the turn loop itself           {ctl:8.2f} us   "
          f"(subtracted: (plr_a) advance, not HUD)")
    print(f"  hud_ammo, count CHANGED         {ammo:8.2f} us   "
          f"{100.0*ammo/80000:5.3f}% of the frame   "
          f"(all {genhud.ammo_slot()[5]} pips repainted; unchanged is the "
          f"early-out, a few us)")
    print(f"  hud_scan, bearing MOVED         {scan:8.2f} us   "
          f"{100.0*scan/80000:5.3f}% of the frame   "
          f"(erase one cell of the pad, light another -- the two-rect "
          f"case; a band change alone is one rect)")
    print(f"    -> C_HUD covers hud_update alone; hud_ammo charges "
          f"C_AMMO itself,\n       and only on the frames it paints "
          f"(worst frame, both: {turn-ctl+ammo:.0f} us)")
    nr = sum(h for (_x, _y, _w, h, _b) in RECTS.r)
    print(f"  hud_static, once per buffer     {stat:8.1f} us   "
          f"{stat/nb:5.3f} us/byte over {nb} bytes")
    print(f"    {len(RECTS.r)} rectangles, {nr} scanlines, "
          f"{nb/float(nr):.1f} bytes a scanline: {2.0*nb:.0f} us of PUSH DE "
          f"and {stat-2.0*nb:.0f} us of per-row setup ({(stat-2.0*nb)/nr:.0f} "
          f"us a row).  Narrow rows cannot amortise a LINETAB lookup, and "
          f"this runs twice, at startup, so it is left alone.")
    return same, turn - ctl, stat, ammo, scan


def main():
    rig = Rig()
    print(f"\nHUD for a {gentab.VP_BW}x{gentab.VP_H} byte viewport at "
          f"({gentab.VP_BX},{gentab.VP_Y}); code+tables "
          f"{len(rig.code)} bytes")

    print("\n=== verify against the model ===")
    bad = (verify_static(rig) + verify_turn(rig) + verify_back(rig)
           + verify_ammo(rig) + verify_scan(rig) + verify_radar(rig))

    print("\n=== timing method calibration ===")
    calibrate(rig)

    print("\n=== measured ===")
    measure(rig)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
