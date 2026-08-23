"""Dump the HUD as it comes out of the emulator, as PNGs.

    python3 engine2/tools/shot_hud.py [outdir]

emu_hud.py proves the bytes are right; this is the other half -- whether the
thing LOOKS like an instrument.  hud.png is the whole 160x200 screen with the
viewport left as poison (so the window the renderer owns is obvious), and
compass_NN.png is the dial alone at eight headings 45 degrees apart.

Pixels are scaled 5x horizontally and 3x vertically, which puts the 160x200
screen back at the 4:3 the monitor shows: a mode-0 pixel is 1.67 times wider
than a scanline is tall, so a circle on screen is 1 byte to 3.33 scanlines
and only at this aspect does the dial look round.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import emu_hud as eh                                            # noqa: E402
import genhud                                                   # noqa: E402
from emu_hud import cpc                                         # noqa: E402
from shot_frame import png, _mode0                              # noqa: E402

SX, SY = 5, 3


def decode(ram, x0, y0, w, h):
    rgb = [list(cpc.ink_rgb(i)) for i in genhud.pal.PEN_INK]
    rows = []
    for y in range(y0, y0 + h):
        line = []
        for bx in range(x0, x0 + w):
            for pix in _mode0(ram[eh.off(bx, y)]):
                line += rgb[pix] * SX
        for _ in range(SY):
            rows.append(line)
    return w * 2 * SX, h * SY, rows


def main(outdir=None):
    outdir = outdir or os.path.join(os.path.dirname(_HERE), "build", "shots")
    os.makedirs(outdir, exist_ok=True)
    rig = eh.Rig()
    ram = rig.once(0)
    w, h, rows = decode(ram, 0, 0, eh.SCR_W, eh.SCR_H)
    png(os.path.join(outdir, "hud.png"), w, h, rows)
    print(f"  hud.png        the whole screen; the viewport is left poisoned")
    cx, cy = genhud.dial_centre()
    x0, y0 = cx - 14, cy - 48
    for i in range(8):
        a = (i * 9) % genhud.N_ANGLES
        ram = rig.upd(a)
        w, h, rows = decode(ram, x0, y0, 28, 96)
        png(os.path.join(outdir, f"compass_{a:02d}.png"), w, h, rows)
    print(f"  compass_NN.png  the dial at 8 headings, 45 degrees apart")
    print(f"written to {outdir}")


if __name__ == "__main__":
    main(*sys.argv[1:])
