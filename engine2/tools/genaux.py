"""engine2/tools/genaux.py -- RAM BANK 6, and why there is a third one.

    python3 engine2/tools/genaux.py
        -> engine2/build/AUX.BIN  and  engine2/src/gen_aux.inc

THE CODE SEGMENT RAN OUT.  `assert game_end <= BUCK0` in main3.asm has
fired fourteen times and the last of them left **22 bytes** between the
end of the program and the march's first face bucket.  Every previous
answer moved the working RAM up a page, shrank NQUAD, or made a routine
conditional; there is nothing of that kind left, and the next feature is
a minimap, two sprites and a second monster.

So: banks 6 and 7 have been sitting there empty since the beginning.
The 6128 has four 16K banks in its extra 64K and this build was using
two of them -- bank 4 for the precalculated tables and bank 5 for the
wall textures -- with 180 and 51 bytes free respectively, which is why
neither could take any of this.  Bank 6 is 16384 bytes, all of them
free, and it costs one LOAD in amaze.bas.

WHAT BELONGS HERE, and it is a rule and not a list: read-only data that
is NOT read inside the frame.  Paging bank 6 in means paging bank 4 OUT,
and bank 4 holds LINETAB, HTAB and the palette -- so anything on the
frame path would have to page twice around every read.  Startup data and
data read once when the world is rebuilt are free of that.

    HUDRECTS   the HUD's static furniture, 71 rectangles of five bytes.
               hud2.asm paints it into each buffer at startup and again
               on new_game, and never touches it in between.  355 bytes
               out of the body, which is sixteen times what was left.

Same shape as engine2/tools/gentex.py, which put the title screen's font
and words in bank 5 for exactly this reason -- read the note there.
"""

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_E2)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import genhud                                                   # noqa: E402

BANK_BASE = 0x4000
BANK_SIZE = 16384
RAMCFG = 0xC6                   # OUT (&7Fxx),&C6 -> bank 6 over &4000


def packed_maze():
    """-> the 64 packed maze bytes, THE ONE PLACE THEY ARE PARSED.

    gen_march.py writes them into gen_maze.inc as a COMMENT now, because
    the bytes themselves live in bank 6 and an .inc that also emitted
    them would put 64 bytes back in the code segment.  Three tools read
    them -- this one, monmodel.py and emu_room.py -- and three parsers
    of a commented-out table is three chances to disagree about the map.
    """
    src = open(os.path.join(_E2, "src", "gen_maze.inc")).read()
    body = src[src.index("; The bytes, for reading"):src.index("NAMMO")]
    out = []
    for line in body.splitlines():
        m = re.match(r";\s+(#[0-9A-Fa-f,#]+)", line)
        if m:
            out += [int(t.strip().lstrip("#"), 16) for t in m.group(1).split(",")]
    assert len(out) == 64, f"{len(out)} packed maze bytes, expected 64"
    return out


def build():
    """-> (blob, addresses).  Everything is placed here, in one place, so
    the .inc cannot disagree with the .BIN about where anything is."""
    blob = bytearray()
    at = {}

    # ---- the HUD's static furniture ---------------------------------
    #  genhud.py owns the geometry and this file owns where it lives, the
    #  same split gentex.py and genmenu.py have.  Importing it rather
    #  than re-deriving it is what stops the two from drifting.
    rects, tab = genhud.build()
    at["HUDRECTS"] = BANK_BASE + len(blob)
    for (x, y, w, h, b) in rects.r:
        blob += bytes((x, y, w, h, b))
    at["HUD_NRECT"] = len(rects.r)

    # ---- the compass needle's 19 headings -------------------------
    #  152 bytes, and it IS read every frame -- which the rule above
    #  forbids, so it is read the way the rule allows: hud_needle pages
    #  bank 6 in, copies the EIGHT bytes for the heading it is drawing
    #  into scratch, and pages bank 4 back before it touches LINETAB.
    #  Two OUTs and an eight-byte copy against a hud_update that is
    #  already 1423 us, and it buys 152 bytes of a code segment that had
    #  none.
    at["HUDNDL"] = BANK_BASE + len(blob)
    for a in range(19):
        for (dx, dy) in tab[a * genhud.HUD_NDOT:(a + 1) * genhud.HUD_NDOT]:
            blob += bytes((dx & 0xFF, dy & 0xFF))
    at["HUD_NDOT"] = genhud.HUD_NDOT

    # ---- the packed maze ------------------------------------------
    #  64 bytes, two bits a cell, read ONCE by march.asm's maze_unpack
    #  when new_game rebuilds the world -- which is the rule at the top
    #  of this file, exactly.  maze_unpack writes SOLID at #3A00, below
    #  the paging window, and reads nothing out of bank 4, so it can run
    #  with bank 6 in and put bank 4 back when it is done.
    at["MAZEDATA"] = BANK_BASE + len(blob)
    blob += bytes(packed_maze())

    assert len(blob) <= BANK_SIZE, (
        f"bank 6 overflows: {len(blob)} > {BANK_SIZE}")
    at["AUXEND"] = BANK_BASE + len(blob)
    return bytes(blob), at


INC = """; ---------------------------------------------------------------------
;  gen_aux.inc -- GENERATED by engine2/tools/genaux.py.  Do not edit.
;
;  RAM bank 6.  Paged over &4000-&7FFF for as long as it takes to read
;  something out of it and then bank 4 goes straight back, because bank 4
;  is where LINETAB is and everything that draws needs LINETAB.  Nothing
;  on the frame path may live here -- see genaux.py for the rule.
; ---------------------------------------------------------------------
AUXCFG      equ #{ramcfg:02X}              ; OUT (&7Fxx),this pages bank 6
HUDRECTS    equ #{hudrects:04X}          ; {nrect} x (db x, y, w, h, byte)
HUD_NRECT   equ {nrect}              ; ...and how many
HUDNDL      equ #{hudndl:04X}          ; the needle: 19 headings x {ndot} x (dx, dy)
MAZEDATA    equ #{maze:04X}          ; 16x16 cells, two bits each
AUXEND      equ #{auxend:04X}
"""


def main():
    blob, at = build()
    out = os.path.join(_E2, "build")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "AUX.BIN"), "wb").write(blob)
    open(os.path.join(_E2, "src", "gen_aux.inc"), "w").write(INC.format(
        ramcfg=RAMCFG, hudrects=at["HUDRECTS"], nrect=at["HUD_NRECT"],
        hudndl=at["HUDNDL"], ndot=at["HUD_NDOT"], maze=at["MAZEDATA"],
        auxend=at["AUXEND"]))
    print(f"bank 6: {len(blob)} of {BANK_SIZE} bytes, "
          f"{BANK_SIZE - len(blob)} free")
    print(f"  HUDRECTS  #{at['HUDRECTS']:04X}  {at['HUD_NRECT']} rectangles, "
          f"{at['HUD_NRECT'] * 5} bytes taken out of the code segment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
