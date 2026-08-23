"""Frame budget for the free-angle renderer.

Two layers of cost:

  (A) THE VALIDATED LAYER -- identical arithmetic to tools/cost.py, counting
      fill bytes, span-lines and rect-lines from the very same quantised
      runs.  This is the part the x1.27 hardware calibration was measured on:
          model_us = (fill/2)*4 + span_lines*28 + rect_lines*19
          hw_ms    = 4.1 + 1.27 * model_us/1000

  (B) THE NEW LAYER -- work the shipped engine does not do at all, because it
      looks the answer up in a table.  Estimated in CPC microseconds directly
      (so it is NOT multiplied by 1.27 again -- that factor calibrates the
      fill/setup model, not these).  Every assumption is a named constant
      below with its justification.
"""

import geom
from geom import Rect

US_PER_PUSH = 4
US_SPAN_LINE = 28
US_RECT_LINE = 19

# ---------------------------------------------------------------- (B) ------
# Grid march: pop a cell, bounds+L1 test, maze lookup, transform the cell to
# view space for the frustum test (2 table lookups + 2 16-bit subs per axis,
# ~56 us), 4 neighbour pushes with a "already queued" bitmap test.
US_MARCH_CELL = 60

# Per visible face, at runtime:
#   backface test (axis-aligned: one 16-bit compare)                  30 us
#   2 endpoints -> view space.  Endpoints are GRID CORNERS, so
#     xv = COS[a][i] - SIN[a][j] - cx0,  z = SIN[a][i] + COS[a][j] - cz0
#     with 72*16*2*2 = 4608 bytes of k*cos / k*sin tables.  ~56 us each   112
#   clip to near + 2 lateral planes (mostly compare-only; a real clip
#     costs a reciprocal + lerp).  Amortised                            80
#   2 perspective divides: reciprocal table lookup (~70 us) + one
#     log/antilog 8-bit multiply for x_screen (~55 us) + y_top/y_bot
#     from s by a shift (~10 us)                              2 x 135 = 270
#   edge slope dx/dy for the two wedges: 1 reciprocal + 1 multiply       125
#   depth->pen, painter key, insert into the sorted draw list            60
#                                                                    ------
#                                                                      677
US_FACE = 500           # central estimate; sensitivity reported at 300/800

# Building one entry of a per-scanline span list at runtime:
#   add slope to the 16.8 edge accumulator (5), take the high byte and
#   halve it to a byte column (3), npush = (right-left)>>1 forced even (8),
#   store the 2-byte record (6)   =  ~22 us
US_SPAN_GEN = 20

# The shipped engine draws the background unconditionally (README: the
# occluder optimisation was REMOVED on purpose so that every frame costs the
# same).  Keep parity.
USE_OCCLUDER = False


def count(frame):
    """-> dict of raw counters + microsecond breakdown."""
    fill = 0
    rect_lines = 0
    span_lines = 0

    for y0, y1, _pen in frame["bands"]:
        h = max(0, y1 - y0)
        rect_lines += h
        fill += h * geom.VP_BW

    for g, _pen in frame["faces"]:
        if isinstance(g, Rect):
            rect_lines += g.h
            fill += g.h * g.npush * 2
        else:
            span_lines += len(g.lines)
            fill += g.fill_bytes

    model_us = (fill // 2) * US_PER_PUSH + span_lines * US_SPAN_LINE \
        + rect_lines * US_RECT_LINE

    # --- optional optimisation, reported separately -----------------------
    # A projected wall quad has VERTICAL left/right edges, so its middle is a
    # constant-width rectangle and only the two wedges at top and bottom
    # vary.  Splitting a Spans face into (wedge, rect, wedge) turns most of
    # its lines back into 19 us rect-lines that need no runtime list entry.
    opt_span = 0
    opt_rect = rect_lines
    for g, _pen in frame["faces"]:
        if isinstance(g, Rect):
            continue
        run = 1
        for i in range(1, len(g.lines) + 1):
            same = i < len(g.lines) and g.lines[i] == g.lines[i - 1]
            if same:
                run += 1
            else:
                if run >= 2:
                    opt_rect += run
                else:
                    opt_span += run
                run = 1
    opt_model_us = (fill // 2) * US_PER_PUSH + opt_span * US_SPAN_LINE \
        + opt_rect * US_RECT_LINE
    _opt_new = (frame["cells_visited"] * US_MARCH_CELL
                + frame["n_faces"] * US_FACE + opt_span * US_SPAN_GEN)
    opt_total_ms = 4.1 + 1.27 * opt_model_us / 1000.0 + _opt_new / 1000.0
    opt_net_ms = 0.46 + 1.27 * opt_model_us / 1000.0 + _opt_new / 1000.0

    march_us = frame["cells_visited"] * US_MARCH_CELL
    face_us = frame["n_faces"] * US_FACE
    gen_us = span_lines * US_SPAN_GEN
    new_us = march_us + face_us + gen_us

    hw_ms = 4.1 + 1.27 * model_us / 1000.0 + new_us / 1000.0
    hw_ms_pess = 4.1 + 1.27 * (model_us + new_us) / 1000.0
    # The 4.1 ms calibration constant is not free-floating: README measures
    # "loop only 0.44 ms" and "+ view + visibility 4.08 ms", i.e. 3.64 ms of
    # it IS the shipped engine's view/visibility build.  The free-angle grid
    # march REPLACES that work rather than adding to it, so for a
    # like-for-like number take the 3.64 ms out and let march_us stand in.
    hw_ms_net = 0.46 + 1.27 * model_us / 1000.0 + new_us / 1000.0

    # --- absolute floor: perfect occlusion, every viewport byte written
    # exactly once (no painter overdraw at all).  Unreachable in practice,
    # but it bounds what any amount of cleverness can buy.
    ideal_fill = geom.VP_H * geom.VP_BW
    ideal_us = (ideal_fill // 2) * US_PER_PUSH + span_lines * US_SPAN_LINE \
        + rect_lines * US_RECT_LINE
    ideal_ms = 4.1 + 1.27 * ideal_us / 1000.0 + new_us / 1000.0

    return dict(ideal_fill=ideal_fill, ideal_ms=ideal_ms,
                overdraw=fill / float(ideal_fill),
                fill=fill, rect_lines=rect_lines, span_lines=span_lines,
                model_us=model_us, march_us=march_us, face_us=face_us,
                gen_us=gen_us, new_us=new_us,
                hw_ms=hw_ms, hw_ms_pess=hw_ms_pess, hw_ms_net=hw_ms_net,
                opt_span=opt_span, opt_rect=opt_rect,
                opt_model_us=opt_model_us, opt_hw_ms=opt_total_ms,
                opt_net_ms=opt_net_ms,
                n_faces=frame["n_faces"],
                cells_visited=frame["cells_visited"])
