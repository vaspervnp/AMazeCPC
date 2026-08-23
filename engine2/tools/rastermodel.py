"""Bit-exact Python model of engine2/src/raster.asm.

This file is the SPEC for the rasteriser, the way projmodel.py is the spec for
the projector: every integer operation here has a one-to-one counterpart in the
Z80, and engine2/tools/emu_rast.py asserts that the Z80 paints EXACTLY the
pixels this model says it should.

WHAT A RUN IS
    (row, end_byte, npush)      row     viewport-relative scanline, 0..VP_H-1
                                end_byte  ONE PAST the right end, 0..VP_BW
                                npush   PUSH DE count; the run is 2*npush
                                        bytes and STARTS at end_byte-2*npush
That is exactly the pair of numbers src/render.asm's span records carry, and
the pair raster.asm computes per scanline.  Runs are byte granular and of even
length because PUSH DE writes two bytes, so an odd width has to round; it
rounds OUTWARD, npush = (w+1)>>1, which takes the extra byte on the LEFT
because PUSH walks backwards from the end.  Rounding inward (w>>1) is what
left a 2-pixel stripe of background between adjacent faces -- see the RUNS
note in raster.asm, and engine2/tools/emu_sliver.py, which counts them.

THE QUAD RECORD kernel.asm hands over, and every function here takes:

    (blo, bhi, hlo, hhi, kind, k)

    blo, bhi   byte columns of the shorter and the taller endpoint, 0..VP_BW
    hlo, hhi   the projected HALF heights there, Q12.4 scanlines, hlo <= hhi
    kind       0 wall, 1 door        k   L1 cell distance 1..7

    The projector emits it in that form (projmodel.pack_quad): rounding x to
    bytes, keeping hh instead of ytop/ybot, and pairing each height with its
    own column are all free there and each of them used to cost the
    rasteriser work per quad.

THE SHAPE
    A quad has vertical sides at the two byte columns and straight top and
    bottom edges, so it is a top wedge, a constant-width body, and a bottom
    wedge.  There is no pitch and the camera is at wall mid-height, so
    ytop and ybot are CY_Q4 -+ hh -- the two wedges are mirror images about
    the horizon row and are generated together, one interpolation per PAIR
    of scanlines.  See the header of raster.asm for why that also removes
    all vertical clipping arithmetic and any need for a divide.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import gentab                                              # noqa: E402
import pal                                                 # noqa: E402


class Cfg:
    """The viewport, straight out of engine2/src/vpcfg.inc."""

    def __init__(self, vp=None):
        v = vp or gentab.load_vpcfg()
        self.VP_BX = v["VP_BX"]
        self.VP_BW = v["VP_BW"]
        self.VP_Y = v["VP_Y"]
        self.VP_H = v["VP_H"]
        self.CYH = v["CYH"]
        self.CY_Q4 = v["CY_Q4"]
        self.XMAX_Q4 = v["XMAX_Q4"]
        self.MAXPUSH = v["MAXPUSH"]
        self.COURSES = v["COURSES"]
        assert self.CY_Q4 == self.CYH * 16
        assert self.CYH * 2 == self.VP_H
        assert self.MAXPUSH * 2 == self.VP_BW


DEFAULT = None


def cfg():
    global DEFAULT
    if DEFAULT is None:
        DEFAULT = Cfg()
    return DEFAULT


def unpack(q, c=None):
    """One quad record -> everything raster.asm derives from it.

    -> (bhi, blo, hhi, hlo, bb, bw, left_tall)

    The record already carries the byte columns and the half heights,
    paired so that hhi belongs to bhi (projmodel.pack_quad), so ONE signed
    subtraction settles all the rest: bhi - blo is the Bresenham numerator
    D, its sign is the step direction, its magnitude is the body width
    (because {bhi, blo} is {ba, bb} in some order), and that sign ALSO
    says which endpoint is the taller -- bhi >= blo exactly when it is the
    right-hand one.  raster.asm:rq_tall_done is this and nothing else.
    """
    c = c or cfg()
    blo, bhi, hlo, hhi, kind, k = q
    assert 0 <= blo <= c.VP_BW and 0 <= bhi <= c.VP_BW, (blo, bhi)
    assert 0 <= hlo <= hhi, (hlo, hhi)
    # the projector's rule, and the rasteriser depends on it: a face that
    # starts at column 0 has an EVEN right column, so no run it produces
    # ever has to be widened past the viewport's left edge.
    assert min(blo, bhi) or not (max(blo, bhi) & 1), (blo, bhi)
    d = bhi - blo
    if d < 0:                                   # LEFT endpoint is taller
        return bhi, blo, hhi, hlo, blo, -d, True
    return bhi, blo, hhi, hlo, bhi, d, False


def raster_quad(q, c=None):
    """One 6-tuple quad RECORD -> the list of runs, in the order raster.asm
    emits them (body top-to-bottom, then each wedge pair outward from the
    horizon).
    """
    c = c or cfg()
    RC = c.CYH
    bhi, blo, hhi, hlo, bb, bw, left_tall = unpack(q, c)
    # rq_lt0: pinned at column 0 with the moving edge on the RIGHT is the
    # one shape that cannot take its odd byte on the left, so it steps the
    # moving edge in WORDS and is even by construction.  bb is even there.
    word = left_tall and bhi == 0

    jlo = RC if hlo >= RC * 16 else (hlo >> 4)  # last CONSTANT-width row
    jhiu = hhi >> 4                             # unclipped end of the wedge
    jhi = min(RC, jhiu)

    runs = []

    # ---- body: rows RC-jlo .. min(VP_H-1, RC+jlo), span [ba, bb] ----
    if bw:
        npush = (bw + 1) >> 1               # ceil: the odd byte goes LEFT
        r0 = RC - jlo
        r1 = min(c.VP_H - 1, RC + jlo)
        for r in range(r0, r1 + 1):
            runs.append((r, bb, npush))

    # ---- wedges: one Bresenham step and TWO scanlines per j ----
    nsteps = jhi - jlo
    if nsteps > 0:
        D = abs(bhi - blo)
        step = 1 if bhi >= blo else -1
        b = blo
        if word:                                # words, not bytes
            D = b = blo >> 1
        # The interpolation runs in u -- HALF HEIGHTS -- not in whole rows.
        # The coverage rule is u = 16*j <= h(x) and h is linear in x, so the
        # moving edge is linear in u; jlo = hlo>>4 and jhiu = hhi>>4 are
        # TRUNCATIONS of that, and running the Bresenham over jlo..jhiu
        # instead walks the edge across its whole travel in slightly fewer
        # rows.  The edge then arrives at the pinned column early and a
        # wedge one or two rows tall loses its span altogether.
        N = hhi - hlo                           # > 0 whenever nsteps > 0
        # Step j means u = 16*j, which is f = hlo & 15 BELOW hlo, so the
        # accumulator starts D*f short.  The -N makes the division FLOOR
        # rather than round-to-nearest: the moving edge then LAGS to the
        # byte boundary outside the exact edge, so the run covers all of
        # the record's own geometry rather than splitting a byte of it --
        # the same outward rounding as npush and project.asm's columns.
        acc = -(D * (hlo - 16 * jlo)) - N
        # hh <= 6144 at the near plane (projmodel.HTAB) and D <= VP_BW, so
        # the accumulator stays inside a SIGNED 16-bit word: raster.asm
        # tests its sign with BIT 7,H.
        assert -32768 <= acc and 16 * D <= 32767, (acc, D)
        for i in range(nsteps):
            j = jlo + 1 + i
            acc += 16 * D
            while acc >= 0:
                acc -= N
                b += step
            if word:
                e, w = 2 * b, 2 * b             # [0, 2b), even by construction
            elif left_tall:
                e, w = b, b - bhi               # run ends at the moving edge
            else:
                e, w = bhi, bhi - b             # run ends at the pinned edge
            npush = (w + 1) >> 1                # ceil: the odd byte goes LEFT
            if npush:
                ru = RC - j
                runs.append((ru, e, npush))
                if ru != 0:                     # row RC+RC is off the bottom
                    runs.append((RC + j, e, npush))
    return runs


# =====================================================================
#  COURSE JOINTS -- the stone look, and the bit-exact spec for
#  raster.asm:raster_joint.
#
#  THREE COURSES PER WALL CELL, AND THE COUNT MUST BE ODD.  The camera
#  sits at wall mid-height, so a boundary at v = 0.5 would project to a
#  DEAD HORIZONTAL line across the whole screen at the horizon row and
#  read as a rendering artefact.  An odd count puts the boundaries either
#  side of eye level -- v = 1/3 and 2/3 -- where they converge on the
#  vanishing point like real masonry.  2 and 4 look broken; 3 looks right.
#
#  THE BOUNDARY IS FREE TO DERIVE.  At a fixed screen x the projection of
#  wall height is LINEAR, so the boundary y at each end of the face is a
#  straight interpolation between that end's own top and bottom y --
#  no re-projection, no march, no new face.  And because the quad record
#  is already written about the horizon (ytop = CY - h, ybot = CY + h),
#  the interpolation collapses:
#
#      v = 1/3   ->   y = CY - h/3          u = h/3, ABOVE the horizon
#      v = 2/3   ->   y = CY + h/3          u = h/3, BELOW it
#
#  -- the SAME u.  So both joints of a face are one pass of the same
#  mirrored row loop the wedge already uses, and the whole geometry is
#  "the line u = h(x)/3", thickened by a scanline either side.
#
#  IT IS NOT DRAWN AS AN UNDERPASS.  Painting the face in mortar and then
#  insetting three stones on top -- which is what the Python preview did,
#  prototype/free-angle/stone.py -- doubles the fill.  The face is drawn
#  EXACTLY as before, and the two joints are overdrawn as thin bands.
#
#  LEVEL OF DETAIL.  No joints past k = JOINT_KMAX.  Beyond about three
#  and a half cells a whole course is thinner than the joint itself and
#  the joints become noise.
# =====================================================================

JOINT_KMAX = 3          # L1 depth key, straight out of the quad record
N_COURSES = 3           # and it must be ODD -- see above


def joint_rows(q, c=None):
    """-> (j0, j1e, D, N, bA, bB) or None -- the row range the two course
    boundaries of this face occupy, counted OUTWARD from the horizon like
    every other row index in this file, and the Bresenham's terms.

    j0 = floor(hlo/48) and j1 = floor(hhi/48) are the rows where the line
    u = h(x)/3 leaves the short end and reaches the tall one; j1e = j1+1
    is the thickening row.  Both are clipped to the horizon row RC, past
    which there is no viewport left.
    """
    c = c or cfg()
    RC = c.CYH
    blo, bhi, hlo, hhi, kind, k = q
    if kind or k > JOINT_KMAX:
        return None
    D = abs(bhi - blo)
    if D == 0:                          # the face itself paints nothing
        return None
    # (3*RC+3)*16: the first hlo whose row would be past the horizon, so
    # the WHOLE joint is off the viewport -- and the first index the
    # DIV3 lookup would be asked for out of range.
    off = (3 * RC + 3) * 16
    if hlo >= off:
        return None
    j0 = (hlo >> 4) // 3
    j1 = RC if hhi >= off else (hhi >> 4) // 3
    j1e = min(j1 + 1, RC)
    return j0, j1e, D, hhi - hlo, blo, bhi


def joint_runs(q, c=None):
    """The two course boundaries of one wall face, as runs, in the order
    raster.asm:raster_joint emits them (outward from the horizon, upper
    scanline then its mirror)."""
    c = c or cfg()
    RC = c.CYH
    r = joint_rows(q, c)
    if r is None:
        return []
    j0, j1e, D, N, bA, bB = r
    step = 1 if bB >= bA else -1
    # The trailing edge P lags the leading edge C by two rows, so the span
    # at row r is [E(r-1), E(r+1)] -- one scanline of line plus one of
    # thickening, which is what makes a square-on joint 2 scanlines tall
    # and a steeply raked one 2 rows' worth of x wide.
    P, cur = bA, bA
    if N == 0:
        # a wall seen square on: the boundary is one horizontal line the
        # full width of the face, and there is no interpolation to do.
        cur = bB
    else:
        f = (q[2] - 48 * j0)            # hlo mod 48, 0..47
        acc = -(D * f) - N
    runs = []
    for row in range(j0, j1e + 1):
        prev = cur
        if N:
            acc += 48 * D
            while acc >= 0:
                acc -= N
                cur += step
            cur = min(cur, bB) if step > 0 else max(cur, bB)
        left, right = (P, cur) if cur >= P else (cur, P)
        w = right - left
        if w == 0:
            w = 1                       # a steep joint still needs a byte
        if left == 0 and (w & 1):
            # the odd byte is taken on the LEFT by npush, and there is no
            # column -1: take it on the right instead.  right < VP_BW here
            # because VP_BW is even and right == w is odd.
            w += 1
            right += 1
        n = (w + 1) >> 1
        if right < 2 * n:
            # the row writes [right - 2n, right-1], so it would start left
            # of column 0.  Widen to the RIGHT instead of dropping a push,
            # which keeps the joint the same thickness; there is always
            # room, because this only fires within two bytes of column 0.
            # raster.asm:rj_rok carries the same rule, and the reason it is
            # needed is written out there: the joint's two edges collapse
            # onto each other on its last row.
            right = 2 * n
        runs.append((RC - row, right, n))
        if RC - row != 0:               # row RC+RC is off the bottom
            runs.append((RC + row, right, n))
        if N:
            P = prev
    return runs


def joint_colour(mortar=None):
    """The solid Mode 0 byte the joints are painted in."""
    return pal.mortar_byte() if mortar is None else mortar


def counts(q, c=None):
    """(body_lines, body_bytes, wedge_lines, wedge_bytes) -- the four things
    the timing fit regresses against."""
    c = c or cfg()
    bl = bb_ = wl = wb = 0
    RC = c.CYH
    # raster_quad emits the body first, so counting the body rows is enough
    # to split the list.
    _bhi, _blo, _hhi, hlo, _bb, bw, _lt = unpack(q, c)
    jlo = RC if hlo >= RC * 16 else (hlo >> 4)
    nbody = 0
    if bw:
        nbody = min(c.VP_H - 1, RC + jlo) - (RC - jlo) + 1
    runs = raster_quad(q, c)
    for i, (r, e, n) in enumerate(runs):
        if i < nbody:
            bl += 1
            bb_ += 2 * n
        else:
            wl += 1
            wb += 2 * n
    return bl, bb_, wl, wb


def quad_shape(q, c=None):
    """What raster_quad's PACING hooks see, as opposed to what its runs
    paint.  engine2/src/main3.asm charges the rasteriser by the scanline
    now, and pacemodel.py has to replay that exactly, so this hands back
    the three things the hooks read:

        bh     body scanlines (rq_bh); the chunk loop draws RQ_BCH of them
               at a time and the last chunk is whatever is left
        npush  PUSH DE pairs in a body run -- the run is 2*npush bytes,
               which is what the per-scanline charge is 2 us a byte of
        D      Bresenham edge steps the wedge takes over its whole travel,
               all of which can fall in ONE pair, which is why raster.asm
               charges 20*D up front rather than spreading it
        wpre   the span, in bytes, at the START of every wedge pair --
               i.e. what rq_wspan2 reads BEFORE that pair's step.  The
               moving edge only ever walks towards the pinned one, so
               wpre[i] >= the width of every row from pair i onwards and
               a chunk charged at wpre[first] cannot under-charge.
    """
    c = c or cfg()
    RC = c.CYH
    bhi, blo, hhi, hlo, _bb, bw, left_tall = unpack(q, c)
    word = left_tall and bhi == 0
    jlo = RC if hlo >= RC * 16 else (hlo >> 4)
    jhi = min(RC, hhi >> 4)
    bh = (min(c.VP_H - 1, RC + jlo) - (RC - jlo) + 1) if bw else 0
    npush = (bw + 1) >> 1 if bw else 0
    n = jhi - jlo
    if n <= 0:
        return dict(bh=bh, npush=npush, D=0, wpre=[])
    D = (blo >> 1) if word else bw
    step = 1 if bhi >= blo else -1
    b = (blo >> 1) if word else blo
    N = hhi - hlo
    acc = -(D * (hlo - 16 * jlo)) - N
    wpre = []
    for _i in range(n):
        wpre.append(2 * b if word else (b - bhi if left_tall else bhi - b))
        acc += 16 * D
        while acc >= 0:
            acc -= N
            b += step
    return dict(bh=bh, npush=npush, D=D, wpre=wpre)


def colour(q, ramp=None):
    """RAMP[(kind<<3) | k], the solid Mode 0 byte raster.asm used to push.

    Kept for the harnesses that still want one byte per face.  What the
    rasteriser actually pushes now is a WORD -- see fill_word()."""
    ramp = ramp if ramp is not None else pal.ramp_table()
    return ramp[((q[4] & 1) << 3) | (q[5] & 7)]


def fill_word(q, wramp=None):
    """-> (E, D), the two bytes raster_quad loads into DE for this face.

    E is the LEFT screen byte, because PUSH stores the low register at the
    lower address.  A wall's E carries pal.GRAIN in its left pixel, which
    is the vertical grain; a door's E and D are equal."""
    wramp = wramp if wramp is not None else pal.wramp_table()
    i = (((q[4] & 1) << 4) | ((q[5] & 7) << 1))
    return wramp[i], wramp[i + 1]


def run_bytes(e, d, right, npush):
    """-> the byte to paint at each column of one filled run.

    The run covers columns [right - 2*npush, right - 1] and every push
    writes (E, D) as a pair, so a column takes E when its offset from the
    run's START is even.  The start is right - 2*npush, and 2*npush is
    even, so the parity is simply the parity of (x - right)."""
    start = right - 2 * npush
    return {x: (e if (x - start) % 2 == 0 else d)
            for x in range(start, right)}


def paint(quads, c=None, ramp=None, mortar=None):
    """Back-to-front into a VP_H x VP_BW byte framebuffer, background 0.
    Each face is its quad and then, on top of it, its two course joints --
    which is exactly the order raster_frame draws them in."""
    c = c or cfg()
    fb = bytearray(c.VP_H * c.VP_BW)
    mc = joint_colour(mortar)
    for q in quads:
        we, wd = fill_word(q)
        for runs, (ce, cd) in ((raster_quad(q, c), (we, wd)),
                               (joint_runs(q, c), (mc, mc))):
            for (r, e, n) in runs:
                s = e - 2 * n
                assert 0 <= s and e <= c.VP_BW and 0 <= r < c.VP_H, (r, s, e)
                for x in range(s, e):
                    fb[r * c.VP_BW + x] = ce if (x - s) % 2 == 0 else cd
    return fb
