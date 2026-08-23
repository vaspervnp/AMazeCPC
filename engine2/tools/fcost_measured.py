"""Frame budget for the free-angle renderer -- MEASURED GEOMETRY COSTS.

COPY of prototype/free-angle/fcost.py.  The only edits are in layer (B):
the hand-counted estimates have been replaced by a least-squares fit to the
Z80 geometry kernel running on a cycle-accurate CPC 6128.

    engine2/src/kernel.asm : frame_geom = march + proj_setup + proj_face
    measured by engine2/tools/emu_kernel.py over 127 player states
    refit onto free.py's own counters by engine2/tools/refit_free.py

    (2026-08 REMEASURE, after the incremental view-space march and the
     table-driven projector landed; engine2/tools/emu_kernel.py time +
     refit_free.py, 127 states, calibration 100 NOPs = 100.08 us)

        geometry_us = 3371 + 472.4*cells_visited + 1051.9*n_faces
        R^2 = 0.9877, RMS residual 833 us, mean 14043 us, max 34247 us

    (superseded)  7672 + 543.5*cells_visited + 1233.5*n_faces

Two things changed shape, not just value:
  * there is now a per-frame CONSTANT, US_GEOM_FIXED.  march_setup builds six
    16-entry frustum tables (3.1 ms) and proj_setup builds four 17-entry
    lattice tables (1.9 ms) whatever the frame contains; the old estimate had
    no constant term at all.
  * the numbers are 7x the estimate at the mean state (20.1 ms measured vs
    2.9 ms estimated).

Layer (A), the x1.27-calibrated fill/span/rect model, is untouched.

Frame budget for the free-angle renderer.

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
#
# MEASURED: 543.5 us, 9.1x the estimate.  The march is a flood fill whose
# per-cell work is three 16-bit table-sum sign tests plus four neighbour
# pushes, but it is dominated by the fixed setup, which the fit puts in
# US_GEOM_FIXED below.
US_MARCH_CELL = 472.4

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
# MEASURED: 1233.5 us per DRAWN face, 2.5x the 500 us estimate.  The kernel
# pays for every CANDIDATE the march files (1.6 candidates per drawn face at
# 48x128) and only discovers on the way out that some are off screen, so a
# drawn face carries its share of the rejected ones.  Per candidate the
# measured cost is 700 us; per candidate that survives to a quad, 1234 us.
US_FACE = 1051.9

# MEASURED per-frame constant: march_setup 3.1 ms + proj_setup 1.9 ms +
# flood seed + bucket reset + the per-face dispatch in project_all.
US_GEOM_FIXED = 3371.0

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
    _opt_new = (US_GEOM_FIXED + frame["cells_visited"] * US_MARCH_CELL
                + frame["n_faces"] * US_FACE + opt_span * US_SPAN_GEN)
    opt_total_ms = 4.1 + 1.27 * opt_model_us / 1000.0 + _opt_new / 1000.0
    opt_net_ms = 0.46 + 1.27 * opt_model_us / 1000.0 + _opt_new / 1000.0

    march_us = US_GEOM_FIXED + frame["cells_visited"] * US_MARCH_CELL
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
