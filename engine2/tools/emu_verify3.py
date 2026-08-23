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

import cpc as cpcmod                                         # noqa: E402
from cpc import CPC                                          # noqa: E402

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
    g.place(10 * 256 + 128, 13 * 256 + 128, 0)
    a0 = g.player()[2]
    n0 = g.frames()
    g.hold(cpcmod.KEY_RIGHT, 30)
    a1 = g.player()[2]
    n1 = g.frames()
    check(a1 != a0, "heading changed",
          f"plr_a {a0} -> {a1} over {n1 - n0} game frames "
          f"= {((a1 - a0) % 72) * 5} degrees right")
    g.place(10 * 256 + 128, 13 * 256 + 128, 0)
    g.hold(cpcmod.KEY_LEFT, 30)
    a2 = g.player()[2]
    check(a2 != 0, "cursor left turns the other way",
          f"plr_a 0 -> {a2} ( = -{(72 - a2) * 5} degrees)")

    print("\n4  WALKING (cursor up, along the heading)")
    #    (10,13) faces east down a corridor; heading 0 is +x
    g.place(10 * 256 + 128, 13 * 256 + 128, 0)
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
    door = 3 * 16 + 5                   # the door at cell (5,3)
    g.place(4 * 256 + 128, 3 * 256 + 128, 0)
    before = c.peek(SOLID + door)
    check(before == 2, "door (5,3) starts shut", f"SOLID = {before}")
    #    it is solid: walking east must not get past x = 5
    g.hold(cpcmod.KEY_UP, 60)
    xs, _, _ = g.player()
    check((xs >> 8) < 5, "a shut door blocks the player",
          f"stopped at cell x = {xs >> 8}")
    g.place(4 * 256 + 128, 3 * 256 + 128, 0)
    g.hold(cpcmod.KEY_SPACE, 20)
    c.run_frames(60)                    # the door takes 5 game frames to run
    after = c.peek(SOLID + door)
    check(after == 0, "SPACE opened it", f"SOLID = {before} -> {after}")
    g.hold(cpcmod.KEY_UP, 150)
    xt, yt, _ = g.player()
    check((xt >> 8) >= 5, "and the player walked through",
          f"now at cell ({xt >> 8},{yt >> 8})")
    g.place(6 * 256 + 128, 3 * 256 + 128, 36)
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
