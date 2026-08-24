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
        self.c.run_frames(500)          # loader + two hud_static passes

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

    print("\n7  FRAME PERIOD (measured, one gap at a time, five samples a"
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
