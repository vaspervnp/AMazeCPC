"""engine2/tools/gensnd.py -- the sound effects, as AY register steps.

    python3 engine2/tools/gensnd.py           -> engine2/src/gen_snd.inc

THE AY WAS NEVER TOUCHED until this file.  The CPC's AY-3-8912 sits
behind the same 8255 PPI that reads the keyboard -- engine2/src/game.asm's
scan_keys already speaks half the protocol, because reading a key row IS
an AY register read -- so the hardware was one pulse away the whole time.

FIFTY TICKS A SECOND, ON A FIVE-FRAME-A-SECOND GAME.  The engine runs
interrupts OFF and draws 5.56 frames a second, which is far too coarse
for a gunshot: a two-step envelope would last 360 ms.  But every one of
the nine vsync waits a frame goes through ONE routine, main3.asm's
wait_vsync, so hanging the sound tick there gives a true 50 Hz driver
with no interrupt and no second clock.  That is the whole trick.

A STEP IS SIX BYTES AND A TICK USUALLY WRITES NOTHING.  An effect is a
list of steps; a step holds every AY register the driver touches and how
many ticks to hold it.  So the common tick -- inside a held step -- is a
decrement and a return, and the expensive one only happens when the
sound actually changes.  That matters because the tick runs nine times a
frame and the frame budget is measured in microseconds.

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
TONE = SILENT & ~0x01           # ...channel A tone on
NOISE = SILENT & ~0x08          # ...channel A noise on
BOTH = TONE & NOISE

MAXVOL = 15


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
    assert not (mix & 0xC0), "mixer bits 6/7 would turn the keyboard round"
    return [ticks, lo, hi, n, mix, vol]


def build():
    out = []
    for name, steps in EFFECTS:
        rows = [step_bytes(*s) for s in steps]
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
