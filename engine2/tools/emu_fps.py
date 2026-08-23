"""MEASURE the game cadence of build/amaze.dsk, in vsync periods.

    python3 engine2/tools/emu_fps.py

Boots the real disc, puts the player in a named place with a poke, and
counts (frame_ctr) over a known number of 50 Hz CPC frames.

SUPERSEDED by engine2/tools/emu_pace.py, and kept only because the
"before" numbers in main3.asm's PACING note came from here.  Two reasons
not to trust it now:

  * it AVERAGES.  A run of 80 ms frames with one 140 ms frame in it comes
    out at 85 and looks locked.  emu_pace.py reports every gap on its own.
  * it teleports the player into a RUNNING frame, which can send the
    march's flood over its own stack -- see emu_pace.py:Rig.place.
"""

import os
import addrs
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

from cpc import CPC                                          # noqa: E402

DSK = os.path.join(_ROOT, "build", "amaze.dsk")
SYM = os.path.join(_ROOT, "build", "e3", "game3.sym")

# (name, cell x, cell y, heading) -- the scenarios frame.asm names
PLACES = [
    ("start, along the corridor", 10, 13, 0),
    ("nose against a wall", 10, 13, 54),
    ("tight corner", 1, 13, 68),
    ("junction", 7, 7, 0),
    ("open cell, off axis", 9, 1, 21),
    ("long sight line", 1, 1, 18),
]


def syms():
    out = {}
    for line in open(SYM):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            out[p[0].upper()] = int(p[1][1:], 16)
    return out


def sweep(c, s, n, seed=7):
    """Cadence over n states drawn uniformly from the reachable space:
    every open cell x 8x8 sub-cell offsets inside the 0.25 collision box
    x every heading."""
    import random
    solid = c.read_ram(addrs.SOLID, 256)
    open_cells = [(i % 16, i // 16) for i in range(256) if solid[i] == 0]
    rnd = random.Random(seed)
    hist = {}
    for _ in range(n):
        cx, cy = rnd.choice(open_cells)
        fx = 64 + rnd.randrange(8) * 16
        fy = 64 + rnd.randrange(8) * 16
        a = rnd.randrange(72)
        c.write_ram(s["PLR_X"], struct.pack("<H", cx * 256 + fx))
        c.write_ram(s["PLR_Y"], struct.pack("<H", cy * 256 + fy))
        c.poke(s["PLR_A"], a)
        c.run_frames(10)
        n0 = struct.unpack("<H", c.read_ram(s["FRAME_CTR"], 2))[0]
        c.run_frames(40)
        n1 = struct.unpack("<H", c.read_ram(s["FRAME_CTR"], 2))[0]
        k = (n1 - n0) & 0xFFFF
        if k == 0:
            continue
        per = int(round(40.0 / k))
        hist[per] = hist.get(per, 0) + 1
    return hist


def main():
    s = syms()
    c = CPC()
    c.insert_disc(DSK)
    c.run_frames(150)
    c.type_text('RUN"DISC\n')
    c.run_frames(400)
    print(f"{'':30s} {'game frames':>12s} {'vsyncs each':>12s} {'ms':>7s}"
          f" {'fps':>6s}")
    for (name, cx, cy, a) in PLACES:
        c.write_ram(s["PLR_X"], struct.pack("<H", cx * 256 + 128))
        c.write_ram(s["PLR_Y"], struct.pack("<H", cy * 256 + 128))
        c.poke(s["PLR_A"], a)
        c.run_frames(20)                        # settle
        n0 = struct.unpack("<H", c.read_ram(s["FRAME_CTR"], 2))[0]
        c.run_frames(200)                       # 200 vsyncs = 4.00 s
        n1 = struct.unpack("<H", c.read_ram(s["FRAME_CTR"], 2))[0]
        n = (n1 - n0) & 0xFFFF
        per = 200.0 / n if n else 0
        print(f"{name:30s} {n:12d} {per:12.2f} {per * 20:7.1f}"
              f" {50.0 / per if per else 0:6.1f}")

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    hist = sweep(c, s, n)
    tot = sum(hist.values())
    print(f"\ncadence over {tot} states drawn from the reachable space:")
    for per in sorted(hist):
        print(f"  {per} vsyncs = {per*20:3d} ms = {50.0/per:4.1f} fps"
              f"   {hist[per]:5d}  {100.0*hist[per]/tot:5.1f}%"
              f"   cell crossing {256.0/24*per*0.020:.2f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
