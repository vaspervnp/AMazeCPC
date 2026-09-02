"""engine2/tools/monmodel.py -- THE MONSTER'S PURSUIT RULE, exhaustively.

    python3 engine2/tools/monmodel.py

game.asm's mon_move steps the monster one cell at a time toward the
player.  A star search would be correct and costs 7.8 ms -- forty times
the whole frame budget -- so the disc runs a GREEDY rule instead: step
along the axis the player is further away on, and if that cell is solid
try the other axis.  Nine instructions and about 200 us.

GREEDY PURSUIT IS NOT COMPLETE AND THIS FILE IS HOW MUCH IT IS NOT.  The
rule has no memory, so a monster whose two candidate cells are both
solid simply stops, and one that oscillates between two cells never
arrives.  The question is not "does it always work" -- it does not --
but "on THIS map, from how many of the places the monster can be, does
it reach the player, and what does it do when it fails".

So this replays the disc's own rule over EVERY (monster cell, player
cell) pair on the map and classifies the outcome.  The state is one
byte, the rule is deterministic and the player is held still, so every
trajectory is eventually periodic: it either arrives, or it enters a
cycle it can never leave.  There is no third answer and no need for a
step limit chosen by taste.

THE MAP IS READ OUT OF gen_maze.inc, not out of tools/world.py.  The
generator is upstream of both, but MAZEDATA is what maze_unpack turns
into SOLID and SOLID is what mon_move reads, so the packed bytes are one
step closer to the thing being modelled.  Same reason pacemodel.py reads
its C_* out of main3.asm.

THREE RICHER RULES WERE MODELLED HERE AND ALL THREE WERE REJECTED, and
the numbers are worth keeping because "greedy is only 54% with the doors
open" invites exactly one of them as an obvious improvement.  Same space,
same denominator, doors open:

    A  as shipped: dominant axis, fall back to the other      53.99%
    C  ...and on both blocked, carry on in the LAST direction 57.24%
    D  ...and if that is blocked too, turn through the four   61.75%
    E  on both blocked, slide along the blocking wall         62.24%

With the doors SHUT all four read 100.00% -- the monster is sealed in one
room and greedy is complete inside a rectangle, so nothing distinguishes
them where the game actually happens.  The best buys eight points open,
costs a byte of state and a dozen instructions, and is still stuck more
than a third of the time.  The rule that would not be stuck aims at the
DOORWAY rather than at the player, which is a search, and a BFS over this
map is ~7.8 ms against a 194.6 ms frame that is already spent.

THE DENOMINATOR IS THE WHOLE ARGUMENT, and the first version of this file
got it wrong: it counted pairs a PLAYER could walk between (doors
passable) and reported the rule at 10.49% doors-shut, because the monster
cannot open a door and so could never reach most of them.  See
reachable().
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)

W = H = 16


def _equ(name, default, src="game.asm"):
    """Read an `equ` out of the source, the same way pacemodel.py does."""
    path = os.path.join(_E2, "src", src)
    for line in open(path):
        p = line.split()
        if len(p) >= 3 and p[0] == name and p[1] == "equ":
            try:
                return int(p[2])
            except ValueError:
                return default
    return default


def load_solid():
    """MAZEDATA out of gen_maze.inc -> the 256 bytes SOLID holds.

    Two bits a cell, low cell in the low bits -- maze_unpack's own
    packing, see march.asm.
    """
    path = os.path.join(_E2, "src", "gen_maze.inc")
    packed, seen = [], False
    mon = _equ("MONSTART", None, "gen_maze.inc")
    for line in open(path):
        s = line.split(";")[0].strip()
        if s.startswith("MAZEDATA"):
            seen = True
            continue
        if seen and s.startswith("db "):
            for b in s[3:].split(","):
                packed.append(int(b.strip().replace("#", "0x"), 0))
        elif seen and packed and not s.startswith("db "):
            seen = False
    assert len(packed) == 64, f"{len(packed)} packed bytes, expected 64"
    solid = []
    for b in packed:
        for sh in (0, 2, 4, 6):
            solid.append((b >> sh) & 3)
    assert len(solid) == 256
    return solid, mon


def step(solid, m, px, py):
    """ONE mon_move step.  -> the monster's new cell.

    This is game.asm's routine and nothing else: the offsets are cell -
    player and SIGNED, the axis with the larger magnitude is tried first,
    a candidate is taken only if SOLID reads 0, and a monster with both
    candidates blocked does not move.

    TIES GO TO X.  `adx >= ady` and not `>`, because the Z80 test is a
    CP and a JR NC, which is the >= branch for free.
    """
    mx, my = m & 15, m >> 4
    dx, dy = mx - px, my - py
    if abs(dx) + abs(dy) < 2:
        return m                        # arrived: it stands and does not
                                        # enter the player's own cell
    sx = -1 if dx > 0 else (1 if dx < 0 else 0)
    sy = -1 if dy > 0 else (1 if dy < 0 else 0)
    first, second = ((sx, 0), (0, sy)) if abs(dx) >= abs(dy) else \
                    ((0, sy), (sx, 0))
    for ox, oy in (first, second):
        if ox == 0 and oy == 0:
            continue
        c = (my + oy) * 16 + (mx + ox)
        if solid[c] == 0:
            return c
    return m                            # boxed in: it stays put


def chase(solid, m0, p, limit=512):
    """-> (steps to adjacency, or None if it never arrives).

    Deterministic rule + one byte of state = eventually periodic, so a
    repeat is a proof of never, not a timeout.
    """
    px, py = p & 15, p >> 4
    m, seen, n = m0, set(), 0
    while n < limit:
        if abs((m & 15) - px) + abs((m >> 4) - py) <= 1:
            return n
        if m in seen:
            return None                 # a cycle: it can never arrive
        seen.add(m)
        nxt = step(solid, m, px, py)
        if nxt == m:
            return None                 # stopped dead
        m, n = nxt, n + 1
    raise AssertionError("limit reached without a repeat -- impossible")


def reachable(solid, start):
    """The cells the MONSTER could ever stand on, starting from `start`.

    THE PASSABILITY HAS TO BE THE MONSTER'S OWN, and the first version of
    this used the PLAYER'S -- `solid[n] != 1`, i.e. doors passable.  That
    put every pair on opposite sides of a SHUT door into the denominator,
    which the monster cannot cross by construction, and reported the rule
    at 10.49% when the honest figure is 100.00%.  A model that judges a
    rule on states the rule cannot reach is measuring the map, not the
    rule.
    """
    seen, stack = {start}, [start]
    while stack:
        c = stack.pop()
        for o in (-1, 1, -16, 16):
            n = c + o
            if o in (-1, 1) and (n >> 4) != (c >> 4):
                continue
            if 0 <= n < 256 and n not in seen and solid[n] == 0:
                seen.add(n)
                stack.append(n)
    return seen


def main():
    solid, mon0 = load_solid()
    rate = _equ("MON_RATE", 8)
    frame_ms = 19.968 * _equ("PACE_FRAMES", 10, "main3.asm")

    for label, shut in (("DOORS SHUT -- the map as it loads", True),
                        ("DOORS OPEN -- every door walked through", False)):
        s = list(solid)
        if not shut:
            s = [0 if v == 2 else v for v in s]
        cells = sorted(c for c in range(256) if s[c] == 0)
        # A pair is only worth judging if the MONSTER'S OWN steps could
        # join them; the rule cannot be blamed for a room sealed behind a
        # shut door it is not allowed to open.
        comp = {}
        for c in cells:
            if c not in comp:
                for r in reachable(s, c):
                    comp[r] = c

        pairs = arrive = 0
        worst, worst_at, stuck = 0, None, []
        for p in cells:
            for m in cells:
                if comp[m] != comp[p] or m == p:
                    continue
                pairs += 1
                n = chase(s, m, p)
                if n is None:
                    stuck.append((m, p))
                else:
                    arrive += 1
                    if n > worst:
                        worst, worst_at = n, (m, p)

        print(f"\n{label}")
        print(f"  {len(cells)} open cells, {pairs} pairs a walk could join")
        print(f"  arrives: {arrive} = {100.0*arrive/pairs:5.2f}%"
              f"   never: {len(stuck)} = {100.0*len(stuck)/pairs:5.2f}%")
        if worst_at:
            m, p = worst_at
            print(f"  worst   {worst} steps: monster ({m&15},{m>>4}) "
                  f"player ({p&15},{p>>4})"
                  f"  = {worst*rate*frame_ms/1000.0:.1f} s at MON_RATE "
                  f"{rate}")
        if stuck:
            print("  never arrives, first eight:")
            for m, p in stuck[:8]:
                print(f"    monster ({m&15},{m>>4})  player ({p&15},{p>>4})")

        # ---- AND THE ONE PAIR THE DISC ACTUALLY STARTS ON.
        if mon0 is not None and s[mon0] == 0:
            st = _equ("START_X", 3, "gen_maze.inc"), \
                 _equ("START_Y", 12, "gen_maze.inc")
            p0 = st[1] * 16 + st[0]
            n = chase(s, mon0, p0)
            print(f"  the map's own pair: monster ({mon0&15},{mon0>>4}) "
                  f"player ({st[0]},{st[1]}) -> "
                  + (f"{n} steps" if n is not None else "NEVER ARRIVES"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
