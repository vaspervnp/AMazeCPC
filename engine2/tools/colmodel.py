"""THE COLUMN RENDERER -- the model the Z80 has to match byte for byte.

Every other part of this engine was built this way: the Python model is the
spec, the assembler is an implementation of it, and engine2/tools/emu_*.py
compares the two on a booted disc.  Nothing here is a sketch.

WHY COLUMNS AT ALL.  A textured wall wants column order and the reason is
arithmetic, not taste: for a fixed screen column the texture COLUMN u is
constant and only v walks down it, linearly.  In row order both u and v
change along the run, which is why a row-order fill can only ever push a
constant and why the span renderer's walls are one flat colour.

=======================================================================
WHAT A SCREEN BYTE COSTS, MEASURED, AND WHAT IT COST THE PLAN
=======================================================================
The architecture was costed at 6.625 us/byte, off the `colimm` row of
engine2/tools/emu_byte.py: `ld sp,hl : ld de,nn : push de : add hl,bc`.
THAT ROW IS A LOWER BOUND THAT NOTHING CAN REACH, because `ld de,nn` is
an IMMEDIATE -- the texture has to already be in the instruction stream,
and putting it there costs more per byte than sampling it does.

Re-measured on the booted 6128 with the loop this file actually
specifies (`colpair`, engine2/test/tst_byte.asm, slope over 96 and 192
bytes, 100-NOP calibration exact to 100.001 us):

    row order, PUSH DE, constant fill            2.000 us/byte
    column pair by PUSH, CONSTANT colour         5.125     <- the floor
    column pair by PUSH, baked immediate         6.625     <- unreachable
    COLUMN PAIR BY PUSH, TEXTURED               10.125     <- this file
    column pair, textured, 2x magnified          7.625
    single column, LD (HL),A, textured          13.625

10.125 is 20.25 us for a scanline of the pair, and it decomposes exactly:

    ld e,h : ld a,(de) : add hl,bc      6 us   sample and step the texture
    exx ... exx                         2 us   two banks, two 16-bit walks
    ld d,a : ld e,a                     2 us   one sample, both screen bytes
    ld sp,hl : push de : add hl,bc     10 us   the screen, 2 bytes at a time

Everything below is arranged so that loop can run: the texture is
TRANSPOSED and page aligned so `ld e,h` is the whole address arithmetic,
the vertical step is a table lookup so there is no divide in the column,
and the columns are done in PAIRS so one PUSH covers two of them.

=======================================================================
AND WHAT THAT MEANS FOR THE FRAME
=======================================================================
Byte counts are exhaustive over all 4,055,040 reachable states
(engine2/tools/wallarea.py for the span renderer, engine2/tools/colarea.py
for this one):

    painted by the span renderer, worst      7252 bytes  (overdraw)
    painted by THIS renderer, worst          4224 bytes  (= the viewport)
    runs (= scanline fills) in the worst frame 738
    column PAIRS in the viewport                22

    span   7252 * 2.000 + 738 * 19.75  =  29.1 ms
    column 4224 * 10.125 + 22 * setup  =  42.8 ms + setup

So the texture is NOT free.  The overdraw and the per-scanline setup the
row order was spending pay for about two thirds of it and no more.  What
the column order does buy outright is the PACING: the largest atomic unit
falls from a whole quad (12486 us MEASURED, 63% of a vsync period) to one
column pair (under 1000 us), which is why raster.asm's RQ_SPLIT and all
of its chunk-hook machinery simply go away.

=======================================================================
THE TEXTURE, AS THE Z80 SEES IT
=======================================================================
walltex.py draws 32x64 Mode 0 PIXELS.  Two pixels are one byte, so that
is TEX_BW = 16 byte columns of TEX_H = 64 rows, and it is emitted
TRANSPOSED -- one contiguous run per COLUMN -- so a column fill is a
linear source walk.

Each column is then REPLICATED FOUR TIMES into a 256-byte page:

    page[i] = column[i >> 2]

which costs 8192 bytes of a 16K bank that had nothing else in it, and
buys the two microseconds a scanline that `and 63 / or base` would cost.
The vertical coordinate is therefore a plain 8.8 fixed-point number whose
HIGH BYTE is the offset in the page -- `ld e,h` -- and whose low byte is
the fraction.  v is quantised to a quarter of a texel, which is finer
than a 96-scanline viewport can show.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import cpchw                                              # noqa: E402
import pal                                                # noqa: E402
import rastermodel as rm                                  # noqa: E402
import walltex                                            # noqa: E402

TEX_BW = walltex.TEX_W // 2         # 16 byte columns
TEX_H = walltex.TEX_H               # 64 rows
IDX_N = 256                         # the vertical index's range: a whole page
IDX_REP = IDX_N // TEX_H            # ...so each texel is 4 index steps

# The half height the projector can produce at the near plane; projmodel's
# HTAB is clamped there, so this bounds every j the renderer ever sees.
HMAX_Q4 = 6144
JMAX = HMAX_Q4 >> 4                 # 384 scanlines of half height
CIDX_SH = 2                         # CTAB is indexed in QUARTER scanlines
CIDX_N = (HMAX_Q4 >> CIDX_SH) + 1   # ...so 1537 entries, not 385


# ===================================================================== #
#  THE TEXTURE PAGES                                                     #
# ===================================================================== #
def tex_pages(rows, pens):
    """-> TEX_BW pages of IDX_N Mode 0 bytes, transposed and replicated.

    `rows` is walltex's TEX_H x TEX_W grid of pen INDICES 0..3 and `pens`
    maps those four onto real Mode 0 pens.  Byte column u carries texture
    pixels 2u (left) and 2u+1 (right), which is the order a Mode 0 byte
    puts them in and therefore the order they appear on the screen.
    """
    out = []
    for u in range(TEX_BW):
        page = bytearray(IDX_N)
        for i in range(IDX_N):
            r = rows[i // IDX_REP]
            page[i] = cpchw.mode0_byte(pens[r[2 * u]], pens[r[2 * u + 1]])
        out.append(bytes(page))
    return out


def wall_pages():
    return tex_pages(walltex.wall(), pal.WALL_TEX_PENS)


def door_pages():
    return tex_pages(walltex.door(), pal.DOOR_TEX_PENS)


# ===================================================================== #
#  CTAB -- everything the vertical walk needs, indexed by j                #
# ===================================================================== #
#  j = h_q4 >> 4 is the half height in WHOLE scanlines, exactly the jlo
#  raster.asm already derives, so the column renderer's silhouette is the
#  span renderer's silhouette and nothing else has to change to keep them
#  comparable.  A column covers rows CYH-j .. CYH+j, i.e. 2j+1 of them,
#  clipped to the viewport.
#
#      step  = the 8.8 index step per scanline = IDX_N / (2j+1)
#      idx0  = where the FIRST VISIBLE row lands, = clip * step, where
#              clip = max(0, j - CYH) is how many rows fell off the top
#
#  Both are looked up, so a column costs no divide at all.  The table is
#  4 bytes x (JMAX+1) = 1540 bytes and lives in the texture bank.
def ctab():
    """-> (step, idx0) indexed by h_q4 >> CIDX_SH, i.e. by the half height
    in QUARTER SCANLINES.

    IT USED TO BE INDEXED BY j = h_q4 >> 4 AND THAT IS WHAT MADE THE WALL
    LOOK BROKEN.  The projector hands over h in Q12.4 -- tenths of a
    scanline -- and indexing by j threw the bottom four bits away.  So
    across a run of adjacent column pairs, while h changed by less than a
    whole scanline, j did not change at all: same step, same idx0, and the
    mortar courses ran DEAD FLAT.  Then j ticked over and every course
    jumped at once.  Worse, course k jumps by k/8 of the whole face, so
    the top course looks nearly right and the bottom ones shear badly --
    which is exactly how it reads on screen.

    The fix is not in the renderer at all, it is here: index the table
    finely enough that the mapping moves when the geometry does.  A
    quarter of a scanline costs 1537 entries x 4 bytes = 6148 bytes of a
    bank that had 6310 free, and costs the Z80 NOTHING -- it reads a table
    either way, and 4*(h >> 2) is h & ~3, so the lookup is an AND rather
    than two shifts.

    step is taken over the TRUE extent 2h and not over the 2j+1 rows the
    fill happens to cover, and idx0 carries the sub-scanline PHASE of the
    wall's top edge -- (r0 - CYH + h) * step -- which is the term that was
    missing altogether.
    """
    c = rm.cfg()
    t = []
    for i in range(CIDX_N):
        if i == 0:
            t.append((0xFFFF, 0))
            continue
        step = min(0xFFFF, (IDX_N << 9) // i)      # 256*256 / (i/2)
        j = i >> 2
        r0 = max(0, c.CYH - j)
        idx0 = ((4 * (r0 - c.CYH) + i) * step) // 4
        t.append((step, idx0 & 0xFFFF))
    return t


def tix(h):
    """h in Q12.4 -> the CTAB index.  Clamped: the projector clamps h at
    the near plane, so nothing beyond CIDX_N is reachable."""
    return min(CIDX_N - 1, max(0, h) >> CIDX_SH)


_CTAB = None


def CTAB():
    global _CTAB
    if _CTAB is None:
        _CTAB = ctab()
    return _CTAB


# ===================================================================== #
#  ONE FACE                                                              #
# ===================================================================== #
def face_span(q):
    """-> (xa, xb, ha, hb, flipped) with xa < xb, heights following.

    The quad record pairs each half height with its own byte column, so
    swapping the ends when blo > bhi has to swap the heights with them.
    """
    blo, bhi, hlo, hhi = q[0], q[1], q[2], q[3]
    if blo <= bhi:
        return blo, bhi, hlo, hhi, False
    return bhi, blo, hhi, hlo, True


def normalise(w, ha, hb):
    """-> (sh, ha>>sh, hb>>sh): the smallest shift that keeps the u
    division inside 16 bits.

    THE ONLY INTERESTING ARITHMETIC IN THIS FILE.  On a wall the half
    height h is proportional to 1/z and the projector makes it LINEAR in
    screen x, so 1/z is linear in x -- and therefore so is u/z.
    Perspective-correct u is the ratio of the two, which for endpoints
    (ha, hb) at parameter s across the face is

        u = s*hb / (ha + s*(hb - ha))

    exact at both ends and bunching toward the far one.  Interpolating u
    linearly instead -- which is what a fixed screen-space pattern does --
    is the error that makes a texture slide across a wall as you walk.

    Both halves of that ratio are linear in x with INTEGER increments if
    the fraction s = t/w is cleared:  with t2 = 2(x - xa) + 1 sampling the
    middle of column x and w2 = 2w,

        N(x) = t2 * hb                  N += 2*hb  per column
        D(x) = w2*ha + t2*(hb - ha)     D += 2*(hb - ha) per column
        u    = floor(TEX_BW * N / D)

    and no division is needed to WALK it, only one 4-bit restoring divide
    per column to read it off.  That divide shifts the remainder left
    once per bit, so D must stay under 32768, i.e. 2*w*max(ha,hb) must --
    hence this shift.  It costs nothing that matters: the shift is the
    smallest that works, so max(ha,hb) >> sh is never below 16384/(2*44)
    = 186, which is seven bits under a coordinate that only needs four.
    """
    sh = 0
    while w * (max(ha, hb) >> sh) >= 16384:
        sh += 1
    return sh, ha >> sh, hb >> sh


def new_cover(c):
    """The per-pair occlusion state: for each pair, the first row still
    uncovered going UP from the horizon and the first going DOWN.

    A WALL FACE'S ROWS AT A COLUMN ARE ALWAYS AN INTERVAL CENTRED ON THE
    HORIZON -- the camera sits at wall mid-height and cannot pitch, so a
    face covers CYH-j .. CYH+j and nothing else.  The union of any number
    of them at one pair is therefore ALSO one interval centred on the
    horizon, and two bytes describe it exactly.

    THAT IS WHAT MAKES FRONT-TO-BACK SAFE, and a boolean does not.  The
    plan for this renderer said a pair is finished once a face covers it
    floor to ceiling, on the argument that the nearest face at a column is
    the tallest there so every farther one is hidden.  MEASURED over
    20736 states, that argument is false in 2862 of them (13.8%): the
    painter key is the march's L1 cell distance, which is not the
    per-column depth order, so a face drawn LATER can still poke out above
    and below one drawn earlier.  Skipping it leaves ceiling where the
    span renderer draws wall.

    Marking a pair done only on FULL coverage is safe against that but
    gives up the cap: the same scan paints 5496 bytes, 130% of the
    viewport, because every partly-covering face repaints the middle.
    The interval keeps both -- it is exact against the span renderer's
    own visibility rule (nearest face wins, which is what back-to-front
    overdraw computes) AND it never paints a byte twice, so the frame is
    capped at VP_BW*VP_H however many faces the kernel emits.
    """
    n = c.VP_BW // 2
    # up = the first uncovered row above the horizon, dn = below it.  The
    # horizon row itself belongs to the TOP band, so dn starts one lower.
    return [[c.CYH] * n, [c.CYH + 1] * n]


def slide(rows, idx, step, dlift):
    """rastcol.asm:rc_slide -- how far a moving door's slab has gone up,
    and its texture with it.

    -> (d, idx') where d is the rise in ROWS and idx' the coordinate
    shifted by exactly those rows:

        d    = (rows * dlift) >> 8
        idx' = idx + d * step

    THE SHIFT IS THE SAME ROWS TIMES THE SAME STEP, so the slab is rigid
    by construction -- there is no second constant that has to be kept in
    step with the first.

    AND `rows` IS WHAT IS ON SCREEN, NOT THE WHOLE SLAB.  A door close
    enough to open is about twice the viewport tall, so its bottom edge
    starts BELOW the screen.  Measured against the whole slab, the first
    quarter of the run moved an edge nobody could see: the opening did
    not grow, the art slid on its own, and what the player saw was a copy
    of the door left standing while the texture crawled past it.
    """
    d = (rows * dlift) >> 8
    return d, (idx + d * step) & 0xFFFF


def is_moving(q):
    """Bit 1 of the kind byte: a door part way through its run.  Bit 0
    still says `door` and still picks the texture."""
    return bool(q[4] & 2)


def pair_walk(q, c, cover=None, over=False, dlift=0):
    """Walk one face's column PAIRS front to back, EVERY pair in the
    face's range -- the ones a nearer face already owns too.

    This is rc_face's pair loop, hook for hook: rastcol.asm now takes one
    cost hook per pair, drawn or skipped (see costcol.inc), so the charge
    model has to see the skipped pairs and the per-pair state the asm's
    hook reads -- the centre half height, the Bresenham step, the cover
    BEFORE this face touches it, and the CLAMPED t2 step rc_pnext will
    take afterwards.  render() only wants the drawn pairs, and gets them
    through the face_columns filter below.

    Yields one dict per pair:
        p, closed, up0, dn0   the pair and the cover before it (model
                              terms: up0 = last free row above, or -1;
                              dn0 = first free row below, or VP_H)
        h, hq                 the centre half height at this pair, Q12.4,
                              exactly the asm's (rc_h), and the
                              per-column Bresenham step (rc_hq)
        delta                 the t2 step rc_pnext takes AFTER this pair:
                              4 is the whole-pair fast path, 1..3 the
                              clamped slow path, 0 nothing
    and, on open pairs only:
        u, j, r0, r1, step, bands, stept, edges   as face_columns had

    PAIRS, NOT COLUMNS, and the face's span is rounded OUTWARD onto them
    -- pa = xa>>1, pb = (xb+1)>>1.  One PUSH writes two horizontally
    adjacent bytes, so two byte columns is the natural grain of a column
    renderer the same way two bytes is the natural grain of a row fill,
    and the span renderer already rounds its runs outward by a byte for
    exactly the same reason (raster.asm, the RUNS note).  What it costs
    is that a face can bleed one column past its own edge; what it saves
    is half of the 10 us a scanline the screen pointer costs.
    """
    xa, xb, ha, hb, flipped = face_span(q)
    w = xb - xa
    if w <= 0:
        return
    npair = c.VP_BW // 2
    pa = max(0, xa >> 1)
    pb = min(npair, (xb + 1) >> 1)
    if pb <= pa:
        return
    up, dn = (cover if cover is not None
              else [[c.CYH] * npair, [c.CYH + 1] * npair])
    if not over and all(up[p] < 0 and dn[p] > c.VP_H - 1
                        for p in range(pa, pb)):
        return

    _sh, han, hbn = normalise(w, ha, hb)
    w2 = 2 * w
    dN = 2 * hbn
    dD = 2 * (hbn - han)
    dh = hb - ha
    hq = (dh if dh >= 0 else -dh) // w2
    moving = is_moving(q) and dlift > 0
    tab = CTAB()

    for p in range(pa, pb):
        # h at the centre sample, TRUNCATED TOWARDS ha -- see the note
        # below -- and the step rc_pnext takes after this pair: the raw
        # sample moves 4 a pair but t2 is clamped into the face, so the
        # step off an odd left edge and the one onto the right edge are
        # 1..3 single columns (the asm's slow path, which charges its
        # own hook) and everything after the clamp is 0.
        def _h(tt):
            return (ha + (tt * dh) // w2) if dh >= 0 else (ha - (tt * -dh) // w2)

        if over:
            # OVERLAY: forget what covered this pair.  The moving door is
            # in front of all of it and this is the last pass to run, so
            # scribbling on the interval is free -- rastcol.asm's
            # rc_pairloop writes the same two bytes.
            up[p], dn[p] = c.CYH, c.CYH + 1
        t2c = min(max(2 * (2 * p - xa) + 2, 1), w2 - 1)
        delta = min(2 * (2 * (p + 1) - xa) + 2, w2 - 1) - t2c
        info = {"p": p, "up0": up[p], "dn0": dn[p],
                "h": _h(t2c), "hq": hq, "delta": delta}
        if not over and up[p] < 0 and dn[p] > c.VP_H - 1:
            info["closed"] = True
            yield info
            continue
        info["closed"] = False
        # t2 samples the middle of the PAIR, clamped into the face: the
        # outermost pair can reach a column the face does not own, and the
        # sample has to come from a column it does.
        #
        # THE +2 IS THE PAIR'S CENTRE AND THE +1 WAS THE LEFT COLUMN'S.
        # A pair writes one sampled byte to both of its byte columns, so
        # whichever column the sample comes from, the other one is wrong
        # by however much h and u move across it.  Sampling the left
        # column made the right one wrong by a WHOLE column every time;
        # sampling the centre makes each of them wrong by half a column
        # and in opposite directions, which is the best a pair can do.
        # It costs nothing -- one conditional add in the per-face setup.
        t2 = t2c
        N = t2 * hbn
        D = w2 * han + t2 * (hbn - han)
        if D <= 0:
            u = 0
        elif N <= 0:
            u = 0
        elif N >= D:
            u = TEX_BW - 1
        else:
            u = (TEX_BW * N) // D
        if flipped:
            u = TEX_BW - 1 - u
        # h at the same sample, in Q12.4, TRUNCATED TOWARDS ha -- not
        # floored: that is what the _h above computes.  Python's // floors
        # towards minus infinity, so on a face that gets SHORTER across
        # the screen (dh < 0) it would round the half height down a step
        # the Z80 does not: the Z80 divides |dh| and subtracts, because a
        # Bresenham has no sign.  Getting this backwards paints one extra
        # scanline at the foot of every descending face, which is what
        # the first build did.
        #
        # EACH BYTE COLUMN OF THE PAIR HAS ITS OWN HALF HEIGHT, half a
        # pair-step either side of the centre sample -- and that
        # difference IS the silhouette staircase.  MEASURED over 9424
        # pairs from 400 real states: 62.5% of pairs have the two columns
        # at different j, 12% differ by four scanlines or more, and the
        # worst single pair differs by 104.  A pair drawn to one j
        # therefore does not step, it BREAKS.
        #
        # So the pair is filled by PUSH only as far as the SHORTER of the
        # two, and the taller column's remaining rows are drawn on their
        # own.  The obvious objection is that this sounds like per-pixel
        # work; it is not, because the extra rows telescope: summed over a
        # face they come to its total height travel, jhi - jlo <= CYH,
        # and not to anything proportional to its width.  MEASURED over
        # the same 400 states, making every edge exact costs 32868 extra
        # bytes against 1324234 already painted -- 2.5%, for a silhouette
        # as accurate as the span renderer's.
        hA, hB = _h(t2 - 1), _h(t2 + 1)             # the two byte columns
        jA = min(JMAX, max(0, hA >> 4))
        jB = min(JMAX, max(0, hB >> 4))
        if jB >= jA:
            js, jt, ofs, hs, ht = jA, jB, 1, hA, hB
        else:
            js, jt, ofs, hs, ht = jB, jA, 0, hB, hA
        j = js
        r0 = max(0, c.CYH - js)
        r1 = min(c.VP_H - 1, c.CYH + js)
        if r1 < r0:
            continue
        step, idx0 = tab[tix(hs)]
        if moving and r1 > r0:
            d, idx0 = slide(r1 - r0, idx0, step, dlift)
            r1 -= d
        # The band ABOVE the horizon starts at the face's own first
        # visible row, so its texture coordinate is CTAB's idx0 and needs
        # no arithmetic at all.  The band BELOW starts wherever the nearer
        # face stopped, which costs one 8x16 multiply -- and only on the
        # faces that are partly occluded, which is the rare path.
        bands = []
        # THE UPPER BAND ENDS AT THE FACE'S OWN BOTTOM ROW, not merely at
        # the horizon.  For a wall r1 is at or below the horizon by
        # construction and this min() never bites; for a DOOR IN MOTION
        # it is the whole animation.  The lift shortens the band BELOW
        # the horizon and nothing else, so a door risen to the horizon
        # kept its upper band at full height for ever -- it stopped
        # shrinking half way and stood there as a copy of itself over the
        # room that was already drawn underneath it.
        if r0 <= min(up[p], r1):
            bands.append((r0, min(up[p], r1), idx0))
        if dn[p] <= r1:
            bands.append((dn[p], r1,
                          (idx0 + (dn[p] - r0) * step) & 0xFFFF))

        # ...and the taller column's own rows, above and below, in ONE
        # byte column.  They carry the taller column's own mapping, so
        # the texture spans its real extent rather than the short one's.
        edges = []
        r0t, r1t = r0, r1
        if jt > js:
            stept, idx0t = tab[tix(ht)]
            r0t = max(0, c.CYH - jt)
            r1t = min(c.VP_H - 1, c.CYH + jt)
            if moving and r1t > r0t:
                dt, idx0t = slide(r1t - r0t, idx0t, stept, dlift)
                r1t -= dt
            e1 = min(r0 - 1, up[p])
            if r0t <= e1:
                edges.append((r0t, e1, idx0t, ofs))
            e0 = max(r1 + 1, dn[p])
            if e0 <= r1t:
                edges.append((e0, r1t,
                              (idx0t + (e0 - r0t) * stept) & 0xFFFF, ofs))
        info.update(u=u, j=j, r0=r0, r1=r1, step=step, bands=bands,
                    stept=stept if jt > js else step, edges=edges)
        yield info

        # THE INTERVAL IS RECORDED OVER THE TALLER COLUMN.  It has to pick
        # one, because rc_up / rc_dn are per PAIR and the edge rows cover
        # only one of the two byte columns.  Recording the taller one lets
        # a farther face be skipped in rows where the SHORTER column is
        # not wall, so the background shows there -- which is what the
        # shorter column should show anyway, since this face does not
        # reach it.  Recording the shorter one instead would let a farther
        # face paint OVER the nearer face's edge, which is the error that
        # actually looks wrong.
        if r0t - 1 < up[p]:
            up[p] = r0t - 1
        if r1t + 1 > dn[p]:
            dn[p] = r1t + 1
    return


def passes(quads):
    """-> the quad list split the way raster_colframe walks it.

    TWO PASSES, and the second is what lets a door open all the way.
    Pass 0 is everything except a door in MOTION, front to back with the
    occlusion interval; pass 1 is the moving doors, drawn on top and
    outside the interval altogether.  See rastcol.asm:rc_pass -- a door
    risen past the horizon covers rows that the two-byte interval cannot
    describe, and drawing it last means it does not have to.
    """
    return ([q for q in quads if not is_moving(q)],
            [q for q in quads if is_moving(q)])


def face_columns(q, c, cover=None, over=False, dlift=0):
    """pair_walk, drawn pairs only -- what render() paints.

    Yields (pair, u, j, r0, r1, step, bands, stept, edges): up to two
    BANDS of rows this face is the nearest cover of, one above the
    horizon and one below, because the rows between them are already
    owned by a nearer face, plus the taller byte column's own EDGE rows.
    The idx in each is the 8.8 texture coordinate at its first row, so
    the caller just walks it.
    """
    for i in pair_walk(q, c, cover, over, dlift):
        if i["closed"]:
            continue
        yield (i["p"], i["u"], i["j"], i["r0"], i["r1"], i["step"],
               i["bands"], i["stept"], i["edges"])


def charge(quads, c, c_cframe, c_cface, c_cskip, c_cols, c_cband,
           c_colr, c_cedge, c_cstep, dlift=0):
    """-> the microsecond charges rastcol.asm takes, in order.

    THE TWIN OF THE COST HOOKS, the way pacemodel.quad_units is the twin
    of main3.asm:pace_quad -- see costcol.inc for the shape and for the
    measured under-charges that forced it.  Every hook runs BEFORE the
    work it pays for and charges an UPPER BOUND on the interval that
    follows it:

        C_CFRAME                 once, before the frame's own setup
        C_CFACE                  the TOP of rc_face -- EVERY record pays
                                 it, degenerate and occluded ones too
        per pair in the range    C_CSKIP when a nearer face owns it, or
                                 rc_charge's bound when it draws:
                                 C_COLS + C_CBAND*bands + C_COLR*rows
                                 + C_CEDGE*edges, all bounded from the
                                 pair's cover and h +- (hq+1) alone
        C_CSKIP + C_CSTEP*delta  rc_pnext's clamped slow step, its own
                                 hook because it happens at most twice a
                                 face

    ONE UNIT PER HOOK, IN THE ASM'S OWN ORDER: the model and the machine
    must take the same unit SEQUENCE, not just the same total, because
    emu_rcol.py's `atomic` cross-checks the charge the Z80 is about to
    take at hook k against the model's k'th unit -- and because the
    greedy yield rule replays these units one at a time, so a sequence
    the disc never executes locks a disc nobody has.
    """
    return [u["frame"] * c_cframe + u["face"] * c_cface
            + u["skip"] * c_cskip + u["pair"] * c_cols
            + u["bands"] * c_cband + u["rows"] * c_colr
            + u["edges"] * c_cedge + u["steps"] * c_cstep
            for u in charge_terms(quads, c, dlift)]


def charge_terms(quads, c, dlift=0):
    """-> one dict of REGRESSORS per hook, in the asm's own order.

    charge() is this weighted by the constants, so the two cannot drift:
    a term that appears here appears in the charge, and a hook that is
    not emitted here is not charged.  It is also what emu_rcol.py's
    `fit` regresses the measured intervals on -- the constants are the
    coefficients of exactly these columns, so a fit is one-sided against
    the same arithmetic rc_charge does.

    The keys are the hooks' own terms:
        frame  raster_colframe's once-a-frame setup
        face   the top of rc_face
        skip   a pair a nearer face owns, and the slow step's own base
        pair / bands / rows / edges   rc_charge's bound at a drawn pair
        steps  single columns in rc_pnext's clamped slow path
    """
    cover = new_cover(c)
    out = []
    if not quads:
        return out                       # raster_colframe rets before
    z = {"frame": 0, "face": 0, "skip": 0, "pair": 0,
         "bands": 0, "rows": 0, "edges": 0, "steps": 0}
    out.append(dict(z, frame=1))         # its hook on an empty list
    # TWO PASSES, in raster_colframe's own order.  rc_face is entered for
    # every record in BOTH passes but returns before the charge on the
    # ones that are not for that pass, so each quad pays C_CFACE exactly
    # once -- in its own pass.
    p0, p1 = passes(quads)
    for over, group in ((False, p0), (True, p1)):
      for q in reversed(group):
        out.append(dict(z, face=1))      # the top of rc_face: every record
        for i in pair_walk(q, c, cover, over, dlift):
            if i["closed"]:
                out.append(dict(z, skip=1))
            else:
                # rc_charge's bound, integer for integer.  up0/dn0 are
                # the cover BEFORE this pair (model terms), the asm's
                # rc_up count is up0 + 1 -- and on the OVERLAY pass they
                # are the values rc_pairloop has just reset, which is why
                # pair_walk clears them before it reports them.
                upc = i["up0"] + 1                   # free rows above
                free = upc + (c.VP_H - i["dn0"])     # ...and in total
                nb = ((1 if upc > 0 else 0)
                      + (1 if i["dn0"] < c.VP_H else 0))
                jhi = min(c.CYH, max(0, i["h"] + i["hq"] + 1) >> 4)
                jlo = min(c.CYH, max(0, i["h"] - i["hq"] - 1) >> 4)
                out.append(dict(z, pair=1, bands=nb,
                                rows=min(2 * jhi + 1, free),
                                edges=min(2 * (jhi - jlo), free)))
            if 1 <= i["delta"] <= 3:
                out.append(dict(z, skip=1, steps=i["delta"]))
    return out


# ===================================================================== #
#  THE FRAME                                                             #
# ===================================================================== #
def render(quads, c=None, pages_wall=None, pages_door=None,
           dlift=0):
    """-> (16K screen image, stats).

    The buffer is the whole &C000 page the Z80 writes, so emu_rast.py can
    compare all of it and catch a stray write outside the viewport the
    same way it does for the span renderer.  Nothing outside the columns
    this returns is touched: the background is bg_fill's job and this
    model leaves it zero.
    """
    c = c or rm.cfg()
    pw = pages_wall if pages_wall is not None else wall_pages()
    pd = pages_door if pages_door is not None else door_pages()
    scr = bytearray(0x4000)
    cover = new_cover(c)
    painted = 0
    pairs = 0

    # FRONT TO BACK, AND IT IS A REVERSE WALK, NOT A SORT.  The quad list
    # arrives in painter order, back to front -- kernel.asm:project_all
    # empties the march's buckets "7..1, back to front" -- because the row
    # renderer needs to overdraw.  Column order wants the opposite, and
    # reading the same list backwards IS the opposite: no sort, no key, no
    # scratch space.  This model reverses rather than sorting on q[5] so
    # that it says the same thing as the Z80 on a list that is NOT in
    # painter order, which is exactly what emu_rast.py's random batches
    # are; sorting here would have made the two disagree on every one of
    # them and blamed the rasteriser.
    # TWO PASSES, exactly as raster_colframe walks it: everything but a
    # door in MOTION, front to back, and then the moving doors ON TOP and
    # outside the occlusion interval.  See passes().
    p0, p1 = passes(quads)
    for over, group in ((False, p0), (True, p1)):
      for q in reversed(group):
        pages = pd if (q[4] & 1) else pw
        for (p, u, _j, _r0, _r1, step, bands,
             stept, edges) in face_columns(q, c, cover, over, dlift):
            page = pages[u]
            for br0, br1, idx in bands:
                pairs += 1
                for r in range(br0, br1 + 1):
                    y = c.VP_Y + r
                    a = (y & 7) * 0x800 + (y >> 3) * 80 + c.VP_BX + 2 * p
                    b = page[(idx >> 8) & 0xFF]
                    scr[a] = b
                    scr[a + 1] = b
                    idx = (idx + step) & 0xFFFF
                    painted += 2
            for er0, er1, idx, ofs in edges:
                for r in range(er0, er1 + 1):
                    y = c.VP_Y + r
                    a = ((y & 7) * 0x800 + (y >> 3) * 80 + c.VP_BX
                         + 2 * p + ofs)
                    scr[a] = page[(idx >> 8) & 0xFF]
                    idx = (idx + stept) & 0xFFFF
                    painted += 1
    return bytes(scr), {"painted": painted, "pairs": pairs,
                        "covered": sum(1 for v in scr if v)}


if __name__ == "__main__":
    c = rm.cfg()
    t = CTAB()
    print(f"viewport {c.VP_BW}x{c.VP_H}, {c.VP_BW // 2} column pairs, "
          f"horizon row {c.CYH}")
    print(f"texture {TEX_BW} byte columns x {TEX_H} rows, replicated "
          f"x{IDX_REP} into {IDX_N}-byte pages")
    print(f"  wall+door pages {2 * TEX_BW * IDX_N} bytes, "
          f"CTAB {4 * len(t)} bytes")
    for j in (0, 1, 24, 48, 49, 96, 192, JMAX):
        print(f"  j={j:3d}  2j+1={2*j+1:4d}  step={t[j][0]:5d} "
              f"({t[j][0] / 256 / IDX_REP:6.3f} texels/scanline)  "
              f"idx0={t[j][1]:5d}")
