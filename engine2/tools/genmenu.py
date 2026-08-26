"""engine2/tools/genmenu.py -- the title screen's font and its words.

    python3 engine2/tools/genmenu.py          -> engine2/src/gen_menu.inc

THE ENGINE HAD NO TEXT AT ALL until this file.  Everything the HUD draws
is a rectangle (genhud.py), which is right for dials and pips and wrong
for twenty-six characters of credit line, so the menu brings the one
thing a title screen cannot do without: a font.

FOUR PIXELS WIDE, AND THAT IS FORCED, NOT CHOSEN.  Mode 0 is 160 pixels
across.  The line the credits have to fit --

    REVIVE8BIT - 2026 - VASPER

-- is 26 characters, so the pitch can be at most 160/26 = 6.15 pixels.
A mode-0 byte is TWO pixels, so a pitch that is not a whole number of
bytes would put half the glyphs on a byte boundary and half straddling
one, and the blitter would need a shift path for the odd ones.  Six
pixels is three bytes exactly: four of ink and two of gap.  So the
glyphs are 4x6 and every one of them starts on a byte.

THE BLITTER IS A NIBBLE LOOKUP.  A glyph row is four pixels, which is
one nibble of the font and two bytes of screen, so drawing a row is one
table read.  The table is per PEN -- Python knows mode 0's scrambled bit
layout and the Z80 should not have to -- and there is one for each
colour the screen uses.  32 bytes a pen against a shift-and-mask loop
that would be bigger and slower.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import cpchw as cpc                                            # noqa: E402
import pal                                                     # noqa: E402

SCR_W, SCR_H = cpc.SCR_W_BYTES, cpc.SCR_H       # 80 bytes, 200 lines

GW, GH = 4, 6                   # glyph, in PIXELS
PITCH = 3                       # ...and in screen BYTES, gap included
LINE = 8                        # scanlines from one row of text to the next

# ---------------------------------------------------------------- font ----
#  '#' is ink.  Four columns, six rows, capitals only -- at four pixels a
#  lower case with descenders is not readable and a title screen does not
#  need one.  The digits and the two punctuation marks are the ones the
#  words below actually use; CHARSET is checked against them at the foot
#  of this file, so a letter nobody draws cannot sit here unnoticed.
GLYPHS = {
    ' ': ["....", "....", "....", "....", "....", "...."],
    'A': [".##.", "#..#", "#..#", "####", "#..#", "#..#"],
    'B': ["###.", "#..#", "###.", "#..#", "#..#", "###."],
    'C': [".###", "#...", "#...", "#...", "#...", ".###"],
    'D': ["###.", "#..#", "#..#", "#..#", "#..#", "###."],
    'E': ["####", "#...", "###.", "#...", "#...", "####"],
    'F': ["####", "#...", "###.", "#...", "#...", "#..."],
    'G': [".###", "#...", "#.##", "#..#", "#..#", ".###"],
    'H': ["#..#", "#..#", "####", "#..#", "#..#", "#..#"],
    'I': ["###.", ".#..", ".#..", ".#..", ".#..", "###."],
    'J': ["..##", "...#", "...#", "...#", "#..#", ".##."],
    'K': ["#..#", "#.#.", "##..", "##..", "#.#.", "#..#"],
    'L': ["#...", "#...", "#...", "#...", "#...", "####"],
    'M': ["#..#", "####", "####", "#..#", "#..#", "#..#"],
    'N': ["#..#", "##.#", "##.#", "#.##", "#.##", "#..#"],
    'O': [".##.", "#..#", "#..#", "#..#", "#..#", ".##."],
    'P': ["###.", "#..#", "#..#", "###.", "#...", "#..."],
    'Q': [".##.", "#..#", "#..#", "#..#", "#.#.", ".#.#"],
    'R': ["###.", "#..#", "#..#", "###.", "#.#.", "#..#"],
    'S': [".###", "#...", ".##.", "...#", "...#", "###."],
    'T': ["####", ".#..", ".#..", ".#..", ".#..", ".#.."],
    'U': ["#..#", "#..#", "#..#", "#..#", "#..#", ".##."],
    'V': ["#..#", "#..#", "#..#", "#..#", ".##.", ".##."],
    'W': ["#..#", "#..#", "#..#", "####", "####", "#..#"],
    'X': ["#..#", "#..#", ".##.", ".##.", "#..#", "#..#"],
    'Y': ["#..#", "#..#", ".##.", ".#..", ".#..", ".#.."],
    'Z': ["####", "...#", "..#.", ".#..", "#...", "####"],
    '0': [".##.", "#..#", "#.##", "##.#", "#..#", ".##."],
    '1': ["..#.", ".##.", "..#.", "..#.", "..#.", ".###"],
    '2': [".##.", "#..#", "...#", "..#.", ".#..", "####"],
    '3': ["###.", "...#", ".##.", "...#", "...#", "###."],
    '4': ["#..#", "#..#", "####", "...#", "...#", "...#"],
    '5': ["####", "#...", "###.", "...#", "...#", "###."],
    '6': [".###", "#...", "###.", "#..#", "#..#", ".##."],
    '7': ["####", "...#", "..#.", "..#.", ".#..", ".#.."],
    '8': [".##.", "#..#", ".##.", "#..#", "#..#", ".##."],
    '9': [".##.", "#..#", "#..#", ".###", "...#", "###."],
    '-': ["....", "....", "####", "....", "....", "...."],
    '.': ["....", "....", "....", "....", "....", ".#.."],
}
CHARSET = "".join(sorted(GLYPHS))


# ------------------------------------------------------------- palette ----
#  Four pens, and none of them is new: the menu borrows what the HUD and
#  the walls already spend, so the title screen cannot push the palette
#  over sixteen.
P_TITLE = pal.HUD_TEXT              # 15, bright white  -- the name
P_KEY = pal.HUD_FRAME               # 6,  bright cyan   -- the key names
P_TEXT = 1                          # 1,  pastel blue   -- what they do
P_GO = 7                            # 7,  bright yellow -- press space
P_FOOT = 14                         # 14, white/grey    -- the credit
#  THE FIRST SET WAS UNREADABLE and it is worth saying why, because the
#  palette's names do not warn you: pal.CEIL_NEAR is pen 11 and pen 11 is
#  firmware ink 1, which is the DARK blue the ceiling is -- correct for a
#  ceiling that has to recede, wrong for a line of text on black.  Same
#  for pen 4.  Text wants luminance against the background, so these are
#  chosen by ink and not by the role the name suggests.
PENS = [P_TITLE, P_KEY, P_TEXT, P_GO, P_FOOT]
BG = 0                              # black


def nib_bytes(nib, pen):
    """-> the two mode-0 bytes for four pixels, ink where the bit is set.

    Built by asking cpchw for the SOLID byte of the pen and of the
    background and taking each pixel's bits from whichever the bit
    selects -- so the scrambled mode-0 layout is answered once, here,
    from the same table the rest of the engine uses.
    """
    ink, bg = cpc.MODE0_SOLID[pen], cpc.MODE0_SOLID[BG]
    out = []
    for half in range(2):                       # two pixels a byte
        b = 0
        for px in range(2):
            on = nib & (8 >> (half * 2 + px))
            src = ink if on else bg
            # pixel 0 of a byte is bits 7,5,3,1; pixel 1 is 6,4,2,0
            for bit in (7 - px, 5 - px, 3 - px, 1 - px):
                b |= src & (1 << bit)
        out.append(b)
    return out


# ---------------------------------------------------------------- words ----
#  (row, pen, column, text).  Row is in units of LINE scanlines; column
#  is in screen BYTES, or None to centre.
#
#  KEY_COL AND USE_COL ARE DERIVED, not typed: the second column has to
#  clear the widest key name, and picking 13 by eye put MOVE AND TURN
#  through the middle of ARROWS.  build() asserts the two never overlap
#  for any line, so a longer key name moves the column instead of
#  colliding with it.
KEY_COL = 3
KEY_MAX = 9                         # 'CTRL OR Z', the longest of them
USE_COL = KEY_COL + (KEY_MAX + 1) * PITCH

MENU = [
    (2,  P_TITLE, None, "A M A Z E"),
    (6,  P_KEY,   KEY_COL,    "ARROWS"),
    (6,  P_TEXT,  USE_COL,   "MOVE AND TURN"),
    (8,  P_KEY,   3,    "SHIFT"),
    (8,  P_TEXT,  USE_COL,   "RUN"),
    (10, P_KEY,   KEY_COL,    "SPACE"),
    (10, P_TEXT,  USE_COL,   "OPEN A DOOR"),
    (12, P_KEY,   KEY_COL,    "CTRL OR Z"),
    (12, P_TEXT,  USE_COL,   "FIRE"),
    (14, P_KEY,   KEY_COL,    "ESC"),
    (14, P_TEXT,  USE_COL,   "QUIT"),
    (18, P_GO,    None, "PRESS SPACE TO START"),
    (23, P_FOOT,  None, "REVIVE8BIT - 2026 - VASPER"),
]


def place(col, text):
    """-> the byte column a line starts at, centring when col is None."""
    w = len(text) * PITCH
    assert w <= SCR_W, f"{text!r} is {w} bytes, wider than the screen"
    return (SCR_W - w) // 2 if col is None else col


def build():
    for _row, _pen, col, text in MENU:
        for ch in text:
            assert ch in GLYPHS, f"no glyph for {ch!r} in {text!r}"
        assert place(col, text) + len(text) * PITCH <= SCR_W, text
    # THE TWO COLUMNS MUST NOT MEET.  A key name that outgrows KEY_MAX
    # would otherwise be overprinted by its own description, which is
    # what 'ARROWS' and 'MOVE AND TURN' did when the column was a number
    # somebody picked by looking at the screen.
    for _row, pen, col, text in MENU:
        if pen == P_KEY:
            assert col == KEY_COL, f"{text!r} is not in the key column"
            assert len(text) <= KEY_MAX, (
                f"{text!r} is {len(text)} characters, past KEY_MAX "
                f"{KEY_MAX} -- widen USE_COL with it")
            assert col + len(text) * PITCH <= USE_COL, text
        elif pen == P_TEXT:
            # ...AND THE DESCRIPTIONS MUST ALL BE IN THE SAME ONE.  One
            # of them was left at the old hand-picked 13 when the rest
            # moved to USE_COL, and nothing noticed until the screenshot:
            # RUN sat halfway through SHIFT.
            assert col == USE_COL, (
                f"{text!r} starts at {col}, not USE_COL {USE_COL}")
    return MENU


def unused():
    """-> the glyphs this screen does not draw.

    REPORTED, NOT ASSERTED.  The first version made it an error, on the
    house rule that a table nothing reads is dead weight -- and that rule
    is wrong for a FONT.  The alphabet is the asset; the menu is one
    consumer of it, and the next one (a score, a level name) will want
    the letters this one happens not to spell with.  238 bytes buys the
    whole of it.
    """
    return [c for c in CHARSET
            if c != ' ' and not any(c in t for _r, _p, _c, t in MENU)]


def write_inc(path):
    build()
    L = ["; Generated by engine2/tools/genmenu.py -- do not edit.",
         "; The title screen: a 4x6 font, one nibble-to-screen table per",
         "; pen, and the words.  See that file for why the glyphs are four",
         "; pixels wide and the pitch three bytes.",
         "",
         f"MN_GH        equ {GH}   ; glyph rows",
         f"MN_PITCH     equ {PITCH}   ; screen bytes from one glyph to the next",
         f"MN_LINE      equ {LINE}   ; scanlines from one row of text to the next",
         f"MN_NPEN      equ {len(PENS)}   ; nibble tables, one a pen",
         ""]

    L.append("; ---- nibble -> two screen bytes, one table per pen ----")
    L.append("MNPENS                      ; dw, indexed by the pen slot")
    for i, _p in enumerate(PENS):
        L.append(f"    dw MNP{i}")
    for i, p in enumerate(PENS):
        L.append(f"MNP{i}                        ; pen {p}")
        for n in range(16):
            b0, b1 = nib_bytes(n, p)
            L.append(f"    db #{b0:02X},#{b1:02X}")

    L.append("")
    L.append("; ---- the glyphs, MN_GH bytes each, one nibble a row ----")
    L.append(f"; charset: {CHARSET!r}")
    L.append("MNFONT")
    for ch in CHARSET:
        rows = GLYPHS[ch]
        assert len(rows) == GH and all(len(r) == GW for r in rows), ch
        bits = ",".join("#%02X" % sum((8 >> i) for i, c in enumerate(r)
                                      if c == '#') for r in rows)
        L.append(f"    db {bits}   ; {ch!r}")

    L.append("")
    L.append("; ---- the words: db y, x, pen slot, length, then the glyph")
    L.append(";      indices.  A length of 0 ends the list.")
    L.append("MNTEXT")
    for row, pen, col, text in MENU:
        x = place(col, text)
        idx = ",".join(str(CHARSET.index(c)) for c in text)
        L.append(f"    db {row * LINE:3d},{x:3d},{PENS.index(pen)},{len(text):3d}"
                 f"   ; {text!r}")
        L.append(f"    db {idx}")
    L.append("    db 0,0,0,0")
    open(path, "w").write("\n".join(L) + "\n")


def main():
    out = os.path.join(_E2, "src", "gen_menu.inc")
    write_inc(out)
    n = sum(len(t) for _r, _p, _c, t in MENU)
    print(f"menu: {len(MENU)} lines, {n} characters, {len(CHARSET)} glyphs, "
          f"{len(PENS)} pens")
    print(f"  font {GW}x{GH} px, pitch {PITCH} bytes = "
          f"{SCR_W // PITCH} characters a line")
    u = unused()
    if u:
        print(f"  glyphs this screen does not spell with: {''.join(u)}")
    for _row, _pen, col, text in MENU:
        print(f"  x={place(col, text):3d}  {text!r}")
    print("wrote", out)


if __name__ == "__main__":
    main()
