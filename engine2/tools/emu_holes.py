"""MEASURE the two units main3.asm's constants do not obviously cover:
the march_setup MARK clear, and the frame TAIL (flip + game_step + the
head of main_loop).

    python3 engine2/tools/emu_holes.py [nstates]

Method is emu_pacefit.py's: boot build/amaze.dsk, drop a counter loop into
the free RAM at #3F00 of the RUNNING game, bump a 16-bit counter once per
iteration with interrupts off, and subtract an identical loop with the
CALL removed.  Calibrated against 100 NOPs.

BASE, BASE_TOP AND THE RC_VARS GUARD ARE IMPORTED from emu_pacefit rather
than written down again here.  This file kept its own `BASE = 0x3A00`,
which is where memmap.inc now puts QUADS.

OF THE TWO DEFECTS THAT COST emu_pacefit ITS NUMBERS, ONLY ONE WAS LIVE
HERE, AND IT IS THE ONE THAT MOVED THE READINGS.  Nothing this file
benches is project_all, so the quad list was never written and the
harness was never overwritten -- #3A00 was wrong and harmless, a trap
armed for whoever next added a call to it.  The PAGING was not harmless:
the rig boots the disc and stops the CPU at an arbitrary point in the
frame, rastcol.asm pages bank 5 over #4000 for its fill, and game_step
and march_setup both read the table bank -- so `_head` now selects bank 4
before it does anything else.  See the note above emu_pacefit.BASE.

The two additions here:

  * PRELUDE LINES.  game_step MOVES the player, so a bench loop wanders
    off the state being measured and the average hides the worst case.
    Every bench can therefore run a fixed prelude before the call, and
    the overhead loop runs the SAME prelude, so what is left is the call
    alone -- at a pinned position, heading and key state.

  * REAL KEYS.  game_step reads the matrix itself (game.asm:scan_keys),
    so the harness holds actual keys down rather than poking KEYS, and
    the cost of turning and of the collision test is the real one.
"""

import os
import addrs
import random
import struct
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

from cpc import CPC                                          # noqa: E402
import bootdisc                                              # noqa: E402
import cpc as cpcmod                                         # noqa: E402
import pacemodel as P                                        # noqa: E402
# ONE number, not a second copy of it.  BASE/BASE_TOP and the RC_VARS
# guard live in emu_pacefit; importing them means moving the harness
# window moves it for every rig at once.
from emu_pacefit import BASE, BASE_TOP, _rc_vars_end          # noqa: E402

DSK = os.path.join(_ROOT, "build", "amaze.dsk")
SYM = os.path.join(_ROOT, "build", "e3", "game3.sym")

# ---- THE FIRE KEY, AND WHY IT IS Z AND NOT CTRL.  game.asm's fire_edge
#  takes either, but the emulator's key_down() maps ASCII to the matrix
#  and reaches no modifier at all -- see the note in fire_edge.  Z is the
#  one of the two a harness can press.
KEY_FIRE = ord('z')

# Read out of game.asm, not copied: `fire` and `mon_hit` are benched
# below and both have an early-out that a stale constant would leave the
# bench sitting on.
AMMO_MAX = P._equ("AMMO_MAX", 6, "game.asm")
MON_HPMAX = P._equ("MON_HPMAX", 3, "game.asm")
SCRATCH = os.path.join(_E2, "build")


class Rig:
    def __init__(self):
        self.s = {}
        for line in open(SYM):
            p = line.split()
            if len(p) >= 2 and p[1].startswith("#"):
                self.s[p[0].upper()] = int(p[1][1:], 16)
        self.c = CPC()
        self.c.insert_disc(DSK)
        self.c.run_frames(150)
        self.c.type_text('RUN"DISC\n')
        self.c.run_frames(500)
        bootdisc.start(self.c)   # past the title screen -- see bootdisc.py
        self.solid = self.c.read_ram(addrs.SOLID, 256)
        self.ovh = 0.0

    def _asm(self, name, lines):
        # per-process, so two of these can run at once without one
        # assembling over the other's .bin half way through
        name = "%s%d" % (name, os.getpid())
        src = os.path.join(SCRATCH, name + ".asm")
        os.makedirs(SCRATCH, exist_ok=True)
        open(src, "w").write("\n".join(lines) + "\n")
        r = subprocess.run(["rasm", name + ".asm", "-o", name],
                           cwd=SCRATCH, capture_output=True)
        if r.returncode:
            raise RuntimeError(r.stdout.decode() + r.stderr.decode())
        blob = open(os.path.join(SCRATCH, name + ".bin"), "rb").read()
        # ---- AND CHECK IT FITS WHERE IT IS PUT.  The harnesses here are
        # small -- the biggest is the 100-NOP calibration at 141 bytes,
        # against the 192 the window holds -- but "small" was true of the
        # old ones too and nothing checked, so it is checked.
        lo = _rc_vars_end()
        assert BASE >= lo, (
            "harness BASE #%04X is inside rastcol.asm's RC_VARS "
            "(ends #%04X)" % (BASE, lo))
        assert BASE + len(blob) <= BASE_TOP, (
            "harness `%s` is %d bytes, #%04X..#%04X, past #%04X -- the "
            "CPU stack grows down into it from #3FF0"
            % (name, len(blob), BASE, BASE + len(blob), BASE_TOP))
        return blob

    def _head(self):
        # ---- SELECT BANK 4 FIRST.  This rig boots the disc and calls
        # run_frames(500), which stops the CPU at an ARBITRARY point
        # inside a 9-vsync game frame; rastcol.asm pages bank 5 over
        # #4000 for its textured fill and pages 4 back at rc_done, so
        # whether a harness read LINETAB/PROJ/BOBV or TEXTURE was a coin
        # flip nothing in the tool controlled.  march_setup and game_step
        # both read the table bank, so this is not decoration.
        #
        # BASE and the stack are below #4000, so the `out` is outside the
        # window it moves and cannot pull the ground out from under the
        # code doing it.
        return ["    org #%04X" % BASE, "    di",
                "    ld bc,#7FC4", "    out (c),c",     # RAM config 4
                "    ld sp,#3FF0",
                "    xor a", "    ld (#%04X),a" % self.s["PACE_LEFT"],
                "    ld hl,0", "    ld (#%04X),hl" % self.s["COST_ACC"],
                # pace_wait waits even with the budget gone, which is the
                # whole point of it; a bench loop must not, so stub it.
                "    ld a,#C9", "    ld (#%04X),a" % self.s["PACE_WAIT"]]

    def _loop(self, body, pre, us):
        lines = (["    ld hl,0", "    ld (cnt),hl", "lp  ld hl,(cnt)",
                  "    inc hl", "    ld (cnt),hl"] + list(pre) + list(body)
                 + ["    jr lp", "cnt dw 0"])
        blob = self._asm("holes", self._head() + lines)
        self.c.write_ram(BASE, blob)
        self.c.set_pc(BASE)
        self.c.run_us(6000)
        ca = BASE + len(blob) - 2
        self.c.write_ram(ca, b"\x00\x00")
        t = self.c.run_us(us)
        n = struct.unpack("<H", self.c.read_ram(ca, 2))[0]
        if not 0 < n < 60000:
            raise RuntimeError("counter unusable: %d" % n)
        return (t / 4.0) / n

    def bench(self, target=None, nops=0, pre=(), us=400000):
        """-> us for the call, with the loop AND the prelude removed."""
        body = ([] if target is None else ["    call #%04X" % target])
        body += ["    nop"] * nops
        hot = self._loop(body, pre, us)
        cold = self._loop([], pre, us)
        return hot - cold

    def place(self, px, py, a):
        self.c.write_ram(self.s["PLR_X"], struct.pack("<H", px))
        self.c.write_ram(self.s["PLR_Y"], struct.pack("<H", py))
        self.c.poke(self.s["PLR_A"], a)

    def pin(self, px, py, a):
        """Prelude that restores the player before every call."""
        return ["    ld hl,#%04X" % px,
                "    ld (#%04X),hl" % self.s["PLR_X"],
                "    ld hl,#%04X" % py,
                "    ld (#%04X),hl" % self.s["PLR_Y"],
                "    ld a,#%02X" % a,
                "    ld (#%04X),a" % self.s["PLR_A"]]

    def keys(self, *ks):
        # Z IS IN THIS LIST BECAUSE IT IS A GAME KEY.  game.asm's
        # fire_edge reads row 8 bit 7 as well as CTRL, so a bench that
        # never presses it never measures `fire` -- and `fire` runs
        # inside game_step, which is what C_TAIL bounds.
        for k in (cpcmod.KEY_UP, cpcmod.KEY_DOWN, cpcmod.KEY_LEFT,
                  cpcmod.KEY_RIGHT, cpcmod.KEY_SPACE, KEY_FIRE):
            self.c.key_up(k)
        for k in ks:
            self.c.key_down(k)
        self.c.run_frames(2)


def reachable(solid, px, py):
    import emu_pace as ep
    return ep.reachable(solid, px, py)


def main(nstates=24):
    rig = Rig()
    print("=== timing method: empty loop removed, +100 NOPs calibrates to "
          "%.2f us" % rig.bench(None, nops=100))

    s = rig.s
    ms = s["MARCH_SETUP"]
    gen = s["M_GEN"]

    # The states.  march_setup's four seed multiplies and its L1 build are
    # position- and heading-dependent (MEASURED 1337-1401 us across states
    # before the clear was amortised), so both halves of this file sweep
    # the lattice a walking player actually lands on rather than trusting
    # whatever state the game happened to be left in.
    import emu_pace as ep
    offs = ep.lattice_offsets()
    rnd = random.Random(31337)
    pool = [((cx << 8) | ox, (cy << 8) | oy, a)
            for cy in range(16) for cx in range(16) for ox in offs
            for oy in offs for a in range(72)
            if ep.reachable(rig.solid, (cx << 8) | ox, (cy << 8) | oy)]
    states = rnd.sample(pool, nstates)

    # ---- (a) march_setup, flat frame vs the frame the generation wraps
    print("\n=== (a) march_setup, worst over %d states" % len(states))
    flat = wrap = 0.0
    fst = wst = None
    for (px, py, a) in states:
        pin = rig.pin(px, py, a)
        f = rig._loop(["    call #%04X" % ms],
                      pin + ["    ld a,1", "    ld (#%04X),a" % gen], 250000)
        w = rig._loop(["    call #%04X" % ms],
                      pin + ["    ld a,#FF", "    ld (#%04X),a" % gen],
                      250000)
        b = rig._loop([], pin + ["    ld a,1",
                                 "    ld (#%04X),a" % gen], 250000)
        if f - b > flat:
            flat, fst = f - b, (px, py, a)
        if w - b > wrap:
            wrap, wst = w - b, (px, py, a)
    print("  flat frame (m_gen 1 -> 2)        %8.1f us  at (%04X,%04X)h%d"
          % ((flat,) + fst))
    print("  wrap frame (m_gen 255 -> 1)      %8.1f us  at (%04X,%04X)h%d"
          % ((wrap,) + wst))
    print("  the step the wrap adds           %8.1f us" % (wrap - flat))
    print("  C_MSETUP %d -- margin flat %+.1f, WRAP %+.1f"
          % (P.C_MSETUP, P.C_MSETUP - flat, P.C_MSETUP - wrap))

    # ---- (b) the tail: flip + game_step + the head of main_loop
    print("\n=== (b) the tail")
    flip = rig.bench(s["FLIP"])
    # the head of main_loop, assembled verbatim into the scratch RAM
    head = ["    ld hl,(#%04X)" % s["FRAME_CTR"], "    inc hl",
            "    ld (#%04X),hl" % s["FRAME_CTR"],
            "    ld a,(#%04X)" % s["BACKBUF"],
            "    call #%04X" % s["FRAME_SETBUF"],
            "    ld a,(#%04X)" % s["BACKBUF"],
            "    call #%04X" % s["HUD_SETBUF"]]
    if P.GUN:
        head += ["    ld a,(#%04X)" % s["BACKBUF"],
                 "    call #%04X" % s["GUN_SETBUF"]]
    head += ["    ld hl,(#%04X)" % s["COST_ACC"], "    ld de,%d" % P.C_TAIL,
             "    add hl,de", "    ld (#%04X),hl" % s["COST_ACC"],
             "    ld a,%d" % P.PACE_FRAMES,
             "    ld (#%04X),a" % s["PACE_LEFT"]]
    lhead = rig._loop(head, [], 400000) - rig._loop([], [], 400000)
    print("  flip                             %8.1f us" % flip)
    print("  main_loop head (setbufs + acc)   %8.1f us" % lhead)

    # game_step, at pinned states, over the key combinations a player can
    # actually hold.  Turning and walking are the expensive branches and
    # they compose, so the worst is a turn AND a walk.
    combos = [("still", ()), ("FIRE", (KEY_FIRE,))]
    for wn, wk in (("U", cpcmod.KEY_UP), ("D", cpcmod.KEY_DOWN)):
        for tn, tk in (("", None), ("+L", cpcmod.KEY_LEFT),
                       ("+R", cpcmod.KEY_RIGHT)):
            ks = (wk,) + ((tk,) if tk else ())
            combos.append((wn + tn, ks))
            combos.append((wn + tn + "+FIRE", ks + (KEY_FIRE,)))
            combos.append((wn + tn + "+SPC", ks + (cpcmod.KEY_SPACE,)))
    # ---- AND THE MONSTER'S FRAME IS FORCED, the same way (hud_cur) is
    # forced below.  game.asm's mon_move returns after two instructions on
    # five frames in six and walks a cell on the sixth -- as_l1, two
    # mm_dirs and up to two SOLID reads.  A bench that let the counter run
    # would sample the cheap branch five times out of six and report a
    # MEAN, and C_TAIL is not a mean, it is a bound.  (mon_tick) at 1
    # makes every call take the expensive path.
    #
    # MONCELL is restored too: mon_move WRITES it, so 250 ms of bench loop
    # would otherwise walk the monster onto the player, where mon_move
    # returns early at L1 < 2 and the measurement collapses to the cheap
    # branch again -- silently, and in the safe-looking direction.
    pre_mon = ["    ld a,1", "    ld (#%04X),a" % s["MON_TICK"],
               "    ld a,%d" % rig.c.peek(s["MONCELL"]),
               "    ld (#%04X),a" % s["MONCELL"]]

    # ---- AND THE SAME FOR THE TRIGGER.  `fire` is an edge, an ammo
    # count and a monster that can die, so three things have to be put
    # back before every call or the loop measures the CHEAP branch:
    # PREVKEYS, else there is one edge in 250 ms of bench and the rest
    # are no-ops; plr_ammo, else the magazine empties in six calls and
    # every call after that is SFX_CLICK and a ret; mon_hp, else the
    # third round kills the monster, MONCELL goes #FF, and fx_fire can
    # never read FX_BLOOD again.  All three fail SILENTLY and all three
    # fail LOW.
    pre_fire = ["    ld hl,#%04X" % (s["PREVKEYS"] + 8), "    ld (hl),#FF",
                "    ld a,%d" % AMMO_MAX,
                "    ld (#%04X),a" % s["PLR_AMMO"],
                "    ld a,%d" % MON_HPMAX,
                "    ld (#%04X),a" % s["MON_HP"]]

    worst = {}
    for name, ks in combos:
        rig.keys(*ks)
        if cpcmod.KEY_SPACE in ks:
            # SPACE acts on the PRESS EDGE only, so PREVKEYS must show it
            # released before every call for door_act to run every time.
            pre_spc = ["    ld hl,#%04X" % (s["PREVKEYS"] + 5),
                       "    ld (hl),#FF"]
        else:
            pre_spc = []
        pre_spc = pre_spc + pre_mon + (pre_fire if KEY_FIRE in ks else [])
        w, warg = 0.0, None
        for (px, py, a) in states:
            v = rig.bench(s["GAME_STEP"], pre=rig.pin(px, py, a) + pre_spc,
                          us=250000)
            if v > w:
                w, warg = v, (px, py, a)
        worst[name] = w
        print("  game_step %-9s worst over %d states  %8.1f us  at "
              "(%04X,%04X)h%d" % (name, len(states), w, warg[0], warg[1],
                                  warg[2]))
    rig.keys()

    # door_act on its own, over the same states.  It is called only on the
    # SPACE press edge, and it TOGGLES the door it finds, so successive
    # calls at one state walk the door through its states and the bench
    # sees the whole spread rather than one phase of it.
    dalone = 0.0
    for (px, py, a) in states:
        dalone = max(dalone, rig.bench(s["DOOR_ACT"], pre=rig.pin(px, py, a),
                                       us=250000))
    print("  door_act  alone     worst over %d states  %8.1f us"
          % (len(states), dalone))
    ds = 0.0
    for (px, py, a) in states[:4]:
        ds = max(ds, rig.bench(s["DOORS_STEP"], us=250000))
    print("  doors_step alone                          %8.1f us" % ds)

    # The SPACE branch is charged on its own (game.asm:door_paced), so the
    # flat tail constant only has to bound the frames that do NOT open a
    # door -- which is what these two maxima separate.
    nospc = max(v for k, v in worst.items() if "SPC" not in k)
    spc = max(worst.values())
    tail = flip + lhead + nospc
    print("\n  TAIL (no door)  = flip %.1f + game_step %.1f + head %.1f"
          " = %.1f us" % (flip, nospc, lhead, tail))
    print("  C_TAIL %d -- margin %+.1f" % (P.C_TAIL, P.C_TAIL - tail))
    # The SPACE branch, bounded by the LARGER of the two things that
    # measure it: the differential inside game_step, and door_act benched
    # on its own.  They disagree because opening a door changes SOLID and
    # so changes what move_apply does next, which pulls the differential
    # DOWN -- so the direct bench is the honest bound and the constant is
    # fitted to it.
    dact = max(spc - nospc, dalone)
    print("\n  the SPACE press edge (door_act) costs up to %.1f us"
          " (differential %.1f, benched alone %.1f)"
          % (dact, spc - nospc, dalone))
    cd = getattr(P, "C_DOORACT", 0)
    print("  C_DOORACT %d -- margin %+.1f" % (cd, cd - dact))
    print("  TAIL (door opened) %.1f us, charged %d"
          % (tail + dact, P.C_TAIL + cd))

    # ---- (c) hud_update, over all 72 headings.
    #  The same audit C_MSETUP failed: C_HUD came from ONE measurement of
    #  ONE heading transition (emu_hud.py, 1360.2 us), and the needle's
    #  eight blocks do not cost the same at every heading.  hud_update
    #  only repaints when the heading changed, so (hud_cur) is forced to
    #  the opposite heading before every call to keep the bench on the
    #  erase-and-redraw branch.
    print("\n=== (c) hud_update, needle MOVED, over all 72 headings")
    hw, hwa = 0.0, None
    for h in range(72):
        pre = ["    ld a,%d" % h, "    ld (#%04X),a" % s["PLR_A"],
               "    ld a,%d" % ((h + 36) % 72),
               "    ld (#%04X),a" % s["HUD_CUR"],
               "    ld (#%04X),a" % (s["HUD_CUR"] + 1)]
        v = rig.bench(s["HUD_UPDATE"], pre=pre, us=250000)
        if v > hw:
            hw, hwa = v, h
    print("  worst %.1f us at heading %d" % (hw, hwa))
    print("  C_HUD %d -- margin %+.1f" % (P.C_HUD, P.C_HUD - hw))

    ok = (P.C_TAIL >= tail and P.C_TAIL + cd >= tail + dact
          and P.C_MSETUP >= wrap and P.C_MSETUP >= flat and P.C_HUD >= hw)
    print("\n  EVERY CONSTANT A ONE-SIDED UPPER BOUND: %s" % ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 24))
