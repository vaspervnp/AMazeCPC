"""VERIFY build/amaze.dsk on a cycle-accurate CPC 6128, and say why.

    python3 engine2/tools/emu_verify3.py

Boots the real disc through the real BASIC loader and then checks, one
claim per section, reading everything back out of the running machine:

    1  the screen mode is 0
    2  the CRTC display base alternates -- the disc is double buffered
    3  cursor right turns the player, 5 degrees a frame
    4  cursor up moves plr_x / plr_y along the heading
    5  a wall cannot be walked into
    6  SPACE opens a door, and the player can then walk through it
    7  the frame period, measured from (frame_ctr) against CPC frames

Nothing here is modelled: every number is read from RAM or from the CRTC
while the game is running.
"""

import os
import addrs
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import cpc as cpcmod                                         # noqa: E402
from cpc import CPC                                          # noqa: E402
import bootdisc                                              # noqa: E402
import world                                                 # noqa: E402


def a_door():
    """-> (cell index, an OPEN neighbour, the heading that faces it).

    THE DOOR IS FOUND IN THE MAP, NOT WRITTEN DOWN HERE.  This test used
    to hardcode cell (5,3) and stand the player on (4,3).  When the maze
    became twelve rooms joined by doors the door moved to (4,3) and (5,3)
    became plain floor -- so `starts shut` and `SPACE shuts it again`
    both read SOLID = 0 and failed, the player was being placed INSIDE
    the door, and the failure was reported for eight months as "the doors
    are broken" when the doors were fine and the coordinate was stale.
    That is the same class of mistake engine2/tools/addrs.py exists to
    remove, one map further out: never copy a number that the source of
    truth can be asked for.
    """
    grid, _sx, _sy = world.load_maze()
    for y in range(world.MAZE_H):
        for x in range(world.MAZE_W):
            if grid[y][x] != world.DOOR:
                continue
            # stand one cell away, on open floor, looking at the door.
            # heading 0 is +x and the 72 headings are 5 degrees apart.
            for dx, dy, head in ((-1, 0, 0), (1, 0, 36),
                                 (0, -1, 18), (0, 1, 54)):
                nx, ny = x + dx, y + dy
                if (0 <= nx < world.MAZE_W and 0 <= ny < world.MAZE_H
                        and grid[ny][nx] == world.FLOOR):
                    return (y * 16 + x, (x, y), (nx, ny), head)
    raise SystemExit("no door in the maze")


def all_doors():
    """-> every DOOR cell in the map, in SOLID scan order (the order
    game_init registers them in, so a MAXDOORS truncation drops the
    TAIL of this list)."""
    grid, _sx, _sy = world.load_maze()
    return [(x, y) for y in range(world.MAZE_H)
            for x in range(world.MAZE_W) if grid[y][x] == world.DOOR]


def door_neighbour(x, y):
    """-> (nx, ny, heading) standing on open floor, looking at the door."""
    grid, _sx, _sy = world.load_maze()
    for dx, dy, head in ((-1, 0, 0), (1, 0, 36), (0, -1, 18), (0, 1, 54)):
        nx, ny = x + dx, y + dy
        if (0 <= nx < world.MAZE_W and 0 <= ny < world.MAZE_H
                and grid[ny][nx] == world.FLOOR):
            return nx, ny, head
    return None


def a_run(dx, dy, need=2):
    """-> (cx, cy) FLOOR cell with `need` clear floor cells at (dx,dy).

    Same rule as a_door(): ask the map, do not write a cell down.  The
    walking checks used to start at (10,13) "facing east down a
    corridor"; on the 4x4-room map that cell is a shut DOOR, so the
    player stood inside it and could not move, and a perfectly good
    movement routine reported dx = +0.000.
    """
    grid, _sx, _sy = world.load_maze()
    for y in range(world.MAZE_H):
        for x in range(world.MAZE_W):
            if grid[y][x] != world.FLOOR:
                continue
            if all(0 <= x + dx * i < world.MAZE_W
                   and 0 <= y + dy * i < world.MAZE_H
                   and grid[y + dy * i][x + dx * i] == world.FLOOR
                   for i in range(1, need + 1)):
                return x, y
    raise SystemExit(f"no {need}-cell run in direction ({dx},{dy})")


DSK = os.path.join(_ROOT, "build", "amaze.dsk")
SYM = os.path.join(_ROOT, "build", "e3", "game3.sym")
SOLID = addrs.SOLID                          # the kernel's live 16x16 map

# PACE_FRAMES is main3.asm's, read from the source so this file cannot
# drift from the disc it is checking.
PACE_N = int([l.split()[2] for l in open(os.path.join(_E2, "src", "main3.asm"))
              if l.startswith("PACE_FRAMES equ")][0])

# How long a door must take to run, in GAME frames.  A door steps once a
# frame from DOOR_SHUT to DOOR_OPEN (game.asm:doors_step), so the run IS
# the difference between them -- read it out of the source rather than
# writing the answer down here, the same way PACE_FRAMES is read above.
_G = open(os.path.join(_E2, "src", "game.asm")).read().split("\n")


def _equ(name):
    for line in _G:
        p = line.split()
        if len(p) >= 3 and p[0] == name and p[1] == "equ":
            return int(p[2])
    raise SystemExit(f"{name} not found in game.asm")


AMMO_MAX = _equ("AMMO_MAX")     # game.asm's magazine size
AMMO_NEAR = _equ("AMMO_NEAR")   # ...and its distance bands, in
AMMO_MID = _equ("AMMO_MID")     # L1 cells

# ...and the MAP's numbers, from the include gen_march.py wrote: how many
# pickups it scattered, and where the player starts (world.py asserts no
# pickup is on that cell, which is what makes it the right place to test
# firing from).
_GM = open(os.path.join(_E2, "src", "gen_maze.inc")).read().split("\n")


def _gm(name):
    for line in _GM:
        p = line.split()
        if len(p) >= 3 and p[0] == name and p[1] == "equ":
            return int(p[2])
    raise SystemExit(f"{name} not found in gen_maze.inc")


NAMMO = _gm("NAMMO")
START = (_gm("START_X"), _gm("START_Y"))
MONSTART = _gm("MONSTART")      # where the map puts the monster; MONCELL
                                # is the byte that MOVES, so a test that
                                # wants the start has to read the equ
MON_HPMAX = _equ("MON_HPMAX")
MON_RATE = _equ("MON_RATE")

# pip.asm's half width in column PAIRS, which is also the AIM CONE: the
# shot hits when the pairs mon_draw painted include the crosshair's.
_PIP = open(os.path.join(_E2, "src", "pip.asm")).read().split("\n")


# ...and it is an `equ` of ANOTHER equ now: MON_HW is SPR_MON_HW, which
# engine2/tools/genspr.py emits from the monster's own art, so widening
# the sprite widens the aim cone by construction instead of by somebody
# remembering to change a second literal.  So this follows one hop into
# the generated file rather than demanding a number.
_SPR = open(os.path.join(_E2, "src", "gen_spr.inc")).read().split("\n")


def _pe(name, where=None):
    for line in (where or _PIP):
        p = line.split()
        if len(p) >= 3 and p[0] == name and p[1] == "equ":
            try:
                return int(p[2])
            except ValueError:
                return _pe(p[2], _SPR)      # one hop, into gen_spr.inc
    raise SystemExit(f"{name} not found in pip.asm or gen_spr.inc")


MON_HW = _pe("MON_HW")
FX_BLOOD = 0xC3
PLR_HPMAX = _equ("PLR_HPMAX")

# ...and the health bar's geometry, which genhud.py derives from the slot
# that holds it.  Read, not copied: section 11 checks the PIXELS.
_GH = open(os.path.join(_E2, "src", "gen_hud.inc")).read().split("\n")


def _gh(name):
    for line in _GH:
        p = line.split()
        if len(p) >= 3 and p[0] == name and p[1] == "equ":
            return int(p[2].replace("#", "0x"), 0)
    raise SystemExit(f"{name} not found in gen_hud.inc")


HUD_HPX, HUD_HPY = _gh("HUD_HPX"), _gh("HUD_HPY")
HUD_HPW, HUD_HPSEG = _gh("HUD_HPW"), _gh("HUD_HPSEG")
HUD_HPPEN = _gh("HUD_HPPEN")

# ---- THE SCORE DIGIT'S PLACE ON THE WIN SCREEN, and the font rows that
#  must land there.  genmenu.py owns the layout and the nibble->bytes
#  mapping, so both are IMPORTED rather than restated: a screen that
#  moves takes its test with it.
import genmenu as _GMENU                                    # noqa: E402
MN_GH, MN_O_FONT = _GMENU.GH, _GMENU.blob()[1]["FONT"]
P_TEXT = _GMENU.PENS.index(_GMENU.P_TEXT)


def gm_nib(nib, pen):
    return _GMENU.nib_bytes(nib, _GMENU.PENS[pen])


_win = [(r, c, t) for r, _p, c, t in _GMENU.WIN if _GMENU.SCORE_CH in t][0]
SCORE_WIN_X = (_GMENU.place(_win[1], _win[2])
               + _win[2].index(_GMENU.SCORE_CH) * _GMENU.PITCH)
SCORE_WIN_Y = _win[0] * _GMENU.LINE

# ...and the score's "0" glyph, which game.asm INCs from.
_GN = open(os.path.join(_E2, "src", "gen_menu.inc")).read().split("\n")
MN_G0 = [int(l.split()[2]) for l in _GN
         if l.split()[:2] == ["MN_G0", "equ"]][0]

# pip.asm's scratch is `equ`, and rasm emits no symbol for an equ, so
# these are computed the way the source computes them.  The asserts in
# pip.asm are what keep the two bases where they are.
PIPVARS, FXVARS = 0x3DF0, 0x3EA0
A_PIP_P, A_BX_BOT = PIPVARS + 4, PIPVARS + 15
A_FX_PEN, A_MON_BOT = FXVARS + 2, FXVARS + 3

DOOR_MIN_FRAMES = 6
assert _equ("DOOR_OPEN") - _equ("DOOR_SHUT") >= DOOR_MIN_FRAMES, (
    "game.asm's door runs in %d frames, under the %d this checks for"
    % (_equ("DOOR_OPEN") - _equ("DOOR_SHUT"), DOOR_MIN_FRAMES))


def syms():
    out = {}
    for line in open(SYM):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            out[p[0].upper()] = int(p[1][1:], 16)
    return out


class Game:
    def __init__(self):
        self.s = syms()
        self.c = CPC()
        self.c.insert_disc(DSK)
        self.c.run_frames(150)
        self.c.type_text('RUN"AMAZE\n')
        self.c.run_frames(bootdisc.LOAD_FRAMES)
        bootdisc.start(self.c)   # past the title screen -- see bootdisc.py          # loader + two hud_static passes

    def player(self):
        x, y = struct.unpack("<HH", self.c.read_ram(self.s["PLR_X"], 4))
        return x, y, self.c.peek(self.s["PLR_A"])

    def place(self, x, y, a, settle=25):
        """Teleport the player and RESTART the main loop.  Writing
        (plr_x) into a RUNNING frame is not safe -- the march re-reads the
        player's cell after march_setup has seeded the frustum from the
        old one, and a write between the two sends the flood past the
        seven cells it is bounded by and over its 128-entry stack.  A
        player never teleports, so it is the harness's problem; the six
        bytes at #39C0 reset SP and re-enter main_loop."""
        self.c.write_ram(self.s["PLR_X"], struct.pack("<H", x))
        self.c.write_ram(self.s["PLR_Y"], struct.pack("<H", y))
        self.c.poke(self.s["PLR_A"], a)
        self.c.write_ram(0x39C0, bytes([0xF3, 0x31, 0xF0, 0x3F, 0xC3])
                         + struct.pack("<H", self.s["MAIN_LOOP"]))
        self.c.set_pc(0x39C0)
        self.c.run_frames(settle)

    def hold(self, key, frames):
        self.c.key_down(key)
        self.c.run_frames(frames)
        self.c.key_up(key)
        self.c.run_frames(12)

    def frames(self):
        return struct.unpack("<H", self.c.read_ram(self.s["FRAME_CTR"], 2))[0]

    def base(self):
        """The 16k page R12/R13 select.  The CRTC holds a character
        address, so bits 12-13 of it are the buffer bits 14-15 that
        main3.asm writes as R12 = &30 (&C000) or &20 (&8000)."""
        return ((self.c.crtc_screen_addr >> 12) & 3) * 0x4000


def main():
    g = Game()
    c = g.c
    ok = True
    # SAMPLED AT BOOT, CHECKED IN SECTION 10.  MONCELL is a byte the
    # monster walks and mon_hit sets to #FF, and by the time section 10
    # runs the earlier sections have spent forty rounds and walked the
    # whole map -- so reading it there tests nothing about game_init.
    # First attempt did exactly that and read #FF.
    mon_at_boot = c.peek(g.s["MONCELL"])
    # ...AND THEN TAKEN OFF THE MAP FOR SECTIONS 1-9.
    #
    #  It hunts now.  Section 7 walks the player onto all six pickups and
    #  section 8 stands him in seventeen places; the monster follows,
    #  bites, and the player DIES half way through -- after which the
    #  death screen has stopped the frame loop and every check below it
    #  is measuring a machine that is not running.  MEASURED: eight
    #  checks in sections 7, 8, 10 and 11 failed at once, and every one
    #  of them was this.
    #
    #  #FF is a legal map -- mon_draw, mon_scan and mon_move all test for
    #  it -- so this is not a special mode, it is the no-monster map.
    #  Section 10 puts it back, because that is the section about it.
    c.poke(g.s["MONCELL"], 0xFF)

    def check(cond, what, detail):
        nonlocal ok
        if not cond:
            ok = False
        print(f"  [{'PASS' if cond else 'FAIL'}] {what}: {detail}")

    def gframe(limit=60):
        """Run until (frame_ctr) moves.  -> False if it never does.

        THE BOUND IS NOT DEFENSIVE PROGRAMMING, IT IS THE TEST.  The
        obvious `while frames() == f0: run_us(...)` spins for ever the
        moment the player dies, because the death screen stops the frame
        loop -- which is precisely what section 11 exists to check.  It
        hung the whole run once before this was written."""
        f0 = g.frames()
        for _ in range(limit * 6):          # 6 x 4 ms is over a period
            c.run_us(4000)
            if g.frames() != f0:
                return True
        return False

    print("1  SCREEN MODE")
    check(c.mode == 0, "mode 0", f"c.mode = {c.mode}")

    print("\n2  DOUBLE BUFFERING (CRTC R12 display base)")
    seen = []
    for _ in range(40):
        b = g.base()
        if not seen or seen[-1] != b:
            seen.append(b)
        c.run_frames(2)
    bases = sorted(set(seen))
    check(len(bases) == 2 and bases == [0x8000, 0xC000],
          "base alternates &8000 / &C000",
          f"observed {[hex(b) for b in bases]}, "
          f"{len(seen)} transitions in 80 CPC frames")

    print("\n3  TURNING (cursor right, 5 deg per game frame)")
    # ANY open cell will do for turning, but it must BE open: ask the map.
    tx, ty = a_run(1, 0)
    g.place(tx * 256 + 128, ty * 256 + 128, 0)
    a0 = g.player()[2]
    n0 = g.frames()
    g.hold(cpcmod.KEY_RIGHT, 30)
    a1 = g.player()[2]
    n1 = g.frames()
    check(a1 != a0, "heading changed",
          f"plr_a {a0} -> {a1} over {n1 - n0} game frames "
          f"= {((a1 - a0) % 72) * 5} degrees right")
    g.place(tx * 256 + 128, ty * 256 + 128, 0)
    g.hold(cpcmod.KEY_LEFT, 30)
    a2 = g.player()[2]
    check(a2 != 0, "cursor left turns the other way",
          f"plr_a 0 -> {a2} ( = -{(72 - a2) * 5} degrees)")

    print("\n4  WALKING (cursor up, along the heading)")
    #    a cell with clear floor to its EAST, found in the map; heading 0
    #    is +x.  It used to be the written-down (10,13), which the 4x4-room
    #    map turned into a shut door -- the player stood inside it, could
    #    not move, and the movement code was blamed.
    g.place(tx * 256 + 128, ty * 256 + 128, 0)
    x0, y0, _ = g.player()
    g.hold(cpcmod.KEY_UP, 40)
    x1, y1, _ = g.player()
    check(x1 > x0, "plr_x increased walking east",
          f"({x0:04X},{y0:04X}) -> ({x1:04X},{y1:04X}), "
          f"dx = {(x1 - x0) / 256.0:+.3f} cells, "
          f"dy = {(y1 - y0) / 256.0:+.3f}")
    #    and on a diagonal heading both coordinates must move
    g.place(9 * 256 + 128, 13 * 256 + 128, 63)
    x0, y0, _ = g.player()
    g.hold(cpcmod.KEY_UP, 30)
    x2, y2, _ = g.player()
    check(x2 != x0 and y2 != y0, "both axes move on a 45 deg heading",
          f"heading 63 = 315 deg: dx {(x2 - x0) / 256.0:+.3f} "
          f"dy {(y2 - y0) / 256.0:+.3f} cells")

    # ---- AND ALL SEVENTY-TWO, against the angle each one MEANS.
    #
    #  THIS CHECK EXISTS BECAUSE TWO HEADINGS ARE NOT A COMPASS.  The two
    #  above are heading 0 and heading 63 -- quadrant 0 and quadrant 3.
    #  game.asm's step_vector folds one quarter of STEPTAB four ways, and
    #  the QUADRANT 1 fold was wrong: it produced (-cos t, sin t) where it
    #  wanted (-sin t, cos t), i.e. headings 18..35 mirrored about 135
    #  degrees.  Heading 18 walked due WEST while gen_march.py's MARCHTB
    #  -- which has all 72 headings and no folding -- pointed the VIEW due
    #  south.  A quarter of the compass walked sideways to the picture,
    #  and every test in this file passed.
    #
    #  It is measured off (mv_dx)(mv_dy), which step_vector writes once a
    #  frame, so it needs no walking and no collision-free space: poke the
    #  heading, run a frame, read the vector.
    print("\n4b THE STEP VECTOR AT ALL 72 HEADINGS (step_vector's fold)")
    import math
    bad = []
    for a in range(72):
        c.poke(g.s["PLR_A"], a)
        gframe()
        dx = struct.unpack("<h", c.read_ram(g.s["MV_DX"], 2))[0]
        dy = struct.unpack("<h", c.read_ram(g.s["MV_DY"], 2))[0]
        got = math.degrees(math.atan2(dy, dx)) % 360
        want = (5.0 * a) % 360
        if abs((got - want + 180) % 360 - 180) > 4.0:
            bad.append((a, round(got, 1), want))
    check(not bad, "every heading steps along the angle it names",
          "all 72 within 4 deg of 5a" if not bad else
          f"{len(bad)} wrong, first five: "
          + ", ".join(f"a={a} got {got} want {want}" for a, got, want
                      in bad[:5]))

    print("\n5  COLLISION (the player cannot enter a wall)")
    solid = c.read_ram(SOLID, 256)
    #    (1,13) with a wall to the west at (0,13); walk west into it
    g.place(1 * 256 + 128, 13 * 256 + 128, 36)
    g.hold(cpcmod.KEY_UP, 200)
    x, y, _ = g.player()
    cx, cy = x >> 8, y >> 8
    check(solid[cy * 16 + cx] == 0, "player is in an open cell",
          f"stopped at ({x:04X},{y:04X}) = cell ({cx},{cy}), "
          f"SOLID = {solid[cy * 16 + cx]}")
    check((x & 0xFF) >= 64, "kept a 0.25-cell clearance from the wall plane",
          f"fractional x = {(x & 0xFF) / 256.0:.3f} cells, PRAD = 0.250")
    #    every cell of the maze, walked into from its open neighbour
    bad = []
    for cy in range(1, 15):
        for cx in range(1, 15):
            if solid[cy * 16 + cx] != 1:
                continue
            for a, (dx, dy) in ((0, (-1, 0)), (36, (1, 0)),
                                (18, (0, -1)), (54, (0, 1))):
                sx, sy = cx + dx, cy + dy
                if solid[sy * 16 + sx] != 0:
                    continue
                g.place(sx * 256 + 128, sy * 256 + 128, a, settle=6)
                g.hold(cpcmod.KEY_UP, 30)
                px, py, _ = g.player()
                if solid[(py >> 8) * 16 + (px >> 8)] != 0:
                    bad.append((sx, sy, a, px >> 8, py >> 8))
                break
    check(not bad, "walked into every wall in the maze from a neighbour",
          f"{len(bad)} penetrations" if bad else
          "0 penetrations, all cells ended open")

    print("\n6  DOORS (SPACE)")
    door, (dx, dy), (nx, ny), head = a_door()
    g.place(nx * 256 + 128, ny * 256 + 128, head)
    before = c.peek(SOLID + door)
    check(before == 2, f"door ({dx},{dy}) starts shut", f"SOLID = {before}")
    #    it is solid: walking at it must not get into its cell
    g.hold(cpcmod.KEY_UP, 60)
    xs, ys, _ = g.player()
    check((xs >> 8, ys >> 8) != (dx, dy), "a shut door blocks the player",
          f"stopped at cell ({xs >> 8},{ys >> 8}), the door is ({dx},{dy})")
    g.place(nx * 256 + 128, ny * 256 + 128, head)
    g.hold(cpcmod.KEY_SPACE, 20)
    c.run_frames(60)                    # the door takes 5 game frames to run
    after = c.peek(SOLID + door)
    check(after == 0, "SPACE opened it", f"SOLID = {before} -> {after}")
    g.hold(cpcmod.KEY_UP, 150)
    xt, yt, _ = g.player()
    #    walking through it means reaching the door cell or passing beyond
    through = ((xt >> 8, yt >> 8) == (dx, dy)
               or (xt >> 8, yt >> 8) == (dx + (dx - nx), dy + (dy - ny)))
    check(through, "and the player walked through",
          f"now at cell ({xt >> 8},{yt >> 8}), from ({nx},{ny}) "
          f"through ({dx},{dy})")
    # STEP OUT OF THE DOORWAY FIRST.  The walk above leaves the player
    # standing IN the door's own cell, and a door does not shut on the
    # player -- so SPACE there is a no-op and the check reads SOLID = 0
    # for a door that works perfectly.
    g.place(nx * 256 + 128, ny * 256 + 128, head)
    g.hold(cpcmod.KEY_SPACE, 20)
    c.run_frames(60)
    check(c.peek(SOLID + door) == 2, "SPACE shuts it again",
          f"SOLID = {c.peek(SOLID + door)}")

    # ---- AND IT RUNS GRADUALLY, one door_st step per GAME frame.
    #
    # SPACE has to be down across a whole game frame to be seen -- keys
    # are polled once a frame and a frame is PACE_FRAMES vsyncs -- but it
    # must be RELEASED before the run ends or door_act fires again and
    # sends the door back the other way.  So hold through exactly one
    # game frame, then sample door_st per game frame.
    g.place(nx * 256 + 128, ny * 256 + 128, head)
    c.run_frames(30)
    # door_st is an `equ` now (it moved to the free RAM above QUADS),
    # and rasm puts only LABELS in the .sym file -- so it comes from
    # addrs.py, which parses it out of game.asm.
    st_addr = addrs.DOOR_ST
    c.key_down(cpcmod.KEY_SPACE)
    seen, last, held = [], g.frames(), 0
    for _ in range(1500):
        c.run_us(2000)
        f = g.frames()
        if f == last:
            continue
        last = f
        held += 1
        if held == 1:
            c.key_up(cpcmod.KEY_SPACE)
        seen.append((c.peek(st_addr), c.peek(SOLID + door)))
        if c.peek(SOLID + door) == 0:
            break
    run = len(seen)
    steps = sorted(set(s for s, _ in seen))
    check(run >= DOOR_MIN_FRAMES,
          f"the door takes at least {DOOR_MIN_FRAMES} frames to open",
          f"{run} game frames, door_st {steps[0]}..{steps[-1]} "
          f"one step a frame, passable on the last")

    # ---- AND EVERY OTHER DOOR IN THE MAP, not just the one above.
    #
    # THIS IS THE CHECK THAT WAS MISSING.  game_init registers at most
    # MAXDOORS doors and silently drops the rest (game.asm), and the map
    # grew to twelve doors against a MAXDOORS of eight -- so four doors,
    # including the one beside the player's start cell, could never be
    # opened.  Every check above passed throughout, because a_door()
    # returns the FIRST door in scan order and that one was inside the
    # cap.  One working door proves nothing about the others.
    dead = []
    for (ddx, ddy) in all_doors():
        di = ddy * 16 + ddx
        st = door_neighbour(ddx, ddy)
        if st is None:
            continue
        g.place(st[0] * 256 + 128, st[1] * 256 + 128, st[2])
        c.run_frames(30)
        # the checks above leave THEIR door open, so shut anything that is
        # open before testing that it opens.  A door that will not shut is
        # just as dead as one that will not open, so it still counts.
        if c.peek(SOLID + di) != 2:
            g.hold(cpcmod.KEY_SPACE, 12)
            c.run_frames(20 * (DOOR_MIN_FRAMES + 4))
            if c.peek(SOLID + di) != 2:
                dead.append((ddx, ddy, "would not shut"))
                continue
        c.key_down(cpcmod.KEY_SPACE)
        last, held, opened = g.frames(), 0, False
        for _ in range(1500):
            c.run_us(2000)
            f = g.frames()
            if f == last:
                continue
            last = f
            held += 1
            if held == 1:
                c.key_up(cpcmod.KEY_SPACE)
            if c.peek(SOLID + di) == 0:
                opened = True
                break
            if held > DOOR_MIN_FRAMES + 6:
                break
        if not opened:
            dead.append((ddx, ddy, f"still SOLID after {held} frames"))
    ndoor = len(all_doors())
    check(not dead, "EVERY door in the map opens",
          f"{ndoor - len(dead)} of {ndoor} opened"
          + (f"; DEAD: {dead}" if dead else ""))

    print("\n7  SHOOTING AND PICKUPS (Z fires; CTRL does too, but the "
          "emulator\n       cannot press a modifier -- see game.asm's "
          "fire_edge)")
    tab = c.read_ram(g.s["AMMOTAB"], NAMMO)
    amx = g.s["PLR_AMMO"]
    # The map's list, as cells.  Read off the RUNNING MACHINE rather than
    # imported from world.py, so a table the build failed to emit shows up
    # here as a wrong cell and not as a Python constant agreeing with
    # itself.
    cells = [(b & 15, b >> 4) for b in tab]
    def shoot():
        """One press edge, guaranteed.

        A GAME frame is PACE_FRAMES vsyncs, so the key has to be held
        for longer than that or scan_keys can miss the press entirely --
        the first version held it for 4 and silently lost two shots in
        six.  Down for PACE_N+5 and up for PACE_N+5 means at least one
        scan sees it down and at least one sees it up: exactly one edge,
        every time."""
        c.key_down(ord('z'))
        c.run_frames(PACE_N + 5)
        c.key_up(ord('z'))
        c.run_frames(PACE_N + 5)

    g.place(START[0] * 256 + 128, START[1] * 256 + 128, 0)  # no pickup here
    check(c.peek(amx) == AMMO_MAX, "the magazine starts full",
          f"plr_ammo = {c.peek(amx)} of {AMMO_MAX}")

    n0 = c.peek(amx)
    shoot()
    check(c.peek(amx) == n0 - 1, "Z fires one round",
          f"{n0} -> {c.peek(amx)}")

    n0 = c.peek(amx)                    # HELD DOWN is still one round
    c.key_down(ord('z'))
    c.run_frames(120)
    held = c.peek(amx)
    c.key_up(ord('z'))
    c.run_frames(12)
    check(held == n0 - 1, "holding Z down does NOT empty the magazine",
          f"{n0} -> {held} over 120 frames held")

    for _ in range(AMMO_MAX + 2):       # empty it, then keep pulling
        shoot()
    check(c.peek(amx) == 0, "an empty magazine stays at zero, it does not"
          " wrap", f"plr_ammo = {c.peek(amx)} after {AMMO_MAX+2} more shots")

    # ...and the pickups.  Stand on each one in turn: ammo_pick runs every
    # game frame off the player's cell, so a teleport onto it is the same
    # thing the walk is.
    got, missed = [], []
    for i, (cx, cy) in enumerate(cells):
        g.place(cx * 256 + 128, cy * 256 + 128, 0)
        if c.peek(amx) == AMMO_MAX and c.peek(g.s["AMMO_ST"] + i) == 0xFF:
            got.append((cx, cy))
        else:
            missed.append(((cx, cy), c.peek(amx),
                           c.peek(g.s["AMMO_ST"] + i)))
        for _ in range(AMMO_MAX):       # empty it again for the next one
            shoot()
    check(not missed, f"every one of the {len(cells)} pickups refills the "
          "magazine and is then gone",
          f"{len(got)} of {len(cells)}: {got}"
          + (f"; MISSED: {missed}" if missed else ""))

    # A TAKEN PICKUP IS TAKEN.  Walk back onto the first one on an empty
    # magazine: nothing should happen.
    cx, cy = cells[0]
    g.place(cx * 256 + 128, cy * 256 + 128, 0)
    check(c.peek(amx) == 0, "a pickup already collected does not come back",
          f"plr_ammo = {c.peek(amx)} standing on {(cx, cy)} again")

    print("\n8  THE AMMO SCANNER (the direction pad in the middle-left "
          "slot)")
    # THE RULE, IN PYTHON, from game.asm:ammo_scan.  Not a restatement of
    # the answer -- a restatement of the METHOD, which is what makes a
    # disagreement mean something.
    OCTAB = [0, 1, 2,  4, 3, 2,  0, 7, 6,  4, 5, 6]

    def scan_model(px, py, a, live):
        best, bd = None, 999
        for (cx, cy) in live:                       # strictly nearer wins
            d = abs(cx - px) + abs(cy - py)
            if d < bd:
                bd, best = d, (cx, cy)
        if best is None:
            return 0xFF
        dx, dy = best[0] - px, best[1] - py
        ax, ay = abs(dx), abs(dy)
        shape = 2 if 2 * ay >= 5 * ax else (0 if 2 * ax >= 5 * ay else 1)
        i = (1 if dy < 0 else 0) * 2 + (1 if dx < 0 else 0)
        o = OCTAB[i * 3 + shape]
        p, n = 0, a + 4                             # round(a / 9)
        while n >= 9:
            n -= 9
            p += 1
        band = 0 if bd <= AMMO_NEAR else (1 if bd <= AMMO_MID else 2)
        return (band << 4) | ((o - p) & 7)

    adir = g.s["AMMO_DIR"]
    # RE-ARM FIRST.  Section 7 walked over every pickup to prove they can
    # be collected, so by here the map is stripped -- and a scanner test
    # run against an empty map is not a test: every case would compare
    # #FF against #FF and pass.  Put the map's own table back, which is
    # exactly what game.asm's ammo_arm does.
    c.write_ram(g.s["AMMO_ST"], tab)
    g.place(START[0] * 256 + 128, START[1] * 256 + 128, 0)
    live = [cell for cell, b in
            zip(cells, c.read_ram(g.s["AMMO_ST"], NAMMO)) if b != 0xFF]
    check(len(live) == NAMMO, "the pickups are back for this section",
          f"{len(live)} of {NAMMO} live: {live}")
    print(f"       {len(live)} pickups on the map: {live}")

    # (a) ALL 72 HEADINGS from one spot -- the heading half of the sum,
    #     which is where an off-by-one sector would live.
    bad = []
    for a in range(72):
        g.place(START[0] * 256 + 128, START[1] * 256 + 128, a, settle=14)
        got, want = c.peek(adir), scan_model(START[0], START[1], a, live)
        if got != want:
            bad.append((a, got, want))
    check(not bad, "the bearing is right at all 72 headings",
          f"from the start cell {START}"
          + (f"; WRONG at {len(bad)}: {bad[:4]}" if bad else ""))

    # (b) MANY POSITIONS at a fixed heading -- the geometry half.  Every
    #     floor cell that is not itself a pickup, so nothing is collected.
    bad, n = [], 0
    for cy in range(1, 15):
        for cx in range(1, 15):
            if c.peek(SOLID + cy * 16 + cx) != 0 or (cx, cy) in live:
                continue
            n += 1
            if n % 3:                       # a third of them: ~40 places
                continue
            g.place(cx * 256 + 128, cy * 256 + 128, 0, settle=14)
            got, want = c.peek(adir), scan_model(cx, cy, 0, live)
            if got != want:
                bad.append(((cx, cy), got, want))
    check(not bad, "...and at a third of the standable cells, facing east",
          f"{n // 3} places checked"
          + (f"; WRONG at {len(bad)}: {bad[:4]}" if bad else ""))

    # (c) AND WITH THE MAP STRIPPED IT POINTS AT THE WAY OUT.
    #
    #  THIS CHECK USED TO ASSERT THE PAD WENT DARK, and that was the
    #  behaviour until the exit existed: the reward for clearing the maze
    #  was to lose the only instrument that says where anything is, with
    #  one cell of 256 left to find.  game.asm's as_none now scans
    #  EXIT_CELL instead, through the same as_pack the pickups use.
    #
    #  Checked by GEOMETRY and not by "it is not #FF": stand three cells
    #  due west of the exit facing east and the bearing must be 0 -- dead
    #  ahead -- and the band must be the near one.  A pad that pointed
    #  anywhere at all would pass the weaker test.
    for i in range(NAMMO):
        c.poke(g.s["AMMO_ST"] + i, 0xFF)
    ex, ey = _gm("EXIT_X"), _gm("EXIT_Y")
    g.place((ex - 3) * 256 + 128, ey * 256 + 128, 0)
    d = c.peek(adir)
    check(d != 0xFF and (d & 7) == 0 and (d >> 4) == 0,
          "with every pickup taken the pad points at the EXIT",
          f"three cells west of the exit ({ex},{ey}) facing east: "
          f"ammo_dir = #{d:02X} -> band {d >> 4}, bearing {d & 7} "
          f"(0 = dead ahead)")

    # ...and it goes dark only when the map has no exit either, which is
    # EXIT_CELL #FF -- a case this map cannot produce, so it is asserted
    # in the generator (gen_march.emit_exit) rather than measured here.

    # =================================================================
    print("\n10 THE MONSTER (it walks at you, and three rounds kill it)")
    mc, mhp, mtk = g.s["MONCELL"], g.s["MON_HP"], g.s["MON_TICK"]

    # ---- (a) PURSUIT, against engine2/tools/monmodel.py's replay of the
    #      same rule.  Not against a description of it: the model steps
    #      the cell in Python and the two are compared cell for cell.
    import monmodel as MM
    solid, _ = MM.load_solid()
    check(mon_at_boot == MONSTART,
          "the disc boots with the monster where the MAP put it",
          f"MONCELL at boot = {mon_at_boot} = "
          f"({mon_at_boot&15},{mon_at_boot>>4}), MONSTART = {MONSTART}")

    MX, MY, PX, PY = 1, 12, 4, 12       # same room, monster due WEST
    c.poke(mc, MY * 16 + MX)
    c.poke(mhp, 99)
    c.poke(mtk, 1)                      # step on the very next frame
    g.place(PX * 256 + 128, PY * 256 + 128, 0)
    disc, want, m = [], [], MY * 16 + MX
    for _ in range(4):
        gframe()                        # exactly one GAME frame
        disc.append(c.peek(mc))
        m = MM.step(solid, m, PX, PY)
        want.append(m)
        for _ in range(MON_RATE - 1):   # ...and the frames it holds still
            gframe()
    check(disc == want, "it walks the cells monmodel.py says it walks",
          f"disc {disc}, model {want}")
    check(disc[-1] == PY * 16 + PX - 1,
          "and it STOPS beside the player, never on him",
          f"ended at cell {disc[-1]} = "
          f"({disc[-1]&15},{disc[-1]>>4}), player ({PX},{PY})")

    # ---- (b) THE AIM CONE.  Turn with the real key rather than
    #      teleporting per heading: place() restarts main_loop and the
    #      point here is what a player sees while turning.
    c.poke(mc, MY * 16 + MX)
    c.poke(mhp, 99)
    c.poke(mtk, 99)                     # frozen for the sweep
    g.place(PX * 256 + 128, PY * 256 + 128, 0)
    cone, drawn, pairs = [], [], {}
    c.key_down(cpcmod.KEY_RIGHT)
    for _ in range(80):
        gframe()
        a = c.peek(g.s["PLR_A"])
        if c.peek(A_BX_BOT) and a not in drawn:
            drawn.append(a)
            pairs[a] = c.peek(A_PIP_P)
        if c.peek(A_MON_BOT) and a not in cone:
            cone.append(a)
    c.key_up(cpcmod.KEY_RIGHT)
    c.run_frames(12)
    check(0 < len(cone) < len(drawn),
          "the aim cone is NARROWER than the monster is visible across",
          f"drawn on {len(drawn)} headings, hit on {len(cone)}"
          f" = {len(cone)*5} of {len(drawn)*5} degrees: {sorted(cone)}")
    check(len(cone) <= 2 * MON_HW + 1,
          "...and no wider than the pairs it actually paints",
          f"MON_HW {MON_HW} paints {2*MON_HW+1} pairs, cone is"
          f" {len(cone)} headings; centre pair of each:"
          + " ".join(f" h{a}:{pairs[a]}" for a in sorted(cone)))

    # ---- (c) THREE ROUNDS.  The monster leaves the map by MONCELL going
    #      #FF, which is what mon_draw, mon_scan and the radar all test.
    c.poke(mc, MY * 16 + MX)
    c.poke(mhp, MON_HPMAX)
    c.poke(mtk, 99)
    c.poke(g.s["PLR_AMMO"], AMMO_MAX)
    g.place(PX * 256 + 128, PY * 256 + 128, sorted(cone)[0] if cone else 36)
    hp = [c.peek(mhp)]
    for _ in range(MON_HPMAX):
        c.key_down(ord('z'))
        c.run_frames(PACE_N + 5)
        c.key_up(ord('z'))
        c.run_frames(PACE_N + 5)
        hp.append(c.peek(mhp))
    check(hp == list(range(MON_HPMAX, -1, -1)),
          f"{MON_HPMAX} rounds take it down one hit point each",
          f"mon_hp {hp}")
    check(c.peek(mc) == 0xFF, "at zero it leaves the map",
          f"MONCELL = #{c.peek(mc):02X}")
    check(c.peek(g.s["MON_BLIP"]) == 0xFF, "...and its radar blip goes out",
          f"mon_blip = #{c.peek(g.s['MON_BLIP']):02X}")
    n0 = c.peek(g.s["PLR_AMMO"])
    c.key_down(ord('z'))
    c.run_frames(PACE_N + 5)
    c.key_up(ord('z'))
    c.run_frames(PACE_N + 5)
    check(c.peek(A_FX_PEN) != FX_BLOOD,
          "a shot through where it stood no longer draws blood",
          f"fx_pen = #{c.peek(A_FX_PEN):02X}, ammo {n0} -> "
          f"{c.peek(g.s['PLR_AMMO'])}")

    # =================================================================
    print("\n11 HEALTH, THE BITE, AND THE DEATH SCREEN")
    php, mc, mtk = g.s["PLR_HP"], g.s["MONCELL"], g.s["MON_TICK"]

    # ---- (a) THE BAR IS READ OFF THE SCREEN, not off the variable.
    #      A readout that agrees with the byte it was handed proves
    #      nothing; the question is whether the pixels moved.
    def bar_bytes():
        y = HUD_HPY + 2                 # a scanline inside the bar
        addr = g.base() + (y & 7) * 0x800 + (y >> 3) * 80 + HUD_HPX
        return sum(1 for b in c.read_ram(addr, HUD_HPW) if b == HUD_HPPEN)

    MX, MY, PX, PY = 3, 12, 4, 12       # adjacent: L1 == 1, so it bites
    c.poke(mc, MY * 16 + MX)
    c.poke(g.s["MON_HP"], 99)           # unkillable, so the test is the
    c.poke(mtk, 99)                     # bite and nothing else
    c.poke(php, PLR_HPMAX)
    g.place(PX * 256 + 128, PY * 256 + 128, 36)
    # ---- LET BOTH BUFFERS CATCH UP BEFORE READING PIXELS.  hud_health
    #      paints the buffer being drawn INTO, so the displayed one is a
    #      frame behind until the value has been stable for two frames.
    #      Sampled on the frame of the change, the bar reads the previous
    #      hit point -- which is the readout working, not failing.
    gframe()
    gframe()
    c.poke(mtk, 1)                      # ...and NOW let it bite
    seen, bars = [], []
    for _ in range(PLR_HPMAX + 1):
        seen.append(c.peek(php))
        bars.append(bar_bytes())
        if not seen[-1]:
            break
        for _ in range(MON_RATE):       # one whole bite interval
            if not gframe():
                break
    check(seen == list(range(PLR_HPMAX, -1, -1)),
          "standing next to it costs one hit point every MON_RATE frames",
          f"plr_hp {seen}")
    check(bars == [n * HUD_HPSEG for n in seen],
          "and the bar ON SCREEN shrinks with it",
          f"{bars} bytes of HUD_HPPEN against "
          f"{[n * HUD_HPSEG for n in seen]} wanted")

    # ---- (b) AT ZERO THE GAME STOPS.  frame_ctr is the witness: the
    #      death screen is menu.asm waiting for SPACE, so no game frame
    #      completes at all while it is up.
    f0 = g.frames()
    c.run_frames(4 * PACE_N)
    check(g.frames() == f0, "at zero hit points the frame loop stops",
          f"{(g.frames() - f0) & 0xFFFF} game frames in {4*PACE_N} CPC "
          f"frames -- the death screen is up")

    # ---- (c) ...AND SPACE STARTS A NEW LIFE, world and all.  MENUBUF is
    #      SOLID, so painting that screen destroyed the map: if the map
    #      were not rebuilt the player would be standing inside the
    #      menu's font table.
    c.key_down(cpcmod.KEY_SPACE)
    c.run_frames(PACE_N + 5)
    c.key_up(cpcmod.KEY_SPACE)
    c.run_frames(12 * PACE_N)
    x, y, _ = g.player()
    solid_now = c.read_ram(SOLID, 256)
    check(c.peek(g.s["PLR_AMMO"]) == AMMO_MAX
          and c.peek(mc) != 0xFF and c.peek(g.s["MON_HP"]) == MON_HPMAX,
          "SPACE re-arms the player AND puts the monster back",
          f"plr_hp {c.peek(php)}, plr_ammo {c.peek(g.s['PLR_AMMO'])}, "
          f"MONCELL {c.peek(mc)}, mon_hp {c.peek(g.s['MON_HP'])}")
    check((x >> 8, y >> 8) == START and solid_now[(y >> 8) * 16 + (x >> 8)] == 0,
          "...and REBUILDS THE MAP the death screen wrote over",
          f"player at ({x>>8},{y>>8}), START {START}, "
          f"SOLID there = {solid_now[(y>>8)*16+(x>>8)]}")
    f0 = g.frames()
    c.run_frames(4 * PACE_N)
    check(g.frames() != f0, "the frame loop is running again",
          f"{(g.frames() - f0) & 0xFFFF} game frames in {4*PACE_N} CPC frames")

    # ---- (d) AND THE OPENING IS SURVIVABLE, which is the one thing
    #      about this game that a model cannot tell you.  From a cold
    #      boot the map points the player AT the monster (START_A), so
    #      three rounds and nothing else should end it with no damage
    #      taken.  It did not before: plr_a was 0, due east, with the
    #      monster two cells west, and a 180-degree turn is 36 frames
    #      against a bite every 6 from frame 12.
    g2 = Game()
    for _ in range(MON_HPMAX):
        g2.c.key_down(ord('z'))
        g2.c.run_frames(PACE_N + 5)
        g2.c.key_up(ord('z'))
        g2.c.run_frames(PACE_N + 5)
    check(g2.c.peek(g2.s["MONCELL"]) == 0xFF
          and g2.c.peek(g2.s["PLR_HP"]) == PLR_HPMAX,
          "from a COLD BOOT, three rounds kill it before it touches you",
          f"MONCELL #{g2.c.peek(g2.s['MONCELL']):02X}, "
          f"plr_hp {g2.c.peek(g2.s['PLR_HP'])} of {PLR_HPMAX}, "
          f"START_A {_gm('START_A')}")
    del g2

    # =================================================================
    print("\n12 THE EXIT AND THE SCORE (the level can now be WON)")
    scr, adir2 = g.s["SCR_G"], g.s["AMMO_DIR"]
    ex, ey = _gm("EXIT_X"), _gm("EXIT_Y")

    # ---- (a) THE SCORE IS A GLYPH INDEX, so the check is that it walks
    #      the DIGITS and never leaves them.  MN_G0 is CHARSET's '0'.
    g3 = Game()
    base = g3.c.peek(scr)
    check(base == MN_G0, "a life starts at score zero",
          f"scr_g = {base}, MN_G0 = {MN_G0} ('0')")
    for _ in range(MON_HPMAX):          # the opening kills the monster
        g3.c.key_down(ord('z'))
        g3.c.run_frames(PACE_N + 5)
        g3.c.key_up(ord('z'))
        g3.c.run_frames(PACE_N + 5)
    check(g3.c.peek(g3.s["MONCELL"]) == 0xFF
          and g3.c.peek(scr) == MN_G0 + 1,
          "killing the monster scores one",
          f"scr_g {base} -> {g3.c.peek(scr)}")

    tab = g3.c.read_ram(g3.s["AMMOTAB"], NAMMO)
    for b in tab:                       # ...and every pickup scores one
        g3.place((b & 15) * 256 + 128, (b >> 4) * 256 + 128, 0)
        for _ in range(3):              # let ammo_scan see the cell
            f0 = g3.frames()
            for _ in range(60):
                g3.c.run_frames(1)
                if g3.frames() != f0:
                    break
    got = g3.c.peek(scr) - MN_G0
    check(got == NAMMO + 1,
          "...and so does every pickup, and the count stays a DIGIT",
          f"score {got} of {NAMMO} pickups + 1 monster; "
          f"scr_g {g3.c.peek(scr)} <= MN_G0+9 = {MN_G0 + 9}")

    # ---- (b) THE EXIT ENDS THE LEVEL.  Walked onto, not teleported onto:
    #      the win test is in game_step and a teleport re-enters main_loop,
    #      so walking is the case a player actually produces.
    g3.place((ex - 1) * 256 + 128, ey * 256 + 128, 0)
    f0 = g3.frames()
    g3.c.run_frames(2 * PACE_N)
    check(g3.frames() != f0, "one cell short of the exit, the game runs",
          f"{(g3.frames() - f0) & 0xFFFF} game frames")
    g3.c.key_down(cpcmod.KEY_UP)
    g3.c.run_frames(40 * PACE_N)
    g3.c.key_up(cpcmod.KEY_UP)
    x, y, _ = g3.player()
    f0 = g3.frames()
    g3.c.run_frames(4 * PACE_N)
    check((x >> 8, y >> 8) == (ex, ey) and g3.frames() == f0,
          "walking onto it stops the frame loop -- the win screen is up",
          f"player at ({x>>8},{y>>8}), exit ({ex},{ey}), "
          f"{(g3.frames() - f0) & 0xFFFF} game frames in {4*PACE_N} CPC")

    # ---- ...AND THE SCORE IS ON THE SCREEN, byte for byte against the
    #      FONT.  Checking (scr_g) only proves the game counted; this
    #      proves menu.asm's mn_char substitution actually drew the right
    #      glyph.  The font is readable because the win screen IS the
    #      blob: menu.asm LDIRs it down over SOLID, so MENUBUF+MN_O_FONT
    #      holds the same rows the blitter just used.
    got = g3.c.peek(scr)
    font = g3.c.read_ram(SOLID + MN_O_FONT + got * MN_GH, MN_GH)
    want = [gm_nib(n, P_TEXT) for n in font]     # two mode-0 bytes a row
    seen = []
    for r in range(MN_GH):
        yy = SCORE_WIN_Y + r
        addr = 0xC000 + (yy & 7) * 0x800 + (yy >> 3) * 80 + SCORE_WIN_X
        seen.append(list(g3.c.read_ram(addr, 2)))
    check(seen == want and any(any(b) for b in seen),
          "...with the score DRAWN on it, byte for byte against the font",
          f"glyph {got} ('{got - MN_G0}') at ({SCORE_WIN_X},{SCORE_WIN_Y}): "
          f"screen {seen} vs font {want}")

    # ---- (c) ...AND SPACE STARTS A NEW LIFE, score included.
    g3.c.key_down(cpcmod.KEY_SPACE)
    g3.c.run_frames(PACE_N + 5)
    g3.c.key_up(cpcmod.KEY_SPACE)
    g3.c.run_frames(12 * PACE_N)
    f0 = g3.frames()
    g3.c.run_frames(4 * PACE_N)
    check(g3.c.peek(scr) == MN_G0 and g3.frames() != f0,
          "SPACE resets the score and the world runs again",
          f"scr_g {g3.c.peek(scr)}, "
          f"{(g3.frames() - f0) & 0xFFFF} game frames")
    del g3

    # =================================================================
    print("\n13 FRAME PERIOD (measured, one gap at a time, five samples a"
          " vsync)")
    print("       The old four-chunk pad gave 80 ms 79% / 100 ms 20% /"
          " 120 ms 1% / 140 ms\n"
          "       0.5%.  main3.asm now carries a cost accumulator and"
          " yields on it, so\n"
          f"       every frame is exactly PACE_FRAMES = {PACE_N} vsyncs."
          "  engine2/tools/emu_pace.py\n"
          "       is the full sweep; these are four named views.")
    seen = set()
    for name, cx, cy, a in (("corridor", 10, 13, 0),
                            ("junction", 7, 7, 0),
                            ("nose against a wall", 10, 13, 54),
                            ("worst state in the maze", 1, 13, 68),
                            ("140 ms outlier (14,7) h48", 14, 7, 48),
                            ("140 ms outlier (1,5) h12", 1, 5, 12)):
        g.place(cx * 256 + 128, cy * 256 + 128, a)
        per = []
        last, at = g.frames(), None
        for i in range(200):                    # 200 x 4 ms = 40 vsyncs
            c.run_us(4000)
            n = g.frames()
            if n != last:
                if at is not None:
                    per.append(int(round((i - at) * 4.0
                                         / (((n - last) & 0xFFFF) * 19.968))))
                at, last = i, n
        seen |= set(per)
        print(f"       {name:26s} {len(per):2d} frames, "
              f"{sorted(set(per))} vsyncs = "
              f"{[round(p*19.968,1) for p in sorted(set(per))]} ms")
    check(seen == {PACE_N}, "the frame period is LOCKED",
          f"every frame measured {sorted(seen)} vsyncs"
          f" = {[round(p*19.968,1) for p in sorted(seen)]} ms"
          f" = {round(1000/(PACE_N*19.968),2)} fps")

    print(f"\n{'ALL CHECKS PASS' if ok else 'SOMETHING FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
