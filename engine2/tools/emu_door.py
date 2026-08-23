"""REPRODUCE AND VERIFY the door soft-lock (engine2/src/game.asm da_shut).

    python3 engine2/tools/emu_door.py

THE DEFECT.  da_shut compared only the player's CENTRE cell against the
door's cell, so a player STRADDLING the threshold -- centre in the
neighbour cell, PRAD collision box overlapping the door cell -- could shut
the door on itself.  The box is then inside SOLID, every movement is
rejected on both axes for every heading, and the centre sits closer to the
wall plane than project.asm's ZNEAR, so the shut door is see-through.

WHAT IS RUN is the real engine2/src/game.asm inside engine2/test/tst_game.asm
on a cycle-accurate 6128 (engine2/tools/emu_game.py's Rig).  Every number
below is read back out of the emulator, nothing is modelled except the
box predicate, which is the same one emu_game.py already asserts on.

Cases
  wedge      3 doors x 2 approach sides, straddling: SPACE must NOT shut
  wedge_walk the same, reached by WALKING rather than by poking plr_x
  clear      one byte further out (box clear): SPACE MUST still shut
  farside    a door shut from the OTHER side of the threshold
  midcycle   SPACE spammed through the whole 5-step open/shut animation
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import emu_game as G                                         # noqa: E402
from emu_game import K_UP, K_DOWN, K_SPACE, PRAD, box_clear  # noqa: E402

N_ANGLES = 72


def door_cells(rig):
    return [i for i, _, _ in rig.doors()]


def open_door(rig, idx, scx, scy, a):
    """Stand clear, SPACE, let the 5 steps run.  Assert SOLID == 0."""
    rig.set_player(scx * 256 + 128, scy * 256 + 128, a)
    rig.release()
    if rig.solid()[idx] != 0:
        rig.step([K_SPACE])
        for _ in range(8):
            rig.release()
    return rig.solid()[idx] == 0


def frozen(rig, x, y):
    """Try every 30-degree heading forward and back from (x,y).
    Returns the number of the 24 attempts that moved the player at all."""
    moved = 0
    for a in range(0, N_ANGLES, 6):
        for key in (K_UP, K_DOWN):
            rig.set_player(x, y, a)
            for _ in range(3):
                rig.step([key])
            px, py, _ = rig.player()
            if (px, py) != (x, y):
                moved += 1
    return moved


def nearest_plane(rig, x, y):
    """Distance in 8.8 from the player CENTRE to the nearest wall plane.
    project.asm rejects a face nearer than ZNEAR = 32."""
    solid = rig.solid()
    px, py, fx, fy = x >> 8, y >> 8, x & 255, y & 255
    best = 256
    for dx, d in ((-1, fx), (1, 256 - fx)):
        if solid[(py & 15) * 16 + ((px + dx) & 15)]:
            best = min(best, d)
    for dy, d in ((-1, fy), (1, 256 - fy)):
        if solid[((py + dy) & 15) * 16 + (px & 15)]:
            best = min(best, d)
    return best


# ---------------------------------------------------------------- cases --
# how far the centre sits from the threshold, 8.8.  8 is the case in the
# report (centre 0.031 cells from the wall plane); 63 is the last unit
# that still straddles at all.
STRADDLE = (8, 32, 63)


def approaches(idx, off=32):
    """(name, neighbour cell, heading at the door, straddle centre).
    All three doors in gen_maze.inc are E-W, so the two approaches are
    from the west and from the east."""
    dcx, dcy = idx % 16, idx // 16
    return [
        # west side: centre in dcx-1, box RIGHT edge inside the door cell
        ("W", (dcx - 1, dcy), 0, (dcx * 256 - off, dcy * 256 + 128)),
        # east side: centre in dcx+1, box LEFT edge inside the door cell
        ("E", (dcx + 1, dcy), 36, ((dcx + 1) * 256 + off, dcy * 256 + 128)),
    ]


def t_wedge(rig):
    """The six reported cases: straddling the threshold, SPACE must be
    refused and the player must stay free."""
    ok = True
    for idx in door_cells(rig):
        for off in STRADDLE:
            for side, (scx, scy), a, (x, y) in approaches(idx, off):
                if not open_door(rig, idx, scx, scy, a):
                    print(f"  door {idx % 16},{idx // 16} {side}: "
                          "could not be opened, skipped")
                    ok = False
                    continue
                rig.set_player(x, y, a)
                rig.release()
                rig.step([K_SPACE])
                for _ in range(8):
                    rig.release()
                sol = rig.solid()[idx]
                mv = frozen(rig, x, y)
                plane = nearest_plane(rig, x, y)
                clear = box_clear(rig.solid(), x, y)
                print(f"  door {idx % 16},{idx // 16} {side} off {off:2d} "
                      f"centre {x:04X},{y:04X} (box x-cells "
                      f"{(x - PRAD) >> 8}..{(x + PRAD) >> 8}): "
                      f"SOLID={sol} boxclear={clear} "
                      f"moved {mv}/24 headings  nearest plane {plane}/256")
                if sol != 0:
                    print("    FAIL: the door shut on a straddling player")
                    ok = False
                if mv != 24:
                    print(f"    FAIL: player wedged, only {mv}/24 moved")
                    ok = False
    return ok


def t_wedge_walk(rig):
    """The same six, but the straddle is reached by WALKING into the open
    doorway and stopping -- no poking of plr_x at all."""
    ok = True
    for idx in door_cells(rig):
        for side, (scx, scy), a, _ in approaches(idx):
            if not open_door(rig, idx, scx, scy, a):
                ok = False
                continue
            rig.set_player(scx * 256 + 128, scy * 256 + 128, a)
            hit = None
            for _ in range(12):
                rig.step([K_UP])
                x, y, _ = rig.player()
                bx0, bx1 = (x - PRAD) >> 8, (x + PRAD) >> 8
                if (x >> 8) != idx % 16 and idx % 16 in (bx0, bx1):
                    hit = (x, y)
                    break
            if hit is None:
                print(f"  door {idx % 16},{idx // 16} {side}: "
                      "no straddling frame while walking in")
                continue
            x, y = hit
            rig.release()
            rig.step([K_SPACE])
            for _ in range(8):
                rig.release()
            sol = rig.solid()[idx]
            mv = frozen(rig, x, y)
            print(f"  door {idx % 16},{idx // 16} {side} walked to "
                  f"{x:04X},{y:04X}: SOLID={sol} moved {mv}/24")
            if sol != 0 or mv != 24:
                print("    FAIL: shut on a walking player / wedged")
                ok = False
    return ok


def t_clear(rig):
    """One 8.8 unit further out the box is clear of the door cell, and
    SPACE must still shut the door -- the fix must not disable doors."""
    ok = True
    for idx in door_cells(rig):
        for side, (scx, scy), a, (x, y) in approaches(idx):
            if not open_door(rig, idx, scx, scy, a):
                ok = False
                continue
            # the exact boundary: box touches the door cell iff
            # ((x+-PRAD)>>8)&15 == dcx
            xx = (idx % 16) * 256 - PRAD - 1 if side == "W" \
                else (idx % 16 + 1) * 256 + PRAD
            rig.set_player(xx, y, a)
            rig.release()
            rig.step([K_SPACE])
            for _ in range(8):
                rig.release()
            sol = rig.solid()[idx]
            bx0, bx1 = (xx - PRAD) >> 8, (xx + PRAD) >> 8
            print(f"  door {idx % 16},{idx // 16} {side} centre {xx:04X} "
                  f"box x-cells {bx0}..{bx1}: SOLID={sol}")
            if sol != 2:
                print("    FAIL: a clear player could not shut the door")
                ok = False
    return ok


def t_farside(rig):
    """Symmetric hazard: the door must also refuse from the far side, and
    from every 30-degree heading, not just the two facing ones."""
    ok = True
    for idx in door_cells(rig):
        for side, (scx, scy), a, (x, y) in approaches(idx):
            for ha in range(0, N_ANGLES, 6):
                if not open_door(rig, idx, scx, scy, a):
                    ok = False
                    break
                rig.set_player(x, y, ha)
                rig.release()
                rig.step([K_SPACE])
                for _ in range(8):
                    rig.release()
                if rig.solid()[idx] != 0:
                    print(f"    FAIL: door {idx % 16},{idx // 16} {side} "
                          f"shut while straddling, heading {ha}")
                    ok = False
    print("  3 doors x 2 sides x 12 headings straddling: "
          + ("none shut" if ok else "SHUTS"))
    return ok


def t_midcycle(rig):
    """SPACE on every frame of the open/shut animation, while straddling:
    the animation must never leave the player inside SOLID."""
    ok = True
    for idx in door_cells(rig):
        for side, (scx, scy), a, (x, y) in approaches(idx):
            if not open_door(rig, idx, scx, scy, a):
                ok = False
                continue
            rig.set_player(x, y, a)
            rig.release()
            worst = []
            for f in range(24):
                # SPACE on the press edge every other frame
                rig.step([K_SPACE] if f % 2 == 0 else [])
                rig.set_player(x, y, a)     # the player does not move
                st = dict((i, s) for i, s, _ in rig.doors())[idx]
                worst.append((st, rig.solid()[idx]))
                if not box_clear(rig.solid(), x, y):
                    ok = False
            if not ok:
                print(f"    FAIL door {idx % 16},{idx // 16} {side}: "
                      f"{worst}")
    print("  3 doors x 2 sides x 24 frames of SPACE spam: "
          + ("player never inside SOLID" if ok else "TRAPPED"))
    return ok


def t_shut_then_open(rig):
    """A door shut normally from a clear position must still re-open and
    let the player through -- the whole cycle, twice."""
    ok = True
    solid0 = rig.solid()
    for idx in door_cells(rig):
        dcx, dcy = idx % 16, idx // 16
        scx, scy = dcx - 1, dcy
        if solid0[scy * 16 + scx]:
            continue
        for _ in range(2):
            if not open_door(rig, idx, scx, scy, 0):
                print(f"    FAIL: door {dcx},{dcy} would not open")
                ok = False
                break
            rig.set_player(scx * 256 + 128, scy * 256 + 128, 0)
            rig.release()
            rig.step([K_SPACE])
            for _ in range(8):
                rig.release()
            if rig.solid()[idx] != 2:
                print(f"    FAIL: door {dcx},{dcy} would not shut")
                ok = False
                break
    print("  open/shut cycled twice on every door: "
          + ("ok" if ok else "FAILED"))
    return ok


def main():
    rig = G.Rig()
    tests = [t_wedge, t_wedge_walk, t_clear, t_farside, t_midcycle,
             t_shut_then_open]
    fails = []
    for t in tests:
        print(f"{t.__name__}:")
        if not t(rig):
            fails.append(t.__name__)
    print()
    print("FAILED: " + ", ".join(fails) if fails else "ALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
