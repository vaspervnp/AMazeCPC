"""Palette, maze data and the visibility rules -- shared by the preview and
the table generator so the Python model and the Z80 cannot drift apart."""

import cpchw as cpc

# ------------------------------------------------------------- palette ----
# Pen -> firmware ink.  Mode 0 gives us all 16, and we spend them on depth
# ramps: shading by distance is what sells the 3D on a 160x200 chunky screen.

# Walls run a cool ramp and the floor a warm one, so a wall never merges into
# the floor it stands on even when both land on the same luminance step.
PEN_INK = [
    0,      # 0  black          -- void beyond the frustum
    26,     # 1  bright white   -- wall, depth 1  (brightest)
    14,     # 2  pastel blue    -- wall, depth 2
    13,     # 3  white/grey     -- wall, depth 3
    2,      # 4  bright blue    -- wall, depth 4
    1,      # 5  blue           -- wall, depth 5
    24,     # 6  bright yellow  -- door, depth 1
    15,     # 7  orange         -- door, depth 2
    6,      # 8  bright red     -- door, depth 3
    3,      # 9  red            -- door, depth 4
    25,     # 10 pastel yellow  -- floor, near
    12,     # 11 yellow (olive) -- floor, far
    1,      # 12 blue           -- ceiling, near
    0,      # 13 black          -- ceiling, far
    20,     # 14 bright cyan    -- HUD frame
    26,     # 15 bright white   -- HUD text
]

WALL_RAMP = [1, 2, 3, 4, 5, 5]      # indexed by depth-1
DOOR_RAMP = [6, 7, 8, 9, 9, 9]
FLOOR_NEAR, FLOOR_FAR = 10, 11
CEIL_NEAR, CEIL_FAR = 12, 13
HUD_FRAME, HUD_TEXT = 14, 15


def wall_pen(f, side, door=False):
    """Depth-shaded pen for a face.  Sides sit one step darker than fronts,
    which reads as directional lighting for free."""
    ramp = DOOR_RAMP if door else WALL_RAMP
    d = max(0, min(len(ramp) - 1, (f - 1) + (1 if side else 0)))
    return ramp[d]


# ---------------------------------------------------------------- maze ----
# '#' wall, '.' floor, '+' door, '@' player start (facing north)

# ROOMS, NOT CORRIDORS -- AND THE SIZE IS SET BY THE MARCH, NOT BY TASTE.
# The march floods outward to R_MAX in L1 cells (marchmodel.py) and files
# faces at L1 1..R_MAX+1, so a wall further than that is never marched and
# never drawn: the room reads as an open field with a sliver of wall on the
# horizon.  A first attempt at four 6x7 halls put EVERY one of its 173
# standable cells past the limit, and the screenshots showed exactly that.
#
# These rooms are 4x4 in a clean 3x3 grid -- 16 floor cells against the 12
# of the 3x4 rooms they replace, and square rather than oblong, which is
# what makes them read as rooms instead of wide corridors.
#
# AND THEY COST THE ENGINE NOTHING.  The obvious rule is that a room W wide
# and H tall puts its far WALL corner at L1 W+H, so W+H <= R_MAX+1 = 7 and
# 4x4 is one too far.  THAT RULE IS TOO STRICT, and the thing it gets wrong
# is worth keeping: the only cell at L1 8 in a 4x4 room is the wall CORNER
# diagonally opposite, and both of its room-side neighbours are also wall,
# so it has no face pointing into the room at all.  What has to be inside
# the march is every VISIBLE face, and those top out at L1 7.
#
# MEASURED, exhaustively, by engine2/tools/roomcost.py over all 8128512
# reachable states of this map -- and measured at R_MAX 6 AND 7, which give
# byte-identical histograms, so the extra radius files nothing and is not
# taken:
#
#     cells popped        max 16   (was ~15 on the 3x4 map)
#     faces filed         max 16
#     farthest bucket k   max  7   <- so seven buckets still, no memory move
#     flood stack depth   max  8   <- against 128 entries; 16x over-provisioned
#
# So R_MAX stays 6, march.asm's bucket pages and flood stack are untouched,
# and the worst march is 16 cells = 11840 us at C_CELL.  Re-run roomcost.py
# after ANY change to this map: the farthest-bucket line is the one that
# matters, because march.asm files a face by |dx|+|dy| with no upper bound
# and a key of 8 would write into the page above the last bucket.
MAZE_SRC = [
    "################",
    "#....#....#....#",
    "#....#....#....#",
    "#....+....+....#",
    "#....#....#....#",
    "##+####+####+###",
    "#....#....#....#",
    "#....#....#....#",
    "#....+....+....#",
    "#....#....#....#",
    "##+####+####+###",
    "#....#....#....#",
    "#..@.#....#....#",
    "#....+....+....#",
    "#....#....#....#",
    "################",
]

# The Mode 2 disc gets its own layout.  It is built around short sight lines
# and small chambers rather than long corridors: dither density reads as depth
# only when there are several distances on screen at once, and a deep corridor
# in mono mostly shows one shade.
MAZE_SRC_M2 = [
    "################",
    "#....#...#.....#",
    "#.##.#.#.#.###.#",
    "#.#..+.#.+...#.#",
    "#.#.##.#.###.#.#",
    "#...#..#...#.#.#",
    "#.###.###.##.#.#",
    "#.#.....#..#...#",
    "#.#.###.#.##.###",
    "#...#.#.#..#...#",
    "#.###.#.##.###.#",
    "#.....#..+.....#",
    "#.#######.####.#",
    "#.....@........#",
    "#.############.#",
    "################",
]

FLOOR, WALL, DOOR = 0, 1, 2

MAZE_W = len(MAZE_SRC[0])
MAZE_H = len(MAZE_SRC)

_ACTIVE = MAZE_SRC


def select_maze(mode):
    """Point the loader at the layout for the target screen mode."""
    global _ACTIVE
    _ACTIVE = MAZE_SRC if mode == 0 else MAZE_SRC_M2


def _check_connected(grid, sx, sy):
    """Every floor cell must be reachable, treating doors as passable.

    A layout with a walled-off pocket would look fine in the preview and only
    show up as an unreachable part of the map, so assert it at build time.
    """
    seen = {(sx, sy)}
    stack = [(sx, sy)]
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not (0 <= nx < MAZE_W and 0 <= ny < MAZE_H):
                continue
            if (nx, ny) in seen or grid[ny][nx] == WALL:
                continue
            seen.add((nx, ny))
            stack.append((nx, ny))
    walkable = {(x, y) for y in range(MAZE_H) for x in range(MAZE_W)
                if grid[y][x] != WALL}
    missing = walkable - seen
    assert not missing, f"maze has unreachable cells: {sorted(missing)}"


def load_maze():
    """-> (grid, start_x, start_y).  grid[y][x] is FLOOR / WALL / DOOR."""
    grid = []
    sx = sy = -1
    for y, row in enumerate(_ACTIVE):
        assert len(row) == MAZE_W, f"maze row {y} is ragged"
        cells = []
        for x, ch in enumerate(row):
            if ch == '#':
                cells.append(WALL)
            elif ch == '+':
                cells.append(DOOR)
            else:
                cells.append(FLOOR)
                if ch == '@':
                    sx, sy = x, y
        grid.append(cells)
    assert sx >= 0, "maze has no '@' start position"
    _check_connected(grid, sx, sy)
    return grid, sx, sy


# ------------------------------------------------------------- facing ----
# 0 N(-y)  1 E(+x)  2 S(+y)  3 W(-x).  +l is always to the player's right.

def view_to_maze(px, py, facing, l, f):
    if facing == 0:
        return px + l, py - f
    if facing == 1:
        return px + f, py + l
    if facing == 2:
        return px - l, py + f
    return px - f, py - l


def cell_at(grid, x, y):
    if 0 <= x < MAZE_W and 0 <= y < MAZE_H:
        return grid[y][x]
    return WALL


# --------------------------------------------------------- visibility ----

def visible_cells(grid, px, py, facing, doors, l_max, f_max):
    """View-space (l, f) cells the player can actually see into.

    A flood through open cells from the player's own cell, restricted to the
    frustum.  Doors are only opaque when fully shut, so an opening door
    progressively reveals what lies beyond it.
    """
    def is_open(l, f):
        mx, my = view_to_maze(px, py, facing, l, f)
        c = cell_at(grid, mx, my)
        if c == WALL:
            return False
        if c == DOOR:
            return doors.get((mx, my), 0) > 0
        return True

    seen = set()
    stack = [(0, 0)]
    while stack:
        l, f = stack.pop()
        if (l, f) in seen:
            continue
        if abs(l) > l_max or not (0 <= f <= f_max):
            continue
        if (l, f) != (0, 0) and not is_open(l, f):
            continue
        seen.add((l, f))
        stack += [(l + 1, f), (l - 1, f), (l, f + 1), (l, f - 1)]
    return seen


# --------------------------------------------------- mode 2 dithering ----
# Mode 2 is 640x200 with two colours, so depth has to come from dither
# density instead of hue.  Each byte is 8 pixels and the renderer rotates it
# one pixel per scanline, which turns every level into a diagonal screen and
# costs a single RRC pair per line.

DITHER = [0x00, 0x80, 0x88, 0xA8, 0xAA, 0xEA, 0xEE, 0xFE, 0xFF]   # 0..8 of 8

# Walls stay the brightest things on screen, the floor sits mid, the ceiling
# goes dark -- so the three surfaces separate by density even where the depth
# ramps overlap.
# Density bands are kept apart so the three surface types never share a tone:
# walls live at 62.5% and up, the floor at 25-50%, the ceiling at 12.5% and
# below.  Within a band, depth still darkens.  Doors instead use a coarse
# 2-on-2-off stripe, so they read as a different *texture* rather than a
# different brightness -- the only cue that survives at any distance in mono.
M2_WALL_LEVEL = [8, 7, 6, 5, 5, 4]      # indexed by depth-1; sides add one
M2_DOOR_PAT = [0xCC, 0xCC, 0xCC, 0x88, 0x88, 0x88]
M2_CEIL_NEAR, M2_CEIL_FAR = 1, 0
M2_FLOOR_NEAR, M2_FLOOR_FAR = 4, 2


def rot8(pat, n):
    """Rotate an 8-bit dither pattern right, matching the Z80's RRC."""
    n &= 7
    return ((pat >> n) | (pat << (8 - n))) & 0xFF


def wall_pattern(f, side, door=False):
    d = max(0, min(len(M2_WALL_LEVEL) - 1, (f - 1) + (1 if side else 0)))
    if door:
        return M2_DOOR_PAT[d]
    return DITHER[M2_WALL_LEVEL[d]]
