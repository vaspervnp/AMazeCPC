"""Render whole frames with tst_frame.asm and dump them as PNGs.

    python3 engine2/tools/shot_frame.py [outdir]

An eyeball check on top of emu_frame.py's byte-exact verification: the
background bands, the depth ramp and the painter order all have to LOOK
right, not just match the model.  One PNG per named scenario, plus a
turn-in-place strip so the 5-degree steps can be seen to be smooth.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import emu_frame as ef                                       # noqa: E402
import pal                                                   # noqa: E402
from emu_frame import cpc                                    # noqa: E402


def png(path, w, h, rows):
    """Minimal RGB PNG writer -- no PIL in this environment."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(
            ">I", zlib.crc32(c) & 0xFFFFFFFF)
    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b""))


def decode(ram, c, scale=3):
    """The viewport rectangle of a mode-0 buffer -> PNG rows (RGB, scaled)."""
    rgb = [list(cpc.ink_rgb(i)) for i in pal.PEN_INK]
    rows = []
    for r in range(c.VP_H):
        y = c.VP_Y + r
        base = (y & 7) * 0x800 + (y >> 3) * 80 + c.VP_BX
        line = []
        for bx in range(c.VP_BW):
            b = ram[base + bx]
            for pix in _mode0(b):
                line += rgb[pix] * scale
        for _ in range(scale):
            rows.append(line)
    return c.VP_BW * 2 * scale, c.VP_H * scale, rows


def _mode0(b):
    p0 = ((b >> 7) & 1) | ((b >> 2) & 2) | ((b >> 3) & 4) | ((b << 2) & 8)
    p1 = ((b >> 6) & 1) | ((b >> 1) & 2) | ((b >> 2) & 4) | ((b << 3) & 8)
    return p0, p1


def main(outdir=None):
    outdir = outdir or os.path.join(os.path.dirname(_HERE), "build", "shots")
    os.makedirs(outdir, exist_ok=True)
    rig = ef.Rig()
    c = rig.cfg
    grid, solid = ef.load()
    for name, px, py, a in ef.scenarios(grid, solid):
        ram, q = rig.run_once(px, py, a, poison=0)
        w, h, rows = decode(ram, c)
        f = name.split(",")[0].replace(" ", "_").replace("(", "").replace(
            ")", "")
        png(os.path.join(outdir, f + ".png"), w, h, rows)
        print(f"  {f}.png   {len(q)} quads")
    # a turn in place, 8 headings 45 deg apart
    _n, px, py, a0 = ef.scenarios(grid, solid)[0]
    for i in range(8):
        ram, q = rig.run_once(px, py, (a0 + 9 * i) % 72, poison=0)
        w, h, rows = decode(ram, c)
        png(os.path.join(outdir, f"turn{i}.png"), w, h, rows)
    print(f"  turn0..7.png  a spin in place, 45 deg apart")
    print(f"written to {outdir}")


if __name__ == "__main__":
    main(*sys.argv[1:])
