"""engine2/tools/bootdisc.py -- boot build/amaze.dsk PAST THE TITLE SCREEN.

Every harness in this directory boots the same way -- insert the disc,
type RUN"DISC, wait -- and since engine2/src/menu.asm arrived, every one
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


def boot(c, dsk=None, settle=500):
    """Insert, RUN"DISC, and press SPACE past the menu.  -> the machine."""
    c.insert_disc(dsk or DSK)
    c.run_frames(150)
    c.type_text('RUN"DISC\n')
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
