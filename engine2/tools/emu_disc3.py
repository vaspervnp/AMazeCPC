"""END-TO-END check of build/amaze.dsk through the real BASIC loader.

    python3 engine2/tools/emu_disc3.py

Boots the disc, walks up to a door, opens it with SPACE, walks through,
and quits with ESC.  Everything asserted here is read out of the running
machine: the door's cell in SOLID, the player's own position, and where
the Z80 ends up after ESC.
"""

import os
import addrs
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import cpc as cpcmod                                         # noqa: E402
from cpc import CPC                                          # noqa: E402
import bootdisc                                              # noqa: E402

DSK = os.path.join(_ROOT, "build", "amaze.dsk")
SYM = os.path.join(_ROOT, "build", "e3", "game3.sym")
SHOTS = os.path.join(_E2, "build", "shots3")


def syms():
    out = {}
    for line in open(SYM):
        p = line.split()
        if len(p) >= 2 and p[1].startswith("#"):
            out[p[0].upper()] = int(p[1][1:], 16)
    return out


def main():
    os.makedirs(SHOTS, exist_ok=True)
    s = syms()
    c = CPC()
    c.insert_disc(DSK)
    c.run_frames(150)
    c.type_text('RUN"AMAZE\n')
    c.run_frames(bootdisc.LOAD_FRAMES)
    bootdisc.start(c)   # past the title screen -- see bootdisc.py
    ok = True
    if c.mode != 0:
        print(f"FAIL: mode is {c.mode}, want 0")
        ok = False

    def place(cx, cy, a):
        c.write_ram(s["PLR_X"], struct.pack("<H", cx * 256 + 128))
        c.write_ram(s["PLR_Y"], struct.pack("<H", cy * 256 + 128))
        c.poke(s["PLR_A"], a)
        c.run_frames(20)

    def player():
        x, y = struct.unpack("<HH", c.read_ram(s["PLR_X"], 4))
        return x, y, c.peek(s["PLR_A"])

    # --- the door at (5,3), approached from (4,3) facing east ----------
    place(4, 3, 0)
    c.screenshot(os.path.join(SHOTS, "door_shut.png"))
    if c.peek(addrs.SOLID + 3 * 16 + 5) != 2:
        print("FAIL: door (5,3) is not shut to start with")
        ok = False
    c.key_down(cpcmod.KEY_SPACE)
    c.run_frames(20)
    c.key_up(cpcmod.KEY_SPACE)
    c.run_frames(40)
    if c.peek(addrs.SOLID + 3 * 16 + 5) != 0:
        print("FAIL: SPACE did not open the door at (5,3)")
        ok = False
    c.screenshot(os.path.join(SHOTS, "door_open.png"))
    c.key_down(cpcmod.KEY_UP)
    c.run_frames(150)
    c.key_up(cpcmod.KEY_UP)
    c.run_frames(20)
    x, y, _ = player()
    print(f"  after opening and walking east: cell {x >> 8},{y >> 8}")
    if (x >> 8) < 5:
        print("FAIL: never walked through the open door")
        ok = False
    c.screenshot(os.path.join(SHOTS, "door_through.png"))

    # --- shut it again from the far side -------------------------------
    place(6, 3, 36)
    c.key_down(cpcmod.KEY_SPACE)
    c.run_frames(20)
    c.key_up(cpcmod.KEY_SPACE)
    c.run_frames(40)
    if c.peek(addrs.SOLID + 3 * 16 + 5) != 2:
        print("FAIL: SPACE did not shut the door again")
        ok = False

    # --- ESC ------------------------------------------------------------
    c.key_down(cpcmod.KEY_ESC)
    c.run_frames(30)
    c.key_up(cpcmod.KEY_ESC)
    c.run_frames(600)                   # the firmware's cold start is slow
    print(f"  after ESC: mode {c.mode}, pc {hex(c.pc)}")
    c.screenshot(os.path.join(SHOTS, "quit.png"))
    if c.mode == 0:
        print("FAIL: ESC did not leave the game")
        ok = False
    before = c.read_ram(0xC000, 0x800)
    c.type_text('PRINT 6*7\n')
    c.run_frames(120)
    if c.read_ram(0xC000, 0x800) == before:
        print("FAIL: BASIC does not respond to the keyboard after ESC")
        ok = False
    c.screenshot(os.path.join(SHOTS, "basic.png"))
    print("PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
