"""The amaze3 screenshots, taken off the BOOTED DISC.

    python3 engine2/tools/shot_amaze3.py [outdir]

Every picture below is the front buffer of a CPC 6128 that booted
build/amaze.dsk through RUN"DISC and is sitting in main3.asm's loop --
not a render harness, not a Python model.  The player is placed by poking
plr_x / plr_y / plr_a, which is the same 8.8 / 0..71 state the keys
produce, and the game is then left to draw several frames of its own.

    amaze3_corridor.png       looking straight down a corridor
    amaze3_turn5.png          the same place, heading + 1 = 5 degrees
    amaze3_turn45.png         the same place, heading + 9 = 45 degrees
    amaze3_between.png        standing 0.75 / 0.25 of the way into a cell
    amaze3_door_shut.png      a door, shut
    amaze3_door_opening.png   two game frames after SPACE
    amaze3_door_open.png      fully open, and see-through
"""

import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import cpc as cpcmod                                         # noqa: E402
from cpc import CPC                                          # noqa: E402

sys.path.insert(0, _HERE)
import addrs                                                 # noqa: E402

DSK = os.path.join(_ROOT, "build", "amaze.dsk")
SYM = os.path.join(_ROOT, "build", "e3", "game3.sym")
SOLID = addrs.SOLID

CORRIDOR = (10 * 256 + 128, 13 * 256 + 128, 0)   # (10,13) faces east


def syms():
    out = {}
    for line in open(SYM):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            out[p[0].upper()] = int(p[1][1:], 16)
    return out


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_ROOT, "build")
    os.makedirs(out, exist_ok=True)
    s = syms()
    c = CPC()
    c.insert_disc(DSK)
    c.run_frames(150)
    c.type_text('RUN"DISC\n')
    c.run_frames(500)
    assert c.mode == 0, f"not in mode 0 after boot: {c.mode}"

    def shot(name, px, py, a, settle=30):
        c.write_ram(s["PLR_X"], struct.pack("<H", px))
        c.write_ram(s["PLR_Y"], struct.pack("<H", py))
        c.poke(s["PLR_A"], a)
        c.run_frames(settle)
        path = os.path.join(out, name)
        c.screenshot(path)
        print(f"  {name:26s} plr ({px:04X},{py:04X}) = "
              f"({px/256.0:6.3f},{py/256.0:6.3f}) heading {a:2d} "
              f"= {a*5:3d} deg   base {hex(c.crtc_screen_addr)}")

    px, py, a = CORRIDOR
    print("corridor, and the same corridor turned:")
    shot("amaze3_corridor.png", px, py, a)
    shot("amaze3_turn5.png", px, py, (a + 1) % 72)
    shot("amaze3_turn45.png", px, py, (a + 9) % 72)

    print("part way between cells (free movement, not on a cell centre):")
    shot("amaze3_between.png", 10 * 256 + 192, 13 * 256 + 64, 2)

    print("a door, opening.  The door is at (5,3).  SPACE only reaches 1.25")
    print("cells (game.asm), and a wall one cell away exactly fills the")
    print("viewport height, so the door is PRESSED for up close and")
    print("PHOTOGRAPHED from (3.5,3.5), two cells back down the passage.")
    door = SOLID + 3 * 16 + 5
    far = (3 * 256 + 128, 3 * 256 + 128, 0)
    near = (4 * 256 + 100, 3 * 256 + 128, 0)

    def go(pos, settle=40):
        c.write_ram(s["PLR_X"], struct.pack("<H", pos[0]))
        c.write_ram(s["PLR_Y"], struct.pack("<H", pos[1]))
        c.poke(s["PLR_A"], pos[2])
        c.run_frames(settle)

    def door_state(tag, name):
        st = c.peek(s["DOOR_ST"])       # 2 shut .. 6 open, one step a frame
        print(f"  {tag:42s} SOLID = {c.peek(door)}  door_st = {st}")
        c.screenshot(os.path.join(out, name))

    go(far)
    door_state("shut, seen from two cells back", "amaze3_door_shut.png")
    go(near)
    door_state("shut, up close (a door face fills the view)",
               "amaze3_door_closeup.png")
    c.key_down(cpcmod.KEY_SPACE)
    c.run_frames(6)
    c.key_up(cpcmod.KEY_SPACE)
    # the run is four steps at one a game frame, i.e. under half a second:
    # step one CPC frame at a time and stop the moment it is part way.
    for _ in range(60):
        c.run_frames(1)
        if 2 < c.peek(s["DOOR_ST"]) < 6:
            break
    door_state("part way through the run", "amaze3_door_opening.png")
    c.run_frames(120)
    print(f"  after the run: SOLID = {c.peek(door)}, "
          f"door_st = {c.peek(s['DOOR_ST'])}")
    go(far)
    door_state("open, from the same spot as the first picture",
               "amaze3_door_open.png")
    print("  NOTE: engine2's quad carries only (kind, k), so a door part way")
    print("  open is still drawn as a whole door face -- the middle picture")
    print("  is a real intermediate STATE, not an intermediate image.")
    print(f"still in the game loop: pc = {hex(c.pc)}, mode = {c.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
