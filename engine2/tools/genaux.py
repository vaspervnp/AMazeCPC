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
import world                                                    # noqa: E402
import marchmodel                                               # noqa: E402
import gen_march                                                # noqa: E402

BANK_BASE = 0x4000
LVREC = 128             # bytes a level; a power of two so the index
                        # is a shift.  See build().
MAXAMMO = 8             # cells a level's record has room for
MAXMON = 4
BANK_SIZE = 16384
RAMCFG = 0xC6                   # OUT (&7Fxx),&C6 -> bank 6 over &4000


def packed_maze():
    """-> the 64 packed maze bytes, THE ONE PLACE THEY ARE PARSED.

    gen_march.py writes them into gen_maze.inc as a COMMENT now, because
    the bytes themselves live in bank 6 and an .inc that also emitted
    them would put 64 bytes back in the code segment.  Three tools read
    them -- this one, monmodel.py and emu_room.py -- and three parsers
    of a commented-out table is three chances to disagree about the map.

    IT IS LEVEL 0's MAP, and only that: gen_maze.inc describes one map.
    build() packs every level straight out of world.py and then asserts
    that level 0's record matches what this returns, so the two readings
    cannot drift apart in silence.
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


def _maxdoors():
    """MAXDOORS out of game.asm -- read, not copied, so it cannot drift."""
    for ln in open(os.path.join(_E2, "src", "game.asm")):
        if ln.startswith("MAXDOORS"):
            return int(ln.split()[2])
    raise KeyError("MAXDOORS not in game.asm")


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
    # ---- THE LEVELS ------------------------------------------------
    #  One FIXED-SIZE record each, so main3.asm's level_load finds the
    #  nth by a shift and not a multiply: LVREC is 128, and A*128 is
    #  `ld h,a / ld l,0 / srl h / rr l`.
    #
    #  A LEVEL IS NOT JUST A GRID.  Where you start, which way you face,
    #  where the pickups are, where the monsters stand and where the way
    #  out is are all part of it, and all of it is checked against the
    #  grid by tools/world.py before it gets here.
    #
    #      +0    64  the maze, two bits a cell
    #      +64    3  start x, start y, start heading
    #      +67    1  the exit cell, y*16+x, or #FF for none
    #      +68    1  pickups, then MAXAMMO cells
    #      +77    1  monsters, then MAXMON cells
    at["LEVELS"] = BANK_BASE + len(blob)
    at["NLEVEL"] = len(world.LEVELS)
    for n in range(len(world.LEVELS)):
        rec = bytearray(LVREC)
        world.select_level(n)
        grid, sx, sy = world.load_maze()
        solid = marchmodel.solid_from_grid(grid)
        for i in range(64):
            b = 0
            for k in range(4):
                b |= solid[i * 4 + k] << (2 * k)
            rec[i] = b
        ex = world.exit_cell(grid, sx, sy)
        rec[64], rec[65] = sx, sy
        mo0 = world.monster_cells(grid, sx, sy)
        rec[66] = gen_march.start_heading(sx, sy, mo0[0] if mo0 else None)
        rec[67] = 0xFF if ex is None else ex[1] * 16 + ex[0]
        am = world.ammo_cells(grid, sx, sy)
        assert len(am) <= MAXAMMO, f"level {n}: {len(am)} pickups > {MAXAMMO}"
        rec[68] = len(am)
        for i, (x, y) in enumerate(am):
            rec[69 + i] = y * 16 + x
        # THE DOOR LIST IS A PER-LEVEL LIMIT TOO, and for the same
        # reason: main3.asm asserts MAXDOORS >= NDOORS off gen_march's
        # count of level 0's doors.  game_init registers doors until it
        # has MAXDOORS of them and then SILENTLY SKIPS THE REST, so a
        # map with more would ship with doors that never open.
        ndoor = sum(1 for row in grid for c in row if c == world.DOOR)
        assert ndoor <= _maxdoors(), (
            f"level {n}: {ndoor} doors > MAXDOORS {_maxdoors()} -- "
            "game_init would register the first few and drop the rest")
        # THE SCORE IS ONE GLYPH, AND IT IS A PER-LEVEL LIMIT NOW.
        # main3.asm asserts `NAMMO + 1 <= 9` off gen_maze.inc, which
        # describes level 0 and nothing else -- so a second map with
        # nine pickups would have rolled the score display past '9'
        # with the build still green.  menu.asm draws scr_g as MN_G0 + n.
        assert len(am) + 1 <= 9, (
            f"level {n}: {len(am)} pickups + 1 monster is {len(am)+1} "
            "points and the score is drawn as a single digit")
        mo = mo0
        assert len(mo) <= MAXMON, f"level {n}: {len(mo)} monsters > {MAXMON}"
        rec[77] = len(mo)
        for i, (x, y) in enumerate(mo):
            rec[78 + i] = y * 16 + x
        blob += bytes(rec)
    world.select_level(0)
    # ...AND THE TWO READINGS OF LEVEL 0 MUST AGREE.  packed_maze() parses
    # the bytes gen_march.py commented into gen_maze.inc; the loop above
    # packs them again out of world.py.  Both are still wanted -- three
    # tools read the .inc -- but two readings of one map that nobody
    # compares is how they drift, so compare them.
    lv0 = blob[at["LEVELS"] - BANK_BASE:at["LEVELS"] - BANK_BASE + 64]
    assert list(lv0) == packed_maze(), (
        "level 0's packed maze differs between world.py and the bytes "
        "gen_march.py wrote into gen_maze.inc -- one generator is stale")
    at["MAZEDATA"] = at["LEVELS"]       # level 0's maze IS the first record

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
MAZEDATA    equ #{maze:04X}          ; level 0's maze -- the first record
LEVELS      equ #{levels:04X}          ; {nlevel} x LVREC, see genaux.py
NLEVEL      equ {nlevel}
LVREC       equ {lvrec}             ; bytes a level, a power of two
; LVO_, not LV_.  rasm's labels are CASE-INSENSITIVE, so an offset
; called LV_EXIT and game.asm's byte called lv_exit are one symbol and
; the build stops with "Alias cannot override existing label" -- which
; is the good outcome; the same collision has been walked into with
; mon_hp/MON_HP and plr_hp/PLR_HPMAX.
LVO_START   equ 64              ; ...and the offsets inside one
LVO_EXIT    equ 67
LVO_NAMMO   equ 68
LVO_NMON    equ 77
MAXAMMO_LV  equ {maxammo}
MAXMON_LV   equ {maxmon}
AUXEND      equ #{auxend:04X}
"""


# ---------------------------------------------------------------------
#  READING A RECORD BACK, for the harnesses.
#
#  emu_verify3.py used to read the pickup cells out of the code segment
#  at AMMOTAB, which level_load deleted: the cells are per-level now and
#  they live in RAM bank 6, where nothing in this directory can page
#  them in.  So the harness asks the generator, and the layout stays
#  known in exactly one place -- the same rule packed_maze() follows.
#
#  It reads build/AUX.BIN and not world.py on purpose: what the game
#  loaded is what is on the disc, so a generator that stopped matching
#  its own output is a test failure and not an invisible agreement.
# ---------------------------------------------------------------------
def read_level(n, blob=None):
    """-> dict(maze, start, heading, exit, ammo, mon) for level n."""
    if blob is None:
        blob = open(os.path.join(_E2, "build", "AUX.BIN"), "rb").read()
    base = _levels_addr() - BANK_BASE + n * LVREC
    r = blob[base:base + LVREC]
    if len(r) != LVREC:
        raise IndexError(f"level {n} is not in AUX.BIN ({len(blob)} bytes)")
    return dict(maze=r[:64], start=(r[64], r[65]), heading=r[66],
                exit=r[67], ammo=list(r[69:69 + r[68]]),
                mon=list(r[78:78 + r[77]]))


def _levels_addr():
    """LEVELS out of the generated .inc -- the address the game uses."""
    for ln in open(os.path.join(_E2, "src", "gen_aux.inc")):
        if ln.startswith("LEVELS "):
            return int(ln.split()[2].lstrip("#"), 16)
    raise KeyError("LEVELS not in gen_aux.inc")


def nlevel():
    for ln in open(os.path.join(_E2, "src", "gen_aux.inc")):
        if ln.startswith("NLEVEL "):
            return int(ln.split()[2])
    raise KeyError("NLEVEL not in gen_aux.inc")


def main():
    blob, at = build()
    out = os.path.join(_E2, "build")
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "AUX.BIN"), "wb").write(blob)
    open(os.path.join(_E2, "src", "gen_aux.inc"), "w").write(INC.format(
        ramcfg=RAMCFG, hudrects=at["HUDRECTS"], nrect=at["HUD_NRECT"],
        hudndl=at["HUDNDL"], ndot=at["HUD_NDOT"], maze=at["MAZEDATA"],
        levels=at["LEVELS"], nlevel=at["NLEVEL"], lvrec=LVREC,
        maxammo=MAXAMMO, maxmon=MAXMON, auxend=at["AUXEND"]))
    print(f"bank 6: {len(blob)} of {BANK_SIZE} bytes, "
          f"{BANK_SIZE - len(blob)} free")
    print(f"  HUDRECTS  #{at['HUDRECTS']:04X}  {at['HUD_NRECT']} rectangles, "
          f"{at['HUD_NRECT'] * 5} bytes taken out of the code segment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
