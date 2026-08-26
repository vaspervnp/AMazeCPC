"""MEASURE what the SHIPPED game frame costs, and fit main3.asm's C_*.

    python3 engine2/tools/emu_pacefit.py [nstates]

WHY NOT emu_frame.py.  That harness times engine2/test/tst_frame.asm,
which includes march/project/raster WITHOUT main3.asm -- so `PACED` is
undefined and the cost hooks are compiled out.  The hooks are part of the
work they charge for (203 us a quad, 109 a face, 44 a cell: 6 ms on a busy
frame), so the constants have to be fitted to code that HAS them.  This
file therefore measures the real thing: it boots build/amaze.dsk, drops a
counter loop into the free RAM at #3A00 of the running game, and calls
bg_fill / march / project_all / raster_paced / hud_update / game_step from
there.

TIMING PROTOCOL is emu_frame.py's: a 16-bit counter bumped once per
iteration with interrupts off, an identical loop with the CALL removed for
the overhead, calibrated against 100 NOPs (99.99 us).  (pace_left) is
zeroed by the loop so the hooks never actually wait.

The regressors are the counters THE Z80 ITSELF charges from, read out of
the machine after one clean pass:

    m_visited          cells the flood popped        -> C_MSETUP, C_CELL
    fg_nquad, FTAB+E0  quads and candidate faces     -> C_FACE, C_REJ
    projmodel's lerps  clips                         -> C_CLIP
    the quad records   blo/bhi/hlo/hhi               -> C_QUAD, C_QS

and the fit is only half the job: the constants main3.asm ships are the
fitted ones ROUNDED UP until they over-predict every state measured, which
is what this file checks and prints last.
"""

import json
import addrs
import os
import random
import re
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
import emu_frame as ef                                       # noqa: E402
import pacemodel as P                                        # noqa: E402
import projmodel as pm                                       # noqa: E402
import rastermodel as rm                                     # noqa: E402

DSK = os.path.join(_ROOT, "build", "amaze.dsk")
SYM = os.path.join(_ROOT, "build", "e3", "game3.sym")
SCRATCH = os.path.join(_E2, "build")
# WHERE THE BENCH HARNESS LIVES, AND IT MUST NOT BE INSIDE QUADS.
#
# It was #3A00, described here as "free RAM: #39C0-#3FEF".  That comment
# was written when the kernel's output list started at #3700; QUADS is
# #3A00 now (memmap.inc), so every blob this file assembled was sitting
# exactly where project_all writes its first quad record.
#
# THE COLLISION WAS INVISIBLE BECAUSE OF A SECOND BUG.  With the table
# bank not paged in -- see _head -- project_all rejected every face, wrote
# ZERO quads, and never reached the harness.  The tool ran, printed a
# `quad` column of 0 and an identical `rast` of 18822 us for state after
# state, and looked like it was measuring something.  Page bank 4 in and
# project_all starts producing real quads, the first of which lands on the
# counter this file reads -- "counter unusable: 0".  Two bugs whose
# symptoms cancelled.
#
# #3F00 is above QUADS (#3A00-#3DBF), above DOORTAB (#3DC0-#3DEF) and
# above rastcol.asm's RC_COVER/RC_VARS at #3E00; _asm asserts both ends
# rather than trusting this comment to stay true, because that is exactly
# what the last comment here did not do.
BASE = 0x3F00
BASE_TOP = 0x3FC0               # ...and the CPU stack grows down from #3FF0


def _rc_vars_end():
    """-> the first byte above rastcol.asm's variable block.

    DERIVED, not written down: the block is RC_COVER + CNPAIR*2 followed
    by ~80 bytes of `rc_x equ RC_VARS+n`, and both the base and the
    largest n are parsed out of the source.  A new variable there moves
    this number on its own.
    """
    src = open(os.path.join(_E2, "src", "rastcol.asm")).read()
    cover = int(re.search(r"^RC_COVER\s+equ\s+#([0-9A-Fa-f]+)", src,
                          re.M).group(1), 16)
    # CNPAIR is gentex.py's, emitted into gen_tex.inc
    gen = open(os.path.join(_E2, "src", "gen_tex.inc")).read()
    npair = int(re.search(r"^CNPAIR\s+equ\s+(\d+)", gen, re.M).group(1))
    top = max(int(m) for m in
              re.findall(r"^rc_\w+\s+equ\s+RC_VARS\+(\d+)", src, re.M))
    return cover + 2 * npair + top + 2      # + the widest variable
FTAB_BPTR = addrs.FTAB + addrs.O_BPTR   # the march's 8 bucket write
                                        # pointers.  IT WAS 0x33E0, and the
                                        # line below was already reading its
                                        # address out of addrs while this
                                        # one kept a copy from two moves ago
                                        # -- so it read the flood stack,
                                        # nface came back 0 on every state,
                                        # and nrej = nface - nq went
                                        # NEGATIVE.  See addrs.py.
QUADS = addrs.QUADS
MIN_N = 400                     # iterations a bench must reach before its
                                # reading is trusted: 1/400 = 0.25%, which
                                # on the 35 ms raster_paced is +-90 us.
                                # See Rig.bench for what 17 iterations did.


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
        """Assemble a bench body, into a file named for THIS PROCESS.

        The name used to be shared, and emu_gun.py borrows this Rig: run
        `emu_pacefit.py` and `emu_gun.py` at the same time and both
        processes write engine2/build/pfbench.asm, call rasm on it, and
        read back engine2/build/pfbench.bin -- so one of them can load the
        OTHER's blob and bench a routine it never asked for.  MEASURED:
        gun_draw, which is 2950.4 us on its own and reads 2950.4 with all
        sixteen cores spinning (the emulator is cycle-accurate, so load
        cannot move it), came out at 19619.7 us during a concurrent
        emu_pacefit run.  The pid makes the collision impossible instead
        of unlikely."""
        name = "%s_%d" % (name, os.getpid())
        src = os.path.join(SCRATCH, name + ".asm")
        os.makedirs(SCRATCH, exist_ok=True)
        open(src, "w").write("\n".join(lines) + "\n")
        subprocess.run(["rasm", name + ".asm", "-o", name],
                       cwd=SCRATCH, capture_output=True, check=True)
        blob = open(os.path.join(SCRATCH, name + ".bin"), "rb").read()
        # ---- AND CHECK IT FITS WHERE IT IS PUT.  See BASE above: the
        # last version of this file assembled every harness on top of the
        # kernel's quad list and nothing said so.
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
        # ---- SELECT BANK 4 FIRST, and it is not belt and braces.  Every
        # harness this Rig builds reads the table bank at #4000 -- BOBV,
        # LINETAB, PROJ, the lot -- and the rig arrives here by booting
        # the disc and calling run_frames(500), which stops the CPU at an
        # ARBITRARY point inside a 9-vsync game frame.  Most of that frame
        # has bank 4 paged, but rastcol.asm swaps bank 5 in over the same
        # window for the textured fill, so whether a harness saw tables or
        # TEXTURE was a coin flip that nothing in the tool controlled.
        #
        # It came up tails the first time the frame's shape changed, and
        # the failure did not look like paging at all: emu_gun.py's bob
        # phase read BOBV out of the unused tail of the texture bank,
        # which is zeros, so gun_step eased towards 0 every frame and 198
        # of 200 frames "disagreed with the model".
        #
        # #3A00 is below #4000, so the out is outside the window it moves
        # and cannot pull the ground out from under the code doing it.
        return ["    org #%04X" % BASE, "    di",
                "    ld bc,#7FC4", "    out (c),c",     # RAM config 4
                "    ld sp,#3FF0",
                "    xor a", "    ld (#%04X),a" % self.s["PACE_LEFT"],
                "    ld hl,0", "    ld (#%04X),hl" % self.s["COST_ACC"],
                # pace_wait NO LONGER returns when the budget is gone -- it
                # waits anyway, which is the whole point of the fix.  A bench
                # loop must not wait, so it is stubbed to RET for the run.
                "    ld a,#C9", "    ld (#%04X),a" % self.s["PACE_WAIT"]]

    def bench(self, target=None, nops=0, us=600000, min_n=MIN_N):
        """-> us per call, loop overhead removed.

        RUNS UNTIL THE COUNTER IS BIG ENOUGH, which is not a refinement.
        The reading is (elapsed / n), so its resolution is 1/n: a fixed
        600 ms window gives n = 65 on bg_fill (1.5%) but n = 17 on
        raster_paced, because raster_paced is 35 ms a call.  1/17 is 6%,
        which on a 35 ms unit is +-2000 us -- and MEASURED, that is
        exactly what it looked like: three states with quite different
        quad lists all read an identical 35279.1 us, because they all
        landed on the same integer n.  A per-unit bound checked at that
        resolution reports whatever the quantisation feels like, and it
        reported raster_paced 1227 us UNDER its charge at one state and
        3681 us OVER at another.

        So the window grows until n reaches min_n.  The counter is not
        reset between runs and run_us returns the time it really ran, so
        the extra passes accumulate into the same average.
        """
        body = ["    ld hl,0", "    ld (cnt),hl", "lp  ld hl,(cnt)",
                "    inc hl", "    ld (cnt),hl"]
        if target is not None:
            body.append("    call #%04X" % target)
        body += ["    nop"] * nops + ["    jr lp", "cnt dw 0"]
        blob = self._asm("pfbench", self._head() + body)
        self.c.write_ram(BASE, blob)
        self.c.set_pc(BASE)
        self.c.run_us(6000)
        ca = BASE + len(blob) - 2
        self.c.write_ram(ca, b"\x00\x00")
        t, n = 0, 0
        for _ in range(64):
            t += self.c.run_us(us)
            n = struct.unpack("<H", self.c.read_ram(ca, 2))[0]
            if n >= min_n or n >= 50000:
                break
            # ...ask for the rest in one go rather than creeping up on it
            us = max(us, int(us * (min_n - n) / max(n, 1)) + us)
            us = min(us, 40000000)
        if not 0 < n < 60000:
            raise RuntimeError("counter unusable: %d" % n)
        self.last_n = n
        return (t / 4.0) / n - self.ovh

    def once(self, *targets):
        """Run the targets ONCE and stop, so the counters they leave are a
        whole pass and not a bench loop caught in the middle of one."""
        blob = self._asm("pfonce", self._head()
                         + ["    call #%04X" % t for t in targets]
                         + ["spin jr spin"])
        self.c.write_ram(BASE, blob)
        self.c.set_pc(BASE)
        self.c.run_us(400000)

    def place(self, px, py, a):
        self.c.write_ram(self.s["PLR_X"], struct.pack("<H", px))
        self.c.write_ram(self.s["PLR_Y"], struct.pack("<H", py))
        self.c.poke(self.s["PLR_A"], a)


def nclip_of(solid, px, py, a):
    """How many clip lerps proj_face pays for over the whole frame -- the
    thing (pf_nclip) counts, taken from the bit-exact model."""
    import marchmodel as mm
    n = [0]
    real = pm.lerp

    def counting(*args):
        n[0] += 1
        return real(*args)
    pm.lerp = counting
    try:
        r = mm.march(solid, px, py, a)
        ipx, ipy = px >> 8, py >> 8
        for (wx, wy, fd, _door, _k), v in zip(r["faces"], r["fviews"]):
            (ax, ay), _b, _nn = pm.face_endpoints(wx, wy, fd)
            pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
        return n[0]
    finally:
        pm.lerp = real


def _col_charge(quads):
    """THE COLUMN RENDERER'S charge for a whole frame's quad list.

    It is not per quad -- what a face costs depends on what the nearer
    faces have already covered -- so unlike quad_cost it cannot be summed
    quad by quad.  colmodel.charge walks the list once, front to back,
    exactly as rastcol.asm does."""
    import colmodel as _cm
    import rastermodel as _rm
    return _cm.charge(quads, _rm.cfg(), P.C_CFRAME, P.C_CFACE, P.C_CSKIP,
                      P.C_COLS, P.C_CBAND, P.C_COLR, P.C_CEDGE, P.C_CSTEP, c_cfar=P.C_CFAR)


def qparts(quads, cyh):
    return [(abs(bhi - blo),
             cyh if hlo >= cyh * 16 else (hlo >> 4),
             min(cyh, hhi >> 4)) for (blo, bhi, hlo, hhi, _kind, _k) in quads]


def main(nstates=40, pick="random"):
    rig = Rig()
    rig.ovh = rig.bench(None)
    cal = rig.bench(None, nops=100)
    print("=== timing method: empty loop %.2f us, +100 NOPs calibrates to "
          "%.2f us" % (rig.ovh, cal))
    cyh = rm.cfg().CYH
    _grid, msolid = ef.load()
    rnd = random.Random(4242)
    import emu_pace as ep
    offs = ep.lattice_offsets()     # the 24/256 movement lattice, not 32/256
    if pick == "worst":
        # THE STATES THE OFFLINE REPLAY SAYS ARE THE MOST EXPENSIVE, not a
        # uniform sample of the lattice.  A random 40 out of 4 million
        # will not contain the worst frame in the maze, and the worst
        # frame is the only one the slack figure is about.
        #
        # engine2/tools/pacescan.py leaves the EXHAUSTIVE top forty in
        # engine2/build/pacescan_top.json -- the most expensive states
        # there are, not the most expensive ones a scan happened to see.
        # Fall back to emu_pace3's sampled search if it has not been run.
        top = os.path.join(SCRATCH, "pacescan_top.json")
        if os.path.exists(top):
            rows_top = json.load(open(top))
            states = [(px, py, a) for _c, px, py, a in rows_top][:nstates]
            print("=== the %d most expensive states in the maze, from "
                  "pacescan.py's\n    exhaustive pass over all 4055040 "
                  "of them" % len(states))
        else:
            import emu_pace3 as ep3
            states, _h, _s = ep3.model_worst(nstates,
                                             max(20000, 200 * nstates))
            print("=== the %d states a SAMPLED replay charges the most "
                  "(run pacescan.py\n    for the exhaustive list)"
                  % len(states))
    else:
        pool = [((cx << 8) | ox, (cy << 8) | oy, a)
                for cy in range(16) for cx in range(16) for ox in offs
                for oy in offs for a in range(72)
                if ep.reachable(rig.solid, (cx << 8) | ox, (cy << 8) | oy)]
        states = rnd.sample(pool, nstates)
    rows = []
    print("%-20s %4s %4s %4s %4s %7s %7s %7s %7s %8s"
          % ("state", "cell", "face", "quad", "clip", "bg", "march", "proj",
             "rast", "sum ms"))
    for (px, py, a) in states:
        rig.place(px, py, a)
        rig.once(rig.s["MARCH"], rig.s["PROJECT_ALL"])
        vis = rig.c.peek(rig.s["M_VISITED"])
        nq = rig.c.peek(rig.s["FG_NQUAD"])
        nface = sum(rig.c.read_ram(FTAB_BPTR, 8)) // 16
        raw = rig.c.read_ram(QUADS, 8 * nq)
        # the WHOLE record, kind and k included: the rasteriser's charge is
        # now replayed chunk by chunk out of pacemodel.quad_units, which
        # walks the Bresenham and needs every field
        quads = [(raw[8 * i], raw[8 * i + 1])
                 + struct.unpack("<2H", raw[8 * i + 2:8 * i + 6])
                 + (raw[8 * i + 6], raw[8 * i + 7])
                 for i in range(nq)]
        bg = rig.bench(rig.s["BG_FILL"])
        mar = rig.bench(rig.s["MARCH"])
        rig.once(rig.s["MARCH"])            # the bench above stopped the
        prj = rig.bench(rig.s["PROJECT_ALL"])   # flood; refill the buckets
        rig.once(rig.s["MARCH"], rig.s["PROJECT_ALL"])
        ras = rig.bench(rig.s["RASTER_PACED"])
        nclip = nclip_of(msolid, px, py, a)
        rows.append(dict(px=px, py=py, a=a, vis=vis, nq=nq, nrej=nface - nq,
                         nclip=nclip, per=qparts(quads, cyh),
                         # ...AND THAT FACE'S JOINTS.  `rast` below benches
                         # RASTER_PACED, which at COURSES 1 calls
                         # raster_joint after every quad, so a charge built
                         # from quad_cost alone is being held against a
                         # measurement that contains work it never counted
                         # -- the raster_paced row of the one-sided table
                         # would read *** UNDER *** for a disc whose
                         # accumulator is in fact charging C_JOINT.  Same
                         # omission pacemodel.units() had.
                         qc=(sum(_col_charge(quads))
                             if P.VPCOL else
                             sum(P.quad_cost(q) + sum(P.joint_units(q))
                                 for q in quads)),
                         nchunk=(len(_col_charge(quads)) if P.VPCOL else
                                 sum(len(P.quad_units(q))
                                     + len(P.joint_units(q))
                                     for q in quads)),
                         bg=bg, march=mar, proj=prj, rast=ras))
        print("(%04X,%04X)a%2d %5d %4d %4d %4d %7.0f %7.0f %7.0f %7.0f %8.2f"
              % (px, py, a, vis, nface, nq, nclip, bg, mar, prj, ras,
                 (bg + mar + prj + ras) / 1000.0))
    hud = rig.bench(rig.s["HUD_UPDATE"])
    game = rig.bench(rig.s["GAME_STEP"])
    flip = rig.bench(rig.s["FLIP"])
    # THE WEAPON, CHARGED BLOCK AND ALL.  gun_paced is `ld bc,C_GUN /
    # cost_unit / gun_step / gun_draw`, i.e. exactly what the frame runs,
    # so C_GUN is one-sided against the same thing every other C_* is.
    #
    # IT HAS TO BE BENCHED IN TWO PIECES, AND THAT IS NOT A SHORTCUT.  The
    # blit's cost now depends on where the bob is -- the sprite is
    # anchored below the bottom edge and the clamp draws GUN_ROWS0 rows at
    # the bottom of the swing and GUN_H at the top, a 726 us spread -- but
    # gun_paced CALLS gun_step, which walks the bob on every iteration of
    # the bench loop.  So benching gun_paced whole cannot hold the offset
    # still: whatever dy is poked in, a few hundred iterations later the
    # reading is the MEAN over the bob cycle, which is what it silently
    # was (4004.5 us against a true worst of 4183.9).  A mean is not a
    # bound.
    #
    # So: bench gun_paced with gun_step stubbed to RET, which pins dy and
    # gives hook + gun_draw at the offset asked for, sweep that over the
    # whole biased range, and add gun_step's own WALKING cost measured on
    # its own.  The sum is exactly max over dy of (hook + gun_step +
    # gun_draw at dy), which is the worst the frame can run -- every term
    # measured, nothing modelled.
    gun = 0.0
    if P.GUN:
        import gunart
        rig.c.poke(rig.s["PLR_MOVING"], 1)
        gstep = rig.bench(rig.s["GUN_STEP"])        # the walking branch
        save = rig.c.read_ram(rig.s["GUN_STEP"], 1)
        rig.c.poke(rig.s["GUN_STEP"], 0xC9)         # RET: pin the bob
        # dy only.  emu_gun.py measures all 45 offsets and gun_draw reads
        # the same microsecond for every dx at a given dy -- the
        # horizontal bob shifts the run, it does not change how many rows
        # are drawn or how many cross a character boundary -- so the nine
        # dy are the whole spread and the other 36 benches are minutes of
        # nothing.
        worst_dy = 0
        for dy in range(0, 2 * gunart.BOB_VA + 1):
            rig.c.poke(rig.s["GUN_DX"], gunart.BOB_HA)
            rig.c.poke(rig.s["GUN_DY"], dy)
            us = rig.bench(rig.s["GUN_PACED"]) + gstep
            if us > gun:
                gun, worst_dy = us, dy
        rig.c.write_ram(rig.s["GUN_STEP"], save)
        print("\ngun_paced (hook + gun_step walking + gun_draw) WORST over "
              "dy %+d..%+d\n  %.1f us at dy = %+d (of which gun_step %.1f), "
              "charged %d -- margin %+.1f"
              % (-gunart.BOB_VA, gunart.BOB_VA, gun,
                 worst_dy - gunart.BOB_VA, gstep, P.C_GUN, P.C_GUN - gun))
    print("\nhud_update (needle unmoved) %.0f us, game_step %.0f us, "
          "flip %.0f us" % (hud, game, flip))
    print("  (hud_update with the needle MOVED is 1360 us -- emu_hud.py; a"
          " bench loop\n   only ever pays it once, so C_HUD comes from"
          " there)")

    # ---- the fits ----------------------------------------------------
    print("\n=== LEAST SQUARES against the Z80's own counters")
    co, rms, r2, _w = ef.lstsq([[1.0, float(r["vis"])] for r in rows],
                               [r["march"] for r in rows])
    print("  march = %.0f + %.1f*cells                     R^2 %.4f "
          "rms %.0f" % (co[0], co[1], r2, rms))
    try:
        co, rms, r2, _w = ef.lstsq(
            [[float(r["nq"]), float(r["nrej"]), float(r["nclip"])]
             for r in rows],
            [r["proj"] for r in rows])
    except ZeroDivisionError:
        # a state list where every frame has the same face mix makes the
        # projector's three regressors collinear.  The fit is a diagnostic;
        # the ONE-SIDED table below is the test, so do not lose it to this.
        co, rms, r2 = (0.0, 0.0, 0.0), 0.0, 0.0
    print("  proj  = %.0f*quad + %.0f*rejected + %.0f*clip    R^2 %.4f "
          "rms %.0f" % (co[0], co[1], co[2], r2, rms))
    co, rms, r2, _w = ef.lstsq(
        [[float(len(r["per"])), float(sum(j for _, j, _ in r["per"])),
          float(sum(h - j for _, j, h in r["per"])),
          float(sum(b * (j + h) for b, j, h in r["per"]))] for r in rows],
        [r["rast"] for r in rows])
    print("  rast  = %.0f*quad + %.2f*jlo + %.2f*wl2 + %.4f*bw*(jlo+jhi)"
          "   R^2 %.4f rms %.0f" % (co[0], co[1], co[2], co[3], r2, rms))

    # ---- and the check that matters ----------------------------------
    def est(r):
        return (P.C_BG + P.C_MSETUP + P.C_CELL * r["vis"]
                + P.C_FACE * r["nq"] + P.C_REJ * r["nrej"]
                + P.C_CLIP * r["nclip"]
                + r["qc"]
                + P.C_HUD + (P.C_GUN if P.GUN and P.GUN_CHARGED else 0)
                + P.C_TAIL)

    # THE TAIL IS NOT CHECKED HERE.  `game` above is game_step benched with
    # NOTHING HELD, which is 656 us; a game_step that turns and walks costs
    # 1120 and one that opens a door 1463, and this loop cannot hold a key
    # without the player walking off the state it is measuring.  That is
    # what engine2/tools/emu_holes.py is for -- it pins the player and holds
    # real keys -- and it is what C_TAIL and C_DOORACT are fitted to.  The
    # columns below are therefore about the RENDER constants; take the tail
    # figures from emu_holes.py.
    def act(r):
        return (r["bg"] + r["march"] + r["proj"] + r["rast"] + 1360
                + gun + game + flip)
    # ---- PER UNIT, which is the invariant the pacing actually rests on --
    #  A frame total that over-predicts proves nothing about a unit: when
    #  the viewport was widened to 44 bytes, C_BG stayed at 8600 against a
    #  measured 9215.8 -- 616 us UNDER -- and the frame total still read
    #  "never under the truth" because march and the projector were over
    #  by more than bg_fill was under.  An interval, though, is bounded by
    #  the units inside IT, so a unit that under-charges can spill an
    #  interval that the frame total says has room.  Each unit is
    #  therefore checked on its own.
    print("\n=== EVERY UNIT A ONE-SIDED UPPER BOUND (charge - measured)")
    units = [("bg_fill", lambda r: P.C_BG, lambda r: r["bg"]),
             ("march", lambda r: P.C_MSETUP + P.C_CELL * r["vis"],
              lambda r: r["march"]),
             ("project_all", lambda r: (P.C_FACE * r["nq"]
                                        + P.C_REJ * r["nrej"]
                                        + P.C_CLIP * r["nclip"]),
              lambda r: r["proj"]),
             ("raster_paced", lambda r: r["qc"], lambda r: r["rast"])]
    units_ok = True
    for name, ch, me in units:
        dd = [ch(r) - me(r) for r in rows]
        good = min(dd) > 0
        units_ok &= good
        print("  %-13s charge - measured  min %+8.1f  max %+8.1f   %s"
              % (name, min(dd), max(dd), "OK" if good else "*** UNDER ***"))

    d = [est(r) - act(r) for r in rows]
    w = max(rows, key=act)
    print("\n=== WHAT main3.asm ACTUALLY CHARGES, against what it costs")
    print("  estimate - actual:  min %+.0f us  max %+.0f us  ratio %.4f"
          % (min(d), max(d), sum(est(r) for r in rows)
             / sum(act(r) for r in rows)))
    print("  worst frame measured %.2f ms, charged %.2f ms"
          % (act(w) / 1000, est(w) / 1000))
    print("  budget %d x %d = %.2f ms"
          % (P.PACE_FRAMES, P.THRESH, P.PACE_FRAMES * P.THRESH / 1000.0))
    # ...and the SLACK, which is against the PERIOD and not the threshold:
    # the threshold is the yield rule's, the period is the wall clock the
    # frame has to fit inside.  `game` here is game_step with NOTHING
    # HELD; emu_holes.py measures the tail with keys down and that is the
    # number to quote, so the tail is added back at C_TAIL, the constant
    # fitted to it, which is an upper bound on it.
    per = P.PACE_FRAMES * 19.968
    work = (act(w) - game - flip + P.C_TAIL) / 1000.0
    print("  WORST FRAME %.2f ms (tail charged at C_TAIL = %d us) against a "
          "period of\n  %d x 19.968 = %.2f ms -- SLACK %.2f ms"
          % (work, P.C_TAIL, P.PACE_FRAMES, per, per - work))
    print("  ESTIMATE NEVER UNDER THE TRUTH: %s" % (min(d) > 0))
    if P.GUN:
        print("  ...and the weapon is inside both columns above: %.2f ms of"
              " the frame,\n     charged %.2f" % (gun / 1000, P.C_GUN / 1000))
    json.dump(rows, open(os.path.join(SCRATCH, "pacefit.json"), "w"))
    ok = (units_ok and min(d) > 0
          and (not (P.GUN and P.GUN_CHARGED) or gun < P.C_GUN))
    return 0 if ok else 1


if __name__ == "__main__":
    _a = sys.argv[1:]
    _pick = "worst" if "worst" in _a else "random"
    _n = int([x for x in _a if x.isdigit()][0]) if any(
        x.isdigit() for x in _a) else 40
    raise SystemExit(main(_n, _pick))
