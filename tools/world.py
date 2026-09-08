"""Palette, maze data and the visibility rules -- shared by the preview and
the table generator so the Python model and the Z80 cannot drift apart."""

import json
import os

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
# R_MAX IS 4 AND THIS NOTE SAID 6 FOR A LONG TIME.  It was 6; cutting it to
# 4 BUYS A WHOLE VSYNC PERIOD, measured, because the flood's area falls as
# the square of the radius -- see the note on R_MAX in marchmodel.py, which
# points back here, and RMAX equ 4 in gen_slopes.inc, which is what the Z80
# actually tests.  Everything past L1 R_MAX+1 is the FAR PLANE: a flat band
# at a fixed height drawn by rastcol.asm's rc_far, not a missing wall.
#
# So the arithmetic below is W + H <= R_MAX+1 = 5, and a 4x4 room is well
# past it -- deliberately.  Its far faces are the far plane, which is the
# whole reason RC_FARH exists.  What the room size still has to respect is
# what the FLOOD costs, and that is measured rather than argued:
#
# MEASURED, exhaustively, by engine2/tools/roomcost.py -- over all 8128512
# reachable states, on EVERY level and in EVERY door configuration, which
# is 81 million states.  An open door is transparent to the march, so the
# doors-shut sweep this note used to quote was a claim about the map as it
# LOADS and about no state a player reaches by opening one:
#
#                        doors shut   doors open
#     cells popped          max 16      max 25
#     faces filed           max 12      max 13
#     farthest bucket k     max  5      max  5   <- of 7 pages
#     flood stack depth     max  8      max 10   <- of 25 entries
#
# So march.asm's bucket pages and flood stack are untouched,
# with room to spare in both.  Re-run roomcost.py after ANY change to this
# map: the farthest-bucket line is the one that matters, because march.asm
# files a face by |dx|+|dy| and a key past the last page would write into
# whatever is above it.  It prints FITS or OVERRUNS against MSTKBOT and
# MSTKTOP read out of march.asm, so it is a verdict and not a reading.
#
# THE MAP ITSELF IS NOT IN THIS FILE.  It is tools/maps/level0.json, and
# so is every other level -- but the paragraph above is about the SHAPE of
# a room and not about one map, so it stays here where a person editing
# the engine will read it.  Re-run roomcost.py after any change, on EVERY
# level.

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

# ---- AMMUNITION, scattered one to a room ---------------------------
#  Cell coordinates, not a map character: SOLID's alphabet is the
#  KERNEL's -- 0 open, 1 wall, 2 shut door, 3 door in motion -- and the
#  march reads it four times a cell in its hot loop.  A fifth code would
#  buy a test in that loop for something the renderer does not draw and
#  the collision does not care about, so pickups live in their own short
#  list instead, the way the doors already do.
#
#  Six of the nine rooms, so a player who has emptied the magazine has
#  somewhere to walk to but not one underfoot.  load_maze() asserts every
#  one of them is FLOOR.
#  The cells are in the level record now -- see LEVELS below, which is
#  loaded from tools/maps/*.json.  AMMO_CELLS is what select_level() binds
#  it to, and every tool here reads that.

# ---- THE MONSTERS, one to a room, and NONE IN THE ROOM YOU START IN --
#  There was one, at (1, 12), two cells west of the start: a test target
#  for the shot's impact effect rather than a game character, and the
#  first thing that happened in a new game was being bitten by it.
#
#  The map is nine 4x4 rooms on a five-cell pitch, so a monster to a room
#  is what the layout asks for.  The player's own room is left empty --
#  you get to turn round and look at where you are before anything comes
#  for you -- and every cell here is checked below against the floor, the
#  pickups, the exit and the start.
#
#  HOW MANY IS A PACING QUESTION, NOT A DESIGN ONE.  pip.asm's mon_draw
#  is the most expensive thing in the frame at close range (6736.7 us
#  measured, one cell away) and C_PIPM has to bound all of them together.
#  See main3.asm.
#  ONE, AND THE NUMBER IS THE FRAME'S TO SET, NOT THE DESIGN'S.  Each
#  extra monster costs ~500 us in game_step -- mon_all runs mon_move for
#  every one -- and C_TAIL bounds the whole frame tail.  MEASURED with
#  emu_holes.py:
#
#      one    tail 3813.9    (C_TAIL 4000, the shipped margin)
#      two    tail ~4400
#      three  tail 4889.0    C_TAIL 4000 -- margin -889.0
#      four   tail 5091.9    C_TAIL 4000 -- margin -1091.9
#
#  and "EVERY CONSTANT A ONE-SIDED UPPER BOUND: False" is the one thing
#  this design cannot ship.  Covering three or four means raising C_TAIL
#  by 900-1100 us on EVERY frame, and pacemodel.py measures the frame's
#  whole spare capacity at about 2500 us before every state gains a
#  period -- which the minimap and the second monster's drawing have
#  already spent most of.
#  Per level, in the map file, and bound here by select_level().

# ---- THE WAY OUT ---------------------------------------------------
#  'X' in the grid above, a plain FLOOR cell in SOLID: the exit is a
#  CELL LIST of one, exactly like the monster and the pickups, and for
#  the same reason -- SOLID's alphabet is the march's four codes and
#  there is no fifth.
EXIT_CHAR = 'X'

FLOOR, WALL, DOOR = 0, 1, 2


# ---------------------------------------------------------------------
#  WHAT THE SHIPPED LEVELS LOOK LIKE, since they are no longer in front of
#  you.  Both are the same nine 4x4 rooms on the same five-cell pitch,
#  because the room SHAPE is what roomcost.py measured and what the pacing
#  rests on.  What differs is the doors and the route: level 0 starts
#  bottom left and leaves top right, level 1 starts top right and leaves
#  bottom left with the two door bands offset so the diagonal is not a
#  straight run.
#
#  WITH THE DOORS SHUT THEY ARE THE SAME MAP TO THE MARCH -- a shut door
#  is opaque exactly like a wall, and the doors sit in different places in
#  the SAME wall ring -- so their doors-shut sweeps agree to the last
#  decimal.  That is a property of these two maps and not a rule; see
#  pacescan.py, which says so before it sweeps.
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
#  THE LEVELS.  THEY ARE FILES, and the module-level load at the foot of
#  this section is the only place they come from.
#
#  There is no literal to fall back on any more, deliberately.  A
#  fallback is a second copy of the map, and a second copy is a thing
#  that can be edited: the editor would write tools/maps/level1.json, the
#  build would go on shipping the literal, and the two would part company
#  with nothing to say so.  So a missing or malformed map file stops the
#  build, loudly, which is what it should do.
#
#  engine2/tools/genaux.py emits one fixed-size record each into RAM bank
#  6; game.asm's level_load pulls one down.  A LEVEL IS NOT JUST A GRID:
#  where you start, where the pickups are, where the monsters stand and
#  where the way out is are all part of it, and each is checked against
#  the grid by load_maze / ammo_cells / monster_cells / exit_cell below.
# ---------------------------------------------------------------------
LEVELS = []                 # filled at the foot of this section
AMMO_CELLS = []             # ...and these are LEVELS[n]'s, bound by
MONSTER_CELLS = []          # select_level()
MONSTER_CELL = None
_ACTIVE = None


# ---------------------------------------------------------------------
#  THE MAP FILE, which is what the editor writes.
#
#  ONE JSON FILE IS ONE ENTRY OF LEVELS ABOVE and nothing more: the same
#  grid (with its '@' and its 'X' in it, exactly as the literals carry
#  them), the same pickup list, the same monster list.  It deliberately
#  does NOT repeat the start and the exit as separate fields -- they are
#  already IN the grid, and a file that said both would be a file that
#  could disagree with itself.  Every assertion in this module still runs
#  on a loaded level, because a loaded level IS a LEVELS entry.
#
#  The generators stay the only writers of the .inc.  See plan.md.
# ---------------------------------------------------------------------
MAPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maps")


def level_to_dict(n, name=None):
    """-> the JSON-shaped dict for LEVELS[n]."""
    lv = LEVELS[n]
    return {
        "name": name or f"level {n}",
        "size": [len(lv["src"][0]), len(lv["src"])],
        "grid": list(lv["src"]),
        "ammo": [list(c) for c in lv["ammo"]],
        "monsters": [list(c) for c in lv["monsters"]],
    }


def level_from_dict(d):
    """-> a LEVELS entry.  Raises ValueError on anything malformed.

    SHAPE ONLY.  Whether the map is PLAYABLE -- connected, one start, the
    pickups on floor -- is decided by load_maze/ammo_cells/monster_cells
    the moment the level is selected, and those are the assertions the
    engine actually depends on.  Duplicating them here would be a second
    opinion about what a legal map is, which is the one thing this file
    exists to prevent.
    """
    try:
        grid = list(d["grid"])
        ammo = [tuple(c) for c in d["ammo"]]
        mon = [tuple(c) for c in d["monsters"]]
    except (KeyError, TypeError) as e:
        raise ValueError(f"map file is missing or malformed: {e}") from e
    if not all(isinstance(r, str) for r in grid):
        raise ValueError("grid must be a list of strings")
    w = d.get("size", [len(grid[0]) if grid else 0, len(grid)])
    if [len(grid[0]) if grid else 0, len(grid)] != list(w):
        raise ValueError(f"size {list(w)} does not match the grid "
                         f"({len(grid[0]) if grid else 0}x{len(grid)})")
    for c in ammo + mon:
        if len(c) != 2 or not all(isinstance(v, int) for v in c):
            raise ValueError(f"{c!r} is not an (x, y) pair of ints")
    return dict(src=grid, ammo=ammo, monsters=mon)


def load_levels(path=None):
    """Fill LEVELS from tools/maps/*.json, sorted by filename.

    THE FILENAME ORDER IS THE LEVEL ORDER.  level0.json, level1.json --
    that is the order the exit walks the player through, and nothing else
    records it.

    Called at import.  There is no fallback and no `try`: a map file that
    is missing or malformed stops every tool in the repository with the
    reason attached, which is the correct outcome for a build whose input
    has gone.  See the note above LEVELS.
    """
    global LEVELS
    d = path or MAPS_DIR
    if not os.path.isdir(d):
        raise ValueError(
            f"{d} is not there, and it is where the maps live.  "
            "`git checkout tools/maps` or draw one with editor/.")
    files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    if not files:
        raise ValueError(f"no map files in {d} -- the game has no levels")
    out = []
    for f in files:
        with open(os.path.join(d, f)) as fh:
            try:
                out.append(level_from_dict(json.load(fh)))
            except ValueError as e:
                raise ValueError(f"{f}: {e}") from e
    LEVELS = out
    select_level(0)
    return files


def select_maze(mode):
    """Point the loader at the layout for the target screen mode.

    Mode 0 is the game and its levels; mode 2 is the mono prototype disc,
    which has no levels, no pickups and no way out -- see MAZE_SRC_M2.
    """
    global _ACTIVE
    if mode == 0:
        select_level(0)
    else:
        _ACTIVE = MAZE_SRC_M2


def export_levels(path=None):
    """Write LEVELS back out as map files.  -> the paths written.

    A NORMALISER, now that the files ARE the source: it rewrites them in
    this module's own formatting.  Two things want that.  `make editor`
    runs it before the C# tests, so those tests compare the editor's
    writer against a freshly canonical file rather than against whatever
    was last committed; and round-tripping a file through here and back
    is the cheapest proof that level_from_dict and level_to_dict agree.

    It is also how a level gets written to somewhere else -- pass a path
    and it will not touch tools/maps.
    """
    d = path or MAPS_DIR
    os.makedirs(d, exist_ok=True)
    out = []
    for n in range(len(LEVELS)):
        p = os.path.join(d, f"level{n}.json")
        with open(p, "w") as f:
            json.dump(level_to_dict(n), f, indent=2)
            f.write("\n")
        out.append(p)
    return out


def select_level(n):
    """Point the loader at LEVELS[n].  -> the level's dict.

    The per-level lists (AMMO_CELLS, MONSTER_CELLS) are module globals
    that four tools already read, so selecting a level rebinds them
    rather than threading a level index through every caller.
    """
    global _ACTIVE, AMMO_CELLS, MONSTER_CELLS, MONSTER_CELL
    lv = LEVELS[n]
    _ACTIVE = lv["src"]
    AMMO_CELLS = list(lv["ammo"])
    MONSTER_CELLS = list(lv["monsters"])
    MONSTER_CELL = MONSTER_CELLS[0] if MONSTER_CELLS else None
    return lv


# ---------------------------------------------------------------------
#  ...AND HERE IS WHERE THE MAPS ARRIVE.  Every tool in this repository
#  imports this module, so this one line is what makes tools/maps the
#  source of the game's levels rather than a copy of them.
#
#  MAZE_W AND MAZE_H COME OFF LEVEL 0, and they are not free numbers: the
#  march indexes SOLID as cy*16 + cx and SOLID is 256 bytes, so 16x16 is
#  the engine's shape and not the map's choice.  A file of another size
#  gets past this and is caught by the generators; the editor refuses to
#  save one at all.
# ---------------------------------------------------------------------
load_levels()

MAZE_W = len(LEVELS[0]["src"][0])
MAZE_H = len(LEVELS[0]["src"])


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


def monster_cells(grid, sx, sy):
    """-> [(x, y)] for the monsters, or [] for this layout.

    THE ROOM THE PLAYER IS IN MUST BE EMPTY, and that is checked here
    rather than eyeballed: rooms are 4x4 on a five-cell pitch, so the
    room of a cell is (x // 5, y // 5).
    """
    if _ACTIVE is MAZE_SRC_M2:
        return []
    home = (sx // 5, sy // 5)
    for (x, y) in MONSTER_CELLS:
        assert grid[y][x] == FLOOR, f"monster {(x, y)} is not floor"
        assert (x, y) != (sx, sy), "monster on the player's start cell"
        assert (x, y) not in AMMO_CELLS, "monster standing on a pickup"
        assert (x // 5, y // 5) != home, \
            f"monster {(x, y)} is in the player's own room"
    assert len(set(MONSTER_CELLS)) == len(MONSTER_CELLS), "two in one cell"
    assert len(set((x // 5, y // 5) for x, y in MONSTER_CELLS)) \
        == len(MONSTER_CELLS), "two monsters in one room"
    return list(MONSTER_CELLS)


def monster_cell(grid, sx, sy):
    """-> the FIRST monster's cell, for callers that want just one."""
    c = monster_cells(grid, sx, sy)
    return c[0] if c else None


def exit_cell(grid, sx, sy):
    """-> (x, y) for the way out, or None for a layout without one."""
    found = [(x, y) for y, row in enumerate(_ACTIVE)
             for x, ch in enumerate(row) if ch == EXIT_CHAR]
    if _ACTIVE is MAZE_SRC_M2:
        return None
    assert len(found) == 1, f"maze needs exactly one {EXIT_CHAR!r}: {found}"
    x, y = found[0]
    assert grid[y][x] == FLOOR, f"exit {(x, y)} is not floor"
    assert (x, y) != (sx, sy), "exit on the player's start cell"
    assert (x, y) not in AMMO_CELLS, "exit on a pickup"
    assert (x, y) != MONSTER_CELL, "exit under the monster"
    return x, y


def ammo_cells(grid, sx, sy):
    """-> [(x, y)] pickups for this layout, validated against the grid.

    Only the mode 0 maze is furnished; the mode 2 disc has no shooting.
    """
    if _ACTIVE is MAZE_SRC_M2:
        return []
    for x, y in AMMO_CELLS:
        assert 0 <= x < MAZE_W and 0 <= y < MAZE_H, f"ammo {(x, y)} off map"
        assert grid[y][x] == FLOOR, f"ammo {(x, y)} is not floor"
        assert (x, y) != (sx, sy), "ammo on the player's start cell"
    assert len(set(AMMO_CELLS)) == len(AMMO_CELLS), "duplicate ammo cell"
    return list(AMMO_CELLS)


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
