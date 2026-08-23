"""The enemy: a guard sprite, quantised to Mode 0 and cut into blitter runs.

The art comes from engine2/art/guard/*.png -- seven poses (four of a walk
cycle, one standing, two firing) extracted from the reference animation and
cropped to ONE COMMON canvas, so the figure cannot jitter sideways between
poses.  Everything below is derived from those files at build time; there is
no hand-drawn copy to fall out of step with them.

UNLIKE THE WEAPON, an enemy cannot be one contiguous run per scanline -- a
standing figure has a gap between the legs and between an arm and the body,
and filling those would paint the maze out behind him.  So each scanline is a
LIST OF SEGMENTS: a start byte and a run of pre-encoded bytes.  That is the
same shape of data the wall rasteriser already consumes, so there is no mask
and no read-modify-write; a two-segment row costs one extra setup and that is
the entire price of transparency here.

Five sizes are baked so he grows as he closes.  They are all sampled from the
same source, and the sampler snaps every segment to a byte boundary, which is
what keeps each row a plain byte copy at every size.

Pens are ones the palette already spends elsewhere -- no new inks:
    0   black          outline, boots, the weapon
    14  white/grey     helmet
    8   orange         uniform and face
    15  bright white   webbing and highlights
    3   bright blue    trousers/boots
    7   bright yellow  the muzzle flash, and only that
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cpchw as cpc                                        # noqa: E402
import pal                                                 # noqa: E402

ART_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "art", "guard")

# Pose order is the order the Z80 indexes them by.  walk0..walk3 is the cycle;
# stand is what he shows when idle; shoot1 is the flash frame.
POSES = ["walk0", "walk1", "walk2", "walk3", "stand", "shoot0", "shoot1"]
WALK = (0, 1, 2, 3)
STAND, SHOOT, FLASH = 4, 5, 6

# Sprite width in PIXELS at each distance band, nearest first.  Even, so every
# segment starts and ends on a byte boundary.
SIZES = [24, 18, 12, 8, 6]

# The pens the quantiser may choose from.  Restricting it to these keeps the
# guard inside the palette the walls and HUD already agreed on.
PENS = [0, 14, 8, 15, 2, 7]

ALPHA_MIN = 128         # below this the source pixel is treated as clear


def _pen_rgb():
    return {p: cpc.ink_rgb(pal.PEN_INK[p]) for p in PENS}


def _classify(rgb):
    """Pick a pen by HUE, not by nearest RGB.

    Nearest-RGB is wrong here and it is worth saying why: the guard's uniform
    is a medium brown around (140,100,60), and in any weighted RGB metric that
    is CLOSER TO GREY (128,128,128) than to the only warm pen available,
    orange (255,128,0).  Quantising by distance therefore painted the whole
    uniform grey with orange speckles where the highlights happened to tip
    over.  Classifying by hue keeps the uniform one flat colour, which is what
    reads as clothing at twenty-four pixels tall.
    """
    r, g, b = rgb
    mx, mn = max(rgb), min(rgb)
    luma = (2 * r + 4 * g + 3 * b) // 9
    sat = mx - mn

    if luma < 55:                       # boots, weapon, deep shadow
        return 0
    if sat < 40:                        # steel helmet and its shading
        return 15 if luma > 190 else 14
    if b > r and b > g:                 # trousers
        return 2
    if r > 235 and g > 200 and b < 110:  # the muzzle flash, and only that:
        return 7                        # a looser rule speckled the uniform
    return 8                            # everything warm: uniform and face


def _nearest(rgb, table):
    return _classify(rgb)


def load(pose):
    from PIL import Image
    return Image.open(os.path.join(ART_DIR, pose + ".png")).convert("RGBA")


def quantise(pose, w):
    """-> rows of pen indices, or None for a clear pixel, at width w."""
    im = load(pose)
    sw, sh = im.size
    h = max(1, round(sh * w / sw))
    im = im.resize((w, h), 3)           # bicubic, then snap: softer edges read
    px = im.load()                      # better than nearest at these sizes
    table = _pen_rgb()
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b, a = px[x, y]
            row.append(None if a < ALPHA_MIN else _nearest((r, g, b), table))
        rows.append(row)
    return rows


def segments(rows):
    """-> per scanline, a list of (x0_byte, [encoded bytes]).

    A byte is emitted if EITHER of its two pixels is solid, and a clear pixel
    inside an emitted byte borrows its neighbour -- the same outward-rounding
    rule the walls and the weapon use, so the silhouette grows by at most one
    pixel instead of showing a hole.
    """
    out = []
    for row in rows:
        w = len(row)
        segs, cur = [], None
        for x in range(0, w - 1, 2):
            a, b = row[x], row[x + 1]
            if a is None and b is None:
                cur = None
                continue
            if a is None:
                a = b
            if b is None:
                b = a
            byte = cpc.mode0_byte(a, b)
            if cur is None:
                cur = (x // 2, [])
                segs.append(cur)
            cur[1].append(byte)
        out.append(segs)
    return out


def build():
    """-> {pose: {width: [ [ (x0,[bytes]), ... ] per scanline ] }}"""
    return {p: {w: segments(quantise(p, w)) for w in SIZES} for p in POSES}


def stats():
    all_ = build()
    out = {}
    for w in SIZES:
        worst = None
        for p in POSES:
            segs = all_[p][w]
            nb = sum(len(d) for r in segs for _, d in r)
            ns = sum(len(r) for r in segs)
            c = {"pose": p, "h": len(segs), "bytes": nb, "segs": ns,
                 "us": nb * 5 + ns * 20}
            if worst is None or c["us"] > worst["us"]:
                worst = c
        out[w] = worst
    return out


def total_bytes():
    all_ = build()
    return sum(len(d) for p in POSES for w in SIZES
               for r in all_[p][w] for _, d in r)


if __name__ == "__main__":
    print(f"{len(POSES)} poses x {len(SIZES)} sizes")
    for w, s in stats().items():
        print(f"  {w:2d}x{s['h']:2d}px  worst pose {s['pose']:6s}"
              f"  {s['bytes']:4d} bytes  {s['segs']:3d} segments"
              f"  ~{s['us'] / 1000:.2f} ms")
    print(f"  all poses, all sizes: {total_bytes()} bytes of run data")
    art = build()
    for p in ("walk0", "shoot1"):
        print(f"  -- {p} at {SIZES[0]}px --")
        for row in quantise(p, SIZES[0]):
            print("   " + "".join("." if c is None else "%X" % c for c in row))
