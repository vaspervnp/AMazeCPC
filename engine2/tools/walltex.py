"""Wolfenstein-style Mode 0 wall and door textures, drawn procedurally.

WHY PROCEDURAL AND NOT A PNG.  A texture that is generated is a texture
that can be RETUNED -- brick height, bond offset, how hard the top edge is
lit -- without redrawing anything by hand, and every number that decides
the look sits in one place where the Z80 side can read it too.  The same
argument gentab.py makes for every other table in this engine.

MODE 0 PIXELS ARE TWICE AS WIDE AS THEY ARE TALL.  A brick that LOOKS
square on a CRT is therefore half as many pixels across as it is down, and
every size below is in Mode 0 pixels, not in apparent ones.  Getting this
backwards is what makes hand-drawn CPC art come out squashed.

    TEX_W  32 px across  = 64 apparent
    TEX_H  64 px down    = 64 apparent      -> the texture reads square

AND THE FEATURES HAVE TO SURVIVE THE RENDERER.  rastcol.asm samples one
texture BYTE per column pair and writes it to both bytes, so every
horizontal feature is doubled on its way to the screen.  A one-pixel
mortar joint comes out two to four pixels wide and irregular; a two-pixel
joint between big stones comes out looking like a joint.  That is why the
stones here are chunky and the joints are thick -- see the note on
_joints() -- and it is a constraint on the ART, not a defect in it.

Four pens each, which is what a stone needs to have a surface rather than
a colour: a mortar, a shadowed face, the face itself, and a lit edge.
"""

TEX_W, TEX_H = 32, 64

# ---- the wall: blue stone in running bond -------------------------------
#   W_MORTAR  the gap between stones -- the darkest thing on the wall
#   W_SHADE   the stone's own shadowed lower edge
#   W_STONE   the face
#   W_LIT     its lit upper edge
W_MORTAR, W_SHADE, W_STONE, W_LIT = 0, 1, 2, 3

COURSE_N = 2            # courses up the texture, of UNEVEN height
STONES = ([3, 2], [2, 3])           # ...so five big stones a face
MORTAR_PX = 2           # the joint, in pixels -- see _courses on why 2
HJITTER = 6             # how far a course height may stray from even
XJITTER = 4             # ...and a vertical joint from evenly spaced
YJITTER = 3             # ...and how far a single STONE rides up or down


def _lfsr(seed=0xACE1):
    """A fixed 16-bit LFSR.  The speckle has to be REPRODUCIBLE -- the Z80
    reads a baked table, so the art must come out the same every build."""
    x = seed
    while True:
        bit = ((x >> 0) ^ (x >> 2) ^ (x >> 3) ^ (x >> 5)) & 1
        x = (x >> 1) | (bit << 15)
        yield x


def _seg(js, x):
    """Which stone of a course x falls in: the joint at or before it."""
    return max(range(len(js)),
               key=lambda k: -((x - js[k]) % TEX_W))


def _courses():
    """-> [(y0, [joint xs], [vertical offset per stone])].

    BIG BLOCKS, NO TWO ALIKE, AND THE COURSE LINES DO NOT RUN STRAIGHT.
    The first wall was two identical 16-pixel stones a course, eight
    courses, every other course offset by exactly half: a grid, and at
    Mode 0's double-width pixels it read as one.  This is three courses of
    uneven height carrying seven or eight stones of uneven width -- and
    each stone carries its OWN vertical offset, so the mortar line between
    two courses steps up and down as it crosses from one stone to the
    next.  Neighbours therefore differ in height as well as in width,
    which is what stops the eye finding the rows.

    THREE CONSTRAINTS SHAPE IT, and all three are about how it is sampled.

    IT HAS TO WRAP, in both axes.  A face samples this texture across its
    whole width and down its whole height, and the texture repeats, so the
    course heights must sum to exactly TEX_H and the joints must be
    consistent modulo TEX_W -- otherwise a seam runs down or across every
    face.  The heights are jittered and the LAST takes up the slack; the
    joints are taken mod TEX_W; and the offset of course 0 serves as the
    bottom of the last course as well as the top of the first, which is
    what keeps the ragged line continuous across the join.

    EVERY JOINT SITS ON AN EVEN x.  A Mode 0 byte is two pixels and
    rastcol.asm samples one BYTE per column pair, writing it to both -- so
    a feature starting on an odd x lands half in one byte and half in the
    next, and the pair repeats that mixed byte: stone, joint, stone,
    joint.  That is what shredded the vertical joints into stripes.
    Snapped to a byte boundary the joint byte is SOLID mortar and doubling
    it gives a clean four-pixel joint.  The lit edge beside it is two
    pixels wide for the same reason.

    THE VERTICAL OFFSETS ARE NOT SO CONSTRAINED, because a byte is two
    pixels ACROSS and one down: nothing about a row is shared with its
    neighbour, so a course line may step by a single pixel and will be
    drawn as one.
    """
    rnd = _lfsr(0xBEEF)
    base = TEX_H // COURSE_N
    hs, left = [], TEX_H
    for _c in range(COURSE_N - 1):
        h = base - HJITTER + next(rnd) % (2 * HJITTER + 1)
        hs.append(h)
        left -= h
    hs.append(left)

    ns = STONES[next(rnd) & 1]
    out, y0 = [], 0
    for h, n in zip(hs, ns):
        step = TEX_W // n
        off = next(rnd) % TEX_W
        js = set()
        for k in range(n):
            j = off + k * step + (next(rnd) % (2 * XJITTER + 1)) - XJITTER
            js.add((j % TEX_W) & ~1)        # EVEN: a whole byte of mortar
        js = sorted(js)
        vo = [(next(rnd) % (2 * YJITTER + 1)) - YJITTER for _k in js]
        out.append((y0, js, vo))
        y0 += h
    return out


def _bounds():
    """-> per x, the sorted course boundaries through that column.

    Boundary c at column x is y0[c] plus the vertical offset of whichever
    stone of course c covers x.  The list wraps: the top of course 0 is
    also the bottom of the last course, one texture down.
    """
    cs = _courses()
    return [[y0 + vo[_seg(js, x)] for y0, js, vo in cs]
            for x in range(TEX_W)]


def _blobs():
    """A 2x2-pixel noise map -- CHUNKY, not per-pixel.

    One pixel in eight going a shade darker is invisible at Mode 0's
    resolution and worse than invisible once the renderer magnifies a
    near wall: it turns into single-pixel confetti with no scale to it.
    Blobs two pixels across and two down survive being magnified and read
    as pitting in the stone.
    """
    rnd = _lfsr(0x1234)
    w, h = (TEX_W + 1) // 2, (TEX_H + 1) // 2
    return [[(next(rnd) & 7) == 0 for _x in range(w)] for _y in range(h)]


def wall():
    """-> TEX_H rows of TEX_W pen indices, 0..3."""
    cs = _courses()
    bnds = _bounds()
    blobs = _blobs()
    rows = []
    for y in range(TEX_H):
        row = []
        for x in range(TEX_W):
            bs = bnds[x]
            # which stone of which course this pixel belongs to, wrapping
            # at the top: rows above the first boundary are the LAST
            # course, one texture up.
            k = COURSE_N - 1
            for i in range(COURSE_N):
                if bs[i] <= y:
                    k = i
            if y < bs[0]:
                yy = y + TEX_H - bs[COURSE_N - 1]
                ch = bs[0] + TEX_H - bs[COURSE_N - 1]
            else:
                top = bs[k]
                bot = bs[k + 1] if k + 1 < COURSE_N else bs[0] + TEX_H
                yy, ch = y - top, bot - top
            js = cs[k][1]
            dx = min((x - j) % TEX_W for j in js)
            if yy < MORTAR_PX:                  # the joint above the course
                row.append(W_MORTAR)
            elif dx < MORTAR_PX:                # the joint beside the stone
                row.append(W_MORTAR)
            elif yy == MORTAR_PX:               # the stone's lit top edge
                row.append(W_LIT)
            elif yy >= ch - 2:                  # and its shadowed bottom
                row.append(W_SHADE)
            elif dx < MORTAR_PX + 2:            # lit left edge -- TWO
                row.append(W_LIT)               # pixels, so it too fills
                                                # a byte rather than half
                                                # of one
            else:
                row.append(W_SHADE if blobs[y // 2][x // 2] else W_STONE)
        rows.append(row)
    return rows


# ---- the door: a metal slab with a central seam -------------------------
#   D_FRAME  the dark surround and the seam
#   D_METAL  the slab
#   D_LIT    its lit bevel
#   D_PANEL  the warm inset panel -- what makes a door read as a DOOR at a
#            distance, when the seam and the bevels have gone
D_FRAME, D_METAL, D_LIT, D_PANEL = 0, 1, 2, 3

FRAME_PX = 2            # the dark jamb down each side
SEAM_PX = 1             # the split down the middle, where it opens
RIB_PITCH = 8           # vertical striations across the slab
BAND_Y = TEX_H // 2     # the lock band, at eye level
BAND_H = 8


def door():
    """-> TEX_H rows of TEX_W pen indices, 0..3.

    A SLAB, NOT A PAIR OF PANELS.  The first version drew a big inset
    rectangle in each leaf and came out as two orange doors side by side.
    A Wolfenstein door is one metal face with VERTICAL STRIATIONS, a seam
    down the middle where it parts, and one horizontal band carrying the
    lock -- and the striations are what make it read as metal at any size,
    because they survive being shrunk in a way a single big panel does not.

    THE PITCH MATTERS MORE THAN THE PATTERN.  At RIB_PITCH 4 a groove and
    its highlight were half the slab and the door came out a barcode; at 8
    they are a quarter, and the eye reads brushed metal instead of stripes.

    The warm accent is confined to the lock band.  It is the only feature
    that has to be legible from across a room, and keeping it small stops
    the door shouting over the walls.
    """
    rows = []
    cx = TEX_W // 2
    for y in range(TEX_H):
        band = BAND_Y - BAND_H // 2 <= y < BAND_Y + BAND_H // 2
        row = []
        for x in range(TEX_W):
            dx = abs(x - cx)
            if x < FRAME_PX or x >= TEX_W - FRAME_PX:
                row.append(D_FRAME)                     # the jamb
            elif y < 2 or y >= TEX_H - 2:
                row.append(D_FRAME)                     # head and threshold
            elif dx < SEAM_PX:
                row.append(D_FRAME)                     # the parting seam
            elif dx == SEAM_PX and x > cx:
                row.append(D_LIT)                       # its lit right lip
            elif band:
                # the lock band: a dark rail with a lit top and the one
                # warm feature on the door
                if y == BAND_Y - BAND_H // 2:
                    row.append(D_LIT)
                elif y == BAND_Y + BAND_H // 2 - 1:
                    row.append(D_FRAME)
                elif 4 <= dx <= 9:
                    row.append(D_PANEL)                 # the plate
                else:
                    row.append(D_METAL)
            else:
                # THE STRIATIONS ARE GROOVES ONLY -- no lit lip.  Mode 0's
                # greys are 0, 128 and 255 and nothing between, so a
                # highlight beside every groove is a 255-against-128 step
                # on a pixel that is already DOUBLE WIDTH: it came out as a
                # white bar and the door read as a barcode twice over.  A
                # dark groove on flat metal is what brushed steel looks
                # like anyway; the two places light is allowed are the lip
                # of the parting seam and the top of the lock rail, and
                # both of those are single features rather than a rhythm.
                row.append(D_FRAME if (x - FRAME_PX) % RIB_PITCH == 0
                           else D_METAL)
        rows.append(row)
    return rows


# ---- the inks each texture's four pens want ----------------------------
# Given as FIRMWARE ink numbers.  pal.py owns the pen assignment; these say
# what the art needs, and the two get reconciled when it is wired up.
WALL_INKS = [1,    # 0 mortar   (  0,  0,128)  dark navy
             2,    # 1 shade    (  0,  0,255)  blue
             11,   # 2 stone    (  0,128,255)  sky blue
             14]   # 3 lit      (128,128,255)  pastel blue

DOOR_INKS = [0,    # 0 frame    (  0,  0,  0)  black
             13,   # 1 metal    (128,128,128)  grey
             26,   # 2 lit      (255,255,255)  white
             15]   # 3 panel    (255,128,  0)  orange


def stats(rows):
    n = len(rows) * len(rows[0])
    c = [sum(r.count(p) for r in rows) for p in range(4)]
    return [f"{100 * v / n:.0f}%" for v in c]


if __name__ == "__main__":
    for name, rows in (("wall", wall()), ("door", door())):
        print(f"{name}: {TEX_W}x{TEX_H} px = {TEX_W * TEX_H // 2} bytes"
              f"   pen mix {stats(rows)}")
