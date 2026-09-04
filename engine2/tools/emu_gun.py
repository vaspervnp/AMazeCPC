"""The weapon: VERIFIED byte for byte on the booted disc, then MEASURED.

    python3 engine2/tools/emu_gun.py            # bob, verify, then measure
    python3 engine2/tools/emu_gun.py bob
    python3 engine2/tools/emu_gun.py verify
    python3 engine2/tools/emu_gun.py measure

BOB.  gun.asm's bob is a rule, not a table lookup -- two phases at
mutually prime periods, an LFSR that nudges one of them, and an ease that
never lets either offset move more than one step in a frame.  So the rule
is written out again in Python below and gun_step is run BOB_FRAMES times
on the real machine with the trail recorded; the two must agree on every
frame.  The model is also what proves the properties the placement
depends on: both offsets stay in range, neither ever steps by more than
one, and the path does not repeat.

VERIFY.  build/amaze.dsk is booted through RUN"AMAZE and left in
main3.asm's loop.  gun_step is stubbed to RET so the bob stays where it
is poked, and for every reachable (dx, dy) -- 5 x 9 = 45 of them -- the
displayed buffer is read back and compared with engine2/tools/gunart.py's
own run list at the address gun.asm should have written it to:

    base + (y & 7)*&800 + (y >> 3)*80 + x

Every byte of every run, at every offset, or it fails.  The check is not
only that the RUNS are right: THE WHOLE 16K SCREEN is compared against
the same frame drawn with gun_draw stubbed out, so a byte written OUTSIDE
the sprite -- a row that stepped wrong, a run that left the viewport
sideways, or a clipped row drawn anyway and landing in the HUD -- is
caught too, and so is a byte the sprite should have written and did not.

THE MODEL CLIPS TOO, AND THAT IS THE POINT OF THIS PHASE.  The sprite is
anchored so that gunart.BOB_CUT scanlines hang below the viewport at the
centre of the bob, and the vertical bob swings both ways about that
anchor, so between GUN_ROWS0 and GUN_H rows are drawn depending on where
the bob is.  want_rows() drops exactly the rows at or below VP_Y+VP_H,
and edges() re-derives, from the model alone, that nothing ever reaches
the left, right or top edge.

MEASURE.  emu_pacefit.py's Rig, which is the protocol the rest of this
project's numbers come from: a 16-bit counter bumped once per iteration
with interrupts off, the same loop with the CALL removed for the
overhead, calibrated against 100 NOPs.  gun_draw is measured at every
(dx, dy), because the vertical offset now decides HOW MANY ROWS ARE
DRAWN as well as how many of them cross a character-row boundary -- the
blit is no longer the same cost at every offset, and what main3.asm's
C_GUN has to clear is the WORST of them, which is the top of the bob.
"""

import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import genhud                                                # noqa: E402
import gunart                                                # noqa: E402
import gentab as G                                           # noqa: E402
from emu_pacefit import Rig, BASE                            # noqa: E402

CORRIDOR = (10 * 256 + 128, 13 * 256 + 128, 0)      # (10,13) facing east

GUN_XB = G.VP_BX + (G.VP_BW - gunart.W // 2) // 2
# the top scanline at the BOTTOM of the swing, gun.asm's GUN_Y0.  The
# anchor is BOB_VA above it and hangs BOB_CUT scanlines below the view.
GUN_Y0 = G.VP_Y + G.VP_H - gunart.H + gunart.BOB_CUT + gunart.BOB_VA
VP_BOT = G.VP_Y + G.VP_H
FRONT = 0xC000

# every reachable offset: dy is the BIASED vertical, 0..2*BOB_VA, exactly
# as (gun_dy) holds it, so 0 is the bottom of the swing and 2*BOB_VA the
# top.  dx is signed and the poke adds the bias.
OFFSETS = [(dx, dy)
           for dy in range(0, 2 * gunart.BOB_VA + 1)
           for dx in range(-gunart.BOB_HA, gunart.BOB_HA + 1)]


def addr(y, x, base=FRONT):
    return base + (y & 7) * 0x800 + (y >> 3) * 80 + x


def want_rows(dx, dy):
    """-> {(y, x): byte} the sprite must leave on screen at this offset.

    dy is the BIASED offset.  Rows at or below VP_Y+VP_H are DROPPED --
    that is the bottom clamp, and the model has to do it too or the
    comparison would not be testing it."""
    out = {}
    for i, r in enumerate(gunart.rows()):
        x0, data = r
        y = GUN_Y0 - dy + i
        if y >= VP_BOT:
            break                       # ...and every row after it
        for j, b in enumerate(data):
            out[(y, GUN_XB + dx + x0 + j)] = b
    return out


def rows_drawn(dy):
    return min(gunart.H, VP_BOT - (GUN_Y0 - dy))


def edges():
    """The placement claims, re-derived from the model at EVERY offset.

    -> (report string, n_bad).  Left, right and top must be strictly
    clear; the bottom must always be reached, because a sprite that
    stops short of the bottom edge is the floating look this replaced."""
    lo_x, hi_x, lo_y = 10**6, -10**6, 10**6
    bad, cut = 0, []
    for dx, dy in OFFSETS:
        top = GUN_Y0 - dy
        lo_y = min(lo_y, top)
        if top < G.VP_Y:
            bad += 1
        if top + gunart.H < VP_BOT:
            bad += 1                    # floats above the bottom edge
        cut.append(gunart.H - rows_drawn(dy))
        for i, (x0, data) in enumerate(gunart.rows()):
            lo_x = min(lo_x, GUN_XB + dx + x0)
            hi_x = max(hi_x, GUN_XB + dx + x0 + len(data) - 1)
    if lo_x < G.VP_BX or hi_x >= G.VP_BX + G.VP_BW:
        bad += 1
    txt = (f"  columns {lo_x}..{hi_x} inside [{G.VP_BX},"
           f"{G.VP_BX + G.VP_BW - 1}] -- clear by {lo_x - G.VP_BX} left, "
           f"{G.VP_BX + G.VP_BW - 1 - hi_x} right\n"
           f"  top row {lo_y} of [{G.VP_Y},{VP_BOT - 1}] -- clear by "
           f"{lo_y - G.VP_Y}\n"
           f"  rows below the bottom edge, and so not drawn: "
           f"{min(cut)}..{max(cut)}   rows DRAWN "
           f"{rows_drawn(2 * gunart.BOB_VA)}.."
           f"{rows_drawn(0)} of {gunart.H}")
    return txt, bad


def read_screen(rig):
    """-> bytes, the whole 16K of the DISPLAYED buffer."""
    # the DISPLAYED buffer is the one main3.asm is not about to paint
    base = 0xC000 if rig.c.peek(rig.s["BACKBUF"]) == 0x80 else 0x8000
    return rig.c.read_ram(base, 0x4000)


def place(rig, pos, dx, dy):
    rig.c.write_ram(rig.s["PLR_X"], struct.pack("<H", pos[0]))
    rig.c.write_ram(rig.s["PLR_Y"], struct.pack("<H", pos[1]))
    rig.c.poke(rig.s["PLR_A"], pos[2])
    rig.c.poke(rig.s["GUN_DX"], dx + gunart.BOB_HA)      # the table's bias
    rig.c.poke(rig.s["GUN_DY"], dy)                      # already biased
    rig.c.run_frames(24)                                 # >= 2 game frames


BOB_FRAMES = 200
# THE TRAIL BUFFER.  #3B00 is march.asm's MARK page (the flood's
# already-pushed flags, #3B00-#3BFF) and the head of the quad list above
# it, and that is fine HERE and nowhere else: this phase runs
# gun_step and nothing else, so nothing marches and nothing projects
# while the 400 bytes below are being filled; march_init wipes MARK and
# the quad list is rebuilt from scratch by the next frame anyway.  The harness CODE is a different matter -- it goes
# at emu_pacefit's BASE, which is above QUADS for exactly that reason.
BOB_BUF = 0x3B00


def bob_model(n, moving=True, start=None):
    """gun.asm's rule, in Python.  -> [(dy_biased, dx_biased), ...].

    BOTH offsets are biased now: the vertical swings either side of the
    anchor and BOBV is stored biased by BOB_VA so the Z80 can ease
    towards it with the same unsigned compare the horizontal uses."""
    vert, horiz = gunart.bob_check()
    bv = [v + gunart.BOB_VA for v in vert]
    bh = [v + gunart.BOB_HA for v in horiz]
    pv = ph = 0
    lfsr = 1
    dy, dx = start or (gunart.BOB_VA, gunart.BOB_HA)     # rest = the anchor
    out = []
    for _ in range(n):
        if moving:
            pv = (pv + 1) % len(bv)
            carry = lfsr & 1                # srl a / jr nc / xor #B8
            lfsr >>= 1
            if carry:
                lfsr ^= 0xB8
            ph = (ph + 1) % len(bh)
            if (lfsr & 3) == 0:             # ...and one or two extra
                ph = (ph + 1) % len(bh)
                if lfsr & 4:
                    ph = (ph + 1) % len(bh)
            tv, th = bv[pv], bh[ph]
        else:
            tv, th = gunart.BOB_VA, gunart.BOB_HA
        for cur, tgt, lim in (("dy", tv, 2 * gunart.BOB_VA),
                              ("dx", th, 2 * gunart.BOB_HA)):
            v = dy if cur == "dy" else dx
            nv = v + 1 if v < tgt else (v - 1 if v > tgt else v)
            assert abs(nv - v) <= 1 and 0 <= nv <= lim, (cur, v, nv)
            if cur == "dy":
                dy = nv
            else:
                dx = nv
        out.append((dy, dx))
    return out


def bob(rig):
    """Run the REAL gun_step BOB_FRAMES times and compare the trail."""
    s = rig.s
    blob = rig._asm("gunbob", rig._head() + [
        "    ld a,1",
        "    ld (#%04X),a" % s["PLR_MOVING"],
        "    ld a,#%02X" % gunart.BOB_HA,       # the rest position, exactly
        "    ld (#%04X),a" % s["GUN_DX"],       # as gun.asm's own db does
        "    ld a,#%02X" % gunart.BOB_VA,       # ...and the anchor, biased
        "    ld (#%04X),a" % s["GUN_DY"],
        "    xor a",
        "    ld (#%04X),a" % s["GUN_PV"],
        "    ld (#%04X),a" % s["GUN_PH"],
        "    inc a",
        "    ld (#%04X),a" % s["GUN_LFSR"],
        "    ld hl,#%04X" % BOB_BUF,
        "    ld b,%d" % BOB_FRAMES,
        "lp  push bc",
        "    push hl",
        "    call #%04X" % s["GUN_STEP"],
        "    pop hl",
        "    ld a,(#%04X)" % s["GUN_DY"],
        "    ld (hl),a",
        "    inc hl",
        "    ld a,(#%04X)" % s["GUN_DX"],
        "    ld (hl),a",
        "    inc hl",
        "    pop bc",
        "    djnz lp",
        "spin jr spin"])
    rig.c.write_ram(BASE, blob)         # ...and BASE is what _head org'd it
    rig.c.set_pc(BASE)
    rig.c.run_us(200000)
    got = rig.c.read_ram(BOB_BUF, BOB_FRAMES * 2)
    want = bob_model(BOB_FRAMES)
    bad = 0
    for i, (dy, dx) in enumerate(want):
        if (got[2 * i], got[2 * i + 1]) != (dy, dx):
            if bad < 8:
                print(f"  FAIL frame {i}: machine "
                      f"({got[2 * i] - gunart.BOB_VA:+d},"
                      f"{got[2 * i + 1] - gunart.BOB_HA:+d}) "
                      f"model ({dy - gunart.BOB_VA:+d},"
                      f"{dx - gunart.BOB_HA:+d})")
            bad += 1
    trail = [(dy - gunart.BOB_VA, dx - gunart.BOB_HA) for dy, dx in want]
    print(f"  {BOB_FRAMES} frames of gun_step: machine == model, {bad} wrong")
    print(f"  dy {min(t[0] for t in trail):+d}.."
          f"{max(t[0] for t in trail):+d} scanlines about the anchor, "
          f"dx {min(t[1] for t in trail):+d}.."
          f"{max(t[1] for t in trail):+d} bytes, "
          f"largest step 1 in both (asserted per frame)")
    # ...and it EASES HOME rather than snapping there, from EITHER side --
    # which is new: rest used to be the bottom of the travel, so the ease
    # was always downward and never had to come back up.
    rest = (gunart.BOB_VA, gunart.BOB_HA)
    for sy in (0, 2 * gunart.BOB_VA):
        for sx in (0, 2 * gunart.BOB_HA):
            home = bob_model(12, moving=False, start=(sy, sx))
            for i in range(1, len(home)):
                assert max(abs(home[i][k] - home[i - 1][k])
                           for k in (0, 1)) <= 1, home
            assert home[-1] == rest, (sy, sx, home[-1])
            n_ease = next(i for i, v in enumerate(home) if v == rest) + 1
            print(f"  standing at ({sy - gunart.BOB_VA:+d},"
                  f"{sx - gunart.BOB_HA:+d}): eases to the anchor in "
                  f"{n_ease} frames, one step each")
    # ...and it does not repeat.  16 x 23 = 368 frames without the LFSR;
    # with it, look for any period at all over a long run.
    long = bob_model(4000)
    per = next((p for p in range(1, 2001)
                if all(long[i] == long[i + p] for i in range(1000, 2000))),
               None)
    print(f"  path repeat period over 4000 frames: "
          f"{per if per else 'none under 2000 frames (= 4 minutes)'}")
    return bad


def verify(rig):
    txt, bad = edges()
    print("  THE PLACEMENT, from the model, at all "
          f"{len(OFFSETS)} offsets:")
    print(txt)
    if bad:
        print(f"  FAIL: {bad} placement claims broken")

    step = rig.c.read_ram(rig.s["GUN_STEP"], 1)
    rig.c.poke(rig.s["GUN_STEP"], 0xC9)     # RET: freeze the bob
    rest = gunart.BOB_VA

    # the same view with the weapon suppressed -- the background the blit
    # is allowed to change, and nothing else
    draw = rig.c.read_ram(rig.s["GUN_DRAW"], 1)
    rig.c.poke(rig.s["GUN_DRAW"], 0xC9)
    place(rig, CORRIDOR, 0, rest)
    clean = read_screen(rig)
    rig.c.write_ram(rig.s["GUN_DRAW"], draw)

    # THE WHOLE 16K, not just the viewport: a row drawn past the bottom
    # clamp would land in the HUD, which the viewport comparison cannot
    # see, and that is exactly the failure this phase now exists to catch.
    #
    # EXCEPT THE EIGHT TICKS OF THE DIAL, which are the one part of the
    # screen that moves on its own.  hud_radar lights one of them a
    # frame as a radar sweep (hud2.asm), so the "clean" reference frame
    # and the 45 posed frames are taken with the sweep at different
    # points and 360 bytes disagree -- all of them #3C against #FC, the
    # resting tick colour against the lit one.  That is the indicator
    # doing its job, not the blitter missing.  The boxes are masked out
    # by NAME, from genhud's own tick geometry, so a tick that moves
    # takes its mask with it and nothing else is forgiven.
    skip = set()
    for (tx, ty, tw, th, _b) in genhud.tick_rects():
        for yy in range(ty, ty + th):
            for xx in range(tx, tx + tw):
                skip.add(addr(yy, xx, 0))
    n = 0
    for dx, dy in OFFSETS:
        place(rig, CORRIDOR, dx, dy)
        got = read_screen(rig)
        want = {addr(y, x, 0): b for (y, x), b in want_rows(dx, dy).items()}
        for off in range(len(got)):
            if off in skip:
                continue
            exp = want.get(off, clean[off])
            if got[off] != exp:
                if bad < 12:
                    print(f"  FAIL dx={dx:+d} dy={dy - rest:+d} "
                          f"screen+#{off:04X}: got #{got[off]:02X} "
                          f"want #{exp:02X}"
                          f"{'  (sprite)' if off in want else ''}")
                bad += 1
        n += 1
    print(f"  {n} bob offsets x {len(clean) - len(skip)} screen bytes = "
          f"{n * (len(clean) - len(skip))} bytes compared, {bad} wrong"
          f"  ({len(skip)} bytes of radar tick masked)")
    rig.c.write_ram(rig.s["GUN_STEP"], step)
    return bad


def measure(rig):
    rig.ovh = 0.0
    rig.ovh = rig.bench(None)
    cal = rig.bench(None, nops=100)
    print(f"  calibration: 100 NOPs = {cal:.2f} us "
          f"(empty loop {rig.ovh:.2f} us, subtracted)")
    place(rig, CORRIDOR, 0, gunart.BOB_VA)

    # gun_step, both branches, before it is stubbed for the draw sweep
    for mv, tag in ((0, "standing (easing home)"), (1, "walking")):
        rig.c.poke(rig.s["PLR_MOVING"], mv)
        print(f"  gun_step  {tag:24s} {rig.bench(rig.s['GUN_STEP']):7.1f} us")
    rig.c.poke(rig.s["PLR_MOVING"], 0)
    rig.c.poke(rig.s["GUN_STEP"], 0xC9)
    worst = (0.0, None)
    best = (1e9, None)
    tot = 0.0
    # THE COST DEPENDS ON dy NOW.  The bottom clamp draws GUN_ROWS0 rows at
    # the bottom of the swing and GUN_H at the top, so the sweep has to
    # cover the whole biased range and the WORST is what C_GUN answers to.
    for dy in range(0, 2 * gunart.BOB_VA + 1):
        row = []
        for dx in range(-gunart.BOB_HA, gunart.BOB_HA + 1):
            rig.c.poke(rig.s["GUN_DX"], dx + gunart.BOB_HA)
            rig.c.poke(rig.s["GUN_DY"], dy)
            us = rig.bench(rig.s["GUN_DRAW"])
            row.append(us)
            tot += us
            if us > worst[0]:
                worst = (us, (dx, dy))
            if us < best[0]:
                best = (us, (dx, dy))
        print("  gun_draw dy=%+d (%2d rows)  " % (dy - gunart.BOB_VA,
                                                  rows_drawn(dy))
              + "  ".join("%7.1f" % v for v in row) + "  us")
    n = len(OFFSETS)
    print(f"  gun_draw  mean {tot / n:8.1f} us   "
          f"BEST {best[0]:8.1f} us at dx={best[1][0]:+d} "
          f"dy={best[1][1] - gunart.BOB_VA:+d}   "
          f"WORST {worst[0]:8.1f} us at dx={worst[1][0]:+d} "
          f"dy={worst[1][1] - gunart.BOB_VA:+d} "
          f"({rows_drawn(worst[1][1])} rows)")

    # SPLIT IT.  Fill the whole unrolled LDI block with RET and every run
    # copies nothing, so what is left is the per-row stepping and the
    # per-band setup.  The difference is what the run data really costs.
    # Measured AT THE WORST OFFSET, where every row is drawn.
    nldi = 2 * G.GUN_MAXN + 1
    save = rig.c.read_ram(rig.s["GUNLDI"], nldi)
    rig.c.poke(rig.s["GUN_DX"], worst[1][0] + gunart.BOB_HA)
    rig.c.poke(rig.s["GUN_DY"], worst[1][1])
    rig.c.write_ram(rig.s["GUNLDI"], b"\xC9" * nldi)
    step = rig.bench(rig.s["GUN_DRAW"])
    rig.c.write_ram(rig.s["GUNLDI"], save)
    full = rig.bench(rig.s["GUN_DRAW"])
    nr = rows_drawn(worst[1][1])
    nb = sum(len(r[1]) for r in gunart.rows()[:nr])
    print(f"  ...of which stepping {step:7.1f} us "
          f"({step / nr:.1f} us a scanline over {nr})")
    print(f"     and the bytes    {full - step:7.1f} us "
          f"({(full - step) / nb:.2f} us a byte over {nb})")
    return 0                            # nothing here can FAIL, only inform


def generation(rig):
    """The disc under the harness and the art in this process must be the
    SAME GENERATION, and this is checked before a single pixel is.

    THIS IS NOT BELT AND BRACES, IT IS THE DEFECT THAT COST A DAY.  The
    comparison below reads the drawing out of gunart.py and the pixels out
    of build/amaze.dsk, and nothing about that arrangement makes the two
    the same age.  `make gun` boots the disc; it did not build it.  So an
    edited drawing was verified against a disc carrying the previous one
    and the harness reported 9450 wrong bytes of 737280 and a weapon with
    no hand -- every diff true, and not one of them a defect in gun.asm.
    A pixel diff cannot tell a broken blitter from a stale disc.

    Two things are compared, because there are two files:

        gun_sig     a word in GAME3.BIN, gentab.py's FNV over the run list
                    AND the geometry (H, the bob amplitudes, the cut, the
                    band count).  It catches a stale GAME3.BIN, whose
                    GUN_H / GUN_ROWS0 / GUN_Y0 are assembled-in constants
                    that no table compare can see.
        GUNBAND     the two bank 4 tables, byte for byte.  They catch a
        GUNPIX      stale TABLES.BIN under a fresh GAME3.BIN.
    """
    want = G.GUN_SIG
    got = struct.unpack("<H", rig.c.read_ram(rig.s["GUN_STAMP"], 2))[0]
    bad = 0
    if got != want:
        print(f"  FAIL: the disc was built from a different gunart.py "
              f"(gun_sig #{got:04X}, this art #{want:04X}). "
              f"Run `make` -- the pixels below would ALL be noise.")
        bad += 1
    # ...AND PARK THE CPU SOMEWHERE BANK 4 IS ACTUALLY PAGED IN.  The
    # peeks below see the CPU's CURRENT paging, and "main3.asm leaves bank
    # 4 at #4000" is only true BETWEEN renders: rastcol.asm swaps bank 5
    # in over the same window for the textured fill and swaps 4 back at
    # rc_done.  The rig stops wherever run_frames(500) happens to land,
    # which at 9 vsyncs a game frame is an arbitrary point inside one, so
    # whether this read saw tables or TEXTURE was a coin flip -- and it
    # came up tails the first time the frame's shape changed, reporting
    # 27 of 31 GUNBAND bytes wrong on a disc that was perfectly fresh.
    #
    # So: stop the machine, select RAM config 4 by hand, and spin.  This
    # rig is discarded when generation() returns -- main() builds a fresh
    # one per phase -- so taking the PC out of the game loop costs
    # nothing here.
    rig.c.run_code(0x3AC0, bytes([0xF3,   # #3AC0-#3FEF is free RAM               # di
                                  0x01, 0xC4, 0x7F,   # ld bc,#7FC4
                                  0xED, 0x49,         # out (c),c
                                  0x18, 0xFE]), 2)    # jr $
    layout = G.build()[1]
    for name, model in (("GUNBAND", G.t_gunband()), ("GUNPIX", G.t_gunpix())):
        addr = layout[name][0]
        # PEEK, not read_ram.  read_ram reads the BASE 64K -- bank 4 lives
        # in the second 64K and is only visible through the CPU's current
        # paging.
        on_disc = bytes(rig.c.peek(addr + i) for i in range(len(model)))
        if bytes(model) != on_disc:
            nw = sum(1 for a, b in zip(model, on_disc) if a != b)
            print(f"  FAIL: bank 4 {name} at #{addr:04X} is a different "
                  f"generation from gunart.py ({nw} of {len(model)} bytes "
                  f"differ). Run `make`.")
            bad += 1
    if not bad:
        print(f"  the disc and gunart.py are the same generation: "
              f"gun_sig #{want:04X}, {len(G.t_gunband())} band bytes and "
              f"{len(G.t_gunpix())} pixel bytes agree")
    return bad


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    bad = 0
    # A FRESH MACHINE PER PHASE.  `bob` and `measure` both take the PC out
    # of main_loop and leave it spinning in the bench harness at BASE, so
    # a later phase that expects the GAME to be drawing frames would read a
    # stale screen -- which is exactly what it did, and it failed 6076
    # bytes of a verify that passes on its own.  Booting is a few seconds;
    # a phase silently measuring a dead machine is not worth saving them.
    for phase, fn, banner in (
            ("gen", generation,
             "GENERATION -- the disc under test IS this gunart.py"),
            ("bob", bob,
             "BOB -- gun_step on the machine against the same rule in Python"),
            ("verify", verify,
             "VERIFY -- the blit, byte for byte, at every bob offset"),
            ("measure", measure,
             "MEASURE -- emu_pacefit's protocol, on the running game")):
        # ...and the generation check runs whatever was asked for, and
        # stops the run if it fails: every number below it is meaningless
        # if the disc is not this art.
        if what in ("all", phase) or phase == "gen":
            print(banner)
            bad += fn(Rig()) or 0
            if phase == "gen" and bad:
                return 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
