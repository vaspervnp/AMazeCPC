"""engine2/tools/gensnd.py -- the sound effects, as AY register steps.

    python3 engine2/tools/gensnd.py           -> engine2/src/gen_snd.inc

THE AY WAS NEVER TOUCHED until this file.  The CPC's AY-3-8912 sits
behind the same 8255 PPI that reads the keyboard -- engine2/src/game.asm's
scan_keys already speaks half the protocol, because reading a key row IS
an AY register read -- so the hardware was one pulse away the whole time.

FIFTY TICKS A SECOND, ON A FIVE-FRAME-A-SECOND GAME.  The engine runs
interrupts OFF and draws 5.01 frames a second, which is far too coarse
for a gunshot: a two-step envelope would last 400 ms.  But every one of
the PACE_FRAMES vsync waits a frame goes through ONE routine, main3.asm's
wait_vsync, so hanging the sound tick there gives a true 50 Hz driver
with no interrupt and no second clock.  That is the whole trick.

A STEP IS SIX BYTES AND A TICK USUALLY WRITES NOTHING.  An effect is a
list of steps; a step holds every AY register the driver touches and how
many ticks to hold it.  So the common tick -- inside a held step -- is a
decrement and a return, and the expensive one only happens when the
sound actually changes.  That matters because the tick runs PACE_TICKS
times a frame and the frame budget is measured in microseconds.

MIXER VALUES KEEP BITS 6 AND 7 CLEAR, ALWAYS.  R7 bit 6 is the direction
of the AY's port A, and on a CPC port A is the KEYBOARD.  Setting it
would leave the machine unable to read a key.  SILENT below is #3F --
everything off, both ports input -- and every mixer here is that with
bits cleared, never set.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)

# ---- the AY registers the driver writes, in the order it writes them ----
#  Channel A only.  B and C are silenced once at startup and never
#  touched again, which is why a step does not carry them.
R_TONE_LO, R_TONE_HI = 0, 1
R_NOISE = 6
R_MIXER = 7
R_VOL_A, R_VOL_B, R_VOL_C = 8, 9, 10

SILENT = 0x3F                   # tone and noise off on all three channels
#  THE ONE ASSERT HERE THAT CAN ACTUALLY FIRE.  R7 bits 6 and 7 are the
#  AY's port A direction and on a CPC port A IS the keyboard, so a mixer
#  with either bit set leaves the machine unable to read a key.  The
#  per-step check in step_bytes() looks like it guards that -- and it is
#  UNREACHABLE: mix starts as SILENT and every line after it only CLEARS
#  bits (&= ~0x01, &= ~0x08), so `mix & 0xC0` cannot become non-zero no
#  matter what EFFECTS says.  The invariant does not live in the steps,
#  it lives in this constant, so the guard belongs on this constant.
assert not (SILENT & 0xC0), "R7 bits 6/7 would turn port A round -- and " \
                            "port A is the keyboard"
TONE = SILENT & ~0x01           # ...channel A tone on
NOISE = SILENT & ~0x08          # ...channel A noise on
BOTH = TONE & NOISE

MAXVOL = 15

# ---- WHAT C_SND RESTS ON, AND IT IS AN INVARIANT ABOUT THIS FILE -----
#  main3.asm charges C_SND = 2200 us once a frame for all PACE_TICKS of
#  the frame's sound ticks.  That number was measured at 1944 us worst on
#  a NINE-tick frame, and the frame it was measured on is the one where
#  SFX_SHOT's steps land four STEP CHANGES plus the stop inside a single
#  window.  At ten ticks the same four loads sit in the window with one
#  more idle tick beside them: 1944 + 31 = 1975, still under 2200.
#
#  A tick that sits inside a held step is a decrement and a return.  A
#  tick that CHANGES step writes five AY registers through snd_wr, and
#  that is the expensive one -- so what the charge really bounds is how
#  many step changes can fall in nine consecutive ticks.
#
#  NOTHING CHECKED IT.  EFFECTS below is a table anybody can edit, and an
#  effect written with five short steps would put five changes in the
#  window and walk straight past 2200 with no tool saying a word: the
#  disc would simply take a tenth vsync period on the frames it played.
#  That is the exact shape of the C_CFAR defect -- a charge derived once,
#  for one configuration, and never re-derived when the thing it
#  described moved.
#
#  THE ASSERT IS ON THE COUNT, NOT ON MICROSECONDS, and that is
#  deliberate.  Deriving the per-tick cost by counting Z80 T-states gave
#  two different answers on two attempts (snd_wr is 48 us or 56 us
#  depending on how the gate array's wait states are applied to OUT
#  (C),r), and this repo does not put a number it guessed into a gate.
#  1944 us for four changes is MEASURED; four is therefore the ceiling
#  that measurement licenses, and a fifth change means C_SND has to be
#  re-measured before it can be trusted -- which is what the assert says.
#
#  AND THE WINDOW IS READ OUT OF main3.asm, NOT WRITTEN HERE.  It was
#  `PACE_TICKS = 9` with a comment saying ": PACE_FRAMES", which is a
#  copy of a constant that has moved twice.  When PACE_FRAMES went to 10
#  this file would still have slid a NINE-tick window over the effects
#  and licensed a table with five loads in the frame's real ten -- the
#  same second-copy failure C_BG had, and the reason pacemodel.py reads
#  every C_* out of the disc's own source.  A window that is too short
#  is the dangerous direction: it under-counts, so it passes.


def _equ(name, default, src="main3.asm"):
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


PACE_TICKS = _equ("PACE_FRAMES", 10)    # snd_tick calls in one game frame
MAX_CHANGES = 4         # ...step changes allowed inside any ten of them


def tone(hz):
    """-> the 12-bit period for a frequency, at the CPC's 1 MHz clock.

    period = 1000000 / (16 * hz), and the AY divides by 16 internally.
    Clamped to 12 bits because that is the register width, and asserted
    away from 0 because a period of 0 is not silence, it is the highest
    frequency the chip has.
    """
    p = int(round(1000000.0 / (16.0 * hz)))
    assert 1 <= p <= 4095, f"{hz} Hz is period {p}, outside the AY's 12 bits"
    return p


#  A step is (ticks, tone_hz or None, noise 0..31 or None, volume 0..15).
#  None means "off": no tone, or no noise.  Ticks are 50ths of a second.
EFFECTS = [
    # ---- 0: silence.  Index 0 is "nothing playing", so the table starts
    #      with an empty effect and snd_play(0) is a legal way to stop.
    ("silence", []),

    # ---- 1: the shot.  A hard noise transient that falls away in three
    #      steps -- 120 ms end to end, which at 5.5 frames a second is
    #      most of the frame the recoil is on screen for.
    ("shot", [
        (1, None, 3, 15),           # the crack: bright noise, full volume
        (2, None, 8, 11),           # ...opening out and dropping
        (3, None, 16, 6),
        (2, None, 24, 2),           # ...to a tail of air
    ]),

    # ---- 2: the shot into STONE.  The same crack with a hard, short
    #      ring on the end: chips off a wall.
    ("shot_stone", [
        (1, None, 3, 15),
        (2, None, 6, 12),
        (2, tone(2200), 20, 9),     # a bright tick over the noise
        (3, None, 26, 4),
    ]),

    # ---- 3: the shot into FLESH.  Same crack, then a low wet thump
    #      instead of a ring.  Low tone, slow noise, no bright edge.
    ("shot_flesh", [
        (1, None, 3, 15),
        (2, None, 10, 12),
        (3, tone(110), 28, 13),     # the thump: low tone under slow noise
        (4, tone(80), 31, 7),
    ]),

    # ---- 4: the dry click, for a trigger pulled on an empty magazine.
    #      One tick.  It has to be unmistakably NOT a shot.
    ("click", [
        (1, None, 1, 8),
    ]),

    # ---- 5: a door.  The six frames a door takes to rise are about a
    #      second, so this is a slow rising tone -- the sound of
    #      something heavy moving, not a beep.
    ("door", [
        (4, tone(140), None, 9),
        (4, tone(175), None, 10),
        (4, tone(210), None, 11),
        (4, tone(250), None, 10),
        (6, tone(300), None, 7),
        (6, tone(330), None, 3),
    ]),

    # ---- 7: the monster dying, and it is the LONGEST effect here on
    #      purpose.  Every other sound in the game is an event; this one
    #      is a consequence, and it is the only feedback that the third
    #      round did something the first two did not.  A falling tone
    #      under opening noise -- 18 ticks, 360 ms, most of two frames.
    #
    #      IT MUST NOT SOUND LIKE shot_flesh, which is what the first
    #      two rounds play.  That one is a 110 Hz thump inside the
    #      crack; this starts above it and falls THROUGH it, so the ear
    #      hears a pitch moving rather than a single hit.
    ("mondie", [
        (3, tone(240), 20, 13),
        (4, tone(170), 24, 12),
        (5, tone(120), 28, 9),
        (6, tone(85), 31, 5),
    ]),

    # ---- 8: TAKING A HIT.  Short, low and ugly, and it must not be
    #      confusable with shot_flesh -- that one is the player DOING
    #      something and this one is the player LOSING something.  So:
    #      no crack at the front, and the pitch goes UP into a squeal
    #      rather than down into a thump.
    ("hurt", [
        (2, tone(150), 12, 14),
        (3, tone(200), 18, 11),
        (3, tone(260), 24, 6),
    ]),

    # ---- 6: picking up ammunition.  Two rising notes, short and clean,
    #      the one sound in the game that should feel like a reward.
    ("pickup", [
        (3, tone(660), None, 12),
        (5, tone(990), None, 12),
        (3, tone(990), None, 5),
    ]),
]

NAMES = [n for n, _ in EFFECTS]


def step_bytes(ticks, hz, noise, vol):
    """-> the six bytes of one step: ticks, tone lo/hi, noise, mixer, vol."""
    assert 1 <= ticks <= 255, ticks
    assert 0 <= vol <= MAXVOL, vol
    mix = SILENT
    lo = hi = 0
    if hz is not None:
        p = hz if isinstance(hz, int) and hz > 4095 else hz
        lo, hi = p & 0xFF, (p >> 8) & 0x0F
        mix &= ~0x01
    n = 0
    if noise is not None:
        assert 0 <= noise <= 31, noise
        n = noise
        mix &= ~0x08
    # Belt and braces, and knowingly so: this cannot fire while mix is
    # built by clearing bits out of SILENT (see the assert on SILENT
    # above, which is the one that guards the invariant).  It is kept so
    # that the day someone computes a mixer here instead of clearing
    # one, the check is already in the right place.
    assert not (mix & 0xC0), "mixer bits 6/7 would turn the keyboard round"
    return [ticks, lo, hi, n, mix, vol]


def worst_window(steps):
    """-> (most step LOADS in any PACE_TICKS-long run, whether the stop
    falls in that same window, and where the window starts).

    Walks the effect's tick timeline the way snd_tick walks it: tick 0
    loads step 0, and a step of N ticks is then held for N ticks before
    the next one loads.

    THE STOP IS COUNTED SEPARATELY, and getting that wrong is what the
    first version of this function did.  st_stop writes two registers,
    not five, so it is not a step load -- and the 1944 us that C_SND
    rests on was measured on SFX_SHOT, whose worst window holds FOUR
    loads AND the stop.  Folding the stop into the same total made the
    ceiling look like five and rejected an effect that ships.
    """
    load_at, t = [], 0
    for _ticks, _hz, _noise, _vol in steps:
        load_at.append(t)
        t += _ticks
    stop_at = t if steps else None
    worst, at, stop_in = 0, 0, False
    for start in range(0, t + 1):
        end = start + PACE_TICKS
        n = sum(1 for c in load_at if start <= c < end)
        if n > worst:
            worst, at = n, start
            stop_in = stop_at is not None and start <= stop_at < end
    return worst, stop_in, at


def build():
    out = []
    for name, steps in EFFECTS:
        rows = [step_bytes(*s) for s in steps]
        n, stop_in, at = worst_window(steps)
        assert n <= MAX_CHANGES, (
            f"effect {name!r} loads {n} steps inside {PACE_TICKS} ticks "
            f"(window from tick {at}{', with the stop' if stop_in else ''})"
            f"; C_SND = 2200 us in main3.asm was MEASURED at "
            f"{MAX_CHANGES} loads plus a stop -- 1944 us. A fifth load "
            f"is about 2320 and the frame takes one vsync period more "
            f"than PACE_FRAMES. "
            f"Re-measure C_SND before raising MAX_CHANGES, or give the "
            f"effect's early steps more ticks.")
        out.append((name, rows))
    return out


def write_inc(path):
    eff = build()
    L = ["; Generated by engine2/tools/gensnd.py -- do not edit.",
         "; The sound effects, as AY register steps.  See that file for the",
         "; register order, why the mixer never sets bits 6 or 7, and why",
         "; the driver ticks out of wait_vsync.",
         "",
         f"SND_STEP     equ 6   ; bytes in one step: ticks, tone lo, tone hi,",
         f"                     ; noise, mixer, volume -- in the order the",
         f"                     ; driver writes them",
         f"SND_N        equ {len(eff)}   ; effects, including 0 = silence",
         f"SND_SILENT   equ #{SILENT:02X}   ; mixer: everything off, ports input",
         "",
         "; ---- the AY registers the driver writes, named once ----",
         f"R_TONE_LO    equ {R_TONE_LO}",
         f"R_TONE_HI    equ {R_TONE_HI}",
         f"R_NOISE      equ {R_NOISE}",
         f"R_MIXER      equ {R_MIXER}",
         f"R_VOL_A      equ {R_VOL_A}",
         f"R_VOL_B      equ {R_VOL_B}",
         f"R_VOL_C      equ {R_VOL_C}",
         ""]
    for i, (name, _rows) in enumerate(eff):
        L.append(f"SFX_{name.upper():<11s} equ {i}")
    L.append("")
    L.append("; ---- effect -> its step list ----")
    L.append("SNDTAB")
    for name, _rows in eff:
        L.append(f"    dw SND_{name.upper()}")
    L.append("")
    for name, rows in eff:
        L.append(f"SND_{name.upper()}")
        for r in rows:
            L.append("    db " + ",".join("#%02X" % b for b in r))
        L.append("    db 0                    ; ...and 0 ticks ends it")
    open(path, "w").write("\n".join(L) + "\n")


def main():
    eff = build()
    out = os.path.join(_E2, "src", "gen_snd.inc")
    write_inc(out)
    total = sum(len(r) * 6 + 1 for _n, r in eff) + len(eff) * 2
    print(f"sound: {len(eff)} effects, {total} bytes of table")
    for name, rows in eff:
        ticks = sum(r[0] for r in rows)
        print(f"  {name:12s} {len(rows)} steps, {ticks:2d} ticks = "
              f"{ticks * 20:4d} ms")
    print("wrote", out)


if __name__ == "__main__":
    main()
