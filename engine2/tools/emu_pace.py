"""MEASURE the frame PERIOD of build/amaze.dsk, exactly, per vsync.

    python3 engine2/tools/emu_pace.py [nstates]     the state sweep
    python3 engine2/tools/emu_pace.py walk          walking speed, held UP

WHY NOT AN AVERAGE.  emu_fps.py counts (frame_ctr) over 200 CPC frames and
divides, which hides everything: a run of 80 ms frames with one 140 ms
frame in it averages to 85 and looks locked.  This samples (frame_ctr)
FIVE TIMES PER VSYNC and reports the gap between each pair of successive
increments on its own, so a single long frame anywhere in the run shows up
as its own entry in the histogram.  "Locked" here means every gap of every
state was the same number of vsyncs -- nothing weaker.

Five samples per vsync, not one, because the increment happens at the top
of main_loop, ~0.7 ms after the flip, i.e. at a fixed but ARBITRARY phase
inside the period: sampled once per vsync it sits right on a sample
boundary for some states and gets read one sample early, which reads out
as a 4-vsync frame that never happened.  At 4 ms a sample a 5-vsync period
is 24.96 samples against a 4-vsync one's 19.97 and the two cannot be
confused.
"""

import collections
import addrs
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

from cpc import CPC                                          # noqa: E402
import bootdisc                                              # noqa: E402
import cpc as cpcmod                                         # noqa: E402

DSK = os.path.join(_ROOT, "build", "amaze.dsk")
SYM = os.path.join(_ROOT, "build", "e3", "game3.sym")
SOLID = addrs.SOLID
DOORTAB = addrs.DOORTAB         # door_idx / door_st / door_tg, MAXDOORS each
VSYNC_MS = 19.968                       # 312 lines x 64 us
# HOW OFTEN THE PERIOD IS SAMPLED, and the resolution every tolerance
# below is derived from.  One number, because a tolerance written as a
# literal goes stale the moment the period moves -- which is what `0.6`
# did when PACE_FRAMES went to 10.
SAMPLE_US = 250

# game.asm's, read from the source: place() restores it -- see there.
PLR_HPMAX = int([l.split()[2] for l in open(os.path.join(_E2, "src",
                                                         "game.asm"))
                 if l.startswith("PLR_HPMAX")][0])


def _maze_equ(name):
    return int([l.split()[2] for l in open(os.path.join(_E2, "src",
                                                        "gen_maze.inc"))
                if l.startswith(name + " ")][0])


# THE WAY OUT, AND WHY A PACING SWEEP HAS TO KNOW WHERE IT IS.  Stand on
# this cell and game_step returns 2, main_loop leaves for player_won, and
# the win screen paints itself over the map -- see Rig.place().  There is
# no steady-state frame on the exit to measure, so the sweep keeps off
# it, and says so rather than quietly sampling around it.
EXIT_X, EXIT_Y = _maze_equ("EXIT_X"), _maze_equ("EXIT_Y")

# main3.asm's PACE_FRAMES, read from the source so this file cannot drift
# from the disc it is measuring.
PACE_N = int([l.split()[2] for l in open(os.path.join(_E2, "src",
                                                      "main3.asm"))
              if l.startswith("PACE_FRAMES equ")][0])

# The six states the old four-chunk pad held at a steady 140 ms, as
# (cell x, cell y, heading).  They are the reason this file exists.
OUTLIERS = [(14, 7, 48), (14, 6, 24), (14, 1, 24),
            (1, 5, 12), (1, 9, 12), (1, 13, 68)]

# ...and the five the cost accumulator held OFF THE VSYNC GRID entirely,
# back when pace_wait returned instead of waiting once the budget was
# spent: 109.2-110.5 ms (5.47 periods) and 119.8 ms where everything else
# was 99.84.  Full (plr_x, plr_y, heading), because the whole point is
# that they are not on a whole-cell centre.
OFFGRID = [(0x0160, 0x0DE0, 69), (0x0160, 0x0DE0, 67),
           (0x0150, 0x0DF0, 67), (0x0AC8, 0x0588, 7),
           (0x0E88, 0x0AE0, 48)]

# ...and the states the WEAPON spilled, back when gun_step and gun_draw
# were charged to nobody.  Each of these is internally CONSTANT -- it sits
# at a rock-steady 139.8 ms -- which is why the check below has to compare
# every state against PACE_N and not merely against itself: a state that
# is reliably one period late passes "internally constant" and passes "on
# the vsync grid", and the old sweep would only have seen it as a second
# bar in the histogram.  MEASURED with main3.asm's GUN_CHARGED at 0.
#     (0x0652, 0x0262, 6)    steady 139.8 ms
#     (0x0378, 0x0740, 39)   steady 139.8 ms
# Both were found by HOLDING KEYS, not by the lattice sample -- neither is
# on a whole-cell centre -- and both read 6 vsyncs again the moment C_GUN
# is charged.  They are named here so the fix is checked on the states
# that actually broke, every run, and not only by a random sample.
SPILL = [(0x0652, 0x0262, 6), (0x0378, 0x0740, 39)]

# ...and the states the weapon USED TO spill on.  THIS LIST IS CLOSED AND
# IT IS KEPT, which is the point of it.
#
# The 28x46 sprite cost 3425-4152 us depending on where the bob was, so
# C_GUN had to be 4500 to stay a one-sided bound, and at 4500 pacescan.py
# named exactly these 28 states of 4055040 as asking for a 6th wait --
# 26 of which then measured a rock-steady 139.8 ms on the booted disc
# while 600 uniformly sampled states on the SAME disc all read 119.81.
#
# The art is 28x38 again, the bench reads 3307.7 us worst, C_GUN is 3400,
# and C_QUAD was RE-SEARCHED against that: 780/22 is the largest charge
# with zero over-budget states over all 4055040.  So these 28 are no
# longer over budget -- and they are still the 28 heaviest packers in the
# maze, so they stay here as the seed that proves it.  A uniform sample
# cannot find 28 states in four million; only naming them can.  If any of
# them ever reads 139.8 again, the search has to be re-run -- NOT C_GUN
# lowered, which is the failure GUN_CHARGED exists to document.
OVERBUDGET = [(0x0140, 0x0DE0, 68), (0x0140, 0x0500, 15),
              (0x0140, 0x0508, 15), (0x0140, 0x0510, 15),
              (0x0758, 0x06F8, 56), (0x0750, 0x06F8, 56),
              (0x0760, 0x06F0, 55), (0x0760, 0x06E8, 55),
              (0x0770, 0x06F8, 55), (0x0768, 0x06E0, 55),
              (0x0770, 0x06F0, 55), (0x0768, 0x06E8, 55),
              (0x0768, 0x06F0, 55), (0x0750, 0x06E0, 56),
              (0x0748, 0x06F0, 56), (0x0748, 0x06E8, 56),
              (0x0750, 0x06E8, 56), (0x0768, 0x06F8, 55),
              (0x0748, 0x06E0, 56), (0x0750, 0x06F0, 56),
              (0x0740, 0x06F0, 56), (0x0740, 0x06E8, 56),
              (0x0150, 0x0DD0, 68), (0x0760, 0x06F8, 55),
              (0x0758, 0x06F8, 55), (0x0148, 0x0DE0, 68)]


def lattice_offsets():
    """THE SUB-CELL OFFSETS A WALKING PLAYER CAN ACTUALLY LAND ON.

    This is the lattice the previous version of this sweep got wrong, and
    getting it wrong is why it reported 100.00% locked while five
    reachable states sat at 109.2 and 119.8 ms.  It sampled offsets at
    multiples of 32/256; the movement STEP is 24/256 of a cell per game
    frame (game.asm), so walking lands on 128 + 24k (mod 256) and their
    wrap, and gcd(24,256) = 8 closes that on every multiple of 8.  A
    32/256 grid meets that set only at four of its thirty-two points."""
    return sorted(set((128 + 24 * k) % 256 for k in range(64)))


def syms():
    out = {}
    for line in open(SYM):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            out[p[0].upper()] = int(p[1][1:], 16)
    return out


class Rig:
    def __init__(self):
        self.s = syms()
        self.c = CPC()
        self.c.insert_disc(DSK)
        self.c.run_frames(150)
        self.c.type_text('RUN"DISC\n')
        self.c.run_frames(500)
        bootdisc.start(self.c)   # past the title screen -- see bootdisc.py
        # THE BOOT MAP, AND IT IS NOW TWO JOBS.  It has always been the
        # map `reachable()` picks states against; place() also writes it
        # BACK now, because the end screens paint over the live one.
        self.solid = self.c.read_ram(SOLID, 256)
        # ...AND THE DOOR TABLES WITH IT, or the two disagree.  SOLID is
        # where a door's passability lives, but door_st / door_tg are the
        # animation state and they are at #3DC0, past the 739 bytes the
        # menu writes -- so they SURVIVE a win screen that eats the map.
        # Putting back a shut SOLID under a door_st that still says OPEN
        # would be a fresh inconsistency of my own making, in exchange
        # for fixing someone else's.  Both, or neither.
        self.doortab = self.c.read_ram(DOORTAB, 3 * addrs.MAXDOORS)
        self.door_n = self.c.peek(self.s["DOOR_N"])
        self.door_anim = self.c.peek(self.s["DOOR_ANIM"])
        self.nended = 0                 # walk steps that ended the level
        self._stub()

    # ---- DI / LD SP,#3FF0 / JP main_loop.  See place() for what it is for.
    #
    #  IT IS WRITTEN BEFORE EVERY JUMP, AND IT USED TO BE WRITTEN ONCE.
    #  #39C0 is not free RAM, which is what the comment here claimed: it is
    #  inside march.asm's FTAB, `equ #3900`, 256 bytes of L1 tables and
    #  bucket write pointers that the march refills EVERY FRAME.  So the
    #  stub survived until the flood happened to reach that far and then
    #  set_pc jumped into whatever the march had left there.
    #
    #  MEASURED: the FIRST place() works and the SECOND hangs the machine
    #  -- frame_ctr stops advancing, 0 game frames in 30 CPC frames, on
    #  every state tried.  emu_verify3.py has always rewritten the bytes
    #  each time and that is exactly why it never saw this.
    #
    #  Seven bytes a teleport is nothing, and it is correct whoever
    #  overwrites the address in between.
    def _stub(self):
        self.c.write_ram(0x39C0, bytes([0xF3, 0x31, 0xF0, 0x3F, 0xC3])
                         + struct.pack("<H", self.s["MAIN_LOOP"]))

    def ctr(self):
        """(frame_ctr) LOW BYTE ONLY -- and that is not an optimisation.

        main3.asm bumps the counter with `ld hl,(frame_ctr) / inc hl /
        ld (frame_ctr),hl`, and LD (nn),HL stores L and then H in two
        separate memory cycles.  Read the sixteen bits from outside and
        the read can land BETWEEN those two writes.  Nothing happens on
        255 frames out of 256, because only L changes; on the frame the
        low byte WRAPS, the pair reads 02FF -> 0200, a delta of 0xFF01,
        and periods() divides by the delta -- so the period comes out as
        0.0000 ms, followed by 0.0010 ms when H catches up.

        MEASURED, not deduced: seed the counter at 02FF and single-step
        the running game a microsecond at a time and both readings appear,
        in that order.  They are what put a "0 vsyncs" bar in a sweep of
        9464 frames and reported a state as unlocked; a frame drawn in
        zero milliseconds is not a cadence defect, it is a torn read.

        A one-byte read cannot tear, the period is 120 ms against a 250 us
        sample so the delta is always 1, and 256 frames is far more than
        any run here needs."""
        return self.c.peek(self.s["FRAME_CTR"])

    def place(self, px, py, a, settle=None):
        """Teleport the player and RESTART the main loop.

        Writing (plr_x) while the game is running is not safe and the
        restart is not cosmetic: the march reads the player's cell again,
        after march_setup has already seeded the frustum from the old one,
        so a write that lands between the two gives the flood a seed and a
        position that disagree.  It then walks far past the seven cells it
        is bounded by and overruns the 128-entry flood stack into the face
        buckets and the code below them.  MEASURED: one run in eighty
        teleports ended with the Z80 executing the back buffer.  A real
        player never teleports, so this is the harness's problem and the
        harness fixes it -- jump to the stub above, which resets SP and
        re-enters main_loop, and no frame ever sees a torn position.

        SETTLE IS IN GAME FRAMES NOW, AND IT USED TO BE 14 CPC FRAMES.
        The jump ABANDONS a frame in flight, so (cost_acc) still holds
        whatever that frame had accumulated and the restarted frame adds
        C_TAIL + C_SND on top of it.  A frame that starts with a full
        accumulator yields early and can honestly need one extra period
        -- once, at the teleport, for a state that is nowhere near its
        budget the rest of the time.

        14 CPC frames is 1.4 game frames at PACE_FRAMES 10.  The constant
        never moved when the period did.  MEASURED: `emu_pace.py 600`
        reported 3 frames of 4800 at 11 vsyncs and named three states;
        each of those three, on a FRESH BOOT, reads [10] over 12 frames,
        and pacescan's replay puts all three at 7-8 waits against a
        9-wait budget.  The 11s were the harness looking at its own
        teleport.

        3 * PACE_N is three whole game frames, so nothing sampled is the
        first frame after the jump."""
        if settle is None:
            settle = 3 * PACE_N
        # ---- AND PUT THE PLAYER BACK ON HIS FEET.  The monster hunts
        # now and bites every MON_RATE frames once it is next to you, so
        # a sweep of 600 states x 8 frames kills the player part way
        # through -- and the death screen STOPS THE FRAME LOOP, which is
        # what this file measures.  MEASURED: the sweep collected 72 game
        # frames instead of 4800 and emu_pace3 146 instead of 10184.
        #
        # The monster is left ON the map on purpose: mon_draw is real
        # work in a real frame and taking it off would measure a frame
        # the disc does not draw.  Only the consequence is undone, and
        # only at a teleport, which is not something a player does
        # anyway.  Same discipline as emu_holes.py's preludes.
        self.c.poke(self.s["PLR_HP"], PLR_HPMAX)
        # ---- ...AND PUT THE MAP BACK, BECAUSE THE END SCREENS EAT IT.
        #
        # THIS IS THE SAME BUG AS THE HP LINE ABOVE AND IT WAS ONLY HALF
        # FIXED.  `MENUBUF equ SOLID` (menu.asm:44): painting menu_win or
        # menu_dead LDIRs MN_BLOB = 739 bytes straight over the live map,
        # the flood's MARK array and the front of the quad list.  The
        # GAME survives that because player_won / player_died jump to
        # new_game, which rebuilds the world -- but THIS HARNESS re-enters
        # at main_loop, below new_game, so the rebuild never runs and
        # every frame from the first win onward marches a map made out of
        # the menu's pen tables.
        #
        # MEASURED, on the disc, one line of evidence each:
        #   * walked(90)'s step 5 starts on EXIT_CELL (13,1) and wins.
        #     85 of its 90 steps end with (nl_screen) != menu_show.  So
        #     the map is already destroyed before the first MEASURED
        #     state, deterministically, at seed 11.
        #   * SOLID differs from its boot copy in 214 of 256 bytes after
        #     that prelude; solid cells go 112 -> 211.
        #   * The states the sweep then reports as 24, 34, 46 vsyncs read
        #     a locked 10 on a fresh boot.  Three of the twelve it named
        #     decode to positions INSIDE WALL CELLS.
        #   * Restore SOLID alone and leave (nl_screen) at menu_win: all
        #     14 states go back to 10 vsyncs.  Restore (nl_screen) alone
        #     and leave the map: byte-identical failure.  So it is the
        #     MAP, not the screen -- the frame loop never actually
        #     leaves, it just floods garbage.
        #   * The whole sweep, with only this undone: 4800 game frames of
        #     4800 at 10 vsyncs, LOCKED: True, against 448 frames and 62
        #     bad states as-is.
        #
        # THE MAP AND THE DOORS, NOT ALL 739 BYTES.  SOLID is static
        # map data -- the
        # doors are the only thing that writes it in play -- so putting
        # the boot copy back is defined and it is also what makes the
        # measured map agree with `self.solid`, which is the map the
        # state pool was chosen against.  MARK and the quad list are in
        # the blob too and they are rebuilt every frame, which is why
        # restoring 256 bytes was measured to be sufficient; restoring
        # boot-time MARK bytes on top of a generation scheme I have not
        # read would be a new bug in exchange for nothing.
        self.c.write_ram(SOLID, self.solid)
        self.c.write_ram(DOORTAB, self.doortab)
        self.c.poke(self.s["DOOR_N"], self.door_n)
        self.c.poke(self.s["DOOR_ANIM"], self.door_anim)
        self.c.write_ram(self.s["PLR_X"], struct.pack("<H", px))
        self.c.write_ram(self.s["PLR_Y"], struct.pack("<H", py))
        self.c.poke(self.s["PLR_A"], a)
        self._stub()                    # the march may have eaten it
        self.c.set_pc(0x39C0)
        self.c.run_frames(settle)

    def ended(self):
        """Did the level END since the last place() -- won, or died?

        (nl_screen) is main3.asm's pointer to the screen new_game will
        paint.  It is menu_show at boot and player_won / player_died are
        the only things that move it.

        IT IS THE ONLY OUTWARD SIGN, which is what made this expensive to
        find.  main_loop does not call nl_call -- only new_game does --
        and this harness re-enters at main_loop, so a machine that has
        won the level goes on counting frames at a perfectly steady
        cadence.  There is no hang to notice; the frames are just drawn
        from a map that is now the menu's pen tables.
        """
        got = struct.unpack("<H", self.c.read_ram(self.s["NL_SCREEN"], 2))[0]
        return got != self.s["MENU_SHOW"]

    def periods(self, nframes=8, step=SAMPLE_US):
        """-> [RAW MILLISECONDS] between successive (frame_ctr) increments.

        250 us a sample, eighty times per vsync, and the answer is NOT
        rounded to a vsync count.  Both of those matter.  Rounding hides
        the only interesting failure: a frame that free-runs is 109.2 ms,
        which is 5.47 periods, and a sweep that reports vsync counts will
        call that either 5 or 6 and never notice.  And sampling once per
        emulated CPC frame manufactures readings that never happened,
        because the increment sits at a fixed but arbitrary phase inside
        the period."""
        last = self.ctr()
        at, out, i = None, [], 0
        limit = int(nframes * 260000 / step) + 400
        while len(out) < nframes and i < limit:
            self.c.run_us(step)
            i += 1
            n = self.ctr()
            if n != last:
                d = (n - last) & 0xFF
                if at is not None:
                    out.append((i - at) * step / 1000.0 / d)
                at, last = i, n
        return out

    def periods_r12(self, nframes=6, step=SAMPLE_US):
        """The same period off the CRTC R12 flip register -- a SECOND,
        independent observable, so a claim about the cadence does not rest
        on one variable in RAM."""
        last = self.c.crtc_screen_addr
        at, out, i = None, [], 0
        limit = int(nframes * 260000 / step) + 400
        while len(out) < nframes and i < limit:
            self.c.run_us(step)
            i += 1
            n = self.c.crtc_screen_addr
            if n != last:
                if at is not None:
                    out.append((i - at) * step / 1000.0)
                at, last = i, n
        return out

    def walked(self, n=90, seed=11):
        """States reached by ACTUALLY HOLDING KEYS from random starts --
        the only sampler that cannot miss a lattice.

        IT USED TO WALK ONTO THE EXIT AND KEEP GOING.  85 of these 90
        steps ended with the level won, starting at step 5, whose random
        start cell IS the exit -- and the positions it then recorded were
        read off a player walking around a map that the win screen had
        overwritten.  Three of the twelve states the sweep went on to
        name decode to positions INSIDE WALL CELLS, which is the tell.
        place() puts the map back now, so the damage no longer outlives
        one step, but the SAMPLE from a step that ended the level is
        still meaningless and is dropped here.
        """
        import random
        rnd = random.Random(seed)
        pool = [((cx << 8) | 128, (cy << 8) | 128, a)
                for cy in range(16) for cx in range(16)
                for a in range(0, 72, 3)
                if reachable(self.solid, (cx << 8) | 128, (cy << 8) | 128)
                and (cx, cy) != (EXIT_X, EXIT_Y)]
        out = []
        self.nended = 0
        for _ in range(n):
            px, py, a = rnd.choice(pool)
            self.place(px, py, a, settle=10)
            k = rnd.choice([cpcmod.KEY_UP, cpcmod.KEY_DOWN])
            self.c.key_down(k)
            self.c.run_frames(rnd.randint(3, 40))
            self.c.key_up(k)
            if rnd.random() < 0.5:
                k2 = rnd.choice([cpcmod.KEY_LEFT, cpcmod.KEY_RIGHT])
                self.c.key_down(k2)
                self.c.run_frames(rnd.randint(2, 20))
                self.c.key_up(k2)
            self.c.run_frames(4)
            if self.ended():
                self.nended += 1        # walked onto the exit; see above
                continue
            out.append((
                struct.unpack("<H", self.c.read_ram(self.s["PLR_X"], 2))[0],
                struct.unpack("<H", self.c.read_ram(self.s["PLR_Y"], 2))[0],
                self.c.peek(self.s["PLR_A"])))
        return out


def reachable(solid, px, py, rad=64):
    """The player's 0.25-cell collision box clear of every solid cell --
    the same test game.asm's movement makes, so the same state space."""
    cx, cy, fx, fy = px >> 8, py >> 8, px & 255, py & 255
    if solid[cy * 16 + cx]:
        return False
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if not (dx or dy):
                continue
            i, j = cx + dx, cy + dy
            if not (0 <= i < 16 and 0 <= j < 16) or solid[j * 16 + i]:
                ex = 0 if dx == 0 else (fx if dx < 0 else 256 - fx)
                ey = 0 if dy == 0 else (fy if dy < 0 else 256 - fy)
                if ex * ex + ey * ey < rad * rad:
                    return False
    return True


def periods_window_ms(nframes=8, step=SAMPLE_US):
    """How long periods() waits before it gives up, in ms.  Kept next to
    the caller that prints it so the two cannot drift."""
    return (int(nframes * 260000 / step) + 400) * step / 1000.0


def sweep(n=1400, seed=8191, nwalk=90):
    import random
    g = Rig()
    rnd = random.Random(seed)
    offs = lattice_offsets()
    pool = [((cx << 8) | ox, (cy << 8) | oy, a)
            for cy in range(16) for cx in range(16)
            for ox in offs for oy in offs for a in range(72)
            if reachable(g.solid, (cx << 8) | ox, (cy << 8) | oy)
            and (cx, cy) != (EXIT_X, EXIT_Y)]
    named = ([((cx << 8) | 128, (cy << 8) | 128, a) for cx, cy, a in OUTLIERS]
             + list(OFFGRID) + list(SPILL) + list(OVERBUDGET))
    walk_states = g.walked(nwalk)
    states = named + walk_states + rnd.sample(
        pool, max(0, n - len(named) - len(walk_states)))
    print(f"{len(offs)} sub-cell offsets on the 24/256 movement lattice -> "
          f"{len(pool)} reachable states (0.25-cell box x 72 headings), "
          f"exit cell ({EXIT_X},{EXIT_Y}) excluded")
    print(f"MEASURING {len(states)}: {len(named)} named bad states, "
          f"{len(walk_states)} reached by HOLDING KEYS, the rest sampled")
    if g.nended:
        print(f"    ({g.nended} walk steps ended the level and were dropped)")
    print("period read at 250 us and NOT rounded to vsyncs\n")

    hist = collections.Counter()
    bad = []
    # A STATE THAT YIELDS NO PERIODS IS THE WORST RESULT THERE IS, and
    # this used to `continue` past it.  periods() gives up after ~2.18 s
    # of emulated time, so an empty list means the frame loop produced
    # fewer than two counter increments in eleven times the budget: the
    # machine is wedged, or every frame is seconds long.  Dropping those
    # silently meant the WORSE the build, the FEWER states got scored --
    # MEASURED, a run that reported "47 states off" had quietly thrown
    # away 523 of its 600 states, and the "k/n states" progress line sat
    # after the same continue, so its absence was the only hint.
    dead = []
    for k, (px, py, a) in enumerate(states):
        g.place(px, py, a)
        per = g.periods()
        if not per:
            dead.append((px, py, a))
            print(f"  ({px:04X},{py:04X}) a={a:2d}  "
                  f"{'named' if k < len(named) else 'sampled':10s} "
                  f"NO FRAMES IN {periods_window_ms():.0f} ms"
                  f"{'  (LEVEL ENDED)' if g.ended() else ''}")
            continue
        for p in per:
            hist[round(p, 1)] += 1
        grid = all(abs(p / VSYNC_MS - round(p / VSYNC_MS)) < 0.06
                   for p in per)
        # ...INTERNALLY CONSTANT, TO THE SAMPLER'S OWN RESOLUTION.  This
        # was `< 0.6` ms, a constant chosen when the period was ~120 ms
        # and never re-derived.  An interval is measured as a whole number
        # of 250 us samples at each end, so two readings of the SAME
        # period can differ by nearly two samples; MEASURED, a locked
        # 199.68 ms frame reads 199.2 .. 200.0, a spread of 0.8, and 0.6
        # flagged 27 states of 600 as MIXED that were every one of them
        # [10] vsyncs.  Deriving the tolerance from `step` instead of
        # writing a number down means it cannot go stale again -- and it
        # is still far tighter than a whole vsync, which is what `grid`
        # and `onpace` below actually test against.
        same = max(per) - min(per) < 4.0 * SAMPLE_US / 1000.0
        # ...AND ON THE RIGHT MULTIPLE.  A state that spends every frame
        # at 7 vsyncs is on the grid and is internally constant, so the
        # two tests above both pass it -- and that is exactly the shape of
        # the failure an uncharged unit produces.  The period has to be
        # PACE_N, not just steady.
        onpace = all(round(p / VSYNC_MS) == PACE_N for p in per)
        # ...AND THE LEVEL MUST STILL BE RUNNING.  A state that wins or
        # dies inside its own eight frames measured the end screen for
        # part of them; place() puts the map back before the NEXT state,
        # so this no longer poisons the run, but the reading is still
        # not a reading of the renderer.  The pool excludes the exit, so
        # if this ever fires it is a named state or a new way to die.
        if g.ended():
            grid = same = onpace = False
        if k < len(named) or not (grid and same and onpace):
            note = ("" if grid and same and onpace
                    else "  <-- LEVEL ENDED MID-MEASUREMENT" if g.ended()
                    else "  <-- NOT A VSYNC MULTIPLE" if not grid
                    else "  <-- MIXED" if not same
                    else "  <-- %d VSYNCS, NOT %d"
                         % (round(max(per) / VSYNC_MS), PACE_N))
            tag = "named" if k < len(named) else "sampled"
            print(f"  ({px:04X},{py:04X}) a={a:2d}  "
                  f"{tag:10s} ctr {sorted(set(round(p,1) for p in per))} "
                  f"r12 {sorted(set(round(p,1) for p in g.periods_r12()))}"
                  f"{note}")
        if not (grid and same and onpace):
            bad.append((px, py, a, per))
        if k and k % 200 == 0:
            print(f"    {k}/{len(states)} states, "
                  f"{sum(hist.values())} frames so far")

    tot = sum(hist.values())
    print(f"\n=== PERIOD, {tot} game frames over {len(states)} states, "
          f"250 us sampling")
    # Bucket by the NEAREST whole vsync, but keep the raw spread inside
    # each bucket on show: a 250 us sampling grid reads one true 119.808
    # ms period as either 119.75 or 120.00, and that is the sampler, not
    # the machine.  Anything that is not within 6% of a whole vsync is
    # counted separately by `bad` above and cannot land in a bucket.
    vs = collections.defaultdict(list)
    for p, c in hist.items():
        vs[int(round(p / VSYNC_MS))] += [p] * c
    if not tot:
        print("    NO FRAMES AT ALL -- every state was wedged.")
    for v in sorted(vs):
        raw = vs[v]
        # ...AND `v` CAN BE ZERO, WHICH USED TO CRASH THE REPORT.  A torn
        # frame_ctr read (see ctr()) or a genuinely sub-vsync gap buckets
        # to 0 and `1000.0/(v*VSYNC_MS)` raised ZeroDivisionError -- so
        # the sweep died without printing its verdict EXACTLY when the
        # pacing was at its worst.  MEASURED: that is how the run at
        # 6087ec8 ended, on state (0C97,077A) a=69 with a 1.2 ms gap.
        fps = "  n/a" if v == 0 else f"{1000.0/(v*VSYNC_MS):5.2f}"
        print(f"    {v} vsyncs = {v*VSYNC_MS:6.2f} ms = "
              f"{fps} fps   {len(raw):6d}  "
              f"{100.0*len(raw)/tot:6.2f}%   "
              f"(raw {min(raw):.1f}..{max(raw):.1f} ms)")
    locked = (len(vs) == 1 and sorted(vs)[0] == PACE_N
              and not bad and not dead)
    print(f"\n    LOCKED: {locked}"
          + ("" if locked else f"  -- {len(vs)} different periods, "
                               f"{len(bad)} states off {PACE_N} vsyncs, "
                               f"{len(dead)} states with NO frames at all"))
    if bad:
        print(f"    states to name in SPILL / OFFGRID at the head of this "
              f"file ({len(bad)} bad, showing up to 20):")
        for px, py, a, per in bad[:20]:
            print(f"      (0x{px:04X}, 0x{py:04X}, {a}),   "
                  f"{sorted(set(round(p,1) for p in per))} ms")
    if dead:
        print(f"    ...and {len(dead)} states produced NO FRAMES in "
              f"{periods_window_ms():.0f} ms each (showing up to 20):")
        for px, py, a in dead[:20]:
            print(f"      (0x{px:04X}, 0x{py:04X}, {a}),")
    return 0 if locked else 1


MINRUN = 3                      # cells a straight run must have to count


def corridors(g):
    """Two long straight runs of different view cost, as
    (name, start px, start py, heading, axis, sign).

    MINRUN WAS 4 AND THE MAP OUTGREW IT.  The map is nine 4x4 rooms, so
    the longest straight run bounded by a wall is x = 1..4 -- three cells
    BEYOND the start, not four.  This returned an empty list and walk()
    then did `runs[0]`:

        IndexError: list index out of range

    That is not a pacing failure, it is this file asserting nothing about
    a map it cannot describe, and CRASHING rather than saying so.  It had
    been doing it since the rooms became 4x4; `make pace` stopped at
    pacescan long before it reached here, which is the same reason
    emu_holes.py went sixteen commits without running.

    3 is the honest floor for the measurement -- three cells of walking
    is still cells per second -- and walk() now says how many runs it
    found rather than indexing blind.
    """
    solid = g.solid

    def openp(x, y):
        return 0 <= x < 16 and 0 <= y < 16 and not solid[y * 16 + x]
    out = []
    for y in range(16):
        for x in range(16):
            if not openp(x, y):
                continue
            n = 0
            while openp(x + n + 1, y):
                n += 1
            if n >= MINRUN and not openp(x - 1, y):
                out.append((f"east from ({x},{y}), {n} cells",
                            (x << 8) | 128, (y << 8) | 128, 0, "x", n))
    for x in range(16):
        for y in range(16):
            if not openp(x, y):
                continue
            n = 0
            while openp(x, y + n + 1):
                n += 1
            if n >= MINRUN and not openp(x, y - 1):
                out.append((f"south from ({x},{y}), {n} cells",
                            (x << 8) | 128, (y << 8) | 128, 18, "y", n))
    return out


def walk(seconds=4.0):
    """Hold UP in two corridors of different view cost and MEASURE
    cells/s.  This is the thing the player actually feels, and the only
    reason the period has to be constant."""
    g = Rig()
    runs = corridors(g)
    # Rank them by what they cost to DRAW, not by length: the point of the
    # test is that two views of different cost walk at the same speed.
    cost = {}
    for r in runs:
        g.place(r[1], r[2], r[3], settle=12)
        c = (0, 0)
        for _ in range(6):
            g.c.run_frames(2)
            c = max(c, (g.c.peek(g.s["FG_NQUAD"]),
                        g.c.peek(g.s["M_VISITED"])))
        cost[r[0]] = c
    runs.sort(key=lambda r: cost[r[0]])
    picks = [runs[0], runs[len(runs) // 2], runs[-1]]
    nframes = int(round(seconds * 1000.0 / (PACE_N * VSYNC_MS)))
    print(f"holding UP for exactly {nframes} game frames in {len(picks)} "
          f"corridors")
    print("  'cells' and 'quads' are the marched cells and the drawn quads "
          "of the view --\n  the cost the period used to depend on.  The "
          "run is counted in GAME FRAMES,\n  not in a fixed window, so "
          "the seconds below are measured and not assumed.\n")
    print("%-30s %5s %5s %8s %8s %9s %11s" %
          ("corridor", "cells", "quads", "seconds", "cells", "cells/s",
           "cells/frame"))
    res = []
    for name, px, py, a, axis, _n in picks:
        g.place(px, py, a, settle=20)
        cq = cost[name]
        sym = g.s["PLR_X" if axis == "x" else "PLR_Y"]
        g.c.key_down(cpcmod.KEY_UP)
        n0 = g.ctr()                        # sync to a frame boundary
        while g.ctr() == n0:
            g.c.run_us(2000)
        n0 = g.ctr()
        p0 = struct.unpack("<H", g.c.read_ram(sym, 2))[0]
        us = 0
        while ((g.ctr() - n0) & 0xFF) < nframes:      # ctr() is 8-bit; see it
            g.c.run_us(2000)
            us += 2000
        p1 = struct.unpack("<H", g.c.read_ram(sym, 2))[0]
        g.c.key_up(cpcmod.KEY_UP)
        cells = (p1 - p0) / 256.0
        secs = us / 1e6
        print("%-30s %5d %5d %8.4f %8.3f %9.4f %11.5f" %
              (name, cq[1], cq[0], secs, cells, cells / secs,
               cells / nframes))
        res.append(cells / secs)
        g.c.run_frames(10)
    lo, hi = min(res), max(res)
    print(f"\n    spread {hi/lo:.4f}x  ({lo:.4f} .. {hi:.4f} cells/s)")
    return 0


def main():
    a = sys.argv[1] if len(sys.argv) > 1 else "1400"
    if a == "walk":
        return walk()
    return sweep(int(a))


if __name__ == "__main__":
    raise SystemExit(main())
