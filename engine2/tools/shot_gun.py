"""The weapon, off the BOOTED DISC, at rest and at both bob extremes.

    python3 engine2/tools/shot_gun.py [outdir]

The pictures are the front buffer of a CPC 6128 that booted
build/amaze.dsk through RUN"DISC and is sitting in main3.asm's loop.  The
bob offsets are POKED (gun_dx, gun_dy) and more frames are drawn, so each
picture is the blitter's real output at that offset -- not a model.

gun_step is STUBBED TO RET first.  It eases both offsets back towards
rest by one step every frame while the player stands still, so a poked
extreme would be half way home again two frames later; with the stub the
offset stays exactly where it was put and the picture is of that offset.

    gun_rest.png        THE ANCHOR: the centre of the travel, centred
                        horizontally, with gunart.BOB_CUT scanlines hanging
                        below the viewport and not drawn
    gun_up.png          the top of the vertical bob, +4 scanlines -- the
                        one pose that draws the whole sprite
    gun_down.png        the bottom of it, -4 scanlines, 8 rows clipped
    gun_left.png        the left end of the horizontal bob, -2 bytes
    gun_right.png       ...and the right end, +2 bytes
    gun_corner.png      up and left at once, which is the corner of the box
                        the sprite can reach
    gun_wall.png        pressed up against a wall, so the sprite is over
                        a bright near face rather than over the floor

The gun_down / gun_up pair is the point of this phase: rest is now the
MIDDLE of the swing, not the bottom of it, and the sprite is cut off by
the bottom edge at every offset -- which is what makes it read as carried
rather than as hovering in front of the camera.
"""

import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import gunart                                                # noqa: E402
from cpc import CPC                                          # noqa: E402
import bootdisc                                              # noqa: E402

HA, VA, H = gunart.BOB_HA, gunart.BOB_VA, gunart.H
ROWS0 = H - gunart.BOB_CUT - VA          # rows drawn at the bottom of the
                                         # swing; + (gun_dy) at any offset

DSK = os.path.join(_ROOT, "build", "amaze.dsk")
SYM = os.path.join(_ROOT, "build", "e3", "game3.sym")

CORRIDOR = (10 * 256 + 128, 13 * 256 + 128, 0)      # (10,13) facing east
NOSE = (1 * 256 + 80, 13 * 256 + 128, 36)           # up against a wall


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
    bootdisc.start(c)   # past the title screen -- see bootdisc.py
    assert c.mode == 0, f"not in mode 0 after boot: {c.mode}"
    c.poke(s["GUN_STEP"], 0xC9)         # RET: freeze the bob where it is put

    def shot(name, pos, dx, dy):
        c.write_ram(s["PLR_X"], struct.pack("<H", pos[0]))
        c.write_ram(s["PLR_Y"], struct.pack("<H", pos[1]))
        c.poke(s["PLR_A"], pos[2])
        c.poke(s["GUN_DX"], dx + HA)
        c.poke(s["GUN_DY"], dy + VA)
        c.run_frames(30)                # several game frames: both buffers
        c.screenshot(os.path.join(out, name))
        print(f"  {name:18s} dx = {c.peek(s['GUN_DX']) - HA:+d} bytes  "
              f"dy = {c.peek(s['GUN_DY']) - VA:+d} lines  "
              f"{ROWS0 + c.peek(s['GUN_DY'])} of {H} rows drawn, "
              f"{H - ROWS0 - c.peek(s['GUN_DY'])} below the viewport")

    # BOTH offsets are stored BIASED, so the anchor is (BOB_HA, BOB_VA) and
    # the arguments here are the SIGNED swing about it.
    print("in a corridor, at the anchor and at the four bob extremes:")
    shot("gun_rest.png", CORRIDOR, 0, 0)
    shot("gun_up.png", CORRIDOR, 0, +VA)
    shot("gun_down.png", CORRIDOR, 0, -VA)
    shot("gun_left.png", CORRIDOR, -HA, 0)
    shot("gun_right.png", CORRIDOR, +HA, 0)
    shot("gun_corner.png", CORRIDOR, -HA, +VA)
    print("against a near wall, so the sprite sits on a bright face:")
    shot("gun_wall.png", NOSE, 0, -1)
    print(f"still in the game loop: pc = {hex(c.pc)}, mode = {c.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
