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

#  ---- THE SCREEN AFTER THE LAST HIT POINT ---------------------------
#  A SECOND WORD LIST, NOT A SECOND SCREEN ROUTINE.  menu.asm's blitter
#  walks a list of (row, x, pen, len, indices...) records terminated by a
#  zero length; which list it walks is one `ld ix`.  So a death screen
#  costs a second list here, four bytes of terminator, and three
#  instructions there -- against a copy of the blitter.
#
#  IT DOES NOT SAY "GAME OVER", because it is not: SPACE restarts, and
#  the line has to say so.  Same P_GO pen as the title's, so the eye
#  looks in the same place for the same instruction.
DEAD = [
    (7,  P_TITLE, None, "YOU ARE DEAD"),
    (11, P_TEXT,  None, "THE MONSTER GOT YOU"),
    (14, P_TEXT,  None, "SCORE @"),
    (17, P_GO,    None, "PRESS SPACE TO TRY AGAIN"),
    (23, P_FOOT,  None, "REVIVE8BIT - 2026 - VASPER"),
]

#  ---- AND THE ONE FOR REACHING THE EXIT -----------------------------
WIN = [
    (7,  P_TITLE, None, "YOU ESCAPED"),
    (11, P_TEXT,  None, "SCORE @"),
    (17, P_GO,    None, "PRESS SPACE TO PLAY AGAIN"),
]

SCREENS = [("TEXT", MENU), ("DEAD", DEAD), ("WIN", WIN)]

#  ---- THE SCORE DIGIT -----------------------------------------------
#  '@' IS NOT A GLYPH, it is a hole in the string.  A character the font
#  cannot spell is emitted as index MN_GSCORE and menu.asm's mn_char
#  substitutes (scr_g) -- a GLYPH INDEX the game keeps, not a number --
#  when it reads that value.  So the score's row, column and pen are
#  chosen here with the rest of the layout and cost the Z80 two
#  instructions.
#
#  IT COSTS NO FONT.  MN_GSCORE is 255, one past every real index, so it
#  needs no blank glyph and shifts no index.  The substitution happens
#  BEFORE mn_glyph is called, so nothing ever looks 255 up.
SCORE_CH = '@'
MN_GSCORE = 255


def place(col, text):
    """-> the byte column a line starts at, centring when col is None."""
    w = len(text) * PITCH
    assert w <= SCR_W, f"{text!r} is {w} bytes, wider than the screen"
    return (SCR_W - w) // 2 if col is None else col


def build():
    # EVERY SCREEN, not just the title.  The death screen brought the
    # first new letters this font had been asked for since it was
    # written, and a missing glyph is a KeyError three functions away in
    # blob(); here it names the character and the line it is in.
    for _name, lines in SCREENS:
        for _row, _pen, col, text in lines:
            for ch in text:
                assert ch in GLYPHS or ch == SCORE_CH, \
                    f"no glyph for {ch!r} in {text!r}"
            assert place(col, text) + len(text) * PITCH <= SCR_W, text
    # THE TITLE MUST NOT CARRY A SCORE.  It is painted before the first
    # game_init, so (scr_g) is whatever the last life left there.
    assert not any(SCORE_CH in t for _r, _p, _c, t in MENU), \
        "the title screen has a score marker in it"
    # THE TWO COLUMNS MUST NOT MEET.  A key name that outgrows KEY_MAX
    # would otherwise be overprinted by its own description, which is
    # what 'ARROWS' and 'MOVE AND TURN' did when the column was a number
    # somebody picked by looking at the screen.
    # ...AND THIS ONE IS THE TITLE SCREEN'S ALONE.  KEY_COL and USE_COL
    # are the two-column layout of the key list; the death screen is
    # centred lines and has no columns to collide.
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
    spelt = set("".join(t for _n, ls in SCREENS for _r, _p, _c, t in ls))
    spelt |= set("0123456789")       # the score digit spells with all of them
    return [c for c in CHARSET if c != ' ' and c not in spelt]


def blob():
    """-> (bytes, offsets) -- the whole payload as one flat block.

    IT LIVES IN RAM BANK 5 ON THE DISC, next to the march's per-heading
    table, and for the same reason: 578 bytes of font, colour tables and
    words, read ONCE at startup, in a code segment whose ceiling assert
    has fired thirteen times.  gentex.py appends it; menu.asm copies it
    down to free RAM and reads it from there.

    So the file emits OFFSETS rather than addresses -- menu.asm adds the
    base it copied to -- which is what lets the same bytes sit in a bank
    the assembler cannot name.
    """
    off = {}
    out = bytearray()

    off["PENS"] = len(out)              # 16 nibbles x 2 bytes, per pen
    for p in PENS:
        for n in range(16):
            out += bytes(nib_bytes(n, p))

    off["FONT"] = len(out)              # GH bytes a glyph, one nibble a row
    for ch in CHARSET:
        rows = GLYPHS[ch]
        assert len(rows) == GH and all(len(r) == GW for r in rows), ch
        for r in rows:
            out.append(sum((8 >> i) for i, c in enumerate(r) if c == '#'))

    for name, lines in SCREENS:         # y, x, pen, len, then the indices
        off[name] = len(out)
        for row, pen, col, text in lines:
            out += bytes((row * LINE, place(col, text), PENS.index(pen),
                          len(text)))
            out += bytes(MN_GSCORE if c == SCORE_CH else CHARSET.index(c)
                         for c in text)
        out += bytes(4)                 # a length of 0 ends the list

    return bytes(out), off


def write_inc(path):
    build()
    data, off = blob()
    L = ["; Generated by engine2/tools/genmenu.py -- do not edit.",
         "; The title screen's font, colours and words live in RAM BANK 5",
         "; (gentex.py puts them there); menu.asm copies them down to free",
         "; RAM at startup.  So this file is OFFSETS into that block, not",
         "; addresses -- see genmenu.blob().",
         "",
         f"MN_GH        equ {GH}   ; glyph rows",
         f"MN_PITCH     equ {PITCH}   ; screen bytes from one glyph to the next",
         f"MN_LINE      equ {LINE}   ; scanlines from one row of text to the next",
         f"MN_NPEN      equ {len(PENS)}   ; nibble tables, one a pen",
         f"MN_BLOB      equ {len(data)}   ; bytes to copy down",
         "",
         f"MN_O_PENS    equ {off['PENS']}   ; ...and where each part starts",
         f"MN_O_FONT    equ {off['FONT']}",
         f"MN_O_TEXT    equ {off['TEXT']}",
         f"MN_O_DEAD    equ {off['DEAD']}",
         f"MN_O_WIN     equ {off['WIN']}",
         "",
         f"MN_GSCORE    equ {MN_GSCORE}   ; mn_char swaps this for (scr_g)",
         f"MN_G0        equ {CHARSET.index('0')}   ; ...and 0 is this glyph",
         ""]
    open(path, "w").write("\n".join(L) + "\n")


def main():
    out = os.path.join(_E2, "src", "gen_menu.inc")
    write_inc(out)
    n = sum(len(t) for _n, ls in SCREENS for _r, _p, _c, t in ls)
    print(f"menu: {sum(len(ls) for _n, ls in SCREENS)} lines over "
          f"{len(SCREENS)} screens, {n} characters, {len(CHARSET)} glyphs, "
          f"{len(PENS)} pens")
    print(f"  font {GW}x{GH} px, pitch {PITCH} bytes = "
          f"{SCR_W // PITCH} characters a line")
    u = unused()
    if u:
        print(f"  glyphs this screen does not spell with: {''.join(u)}")
    for name, lines in SCREENS:
        print(f"  {name}:")
        for _row, _pen, col, text in lines:
            print(f"    x={place(col, text):3d}  {text!r}")
    print("wrote", out)


if __name__ == "__main__":
    main()
