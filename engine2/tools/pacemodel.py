"""The cost-accumulator pacing model -- the Python twin of main3.asm.

Every constant below is the one the Z80 uses (main3.asm, `C_*` and
COST_THI), and every unit of work is charged in the same ORDER and from
the same counters, so replaying this over the reachable state space
answers, offline and exactly, the only question the pad has to get right:

    how many vsync waits does a frame need, and is it the same number for
    every state a player can stand in?

The per-unit constants are UPPER BOUNDS fitted to emulator measurements of
the SHIPPED code -- hooks included -- taken on the booted disc
(engine2/tools/emu_pacefit.py).  The rule is est >= actual for every unit,
so an interval whose ESTIMATE is under the threshold is under 19456 us of
real time, and therefore inside one 20 ms period.

    python3 engine2/tools/pacemodel.py [nstates]
"""

import collections
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

C_TAIL = 1450        # flip + game_step + the head of the loop, MEASURED
                     # 1305.9 us worst with keys HELD (emu_holes.py).  It
                     # was 1050, fitted to a game_step nobody was pressing
                     # anything during.
C_DANIM = 1300       # door_shrink -- one pass over the finished quad
                     # list scaling the door faces, so a door's run is
                     # VISIBLE.  Charged on EVERY frame because the
                     # hook is unconditional, even though it returns at
                     # once unless a door is mid-run.
C_DOORACT = 900      # door_act, MEASURED 756.6 us worst -- the SPACE
                     # press edge, charged where it happens by game.asm
                     # through cost_add rather than added to C_TAIL and
                     # billed to every frame.  The sweep below carries it
                     # on EVERY frame anyway, which is the pessimistic
                     # direction: a player who taps SPACE every frame.
C_HP = 1400          # hud_health when a hit point MOVED.  Two rectangles
                     # of eight rows against the ammo readout's six --
                     # hud_rect is priced per ROW, so a bar is a quarter
                     # of what pips would have cost.  Charged by hud2.asm
                     # itself through cost_add, like C_AMMO.
C_AMMO = 4000        # hud_ammo when the round count MOVED, MEASURED
                     # 3811.1 us worst (emu_hud.py).  Charged by hud2.asm
                     # itself through cost_add, like C_DOORACT and for
                     # the same reason -- it is owed on the frame a round
                     # is fired or a pickup taken, not on all of them.
                     # The sweeps below carry it on EVERY frame, which is
                     # a player who fires as fast as the engine draws.
C_SCAN = 650         # hud_scan when the ammo scanner's lit bearing
                     # MOVED, MEASURED 551.4 us worst (emu_hud.py).
                     # Charged by hud2.asm itself, like C_AMMO.  The
                     # sweeps below carry it on every frame, which is a
                     # player spinning fast enough to cross a sector
                     # boundary five times a second.
C_SND = 2200         # sound.asm's nine ticks a frame, hung on
                     # wait_vsync.  MEASURED 1944 us worst -- the SHOT
                     # effect, four step changes and a stop inside one
                     # nine-tick window.  See main3.asm.
C_SWEEP = 1000       # hud_radar's sweep and blip compare, every frame.
                     # MEASURED 916.0 us.
C_BLIP = 460         # ...one blip that moved (MEASURED 431).  There
                     # are EIGHT of them in the worst frame: six
                     # pickups, the monster, and the monster
                     # repainted where it already is.
C_RNEEDLE = 750      # ...and the needle put back over them (680).
                     # The sweeps below carry the sweep on every frame,
                     # which is true, and the blips and the needle too,
                     # which is a player crossing six sector boundaries
                     # at once, five times a second.
#  ---- THE HUD'S GATES: BUILT, MEASURED, AND NOT SHIPPED ---------------
#  A gate tests without charging, so what it can guarantee is that the
#  ungated run AFTER it cannot take the interval past a vsync period.
#  Threshold = COST_THI - (the worst run that follows), exactly how
#  FACE_THI is COST_THI less one worst face.
#
#    HUD_GATE 0   none -- WHAT THE DISC DOES
#    HUD_GATE 1   ONE gate before the whole block, at COST_THI - 10080
#                 = 9376.  Has to assume the whole run follows it.
#    HUD_GATE 2   TWO gates, before the readouts and before the dial,
#                 each covering only its own run -- 14806 and 14026
#
#  EXHAUSTIVE, DOORS SHUT, 8128512 states:
#
#      HUD_GATE   over budget            mean waits
#        0          69381   0.854%          7.176
#        1         738216   9.082%          7.815
#        2         222372   2.736%          7.440
#
#  So the gate is a NET LOSS -- three times worse in its best
#  arrangement, ten in its worst -- and it is kept here only so the
#  table can be re-run.  The reason it loses is that the over-budget
#  states are not interval overruns at all; they are budget exhaustion,
#  and a gate that fires is one more yield.  Both failures end the frame
#  one period late, so the gate trades a rare late frame for a common
#  one.  main3.asm's cost_add note has the argument in full.
HUD_GATE = 0
N_BLIP = 8           # how many of C_BLIP the worst frame pays for, and
                     # it is a COUNT, not a cost: six pickup cells on the
                     # dial, plus hud_radar erasing the monster's old
                     # square and drawing its new one.  units() emits
                     # this many cost_adds; the number lives here so the
                     # scans cannot each pick their own.
C_MMSEEN = 900      # the minimap: the flood folded into MMBITS, and
C_PIPP = 5900       # pip.asm's three world drawers, on three separate
C_PIPM = 8800        # hooks now -- see main3.asm for why one hook at 8200
C_PIPF = 1000        # was not a bound.  The pickup on the
                     # floor, the monster, and the shot's flash and mark.
                     # MEASURED 7902.6 us worst on the booted disc, with
                     # the monster a cell away.  Charged unconditionally
                     # by main3.asm through cost_unit -- see the note
                     # there for why this one is not a cost_add.
C_BG = 8600          # bg_fill, MEASURED 8501.3 us at 40x96, fixed
C_MSETUP = 1550      # march_setup, MEASURED 1372.8-1445.1 us swept over
                     # the movement lattice (emu_holes.py).  It was 1450,
                     # fitted to one bench at one state, and 1450 cleared
                     # the real worst case by 4.9 us.
C_CELL = 740         # one popped flood cell (m_visited)
C_FACE = 1380        # a candidate face that becomes a quad
C_REJ = 480          # ...one that does not
C_CLIP = 930         # each clip lerp: near plane, left edge, right edge
C_HUD = 1550         # hud_update with the needle moved, MEASURED 1422.5 us
                     # worst over all 72 headings (emu_holes.py).  It was
                     # 1420, from one measurement of one heading.
C_GUN = 4500         # gun_step + gun_draw + the cost_unit in front of them,
                     # MEASURED 4375.2 us as gun_paced on the booted disc
                     # (emu_pacefit.py).  Charged only when GUN is 1, which
                     # is read out of main3.asm below rather than repeated.
# ---- THE RASTERISER, CHARGED BY THE SCANLINE -------------------------
# raster_quad yields INSIDE itself now (raster.asm, rq_bchunk/rq_wchunk),
# so a quad is no longer one unit of work: it is C_QSET, then a chunk per
# RQ_BCH body scanlines, then a chunk per RQ_WCH wedge pairs.  See
# quad_units below -- and note that the four constants here are read out
# of main3.asm by _equ(), not copied.
C_QSET = 880         # raster_quad's setup, roomed before the record is read
C_BLINE = 20         # one body scanline, MEASURED 18.78 us + 1.976/byte;
                     # the bytes are charged at 2 us each on top
C_WPAIR = 122        # one wedge scanline PAIR, MEASURED 2 x 59.05 us
C_CHUNK = 300        # one chunk hook: the SP swap, the pushes, cost_unit
C_PMUL = 90          # ...and the extra a SHORT chunk pays: rq_pmul, and
                     # the transition that always sits behind one
C_WSTEP = 20         # one Bresenham edge step, MEASURED 19.27 us.  Where
                     # in the wedge they fall is not knowable, so every
                     # chunk carries C_WSTEP*w -- see raster.asm
C_JOINT = 7400       # ONE face's two course boundaries, drawn on top of it
                     # by raster.asm:raster_joint when vpcfg.inc's COURSES
                     # is 1, and charged as a unit of its own by
                     # main3.asm:raster_paced.  MEASURED 7189 us on the
                     # booted disc, of which 6909 is per-row setup and 280
                     # is the pixels -- see the note on COURSES in
                     # vpcfg.inc.  It is a FLAT charge, not a formula.

C_FACE_MAX = C_FACE + 3 * C_CLIP     # the headroom FACE_THI leaves
THRESH = 0x4C * 256                  # 19456 us, COST_THI: room then charge
FTHRESH = 0x3C * 256                 # 15360 us, FACE_THI: charge then test

# ---- the HUD gates' thresholds, DERIVED, not chosen ------------------
#  Each is COST_THI less the worst ungated run that follows it, so the
#  interval cannot leave the gate and reach a full 19968 us period.
HUD_RUN_A = C_AMMO + C_SCAN + C_HP                   # the three readouts
HUD_RUN_R = C_SWEEP + N_BLIP * C_BLIP + C_RNEEDLE    # ...and the dial
HUD_RUN = HUD_RUN_A + HUD_RUN_R                      # both, ungated
HUD_THI1 = THRESH - HUD_RUN                          # one gate covers all
HUD_THI_A = THRESH - HUD_RUN_A                       # two gates, each its
HUD_THI_R = THRESH - HUD_RUN_R                       # own run


def _equ(name, default, src="main3.asm"):
    """Read an `equ` out of the source, so this file cannot drift from the
    disc it claims to model."""
    path = os.path.join(os.path.dirname(_HERE), "src", src)
    for line in open(path):
        p = line.split()
        if len(p) >= 3 and p[0] == name and p[1] == "equ":
            try:
                return int(p[2])
            except ValueError:
                return default
    return default


PACE_FRAMES = _equ("PACE_FRAMES", 6)
GUN = _equ("GUN", 1)
GUN_CHARGED = _equ("GUN_CHARGED", 1)
# EVERY cost constant is READ OUT OF main3.asm, not copied.  The values
# written above are documentation of where each number came from; the
# numbers this model actually replays are the disc's own.
#
# This is not tidiness.  C_BG is the one constant that MOVES WITH THE
# VIEWPORT -- 8501.3 us of fill at 40x96, 9215.8 at 44x96 -- and when the
# viewport was widened it stayed at 8600 in both places at once, 616 us
# under the truth, with the model agreeing with the disc because both were
# wrong in the same way.  A model that keeps its own copy of a constant
# cannot catch that; one that reads the disc's can only be wrong if the
# disc is.
for _n in ("C_TAIL", "C_DOORACT", "C_AMMO", "C_HP", "C_SCAN", "C_MMSEEN", "C_PIPP", "C_PIPM", "C_PIPF", "C_SND", "C_SWEEP", "C_BLIP", "C_RNEEDLE", "C_DANIM", "C_BG", "C_MSETUP", "C_CELL",
           "C_FACE",
           "C_REJ", "C_CLIP", "C_HUD", "C_GUN",
           "C_QSET", "C_BLINE", "C_WPAIR", "C_CHUNK", "C_PMUL", "C_WSTEP",
           "C_JOINT"):
    globals()[_n] = _equ(_n, globals()[_n])
# raster.asm owns the chunk sizes; they are `1<<RQ_BLOG`, so read the logs
RQ_BCH = 1 << _equ("RQ_BLOG", 5, "raster.asm")
RQ_WCH = 1 << _equ("RQ_WLOG", 3, "raster.asm")
RQ_SPLIT = _equ("RQ_SPLIT", 0, "raster.asm")
C_QUAD = _equ("C_QUAD", 740)         # the whole-quad charge pace_quad
C_QS = _equ("C_QS", 22)              # takes when RQ_SPLIT is 0
C_QW = _equ("C_QW", 128)
# ...and the joint's own two gates, from the two files that own them:
# COURSES is vpcfg.inc's (it is what compiles the whole thing in or out)
# and JOINT_KMAX is raster.asm's LOD cut, which main3.asm's charge quotes
# by NAME.  Neither is copied here for the same reason C_BG is not.
COURSES = _equ("COURSES", 0, "vpcfg.inc")

# THE COLUMN RENDERER.  vpcfg.inc's VPCOL picks engine2/src/rastcol.asm
# over raster.asm, and its charge is not per quad at all -- it is one
# upper-bound hook per column PAIR, drawn or skipped, plus a hook per
# face and one for rc_pnext's clamped slow step.  colmodel.charge is the
# twin of those hooks, the way quad_units below is the twin of
# pace_quad, and the constants live in engine2/src/costcol.inc -- the
# ONE file main3.asm and tst_rcol.asm both include -- so they are read
# from there.
VPCOL = _equ("VPCOL", 0, "vpcfg.inc")
C_CFACE = _equ("C_CFACE", 1700, "costcol.inc")
C_CFRAME = _equ("C_CFRAME", 2000, "costcol.inc")
C_CSKIP = _equ("C_CSKIP", 370, "costcol.inc")
C_COLS = _equ("C_COLS", 700, "costcol.inc")
C_COLSO = _equ("C_COLSO", 800, "costcol.inc")
C_CBAND = _equ("C_CBAND", 460, "costcol.inc")
C_COLR = _equ("C_COLR", 22, "costcol.inc")
C_CEDGE = _equ("C_CEDGE", 60, "costcol.inc")
C_CSTEP = _equ("C_CSTEP", 120, "costcol.inc")
C_CFAR = _equ("C_CFAR", 1600, "costcol.inc")
C_CFARP = _equ("C_CFARP", 900, "costcol.inc")
C_CFARS = _equ("C_CFARS", 175, "costcol.inc")
C_CFAREND = _equ("C_CFAREND", 400, "costcol.inc")
JOINT_KMAX = _equ("JOINT_KMAX", 3, "raster.asm")
if COURSES and RQ_SPLIT:
    # ...and say so rather than modelling it silently: this pair draws
    # joints that nothing charges (joint_units explains where the hole
    # is), so every "locked" claim below would be about a disc that
    # spends microseconds the accumulator never hears about.
    sys.stderr.write("pacemodel: COURSES 1 with RQ_SPLIT 1 -- raster_frame"
                     " draws the joints and NOTHING charges them.  This"
                     " model reproduces that hole; the disc is unpaced.\n")


def quad_units(q, cyh=None):
    """The charges raster_quad hands the accumulator for ONE quad, in the
    order it hands them over -- one per point at which it can yield.

    This is the twin of raster.asm's rq_bchunk / rq_wchunk.  A quad used
    to be a single unit of up to 12486 us, which is what stopped the frame
    packing into fewer periods; it is now C_QSET plus a chunk per RQ_BCH
    body scanlines plus a chunk per RQ_WCH wedge pairs, and the largest of
    those is about an eighth of a vsync period.
    """
    import rastermodel as _rm
    if not RQ_SPLIT:
        # raster.asm's mid-quad yield is compiled OUT: main3.asm:pace_quad
        # charges the whole quad up front and the quad is one unit.
        cyh = cyh or _rm.cfg().CYH
        blo, bhi, hlo, hhi = q[0], q[1], q[2], q[3]
        bw = abs(bhi - blo)
        jlo = cyh if hlo >= cyh * 16 else (hlo >> 4)
        jhi = min(cyh, hhi >> 4)
        return [C_QUAD + (jlo + jhi) * (C_QS + 2 * bw) + C_QW * (jhi - jlo)]
    sh = _rm.quad_shape(q)
    u = [C_QSET]
    n, bpl = sh["bh"], C_BLINE + 4 * sh["npush"]
    while n > 0:
        k = min(RQ_BCH, n)
        n -= k
        u.append(C_CHUNK + (0 if k == RQ_BCH else C_PMUL) + k * bpl)
    pre, i = sh["wpre"], 0
    while i < len(pre):
        k = min(RQ_WCH, len(pre) - i)
        # ...+ C_WSTEP*w for the Bresenham steps this chunk could take.
        # The edge cannot pass the pinned column, so w bounds them -- see
        # raster.asm:rq_wchunk for why they cannot be charged up front.
        u.append(C_CHUNK + (0 if k == RQ_WCH else C_PMUL)
                 + k * (C_WPAIR + 4 * pre[i]) + C_WSTEP * pre[i])
        i += k
    return u


def quad_cost(q, cyh=None):
    """What a whole quad is charged, summed over its chunks."""
    return sum(quad_units(q, cyh))


def joint_units(q):
    """The charges raster_paced hands the accumulator for ONE face's two
    course boundaries -- [C_JOINT], or [] when it hands over nothing.

    THIS IS A UNIT OF ITS OWN AND NOT PART OF quad_units, exactly as it is
    in main3.asm: folding the joints into pace_quad's charge would make a
    face-plus-its-joints the largest atomic thing in the frame, and the
    period is set by the largest atomic unit rather than by the total.
    Charged separately, a yield may fall between a face and its joints.
    (It is also what keeps quad_cost comparable with a benched
    raster_quad, which is what emu_pacefit.py holds it against.)

    THE GATE IS main3.asm:rp_nojoint's, NOT raster_joint's OWN.  The two
    are deliberately different and the model has to follow the CHARGE:

      * raster_paced reads +6 kind and +7 k and skips the charge on
        kind != 0 or k > JOINT_KMAX.  That is all it tests.
      * raster_joint tests those two as well, and then also drops out on
        a face under a byte wide and on a face whose whole joint sits
        past the horizon (rastermodel.joint_rows returns None for both).

    So there are faces that are CHARGED C_JOINT and draw nothing.  Reading
    joint_rows here instead would be modelling the drawing, and would
    under-charge the disc on exactly those faces -- which is the wrong
    direction for a model whose entire contract is est >= actual.

    AND THE DIVERGENCE IS MEASURED, not assumed.  Over 3000 states and
    12561 quads, 7248 faces are charged C_JOINT and 7130 of them draw
    joints: 118 faces, 1.63% of the charged ones, pay for nothing.  No
    face draws a joint without being charged for it -- that is asserted
    per face, not sampled -- so this gate is a strict superset of
    raster_joint's and the charge is one-sided the way every other
    constant in this file is.

    RQ_SPLIT IS PART OF THE GATE TOO, and not because the joints get
    cheaper.  main3.asm's joint charge lives in raster_paced's RQ_PACED==0
    arm; at RQ_SPLIT 1, raster_paced is `jp raster_frame`, and
    raster.asm:raster_frame calls raster_joint with NO cost hook in front
    of it at all.  The disc would then draw joints it never charged for,
    so a COURSES 1 / RQ_SPLIT 1 build is NOT paced -- see the note in
    units().  The disc ships RQ_SPLIT 0.
    """
    if not COURSES or RQ_SPLIT:
        return []
    kind, k = q[4], q[5]
    if kind or k > JOINT_KMAX:          # a door is not masonry, and
        return []                       # neither is a far face
    return [joint_cost(q)]


# ---------------------------------------------------------------------
#  IT IS NO LONGER A FLAT CONSTANT, AND THAT IS WHY THE DISC LOCKS.
#
#  A joint's cost is dominated by its ROW COUNT, and that varies by more
#  than thirty to one across the faces one frame produces: two mirrored
#  rows on a wall seen square on, seventy on a steeply raked one.  A
#  single constant has to cover the worst of them, so the flat
#  C_JOINT = 7400 billed the worst state's six jointed faces 44,400 us for
#  about ten milliseconds of real work -- and the accumulator then bought
#  vsync periods to cover microseconds nobody was ever going to spend.
#  Exhaustive over all 4,055,040 reachable states:
#
#      flat 7400      worst charged frame 147,894 us   407 states need a
#                                                      NINTH period
#      per row pair   worst charged frame 112,090 us   0 states need an
#                                                      EIGHTH
#
#  Same pixels, same code in raster_joint, two vsync periods back: 5.56
#  fps with excursions becomes 7.15 fps locked.
#
#      us = 480 + 160*pairs + 8*D
#
#  pairs = j1e - j0 is the mirrored row range raster_joint's loop runs
#  over, D = |bhi - blo| the face width in bytes -- the same two numbers
#  the loop is bounded by.  160 = 128 + 32, so the Z80 does two shifts and
#  an add rather than a multiply, and j0 / j1 come out of the DIV3 table
#  raster_joint already uses.
#
#  It stays ONE-SIDED like every other constant in this file: the row
#  range is taken BEFORE raster_joint's own "face under a byte wide" and
#  "joint past the horizon" drop-outs, so a face can be charged and draw
#  nothing, never the reverse.
# THE COEFFICIENTS ARE ONE-SIDED, AND THE FIRST SET WAS NOT.  480/160/8
# reproduced the measured cost closely -- 7232 us against a benched 7189
# on the worst face -- and closely is the wrong target.  Every constant in
# this file has to be an OVER-estimate on EVERY input, because the
# accumulator's whole safety argument is that it never believes it has
# more room than it does.  pacescan replayed 480/160/8 as zero states over
# budget and the BOOTED DISC then took an eighth period on the worst state
# in the maze: the replay cannot see an under-charge, by construction --
# it replays the charge, and an under-charge simply overruns the interval
# without ever asking for another wait.
#
# 900 also has pace_joint's OWN cost to carry, which nothing else charges:
# reading the record, two DIV3 lookups and the shifts, about 80 us a
# jointed face plus ~12 us a quad for the kind/k gate.
#
# 640/176/10 was the SECOND set and it was still under.  emu_pacefit.py,
# benching the charged blocks at the 24 worst states, read raster_paced at
# "charge - measured min -2415.4 us" -- under on some frames even though
# the whole frame had 26 ms of slack, because what matters is not the
# total: an interval that overruns ONE 19,968 us vsync period puts the
# yield past the edge and the frame quietly takes another period.  That is
# how the booted disc showed 8 vsyncs on the worst state while pacescan
# replayed zero states over budget.  900/192/12 puts the worst face at
# 9,492 us against 7,189 measured.
J_BASE, J_PAIR, J_WIDE = 1150, 192, 12


def joint_cost(q, cyh=None):
    """-> microseconds raster_paced charges for ONE face's two joints."""
    import rastermodel as _rm
    CYH = cyh or _rm.cfg().CYH
    blo, bhi, hlo, hhi = q[0], q[1], q[2], q[3]
    off = (3 * CYH + 3) * 16            # raster.asm's J_OFF
    j0 = CYH if hlo >= off else (hlo >> 4) // 3
    j1 = CYH if hhi >= off else (hhi >> 4) // 3
    j1e = j1 if j1 >= CYH else j1 + 1   # the thickening row
    pairs = max(0, j1e - j0)
    return J_BASE + J_PAIR * pairs + J_WIDE * abs(bhi - blo)


def units(ncell, faces, quads, cyh, dlift=0):
    """The frame's work, in the order the Z80 charges it.

    ncell  cells the flood popped                (march.asm, m_visited)
    faces  [(emitted, nclip)] per candidate face, in projection order
    quads  the quad records raster_paced will draw, in order
    dlift  HOW FAR A RUNNING DOOR HAS RISEN, 0..255, as game.asm's
           door_lift hands it to rc_dlift.  0 is "no door is running",
           which is nearly every frame.

    THIS ARGUMENT DID NOT EXIST AND THE DEFAULT WAS THE BUG.  colmodel
    has implemented the lift since the animation landed -- slide(),
    pair_walk(..., dlift) -- and this file never passed it, so every
    moving-door sweep charged a FULL-HEIGHT door face for all six frames
    of a run in which the disc raises the bottom edge by DLIFT = 42, 85,
    128, 170, 213 of 256.  A door one cell away is the biggest quad the
    engine can draw, so that over-charge is the whole of the
    moving-door figure this project has quoted as its open problem.

    -> [(room, charge)], what cost_room / cost_add are given.
    """
    u = [(0, C_BG, C_BG), (0, C_MSETUP, C_MSETUP)]
    u += [(0, C_CELL, C_CELL)] * ncell
    u.append((2, 0, 0))                 # project_all's cost_gate
    for emitted, nclip in faces:
        u.append((1, 0, (C_FACE if emitted else C_REJ) + C_CLIP * nclip))
    # ONE UNIT PER CHUNK, not one per quad: raster_quad yields inside
    # itself, so the accumulator sees a quad as a run of small units.
    #
    # ...AND THEN THAT FACE'S COURSE JOINTS, which are a unit of their own
    # -- see joint_units.  THIS MODEL SPENT THE WHOLE OF THE COURSES 1
    # ERA WITHOUT THEM.  main3.asm charged C_JOINT and this file did not
    # know the constant existed, so pacescan.py went on reporting the
    # FLAT-WALL worst frame (103494 us) for a disc drawing masonry, and
    # C_QUAD and PACE_FRAMES were being searched against a build nobody
    # had.  At 7400 us a face, a frame with several jointed faces is tens
    # of milliseconds heavier than that number: the exhaustive answer was
    # not slightly stale, it was about a different program.
    # ...then the door animation, which walks the finished quad list
    # between project_all and the rasteriser (main3.asm).  It is charged
    # on every frame because the hook is unconditional.
    u.append((0, C_DANIM, C_DANIM))
    if VPCOL:
        # ONE WALK OVER THE WHOLE LIST, not one per quad: the column
        # renderer's charge depends on what the NEARER faces have already
        # covered, so a quad cannot be costed on its own.
        # ...and IMPORT rastermodel HERE.  This read a module global `_rm`
        # that only pacescan.py ever set (it does `pm._rm = rm` in its
        # worker initialiser), so pacescan worked and every other caller
        # of units() died with NameError the moment VPCOL was 1 --
        # emu_pace3.py, the harness that measures the BOOTED DISC against
        # this model, could not run at all.  The one tool that could see
        # the disc disagree with the model was the one the bug silenced.
        import colmodel as _cm
        import rastermodel as _rm
        u += [(0, cc, cc) for cc in
              _cm.charge(quads, _rm.cfg(), C_CFRAME, C_CFACE, C_CSKIP,
                         C_COLS, C_CBAND, C_COLR, C_CEDGE, C_CSTEP,
                         dlift=dlift, c_colso=C_COLSO,
                         c_cfar=C_CFAR, c_cfarp=C_CFARP,
                         c_cfars=C_CFARS, c_cfarend=C_CFAREND)]
    else:
        for q in quads:
            u += [(0, cc, cc) for cc in quad_units(q, cyh)]
            u += [(0, jc, jc) for jc in joint_units(q)]
    u.append((0, C_HUD, C_HUD))
    # ---- THE HUD'S OWN CHARGES, AND THEY GO HERE, NOT IN THE TAIL ----
    #
    # main3.asm:1047-1051 calls hud_ammo, hud_scan and hud_radar between
    # C_HUD's cost_unit and C_PIP's, and every charge they make is a
    # cost_add -- hud2.asm:359, :436, :517, :551, :580, :592, :617.
    #
    # Both this file's sweep and pacescan.py used to fold all of them
    # into the frame HEAD instead, which is the one place they can never
    # be: pace_drain zeroes the accumulator at the end of the frame that
    # made them.  See frame_head() for what that cost.
    #
    # THE WORST CASE, WHICH IS WHAT THESE ARE:
    #   C_AMMO     hud_ammo when the round count moved
    #   C_SCAN     hud_scan when the nearest pickup's bearing moved
    #   C_HP       hud_health when a hit point moved
    #   C_SWEEP    the sweep and the six-way compare -- EVERY frame,
    #              unconditionally (hud2.asm:617)
    #   C_BLIP x8  one per blip that moved: six ammo cells, plus the
    #              monster's erase and its redraw
    #   C_RNEEDLE  putting the compass needle back after a blip erase
    #              clipped it
    # They are not all reachable on one frame -- a frame that moves the
    # ammo count is not usually a frame that moves six blips -- so this
    # is pessimistic on purpose, the same way every other C_* is.  What
    # was wrong before was the POSITION, not the total.
    #
    # ...AND THE GATES THAT KEEP THEM INSIDE A PERIOD.  Ungated, this run
    # can start at COST_THI-1 = 19455 and end at 29535, which is a period
    # and a half -- see the cost_add note in main3.asm.  HUD_GATE picks
    # which arrangement is modelled; the disc's is the one that is 2.
    if HUD_GATE == 1:
        u.append((2, HUD_THI1, 0))              # one gate, low threshold
    elif HUD_GATE == 2:
        u.append((2, HUD_THI_A, 0))             # ...ahead of the readouts
    u.append((3, 0, C_AMMO))
    u.append((3, 0, C_SCAN))
    u.append((3, 0, C_HP))
    if HUD_GATE == 2:
        u.append((2, HUD_THI_R, 0))             # ...and ahead of the dial
    u.append((3, 0, C_SWEEP))
    u += [(3, 0, C_BLIP)] * N_BLIP
    u.append((3, 0, C_RNEEDLE))
    # main3.asm: the minimap, then three hooks for the world drawers
    u.append((0, C_PIPP, C_PIPP))
    u.append((0, C_PIPM, C_PIPM))
    u.append((0, C_PIPF, C_PIPF))
    if GUN and GUN_CHARGED:
        u.append((0, C_GUN, C_GUN))     # main3.asm:gun_paced, room then charge
    return u


def frame_head(space=True):
    """What (cost_acc) really carries into the next frame's first interval.

    THERE WERE FOUR DIFFERENT ANSWERS TO THIS IN engine2/tools, and that
    is why it is a function now.  pacescan.py said C_TAIL + C_SND +
    C_DOORACT + C_AMMO + C_SCAN + C_SWEEP + 8*C_BLIP + C_RNEEDLE =
    16230; this file's own sweep said 10800; emu_pace3.py and
    guardfit.py said C_TAIL + C_DOORACT = 3950.  Three of the four are
    wrong and the wrongest is the one `make pace` runs.

    WHAT THE DISC DOES.  main3.asm calls hud_ammo, hud_scan and
    hud_radar at :1047-1051 and pace_drain at :1060, and pace_drain
    opens with

        ld b,a / xor a / ld (pace_left),a / ld h,a / ld l,a
        ld (cost_acc),hl

    -- it ZEROES the accumulator, unconditionally, before its wait loop.
    So every charge those three routines make through cost_add is wiped
    at the end of the frame it was made in.  None of C_AMMO, C_SCAN,
    C_SWEEP, C_BLIP or C_RNEEDLE can reach the next frame's head; they
    belong in units(), positioned where main3.asm runs them, and that is
    where they now are.

    The only charge that outlives the drain is game.asm:809's
    C_DOORACT, added after it on the frames a player taps SPACE.  On top
    of that main_loop's head adds C_TAIL + C_SND explicitly.

    WHY IT MATTERS THAT THIS IS SMALL.  16230 + C_BG 9320 = 25550, over
    COST_THI 19456, so the model made bg_fill's cost_unit yield on the
    first unit of every frame -- and a yield costs a wait.  The disc's
    6150 + 9320 = 15470 does not yield at all.  The model was spending a
    vsync period a frame that the machine never spends, which put its
    whole wait histogram one column to the right: doors shut read 3.956%
    of states over budget where the corrected head reads 0.054%.
    """
    return C_TAIL + C_SND + (C_DOORACT if space else 0)


def segments(u, acc=0, thresh=THRESH, tail=None, n=PACE_FRAMES):
    """Greedy, exactly as cost_room / cost_unit / pace_drain do it.

    -> (waits taken during the work, worst interval estimate, acc carried
        into the next frame)
    """
    acc += frame_head() if tail is None else tail
    waits, worst, left = 0, acc, n
    for after, room, charge in u:
        if after == 0:                      # ROOM THEN CHARGE
            if acc + room >= thresh and left:
                waits += 1
                left -= 1
                worst = max(worst, acc)
                acc = 0
            acc += charge
        elif after == 2:                    # THE GATE, charging nothing
            # ...against its OWN threshold, carried in the room field.
            # project_all's gate uses FACE_THI, which is COST_THI less
            # one worst face; the HUD's gates use COST_THI less the
            # worst run of cost_adds that follows them.  Same idea, one
            # threshold per thing being gated, so 0 means "the default".
            if acc >= (room or FTHRESH) and left:
                waits += 1
                left -= 1
                worst = max(worst, acc)
                acc = 0
        elif after == 3:
            # cost_add: CHARGE, NO TEST, NO WAIT.  main3.asm:1302.
            #
            # AND IT REALLY MUST NOT TEST.  A cost_add can leave the
            # accumulator ABOVE the threshold -- that is the whole point
            # of it, it hands the microseconds to whatever tests next --
            # so modelling it as a roomed unit with room 0 would fire a
            # wait the Z80 does not take.  The HUD makes five of these in
            # a row; the first one that pushed past COST_THI would have
            # invented a yield for each of the other four.
            acc += charge
        else:                               # CHARGE THEN TEST
            acc += charge
            if acc >= FTHRESH and left:
                waits += 1
                left -= 1
                worst = max(worst, acc)
                acc = 0
    worst = max(worst, acc)
    # pace_drain ends the frame on a vsync edge and zeroes cost_acc --
    # UNCONDITIONALLY.  This used to be `if left:`, which carried the
    # accumulator over on an exhausted budget; the disc does not (see
    # the listing quoted in frame_head).  Every caller passes n=99, so
    # the two agreed in practice, but gridpace.py takes the default.
    acc = 0
    return waits, worst, acc


# ------------------------------------------------------------- the sweep --
def _state_units(solid, px, py, a, cyh, dlift=0):
    import marchmodel as mm
    import projmodel as pm
    nclip = [0]
    real = pm.lerp

    def counting(*args):
        nclip[0] += 1
        return real(*args)
    pm.lerp = counting
    try:
        r = mm.march(solid, px, py, a)
        ipx, ipy = px >> 8, py >> 8
        faces, quads = [], []
        for (wx, wy, fd, door, k), v in zip(r["faces"], r["fviews"]):
            (ax, ay), _b, _n = pm.face_endpoints(wx, wy, fd)
            nclip[0] = 0
            q = pm.project_face(v[0], v[1], v[2], v[3], ax - ipx, ay - ipy, fd)
            faces.append((q is not None, nclip[0]))
            if q is not None:
                quads.append(q + (door, k))
        return units(r["visited"], faces, quads, cyh, dlift)
    finally:
        pm.lerp = real


def sweep(n=3000, seed=90210):
    import emu_frame as ef
    import rastermodel as rm
    grid, solid = ef.load()
    cyh = rm.cfg().CYH
    rnd = random.Random(seed)
    # THE SUB-CELL LATTICE A WALKING PLAYER ACTUALLY LANDS ON: the step is
    # 24/256 of a cell a frame and gcd(24, 256) = 8, so the offsets are the
    # multiples of 8, not the multiples of 32 this used to sample.  Same
    # trap emu_pace.py documents; the replay has to be on the same lattice
    # as the measurement or the two are not talking about the same states.
    import emu_pace as ep
    offs = ep.lattice_offsets()
    pool = [((cx << 8) | ox, (cy << 8) | oy, a)
            for (cx, cy) in ef.floors(grid) for ox in offs for oy in offs
            for a in range(72)
            if ef.reachable(solid, (cx << 8) | ox, (cy << 8) | oy, 64)]
    print(f"{len(pool)} reachable states; replaying {n}")
    hist = collections.Counter()
    wmax, wst, emax, est_ = 0, None, 0, None
    for st in rnd.sample(pool, min(n, len(pool))):
        u = _state_units(solid, st[0], st[1], st[2], cyh)
        acc = 0
        for _ in range(3):                       # settle the carry-over
            waits, worst, acc = segments(u, acc, n=99, tail=frame_head())
        hist[waits] += 1
        if worst > wmax:
            wmax, wst = worst, st
        tot = sum(c for _, _, c in u)
        if tot > emax:
            emax, est_ = tot, st
    print("waits the accumulator asks for (uncapped):")
    for k in sorted(hist):
        print(f"   {k}  {hist[k]:6d}  {100.0*hist[k]/n:5.2f}%"
              f"   -> {k+1} periods"
              + ("" if k < PACE_FRAMES else "   <-- OVER BUDGET"))
    print(f"worst interval estimate {wmax} us at {wst}  "
          f"(threshold {THRESH}, period 20000)")
    print(f"worst frame estimate    {emax} us at {est_}  "
          f"(budget {PACE_FRAMES*THRESH})")
    # N WAITS IS N+1 PERIODS, and this line used to say `<=`.
    #
    # A frame with w waits occupies w+1 vsync periods -- the w intervals
    # the waits end, plus the tail from the last wait to the flip.  So
    # the budget of PACE_FRAMES periods is spent by PACE_FRAMES-1 waits,
    # and a state asking for PACE_FRAMES waits is already one period
    # late.  pacescan.py has always had this right (`if w >=
    # pm.PACE_FRAMES: over.append(...)`) and its legend prints the
    # arithmetic out loud, `{k} waits -> {k+1} periods`.
    #
    # This file did not, so it returned 0 -- PASS -- on a state space
    # pacescan calls over budget, and `make pace` runs BOTH.  The
    # exhaustive scan's non-zero exit was the only thing reporting the
    # failure, and the sampled replay printed a histogram whose last
    # row was the over-budget row without saying so.  Read together
    # they looked like a pass with a bit of headroom left.
    return 0 if max(hist) < PACE_FRAMES else 1


if __name__ == "__main__":
    raise SystemExit(sweep(int(sys.argv[1]) if len(sys.argv) > 1 else 3000))
