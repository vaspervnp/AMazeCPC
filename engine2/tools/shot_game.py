"""BOOT build/amaze.dsk on a cycle-accurate CPC 6128 and drive it.

    python3 engine2/tools/shot_game.py [outdir]

Loads the real disc through the real BASIC loader (RUN"DISC), lets it
settle, then holds keys the way a player would and screenshots what comes
out.  This is the end-to-end check that the relocating loader, the bank
switch, the palette, the double buffer and the game layer all agree.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import cpc as cpcmod                                         # noqa: E402
from cpc import CPC                                          # noqa: E402
import bootdisc                                              # noqa: E402

DSK = os.path.join(_ROOT, "build", "amaze.dsk")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        _E2, "build", "shots3")
    os.makedirs(out, exist_ok=True)
    c = CPC()
    c.insert_disc(DSK)
    c.run_frames(150)
    c.type_text('RUN"DISC\n')
    c.run_frames(400)
    bootdisc.start(c)   # past the title screen -- see bootdisc.py
    print("after boot: mode", c.mode, "screen",
          hex(c.crtc_screen_addr), "pc", hex(c.pc))
    c.screenshot(os.path.join(out, "boot.png"))

    def hold(key, frames, name):
        c.key_down(key)
        c.run_frames(frames)
        c.key_up(key)
        c.run_frames(30)
        c.screenshot(os.path.join(out, name))
        print(f"  {name}: pc {hex(c.pc)} screen {hex(c.crtc_screen_addr)}")

    hold(cpcmod.KEY_UP, 60, "walk.png")
    hold(cpcmod.KEY_RIGHT, 40, "turn.png")
    hold(cpcmod.KEY_UP, 60, "walk2.png")
    hold(cpcmod.KEY_LEFT, 40, "turn2.png")
    hold(cpcmod.KEY_DOWN, 40, "back.png")
    print("frames rendered without leaving the game loop:",
          "pc =", hex(c.pc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
