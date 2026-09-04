"""engine2/tools/bootdisc.py -- boot build/amaze.dsk PAST THE TITLE SCREEN.

Every harness in this directory boots the same way -- insert the disc,
type RUN"AMAZE, wait -- and since engine2/src/menu.asm arrived, every one
of them then sits on the title screen for ever, because the game does
not start until SPACE has been pressed AND released.  Eleven files had
the same four lines and now eleven files have one call, so a change to
how the game starts is a change in one place.

The press is a real key through the matrix, not a poke: menu.asm waits
for the press EDGE, which is the same thing that stops a player who held
SPACE to start from opening the door in front of them on frame one.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.expanduser("~/cpcemu"))

import cpc as cpcmod                                          # noqa: E402

DSK = os.path.join(_ROOT, "build", "amaze.dsk")

# HOW LONG THE LOADER TAKES, IN CPC FRAMES, AND IT IS NOT JUST THE LOAD.
#
# amaze.bas puts revive8b.scr up at &C000 and then waits for SPACE **or
# ten seconds** before it CALLs the game.  Ten seconds is 500 frames on
# top of the ~500 the three binaries take, so a harness that settles for
# 500 and then presses SPACE is pressing it at the LOADING SCREEN and
# arriving at the title menu with nothing left to press.
#
# WAITING THE TIMEOUT OUT RATHER THAN PRESSING PAST IT, deliberately.
# Pressing needs to know which of the two gates the press will land on,
# and getting that wrong is not a hung harness -- it is one extra SPACE
# delivered INTO THE GAME, where SPACE is door_act.  A boot that opens a
# door in front of the player changes every measurement in this
# directory and would look like a pacing defect, not a harness bug.  So:
# sit through the ten seconds, then press once, for the menu.
#
# MEASURED, not guessed.  amaze.bas was instrumented with a POKE either
# side of the wait and the disc booted twice: the wait is ENTERED at
# frame 770 and, untouched, CALLs the game at frame 1240 -- 470 frames,
# 9.4 s, which is the ten-second timeout read through a 300 Hz TIME.
# With SPACE held it CALLs at 780.  boot() spends 150 frames before it
# types, so the settle has to clear 1090; 1400 leaves 310 frames of
# margin for a loader that grows.
LOAD_FRAMES = 1400


def boot(c, dsk=None, settle=LOAD_FRAMES):
    """Insert, RUN"AMAZE, and press SPACE past the menu.  -> the machine."""
    c.insert_disc(dsk or DSK)
    c.run_frames(150)
    c.type_text('RUN"AMAZE\n')
    c.run_frames(settle)
    start(c)
    return c


def start(c, hold=14, after=40):
    """SPACE, held long enough for menu.asm's scan to see it down and
    then up.  menu.asm scans in a tight loop rather than once a game
    frame, so this does not have to cover a 9-vsync period -- but it
    costs nothing to be generous and it keeps working if that changes."""
    c.key_down(cpcmod.KEY_SPACE)
    c.run_frames(hold)
    c.key_up(cpcmod.KEY_SPACE)
    c.run_frames(after)
