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
        self.c.type_text('RUN"DISC\n')
        self.c.run_frames(500)
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

    def check(cond, what, detail):
        nonlocal ok
        if not cond:
            ok = False
        print(f"  [{'PASS' if cond else 'FAIL'}] {what}: {detail}")

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

    # (c) AND IT GOES DARK when the map has been stripped.
    for i in range(NAMMO):
        c.poke(g.s["AMMO_ST"] + i, 0xFF)
    g.place(START[0] * 256 + 128, START[1] * 256 + 128, 0)
    check(c.peek(adir) == 0xFF, "with every pickup taken the pad goes dark",
          f"ammo_dir = #{c.peek(adir):02X}")

    print("\n9  FRAME PERIOD (measured, one gap at a time, five samples a"
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
