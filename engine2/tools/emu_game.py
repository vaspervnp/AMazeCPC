"""UNIT TEST engine2/src/game.asm on a cycle-accurate CPC 6128.

    python3 engine2/tools/emu_game.py collide   walk into walls from every
                                                heading; the player must
                                                never end up inside SOLID
    python3 engine2/tools/emu_game.py slide     sliding along a wall works
    python3 engine2/tools/emu_game.py doors     SPACE, the 5-step animation
                                                and "solid until fully open"
    python3 engine2/tools/emu_game.py all       all three

WHAT IS ACTUALLY RUN is engine2/test/tst_game.asm, which is the real
game.asm and the real march.asm map, driven one frame at a time with the
key matrix POKED rather than scanned (game_run is game_step minus the
matrix read).  Nothing is modelled: every player position asserted on
below is read back out of the emulator's RAM.

THE INVARIANT.  After every frame, the 0.25-cell box around the player
must be clear of SOLID -- all four corner cells open.  That is stricter
than "the player's own cell is open", and it is what stops a corner being
cut through diagonally.  It is also what project.asm needs: it rejects a
wall face nearer than ZNEAR = 0.125 cells, so a player that can get within
0.125 of a wall plane sees through the wall.
"""

import os
import struct
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import addrs                                              # noqa: E402
import gentab                                                # noqa: E402
from cpc import CPC                                          # noqa: E402

BUILD = os.path.join(_E2, "build")
E_INIT, E_STEP = 0x8000, 0x8004
PRAD = 64                       # must match game.asm
STEP = 24
N_ANGLES = 72

# key matrix bits, ACTIVE LOW
K_UP = (0, 0)
K_RIGHT = (0, 1)
K_DOWN = (0, 2)
K_LEFT = (1, 0)
K_SPACE = (5, 7)
K_ESC = (8, 2)


def build():
    blob, layout, _ = gentab.build()
    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "tab_test.bin"), "wb").write(blob)
    gentab.write_inc(os.path.join(BUILD, "tab_equ_test.inc"), blob, layout)
    r = subprocess.run(
        ["rasm", "tst_game.asm", "-I", "../build", "-I", "../src",
         "-o", "../build/tst_game", "-s", "-os", "../build/tst_game"],
        cwd=os.path.join(_E2, "test"), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("rasm failed")
    code = open(os.path.join(BUILD, "tst_game.bin"), "rb").read()
    sym = {}
    for line in open(os.path.join(BUILD, "tst_game")):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            sym[p[0].upper()] = int(p[1][1:], 16)
    return blob, code, sym


class Rig:
    def __init__(self):
        self.tables, self.code, self.sym = build()
        self.c = CPC()
        self.c.run_frames(60)
        self.c.write_ram(gentab.BANK_BASE, self.tables)
        self.c.write_ram(0x8000, self.code)
        self._enter(E_INIT)

    def s(self, n):
        return self.sym[n.upper()]

    def _enter(self, pc):
        self.c.poke(self.s("DONE"), 0)
        self.c.set_pc(pc)
        for _ in range(200):
            self.c.run_frames(1)
            if self.c.peek(self.s("DONE")) == 0xFF:
                return
        raise RuntimeError("harness never finished")

    # ---- state ------------------------------------------------------
    def set_player(self, x, y, a):
        self.c.write_ram(self.s("PLR_X"), struct.pack("<H", x))
        self.c.write_ram(self.s("PLR_Y"), struct.pack("<H", y))
        self.c.poke(self.s("PLR_A"), a)

    def player(self):
        x, y = struct.unpack("<HH", self.c.read_ram(self.s("PLR_X"), 4))
        return x, y, self.c.peek(self.s("PLR_A"))

    def solid(self):
        return self.c.read_ram(addrs.SOLID, 256)

    def doors(self):
        n = self.c.peek(self.s("DOOR_N"))
        idx = self.c.read_ram(self.s("DOOR_IDX"), n)
        st = self.c.read_ram(self.s("DOOR_ST"), n)
        tg = self.c.read_ram(self.s("DOOR_TG"), n)
        return list(zip(idx, st, tg))

    def step(self, keys=()):
        m = bytearray(b"\xff" * 10)
        for row, bit in keys:
            m[row] &= 0xFF ^ (1 << bit)
        self.c.write_ram(self.s("KEYS"), bytes(m))
        self._enter(E_STEP)

    def release(self):
        """One frame with nothing held -- clears the SPACE edge latch."""
        self.step(())


def box_clear(solid, x, y):
    """The game's own collision predicate, in Python."""
    for px in (x - PRAD, x + PRAD):
        for py in (y - PRAD, y + PRAD):
            if solid[((py >> 8) & 15) * 16 + ((px >> 8) & 15)]:
                return False
    return True


# ---------------------------------------------------------------- tests --
def t_collide(rig):
    """Walk into the maze from every cell and every heading and assert the
    player is never inside SOLID."""
    solid = rig.solid()
    starts = [(cx, cy) for cy in range(16) for cx in range(16)
              if solid[cy * 16 + cx] == 0]
    bad = 0
    tested = 0
    worst = None
    for (cx, cy) in starts:
        for a in range(0, N_ANGLES, 3):         # every 15 degrees
            x0, y0 = cx * 256 + 128, cy * 256 + 128
            rig.set_player(x0, y0, a)
            for f in range(14):                 # 14 frames = 1.3 cells
                rig.step([K_UP])
                x, y, _ = rig.player()
                tested += 1
                if not box_clear(solid, x, y):
                    bad += 1
                    if worst is None:
                        worst = (cx, cy, a, f, x, y)
    print(f"  forward from {len(starts)} cells x 24 headings, 14 frames: "
          f"{tested} positions, {bad} inside SOLID")
    if worst:
        print(f"  FIRST VIOLATION cell {worst[0]},{worst[1]} heading "
              f"{worst[2]} frame {worst[3]} at {worst[4]:04X},{worst[5]:04X}")
    return bad == 0


def t_collide_back(rig):
    """Same, walking backwards, which uses the negated step vector."""
    solid = rig.solid()
    starts = [(cx, cy) for cy in range(16) for cx in range(16)
              if solid[cy * 16 + cx] == 0]
    bad = tested = 0
    for (cx, cy) in starts:
        for a in range(0, N_ANGLES, 6):
            rig.set_player(cx * 256 + 128, cy * 256 + 128, a)
            for _ in range(14):
                rig.step([K_DOWN])
                x, y, _ = rig.player()
                tested += 1
                if not box_clear(solid, x, y):
                    bad += 1
    print(f"  backward, {tested} positions, {bad} inside SOLID")
    return bad == 0


def t_nearplane(rig):
    """The collision radius must keep the player further from every wall
    PLANE than project.asm's ZNEAR (0.125 cells = 32 in 8.8), or faces get
    rejected and the player sees through the wall."""
    solid = rig.solid()
    starts = [(cx, cy) for cy in range(16) for cx in range(16)
              if solid[cy * 16 + cx] == 0]
    worst = 999
    for (cx, cy) in starts:
        for a in range(0, N_ANGLES, 3):
            rig.set_player(cx * 256 + 128, cy * 256 + 128, a)
            for _ in range(14):
                rig.step([K_UP])
                x, y, _ = rig.player()
                px, py = x >> 8, y >> 8
                fx, fy = x & 255, y & 255
                for dx, d in ((-1, fx), (1, 256 - fx)):
                    if solid[(py & 15) * 16 + ((px + dx) & 15)]:
                        worst = min(worst, d)
                for dy, d in ((-1, fy), (1, 256 - fy)):
                    if solid[((py + dy) & 15) * 16 + (px & 15)]:
                        worst = min(worst, d)
    print(f"  closest approach to a wall plane: {worst}/256 = "
          f"{worst / 256.0:.3f} cells   (ZNEAR is 0.125)")
    return worst >= PRAD


def t_slide(rig):
    """Push diagonally into a wall: the blocked axis must stop and the free
    axis must keep moving.  Both walls of a corridor, both directions."""
    solid = rig.solid()
    ok = True
    cases = []
    # every open cell that has a wall to the north and open floor east/west
    for cy in range(16):
        for cx in range(16):
            if solid[cy * 16 + cx]:
                continue
            if solid[(cy - 1) * 16 + cx] and not solid[cy * 16 + cx + 1]:
                cases.append((cx, cy, "N", +1))
            if solid[(cy + 1) * 16 + cx] and not solid[cy * 16 + cx + 1]:
                cases.append((cx, cy, "S", +1))
    tested = 0
    for (cx, cy, wall, sgn) in cases[:24]:
        # heading 3 = 15 deg (mostly +x, a little +y) / 69 = -15 deg
        a = 69 if wall == "N" else 3
        x0, y0 = cx * 256 + 128, cy * 256 + 128
        rig.set_player(x0, y0, a)
        for _ in range(6):
            rig.step([K_UP])
        x, y, _ = rig.player()
        tested += 1
        moved_x = x - x0
        if moved_x <= 0:
            print(f"  NO SLIDE at {cx},{cy} wall {wall}: dx={moved_x}")
            ok = False
        if not box_clear(solid, x, y):
            print(f"  INSIDE SOLID while sliding at {cx},{cy}")
            ok = False
    print(f"  {tested} slide cases, all kept the along-wall component"
          if ok else "  slide FAILED")
    return ok


def t_headon(rig):
    """Straight at a wall: the player must stop, and stop clear of it."""
    solid = rig.solid()
    ok = True
    n = 0
    for cy in range(16):
        for cx in range(16):
            if solid[cy * 16 + cx]:
                continue
            for a, (dx, dy) in ((0, (1, 0)), (18, (0, 1)),
                                (36, (-1, 0)), (54, (0, -1))):
                if not solid[(cy + dy) * 16 + cx + dx]:
                    continue
                rig.set_player(cx * 256 + 128, cy * 256 + 128, a)
                for _ in range(10):
                    rig.step([K_UP])
                x, y, _ = rig.player()
                n += 1
                if not box_clear(solid, x, y):
                    print(f"  head-on into wall from {cx},{cy} a={a} "
                          f"ended at {x:04X},{y:04X} INSIDE SOLID")
                    ok = False
                # and it must have stopped short, not passed through
                if abs((x >> 8) - cx) + abs((y >> 8) - cy) != 0:
                    print(f"  head-on from {cx},{cy} a={a} left the cell")
                    ok = False
    print(f"  {n} head-on approaches, all stopped in the open cell"
          if ok else "  head-on FAILED")
    return ok


def t_doors(rig):
    """SPACE opens the nearest door; the door is solid until fully open;
    it animates one step per frame; and it cannot be shut on the player."""
    solid = rig.solid()
    doors = rig.doors()
    print(f"  door cells: {[(i % 16, i // 16) for i, _, _ in doors]}")
    ok = bool(doors)
    for (idx, _, _) in doors:
        dcx, dcy = idx % 16, idx // 16
        # stand in an open cell next to the door and face it
        for a, (dx, dy) in ((0, (-1, 0)), (18, (0, -1)),
                            (36, (1, 0)), (54, (0, 1))):
            scx, scy = dcx + dx, dcy + dy
            if solid[scy * 16 + scx] == 0:
                break
        else:
            continue
        rig.set_player(scx * 256 + 128, scy * 256 + 128, a)
        rig.release()
        rig.step([K_SPACE])
        seq = []
        for _ in range(6):
            rig.release()
            st = dict((i, s) for i, s, _ in rig.doors())[idx]
            sol = rig.solid()[idx]
            seq.append((st, sol))
        print(f"  door {dcx},{dcy} from {scx},{scy} a={a}: "
              f"(state,SOLID) {seq}")
        # the SPACE frame itself runs doors_step, so 2 -> 3 happens on
        # the press and the first sampled frame is already 4
        if [s for s, _ in seq] != [4, 5, 6, 6, 6, 6]:
            print("    FAIL: not one animation step per frame 2..6")
            ok = False
        if [v for _, v in seq] != [2, 2, 0, 0, 0, 0]:
            print("    FAIL: SOLID must stay 2 until the door is fully open")
            ok = False
        # the player can now walk through it
        rig.set_player(scx * 256 + 128, scy * 256 + 128, a)
        for _ in range(16):
            rig.step([K_UP])
        x, y, _ = rig.player()
        if (x >> 8, y >> 8) == (scx, scy):
            print("    FAIL: door open but the player never got through")
            ok = False
        # standing IN the doorway, SPACE must not shut it on us
        rig.set_player(dcx * 256 + 128, dcy * 256 + 128, a)
        rig.release()
        rig.step([K_SPACE])
        for _ in range(6):
            rig.release()
        if rig.solid()[idx] != 0:
            print("    FAIL: door shut on the player standing in it")
            ok = False
        # step out and shut it again for the next door
        rig.set_player(scx * 256 + 128, scy * 256 + 128, a)
        rig.release()
        rig.step([K_SPACE])
        for _ in range(6):
            rig.release()
        if rig.solid()[idx] != 2:
            print("    FAIL: SPACE did not shut the door again")
            ok = False
    return ok


def t_turn(rig):
    """One heading step per frame while held, and the wrap is clean."""
    rig.set_player(10 * 256 + 128, 13 * 256 + 128, 0)
    seq = []
    for _ in range(4):
        rig.step([K_LEFT])
        seq.append(rig.player()[2])
    for _ in range(4):
        rig.step([K_RIGHT])
        seq.append(rig.player()[2])
    print(f"  headings while turning left then right: {seq}")
    return seq == [71, 70, 69, 68, 69, 70, 71, 0]


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    rig = Rig()
    tests = {
        "collide": [t_turn, t_headon, t_collide, t_collide_back, t_nearplane],
        "slide": [t_slide],
        "doors": [t_doors],
    }
    if what == "all":
        run = tests["collide"] + tests["slide"] + tests["doors"]
    else:
        run = tests[what]
    fails = []
    for t in run:
        print(f"{t.__name__}:")
        if not t(rig):
            fails.append(t.__name__)
    print()
    print("FAILED: " + ", ".join(fails) if fails else "ALL PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
