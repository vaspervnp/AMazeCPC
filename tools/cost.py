"""Frame budget model.

Counts what the Z80 renderer will actually do for every reachable player state
in the maze, so viewport size and frustum extent can be tuned against a real
number instead of a guess.  Costs are CPC microseconds.

  PUSH DE          4 us for 2 bytes -- the fill itself
  span-line       28 us of setup per scanline of a trapezoid
  rect-line       19 us of setup per scanline of a rectangle
"""

import sys

import geom
import world
import preview
from geom import Rect

US_PER_PUSH = 4
US_SPAN_LINE = 28
US_RECT_LINE = 19

FRAME_US = 20000            # one 50 Hz frame


def frame_cost(grid, x, y, facing, sub, doors):
    """-> (microseconds, fill_bytes, span_lines, rect_lines)"""
    faces, occ = preview.build_facelist(grid, x, y, facing, sub, doors)

    # The occluder is ignored unless preview.USE_OCCLUDER is set, because the
    # shipped engine does not call find_occluder -- see the note in
    # src/main.asm render_frame.  Subtracting it while modelling the shipped
    # build under-predicts badly -- 9.5 ms against a measured 22.4 ms at the
    # start cell; charging the full background instead tracks hardware to
    # ~1.18x there (18.9 ms modelled).
    bg_lines = geom.VP_H
    if preview.USE_OCCLUDER and occ:
        lo = max(occ[0], geom.VP_Y)
        hi = min(occ[1], geom.VP_Y + geom.VP_H)
        if hi > lo:
            bg_lines -= (hi - lo)
    fill = bg_lines * geom.VP_BW
    rect_lines = bg_lines
    span_lines = 0

    for kind, g, pen, hclip in faces:
        if isinstance(g, Rect):
            h = g.h if hclip is None else hclip
            rect_lines += h
            fill += h * g.npush * 2
        else:
            span_lines += len(g.lines)
            fill += g.fill_bytes

    us = (fill // 2) * US_PER_PUSH + span_lines * US_SPAN_LINE \
        + rect_lines * US_RECT_LINE
    return us, fill, span_lines, rect_lines


def survey(doors=None):
    grid, sx, sy = world.load_maze()
    doors = doors or {}
    tot = 0
    n = 0
    worst = (0, None)
    over = 0
    for y in range(world.MAZE_H):
        for x in range(world.MAZE_W):
            if grid[y][x] != world.FLOOR:
                continue
            for facing in range(4):
                for sub in range(geom.SUBSTEPS):
                    us = frame_cost(grid, x, y, facing, sub, doors)[0]
                    tot += us
                    n += 1
                    if us > 2 * FRAME_US:
                        over += 1
                    if us > worst[0]:
                        worst = (us, (x, y, facing, sub))
    return tot / n, worst, n, over


def main():
    if "--occluder" in sys.argv[1:]:
        preview.USE_OCCLUDER = True
    print(f"viewport {geom.VP_BW}x{geom.VP_H} bytes"
          f" ({geom.VP_BW * 2}x{geom.VP_H} px),"
          f" frustum f<={geom.F_MAX} l<=+-{geom.L_MAX}")
    print("  modelling " + ("USE_OCCLUDER build (not shipped)"
                            if preview.USE_OCCLUDER else "shipped build"))
    avg, worst, n, over = survey()
    us, fill, sl, rl = frame_cost(*(world.load_maze()[0],) + worst[1][:2]
                                  + worst[1][2:], {})
    print(f"  average frame {avg / 1000:6.1f} ms"
          f"   ({avg / FRAME_US:.2f} frames @50Hz)")
    print(f"  worst   frame {worst[0] / 1000:6.1f} ms"
          f"   ({worst[0] / FRAME_US:.2f} frames)  at {worst[1]}")
    print(f"          fill {fill} B, {sl} span-lines, {rl} rect-lines")
    print(f"  states over 2 frames (40ms): {over}/{n}"
          f"  ({100 * over / n:.1f}%)")


if __name__ == "__main__":
    sys.exit(main())
