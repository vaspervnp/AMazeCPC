"""engine2/tools/sprcover.py -- A PICTURE, AS RECTANGLES THE Z80 CAN AFFORD.

Turns a band grid -- pens and holes -- into the `db col, ncol, band0,
band1, pen` list pip.asm's spr_draw walks, in PAINTER order.

THE OBJECTIVE IS MICROSECONDS, NOT RECTANGLES.  hud_rect costs 87 us a
CALL and 63 us a ROW and almost nothing to widen, so a cover with fewer
rectangles can easily be dearer than one with more.  The first version
of this file maximised "does not change the picture" and cheerfully grew
a one-pair rectangle over the whole box: same monster, four times the
money.  cost() below is the whole judgement.

AND THE SEARCH DOES NOT HAVE TO BE GOOD.  genspr.py asserts that
painting the result reproduces the sheet EXACTLY and prints what it
costs, so a better search shows up as a smaller number and nothing else
moves.  What is here -- randomised-restart greedy, hill-climbed on cost
-- beats the hand-tuned art it replaced by 505.6 us across the two
sprites while drawing the identical picture.
"""

"""The rectangle cover, written once so genspr.py can be read."""


import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import sprpng                                                    # noqa: E402

_paint = sprpng.paint


def _cells(r):
    c, n, b0, b1, _p = r
    return [(b, x) for b in range(b0, b1 + 1) for x in range(c, c + n)]


def _seed(target, nb, ncols, lo, rng):
    """target[b][x] = pen or None -> a rectangle list in PAINTER order.

    STAGE 1, REVERSE GREEDY.  Rectangles are chosen LAST-DRAWN FIRST.  A
    rectangle drawn last must show through everywhere it covers, so every
    cell it touches has to be its own pen -- unless the cell is already
    resolved, in which case something drawn even later repaints it.

    STAGE 2, HILL CLIMB.  Greedy cannot find the trick the hand-drawn art
    used: paint the head across two bands and put the eyes ON TOP, which
    is one rectangle fewer than painting the head around them.  So every
    rectangle is offered every expansion, and any expansion that leaves
    the painted picture unchanged is kept -- because it can make a later
    rectangle redundant.  Then redundant rectangles are dropped.

    Neither stage has to be right.  paint() == target is asserted by the
    caller, and that is what makes the answer trustworthy whatever found
    it.
    """
    resolved = set()
    todo = {(b, x) for b in range(nb) for x in range(ncols)
            if target[b][x] is not None}
    out = []
    while todo:
        cands = []
        for b0 in range(nb):
            for b1 in range(b0, nb):
                for x0 in range(ncols):
                    for x1 in range(x0, ncols):
                        pens = {target[b][x] for b in range(b0, b1 + 1)
                                for x in range(x0, x1 + 1)
                                if (b, x) not in resolved}
                        pens.discard(None)
                        if len(pens) != 1:
                            continue
                        pen = pens.pop()
                        ok = all(target[b][x] == pen or (b, x) in resolved
                                 for b in range(b0, b1 + 1)
                                 for x in range(x0, x1 + 1))
                        if not ok:
                            continue
                        g = sum(1 for b in range(b0, b1 + 1)
                                for x in range(x0, x1 + 1)
                                if (b, x) in todo and target[b][x] == pen)
                        if g:
                            cands.append((g, (x0, x1 - x0 + 1, b0, b1, pen)))
        if not cands:
            raise AssertionError("no rectangle covers the remaining cells")
        # PICKING THE BIGGEST GAIN EVERY TIME IS WHAT LOSES.  Taking the
        # monster's two eyes FIRST lets one rectangle then cover its head
        # across two bands and be cut back into -- six rectangles instead
        # of seven -- and no greedy that always takes the largest bite can
        # get there.  So the choice is randomised over the best few and
        # cover() keeps the cheapest of many restarts.
        cands.sort(key=lambda t: -t[0])
        top = [c for g, c in cands if g >= cands[0][0] - 1] or [cands[0][1]]
        best = rng.choice(top)
        out.append(best)
        # GRID COORDINATES UNTIL THE VERY END.  `resolved` and `todo` are
        # indexed 0..ncols-1; storing a rectangle in the sprite's own
        # signed columns here left todo un-emptied and the loop never
        # finished, because discard() was handed x = -1 for cell 0.
        for c in _cells(best):
            resolved.add(c)
            todo.discard(c)
    out.reverse()
    return [(c + lo, n, b0, b1, pen) for (c, n, b0, b1, pen) in out]


# hud_rect, MEASURED (see genspr.py): 87 us a CALL and 63 us a ROW, and
# a row is nearly free to widen.  So a cover is judged on calls AND rows
# drawn, never on the number of rectangles alone -- the first hill-climb
# written here maximised nothing but "does not change the picture" and
# happily grew a one-pair rectangle over the whole box, which paints the
# same monster for four times the money.
C_CALL, C_ROW = 87, 63
BOX = 28                        # rows at one cell -- the case the budget is set by


def cost(rects, edges):
    """-> us for this list at a BOX-row box.  The objective, in full."""
    rows = sum(edges[b1 + 1] - edges[b0] for (_c, _n, b0, b1, _p) in rects)
    return C_CALL * len(rects) + C_ROW * rows * BOX / 256.0


def _climb(rects, target, nb, ncols, lo, edges):
    """Improve until nothing gets cheaper.  Correctness is never traded:
    every candidate must paint the target exactly."""
    best = cost(rects, edges)
    changed = True
    while changed:
        changed = False
        for i in range(len(rects)):
            trial = rects[:i] + rects[i + 1:]
            if _paint(trial, nb, ncols, lo) == target:
                c = cost(trial, edges)
                if c < best:
                    rects, best, changed = trial, c, True
                    break
        if changed:
            continue
        # MERGE TWO OF A PEN INTO THE BOX AROUND THEM.  This is the move
        # the hand-drawn art made and greedy cannot: paint the head across
        # two bands and let the eyes, which come LATER in painter order,
        # cut back into it.  One call instead of two, and the rows are the
        # same rows -- a rectangle is charged its band height once however
        # wide it is.
        for i in range(len(rects)):
            for j in range(len(rects)):
                if i == j or rects[i][4] != rects[j][4]:
                    continue
                ci, ni, i0, i1, pen = rects[i]
                cj, nj, j0, j1, _ = rects[j]
                c0, c1 = min(ci, cj), max(ci + ni, cj + nj) - 1
                box = (c0, c1 - c0 + 1, min(i0, j0), max(i1, j1), pen)
                keep = min(i, j)
                trial = [r for k, r in enumerate(rects) if k not in (i, j)]
                trial.insert(min(keep, len(trial)), box)
                if _paint(trial, nb, ncols, lo) != target:
                    continue
                c = cost(trial, edges)
                if c < best - 1e-9:
                    rects, best, changed = trial, c, True
                    break
            if changed:
                break
        if changed:
            continue
        for i in range(len(rects)):
            pen = rects[i][4]
            for b0 in range(nb):
                for b1 in range(b0, nb):
                    for x0 in range(ncols):
                        for x1 in range(x0, ncols):
                            cand = (x0 + lo, x1 - x0 + 1, b0, b1, pen)
                            if cand == rects[i]:
                                continue
                            trial = list(rects)
                            trial[i] = cand
                            if _paint(trial, nb, ncols, lo) != target:
                                continue
                            c = cost(trial, edges)
                            if c < best - 1e-9:
                                rects, best, changed = trial, c, True
                                break
                        if changed: break
                    if changed: break
                if changed: break
            if changed: break
    return rects


# MEASURED: 8 restarts already finds the best cover of both shipped
# sprites, and 240 finds nothing better -- 4953.6 us either way.  32 is
# eight with margin, and costs 1.8 s of the build.
RESTARTS = 32

# ...AND A CLOCK, because the sheet is painted by hand now.  The climb
# enumerates nb^2 * ncols^2 candidates per rectangle per pass, so a
# sprite with fifteen bands is hundreds of times the work of one with
# four -- and the first thing a striped test sprite did was hang the
# build with no output.  A build step an artist can wedge by drawing is
# not a build step.  MINIMUM restarts always run, so the answer never
# depends on how busy the machine was; the clock only stops the extras.
SECONDS = 2.5
MINIMUM = 4


def cover(target, nb, ncols, lo, edges, restarts=RESTARTS,
          seconds=SECONDS):
    """-> (rects in painter order, restarts actually run).

    Randomised restarts of the greedy, each hill-climbed on COST, keeping
    the best.  The search does not have to be optimal or even good: the
    caller asserts that painting the result reproduces the sheet exactly,
    and prints what it costs.  A better search would show up as a smaller
    number in that print and nothing else would move.
    """
    import random
    import time
    rng = random.Random(20260907)
    best, bc, n = None, float("inf"), 0
    t0 = time.time()
    for i in range(restarts):
        if i >= MINIMUM and time.time() - t0 > seconds:
            break
        r = _climb(_seed(target, nb, ncols, lo, rng), target, nb, ncols, lo,
                   edges)
        c = cost(r, edges)
        n = i + 1
        if c < bc:
            best, bc = r, c
    return best, n
