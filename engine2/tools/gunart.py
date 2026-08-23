"""The first-person weapon: pixel art, and the run list the Z80 blits.

The sprite sits at the bottom centre of the viewport and is drawn over the
finished 3D view every frame.  It is stored as ONE CONTIGUOUS RUN PER
SCANLINE, which is what makes it cheap: the silhouette of a hand holding a
pistol, seen from behind, has no holes, so no mask is needed and each row is
a straight byte copy.

The art is BUILT FROM A SPEC rather than typed out as forty-odd rows of
characters, because a hand-counted row that is one column short is invisible
in the source and obvious on screen.  Each band says how tall it is, how wide,
and which material it is made of; everything is centred and the widths are
forced even so every run starts and ends on a byte boundary.

Pens, and why these:
    K  0   black          outline and shadow (already the ceiling-far pen)
    G  14  white/grey     the slide.  Pen 14 was MORTAR, which is unused
                          while COURSES is 0 and pointed at the same firmware
                          ink as pen 11 anyway, so it was free.
    W  15  bright white   the highlight down the left of the slide
    S  8   orange         the hand.  Mode 0 has no better skin tone, and the
                          only other user of ink 15 is a door, which is never
                          on screen behind the gun.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cpchw as cpc                                        # noqa: E402

PEN = {"K": 0, "G": 14, "W": 15, "S": 8}
CLEAR = "."


# THE APPROVED DRAWING, restored from build/gun_preview.png.  It is written out
# by hand rather than generated from bands: the taper across the muzzle, the
# step where the slide meets the frame and the way the fist swells under it are
# all shapes a band table cannot say, and two attempts to rebuild it from one
# turned it into a traffic cone and then a brick.
#
# The sprite is TALLER than the space it has: BOB_CUT scanlines fall below the
# viewport and are not drawn.  A weapon cut off by the bottom edge reads as
# held; one that sits fully inside the frame reads as floating.
ART = [
    "............KK..............",
    "...........KGGK.............",
    "...........KGGK.............",
    "..........KGGGGK............",
    "..........KGWGGK............",
    "..........KGWGGK............",
    "..........KGWGGK............",
    "..........KGWGGK............",
    ".........KGGWGGGK...........",
    ".........KGGWGGGK...........",
    ".........KGGWGGGK...........",
    ".........KGGWGGGK...........",
    "........KGGGWGGGGK..........",
    "........KGGGWGGGGK..........",
    "........KGGGWGGGGK..........",
    "........KGKKKKKGGK..........",
    "........KGKGGGKGGK..........",
    "........KGKGGGKGGK..........",
    ".......KGGKGGGKGGGK.........",
    ".......KGGKKKKKGGGK.........",
    ".......KGGGGGGGGGGK.........",
    ".......KGGGGGGGGGGK.........",
    ".......KKGGGGGGGGKK.........",
    "......KSKGGGGGGGGKSK........",
    ".....KSSKKGGGGGGKKSSK.......",
    "....KSSSSKKKKKKKKSSSSK......",
    "....KSSSSSSSSSSSSSSSSK......",
    "...KSSSSSSSSSSSSSSSSSSK.....",
    "...KSSSSSSSSSSSSSSSSSSK.....",
    "...KSSSSSSSSSSSSSSSSSSK.....",
    "..KSSSSSSSSSSSSSSSSSSSSK....",
    "..KSSSSSSSSSSSSSSSSSSSSK....",
    "..KSSSSSSSSSSSSSSSSSSSSK....",
    "..KSSSSSSSSSSSSSSSSSSSSK....",
    "..KSSSSSSSSSSSSSSSSSSSSK....",
    "..KSSSSSSSSSSSSSSSSSSSSK....",
    "..KSSSSSSSSSSSSSSSSSSSSK....",
    "..KSSSSSSSSSSSSSSSSSSSSK....",
]
W = len(ART[0])
H = len(ART)




def check():
    for i, row in enumerate(ART):
        assert len(row) == W, f"row {i} is {len(row)} wide, expected {W}"
        for ch in row:
            assert ch in PEN or ch == CLEAR, f"row {i}: unknown '{ch}'"
        body = row.strip(CLEAR)
        assert CLEAR not in body, (
            f"row {i} has a hole; the blitter copies one contiguous run per "
            f"scanline and cannot skip pixels")
    assert W % 2 == 0, "Mode 0 packs 2 pixels per byte; width must be even"


def rows():
    """-> [(x0_byte, [encoded bytes]), ...] one entry per scanline.

    x0 is in bytes from the left of the sprite; the caller adds the sprite's
    own left edge.  A row that is entirely clear yields None.
    """
    out = []
    for row in ART:
        lo = W - len(row.lstrip(CLEAR))
        hi = len(row.rstrip(CLEAR))
        if lo >= hi:
            out.append(None)
            continue
        lo &= ~1                            # snap outward to byte boundaries
        hi = (hi + 1) & ~1
        data = []
        for x in range(lo, hi, 2):
            a = row[x]
            b = row[x + 1] if x + 1 < W else CLEAR
            # a clear pixel inside the snapped run borrows its neighbour, so
            # the silhouette grows by at most one pixel rather than showing a
            # hole -- the same outward-rounding rule the wall runs use
            if a == CLEAR:
                a = b
            if b == CLEAR:
                b = a
            data.append(cpc.mode0_byte(PEN[a], PEN[b]))
        out.append((lo // 2, data))
    return out


def stats():
    rr = rows()
    return {"bytes": sum(len(r[1]) for r in rr if r),
            "lines": sum(1 for r in rr if r), "w": W, "h": H}


if __name__ == "__main__":
    check()
    s = stats()
    print(f"gun sprite {s['w']}x{s['h']} px, {s['lines']} scanlines, "
          f"{s['bytes']} bytes of run data")
    print(f"  blit ~5 us/byte   = {s['bytes'] * 5 / 1000:.2f} ms")
    print(f"  ~20 us/scanline   = {s['lines'] * 20 / 1000:.2f} ms")
    print(f"  total            ~ {(s['bytes'] * 5 + s['lines'] * 20) / 1000:.2f} ms")
    for r in ART:
        print("   " + r.replace(CLEAR, " "))


# ------------------------------------------------------------------ bob ----
# The weapon sways while the player walks.  Two sine tables at DIFFERENT,
# mutually prime periods give a Lissajous path: smooth, and it does not
# visibly repeat (16 x 23 = 368 frames, about 44 s at 8.35 fps).  An LFSR
# nudges the horizontal phase by 1 or 2 every few frames so the path is
# genuinely aperiodic rather than merely long -- the step stays small, so
# the motion never jumps.
#
# THE SPRITE IS ANCHORED BELOW THE BOTTOM EDGE AND BOBS BOTH WAYS.  It used
# to bob UP ONLY, 0..6 scanlines, so that the blitter never had to clip --
# and the side effect was that the RESTING position was the LOWEST one, so
# every step LIFTED the weapon and the thing read as hovering rather than as
# being carried.  Now BOB_CUT scanlines of the sprite fall below the viewport
# at the CENTRE of the travel and are simply not drawn, and the vertical
# offset swings -BOB_VA..+BOB_VA about that anchor.
#
# What that costs is ONE COMPARISON PER BAND in the blitter -- "stop when
# this row would reach VP_Y + VP_H" -- and nothing else.  It is not
# per-pixel clipping and it is not needed on any other side: the horizontal
# bob is +-BOB_HA whole BYTES and stays far inside the left and right edges,
# and the highest the sprite can ever sit still leaves its last row exactly
# on the bottom edge, so it can never run off the TOP either.  gentab.py's
# self_check asserts all three.
#
# Vertical is in scanlines, horizontal in whole bytes so each row stays a
# plain byte copy.

BOB_VP = 16             # vertical period, frames
BOB_HP = 23             # horizontal period, frames
BOB_VA = 4              # vertical amplitude, scanlines EITHER SIDE of rest
BOB_HA = 2              # horizontal amplitude, BYTES either side
BOB_CUT = 4             # scanlines below the viewport at the centre of the
                        # travel: the anchor that makes it read as HELD


def bob_tables():
    """-> (vertical [-BOB_VA..+BOB_VA], horizontal [-BOB_HA..+BOB_HA]).

    The vertical table is a TRIANGLE and it has to be.  The smoothness rule
    is that no frame may move the sprite by more than one scanline, and a
    swing of 2*BOB_VA = 8 scanlines down and 8 back up inside BOB_VP = 16
    frames is 16 unit moves in 16 frames -- so every frame moves by exactly
    one and there is no freedom left for a sine to shape.  (Keeping the
    period at 16 is what keeps it mutually prime with the horizontal 23.)
    The horizontal has slack and stays the rounded sine it was.
    """
    import math
    # a unit triangle wave, 0 at phase 0 and rising, +1 at a quarter turn
    def tri(p):
        return 1.0 - 4.0 * abs(((p + 0.25) % 1.0) - 0.5)
    vert = [round(BOB_VA * tri(i / BOB_VP)) for i in range(BOB_VP)]
    horiz = [round(BOB_HA * math.sin(2 * math.pi * i / BOB_HP))
             for i in range(BOB_HP)]
    return vert, horiz


def bob_check():
    v, h = bob_tables()
    assert all(-BOB_VA <= t <= BOB_VA for t in v), v
    assert all(-BOB_HA <= t <= BOB_HA for t in h), h
    assert min(v) == -BOB_VA and max(v) == BOB_VA, v
    assert min(h) == -BOB_HA and max(h) == BOB_HA, h
    # smoothness: no frame may move the gun more than one step in either axis
    for t in (v, h):
        for i in range(len(t)):
            d = abs(t[(i + 1) % len(t)] - t[i])
            assert d <= 1, f"step of {d} in {t}"
    return v, h
