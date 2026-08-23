"""THE DOOR SOFT-LOCK, on the BOOTED build/amaze.dsk.

    python3 engine2/tools/emu_door_disc.py

engine2/tools/emu_door.py drives game.asm inside the unit harness; this
one drives the SHIPPED disc through the real BASIC loader, real renderer
and real key matrix, so the six reported reproduction cases are exercised
against the binary that actually runs.

Per case: open the door, walk into the doorway until the player's PRAD box
straddles the threshold, press SPACE, then hold UP and DOWN and see whether
the player is stuck.  Everything is read out of the running machine.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import cpc as cpcmod                                         # noqa: E402
import emu_verify3 as V                                      # noqa: E402

PRAD = 64
SOLID = V.SOLID
DOORS = ((5, 3), (11, 5), (4, 9))       # engine2/src/gen_maze.inc


def solid(g, cx, cy):
    return g.c.peek(SOLID + cy * 16 + cx)


def straddling(x, dcx):
    """Is the player's collision box overlapping column dcx while its
    centre is NOT in that column?"""
    return (x >> 8) & 15 != dcx and dcx in (((x - PRAD) >> 8) & 15,
                                            ((x + PRAD) >> 8) & 15)


def case(g, dcx, dcy, side):
    scx = dcx - 1 if side == "W" else dcx + 1
    a = 0 if side == "W" else 36
    # --- open the door from the neighbour cell
    g.place(scx * 256 + 128, dcy * 256 + 128, a)
    if solid(g, dcx, dcy) != 0:
        g.hold(cpcmod.KEY_SPACE, 20)
        g.c.run_frames(60)
    if solid(g, dcx, dcy) != 0:
        return f"  {dcx},{dcy} {side}: FAIL could not open the door"

    # --- edge into the doorway one game frame at a time until straddling
    g.place(scx * 256 + 128, dcy * 256 + 128, a)
    hit = None
    for _ in range(16):
        g.hold(cpcmod.KEY_UP, 8)
        x, _y, _ = g.player()
        if straddling(x, dcx):
            hit = x
            break
    if hit is None:
        return f"  {dcx},{dcy} {side}: no straddling frame (not reproduced)"

    # --- SPACE while straddling
    g.hold(cpcmod.KEY_SPACE, 20)
    g.c.run_frames(60)
    sol = solid(g, dcx, dcy)
    x0, y0, _ = g.player()

    # --- can the player still move?
    g.hold(cpcmod.KEY_UP, 60)
    x1, y1, _ = g.player()
    g.place(x0, y0, a)
    g.hold(cpcmod.KEY_DOWN, 60)
    x2, y2, _ = g.player()
    moved = ((x1, y1) != (x0, y0)) + ((x2, y2) != (x0, y0))

    ok = sol == 0 and moved == 2
    return (f"  {dcx},{dcy} {side}: straddle x={hit:04X} "
            f"(box cols {((hit - PRAD) >> 8) & 15}..{((hit + PRAD) >> 8) & 15},"
            f" centre col {(hit >> 8) & 15})  SOLID after SPACE = {sol}  "
            f"fwd/back moved {moved}/2  -> " + ("OK" if ok else "WEDGED"))


def clear_case(g, dcx, dcy):
    """And a door must still shut when the player has stepped clear."""
    g.place((dcx - 1) * 256 + 128, dcy * 256 + 128, 0)
    if solid(g, dcx, dcy) != 0:
        g.hold(cpcmod.KEY_SPACE, 20)
        g.c.run_frames(60)
    opened = solid(g, dcx, dcy) == 0
    g.hold(cpcmod.KEY_SPACE, 20)
    g.c.run_frames(60)
    shut = solid(g, dcx, dcy) == 2
    return (f"  {dcx},{dcy} from the cell centre next door: opened={opened} "
            f"shut again={shut}  -> " + ("OK" if opened and shut else "FAIL"))


def main():
    g = V.Game()
    print("straddling the threshold, SPACE must be refused:")
    bad = 0
    for (dcx, dcy) in DOORS:
        for side in ("W", "E"):
            line = case(g, dcx, dcy, side)
            print(line)
            if "WEDGED" in line or "FAIL" in line:
                bad += 1
    print("stepped clear, SPACE must still shut:")
    for (dcx, dcy) in DOORS:
        line = clear_case(g, dcx, dcy)
        print(line)
        if "FAIL" in line:
            bad += 1
    print()
    print("ALL PASS" if not bad else f"{bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
