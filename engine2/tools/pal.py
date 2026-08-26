"""engine2's Mode 0 palette -- 16 pens, and the depth ramps the rasteriser
indexes with the quad's own (kind, k) bytes.

    k    ink                 RGB              luma
    1-7  11 sky blue      (  0,128,255)        104

THERE IS NO RAMP.  A WALL IS ONE COLOUR AT EVERY DEPTH.  This went through
three shapes before landing here and the history is the argument:

    six steps that changed HUE  -- bright white, pastel cyan, bright cyan,
        pastel blue, sky blue, bright blue.  It read as six different
        MATERIALS at six different distances, not as one wall receding.
    three steps of one blue     -- ink 14, ink 11, ink 2.  Better, and
        still wrong: a face two cells away was visibly a different blue
        from the one beside it, which is a shading convention, not a wall.
    (a fourth step at ink 5, violet blue, was tried and thrown out: by
        luminance it slots perfectly between 104 and 29, and it is MAGENTA.
        Spacing a ramp by luma is what produced the rainbow in the first
        place.)
    one colour                  -- what is here now.

WHAT CARRIES DEPTH INSTEAD.  Projected height, the horizon, occlusion
order, and above all THE COURSE JOINTS: they converge toward the vanishing
point, and a near wall shows them further apart than a far one.  That is a
real perspective cue rather than a painted-on one, and it is the reason
COURSES is worth its cost now in a way it was not when the ramp was doing
the work.  See vpcfg.inc's COURSES and raster.asm:raster_joint.

Ink 11 is the pick because it is the machine's most saturated mid blue: it
clears both ceiling bands with room to spare (luma 104 against 15 and 0),
so a wall can still never merge into the ceiling, and it leaves ink 14 and
ink 2 free as a LIT and a SHADED edge if faces ever need separating.

The doors keep a WARM ramp (bright yellow, orange, bright red, red).  They
are the one thing that still shades with depth, and deliberately: a door is
a landmark, not a surface, and against a flat blue wall it now separates by
hue as well as by brightness.

AND COLLAPSING THE RAMP FREED FIVE PENS.  Pen 4 is the MORTAR (see below),
which is what the course joints had been missing since the weapon took
their old pen; pen 6 takes the HUD frame off the wall ramp entirely; pens
1, 3 and 5 are spare.

Floor is warm-dark olive so it cannot be confused with a wall, and the
surface detail the flat colour gave up is bought back by GRAIN (vertical,
free) and the course joints (horizontal, and the only thing here that
actually foreshortens).
"""

import cpchw as cpc

# pen -> firmware ink
PEN_INK = [
    0,      # 0  black          -- the void, and the weapon's outline
    14,     # 1  pastel blue    -- SPARE (a lit stone edge, if wanted)
    11,     # 2  sky blue       -- THE WALL, at every depth
    2,      # 3  bright blue    -- SPARE (a shaded stone edge, if wanted)
    1,      # 4  blue (dark)    -- MORTAR, the course joints
    1,      # 5  blue (dark)    -- SPARE
    20,     # 6  bright cyan    -- HUD frame
    24,     # 7  bright yellow  -- door k=1
    15,     # 8  orange         -- door k=2
    6,      # 9  bright red     -- door k=3
    3,      # 10 red            -- door k>=4
    1,      # 11 blue           -- THE CEILING
    12,     # 12 yellow (olive) -- THE FLOOR
    9,      # 13 green          -- SPARE (was the floor's far half)
    13,     # 14 white (grey)   -- the weapon's slide
    26,     # 15 bright white   -- HUD text
]

# indexed by k-1, k = 1..7 (the quad's own depth byte)
WALL_RAMP = [2, 2, 2, 2, 2, 2, 2]       # one colour, every depth
DOOR_RAMP = [7, 8, 9, 10, 10, 10, 10]

# THE FLOOR AND CEILING ARE FLAT TOO, for the same reason the wall is.
# bg_fill paints the background as four bands -- ceiling far, ceiling near,
# floor far, floor near -- and the two halves of each used to be different
# inks, which is depth shading by another name: a horizontal seam ran across
# the middle of the floor and another across the ceiling, at a fixed height,
# not moving with anything in the world.  Pointing both halves at the same
# pen removes the seam and costs NOTHING: bg_fill still paints four bands,
# they are simply the same colour, so no code changes and no cycles move.
#
# Pen 0 stays BLACK and out of this: it is the ceiling-far pen but it is
# also the weapon's outline (pal.GUN_DARK), so the ceiling moves to pen 11
# at both ends rather than dragging the gun's silhouette with it.  Pen 13
# is freed the same way.
CEIL_NEAR, CEIL_FAR = 11, 11
FLOOR_FAR, FLOOR_NEAR = 12, 12
HUD_FRAME, HUD_TEXT = 6, 15
# THE AMMO PIPS, in the top-left readout slot.  Pen 8 is firmware ink 15,
# warm orange -- DOOR_RAMP's second step, so it is already on screen
# whenever a door is two cells away, and the readout borrows a pen the
# palette is spending rather than asking for a seventeenth.  It is also
# the only warm thing in a HUD that is otherwise cyan on navy, which is
# what makes six small blocks readable at all down there.
HUD_AMMO = 8

# THE SCANNER'S DISTANCE RAMP -- the one lit block on the direction pad,
# by how far away the pickup it points at is.  Bright yellow, orange, red:
# a real LUMINANCE ramp (inks 24, 15, 3) as well as a hue one, so it still
# reads as near/mid/far on a monitor that has lost its colour.  The middle
# step is HUD_AMMO itself, which ties the pad to the pips above it.
HUD_SCAN = [7, 8, 10]

# ---------------------------------------------------------------------
#  MORTAR -- the pen raster.asm:raster_joint paints the two course
#  boundaries of a wall face in.  It is a DEDICATED pen, not a step of
#  the wall ramp: the ramp runs grey -> bright blue and is more
#  SATURATED as it recedes, so joints drawn two steps down it glow
#  instead of receding.
#
#  IT HAD TO BE INK 1 OR INK 0.  The rule is that the mortar must be
#  darker than every wall ramp step at every depth, and the darkest step
#  is bright blue (ink 2, luma 29).  Of the 27 firmware inks only two are
#  under that: ink 0 black (luma 0) and ink 1 blue (0,0,128, luma 15).
#  Black is stark against a near wall -- at k = 1 a joint in ink 0 next
#  to bright white reads as a hole punched through the wall -- so the
#  choice is ink 1, dark blue.  pal.check() asserts the invariant.
#
#  WHERE THE PEN CAME FROM.  This used to be pen 14, then the weapon took
#  pen 14 for its slide and the joints were left with no colour they could
#  legally use -- a joint in the gun's grey is BRIGHTER than most of the
#  wall and reads as a highlight, not a gap.  Shortening the wall ramp from
#  six hue-changing steps to three blue ones freed pens 4, 5 and 6, and pen
#  4 is now the mortar, at ink 1, its own slot.
#
#  Ink 1 is also pen 11, the near half of the ceiling.  That duplication is
#  deliberate and harmless: the two never touch on a wall face, because the
#  joints sit at v = 1/3 and 2/3 and never at the top edge.  (It is NOT the
#  trap the shipped discs fell into -- there the duplicate was the DARKEST
#  WALL STEP against the ceiling, so a far wall dissolved into it.)
MORTAR = 4

# Is the mortar ever painted FULL HEIGHT?  It is not today -- the course
# joints are horizontal bands at v = 1/3 and 2/3 -- and while that is true
# the mortar may legally share firmware ink 1 with the ceiling.  Anything
# that draws a vertical mark in the mortar pen must set this, and check()
# will then demand the mortar get an ink of its own.
MORTAR_FULL_HEIGHT = False

# The weapon's four pens.  engine2/tools/gunart.py owns the ART; these are
# the palette slots it draws into, and gentab.py cross-checks them against
# gunart.PEN so the two files cannot drift.
GUN_DARK = 0        # outline and shadow  -- shares the ceiling-far pen
GUN_HAND = 8        # orange              -- shares the k=2 door step
GUN_SLIDE = 14      # white/grey          -- the pen freed above
GUN_HL = 15         # bright white        -- the highlight, = HUD_TEXT

# ---------------------------------------------------------------------
#  THE TWO WALL TEXTURES -- engine2/tools/walltex.py's four pens each,
#  placed in this palette.
#
#  NOT ONE NEW INK BETWEEN THEM, which is the whole reason the textures
#  could be dropped into a palette this full.  walltex asks for
#  WALL_INKS = [1, 2, 11, 14] and DOOR_INKS = [0, 13, 26, 15], and every
#  one of those eight is already here:
#
#      wall  mortar ink  1 -> pen  4   (was MORTAR; COURSES is 0, so dead)
#            shade  ink  2 -> pen  3   (was spare)
#            stone  ink 11 -> pen  2   (was THE WALL, the whole flat ramp)
#            lit    ink 14 -> pen  1   (was GRAIN, the flat wall's stripe)
#
#      door  frame  ink  0 -> pen  0   \
#            metal  ink 13 -> pen 14    |  the weapon's own four pens.  The
#            lit    ink 26 -> pen 15    |  door and the gun want the same
#            panel  ink 15 -> pen  8   /   black/grey/white/orange, so they
#                                          share, and the door costs none.
#
#  PEN_INK IS THEREFORE UNTOUCHED.  Nothing moves, so genhud.py's
#  `assert PANEL == 11 and MARK == 15`, gunart.py's hardcoded PEN dict and
#  every band pen keep meaning what they meant.  The textures are baked to
#  Mode 0 BYTES by colmodel.tex_pages, so the four indices do not have to
#  be contiguous and there is no reason to shuffle the palette to make
#  them so.
#
#  WHAT THE FLAT RAMPS BECOME.  RAMP / WRAMP / RAMPTAB are still built and
#  still shipped -- the span renderer is the fallback build -- so
#  WALL_RAMP and DOOR_RAMP have to keep pointing at a pen that clears
#  check()'s "brighter than the ceiling" rule.  They point at each
#  texture's own dominant pen: the stone and the metal.
WALL_TEX_PENS = [4, 3, 2, 1]        # mortar, shade, stone, lit
DOOR_TEX_PENS = [0, 14, 15, 8]      # frame, metal, lit, panel

KMAX = 7


def wall_pen(k, side=0, door=False):
    """Depth-shaded pen.  `side` darkens by one step (kept for the older
    RAMPTAB layout; engine2's quads do not carry a face normal)."""
    ramp = DOOR_RAMP if door else WALL_RAMP
    return ramp[max(0, min(len(ramp) - 1, (k - 1) + (1 if side else 0)))]


# ---------------------------------------------------------------------
#  THE GRAIN -- vertical structure on a wall, for three microseconds a face.
#
#  raster_quad fills a run with PUSH DE, and PUSH writes E at the LOWER
#  address and D at the higher: E is the LEFT screen byte.  Each byte is two
#  independent Mode 0 pens, so one push lays down four pixels -- and the
#  rasteriser was throwing three quarters of that away by copying one solid
#  byte into both halves (raster.asm: `ld a,(hl) / ld d,a / ld e,a`).
#
#  Make D and E DIFFERENT and every push lays a vertical line, pitch four
#  pixels, at ZERO microseconds per scanline.  The only cost is building the
#  word: a 16-entry byte table becomes a 16-entry WORD table and the load
#  goes from `ld a,(hl) / ld d,a / ld e,a` to `ld e,(hl) / inc hl /
#  ld d,(hl)`.  Measured against the frame budget that is +3 us per QUAD --
#  about 51 us on a seventeen-quad frame, against the +67 us PER QUAD of
#  margin C_QUAD carries (main3.asm).  Nothing per scanline changes, no
#  register moves, PUSHBLK is untouched and the largest atomic unit is
#  unchanged, which is what actually decides the frame period.
#
#  WHICH PEN, AND WHY NOT THE MORTAR.  The obvious choice is pen 4, the
#  mortar -- and it is wrong.  At a four-pixel pitch the grain covers a
#  quarter of the wall, and mortar against wall is a luminance step of 90
#  (14.6 against 104.2): twenty-two black bars across the viewport, a
#  prison fence rather than a surface.  Pen 1, the lit blue that collapsing
#  the ramp freed, is a step of 38 -- it reads as grain in the stone rather
#  than as gaps between stones.
#
#  THE PATTERN IS THE IMAGE'S OWN.  Reduced to the four pixels a single
#  PUSH can carry, the reference masonry's most common row by a wide margin
#  is `.+..` -- stone, lit edge, stone, stone -- at 35.9% of its rows, with
#  flat stone `....` next at 20.3%.  So that is the word: E carries the lit
#  pixel on its RIGHT, D is solid stone.  An earlier version put the mark on
#  E's LEFT, which is `+...` and only 9.4% of the source; it looked similar
#  and was not the picture.
#
#  AND CALL IT WHAT IT IS.  This is not masonry and it does not foreshorten:
#  the pitch is fixed in SCREEN space, so a stone would be 0.21 cells wide
#  at one cell and 1.5 at seven.  At four pixels there is no room for that
#  error to show, because the pitch is the byte grid the wall edges already
#  quantise to.  At eight or sixteen it shows badly -- the wall slides under
#  the stripes as you walk and whole lines are born mid-face -- which is why
#  the pitch stays at the one the fill word gives away for nothing.
#  SET GRAIN TO None FOR A FLAT WALL.  Everything else -- the word table,
#  the rasteriser's two-byte load, the model -- stays exactly as it is; the
#  entries simply come out byte-symmetric and the picture is what it was.
#  The three microseconds a quad are already spent either way, so this is a
#  pure look switch with no timing consequence at all.
GRAIN = 1               # pen 1, ink 14 pastel blue, luma 142 vs the wall 104


def wramp_table():
    """32 bytes: the 16 ramp_table() entries as WORDS, low byte first.

    Low byte = E = the LEFT screen byte, high byte = D = the right one.
    Walls carry the grain in their left pixel; doors stay solid, because a
    door is a landmark and wants to read as one flat slab of colour."""
    out = []
    for door in (0, 1):
        for k in range(0, 8):
            if k == 0:
                e = d = cpc.MODE0_SOLID[0]      # unreachable, k is never 0
            else:
                p = wall_pen(k, 0, door)
                d = cpc.MODE0_SOLID[p]
                e = d if (door or GRAIN is None) else cpc.mode0_byte(p, GRAIN)
            out += [e, d]
    return out


def ramp_table():
    """16 bytes, indexed EXACTLY as raster.asm indexes it:

        index = (kind << 3) | k,      kind 0 = wall / 1 = door,  k = 1..7

    so the rasteriser turns the quad's +12 and +13 bytes into a solid Mode 0
    byte with three shifts and an add.  Entries 0 and 8 are unreachable (k is
    never 0) and are filled with black."""
    out = []
    for door in (0, 1):
        out.append(cpc.MODE0_SOLID[0])
        for k in range(1, 8):
            out.append(cpc.MODE0_SOLID[wall_pen(k, 0, door)])
    return out


def mortar_byte():
    """The solid Mode 0 byte raster.asm:raster_joint pushes -- one byte,
    depth-independent, because the mortar is one pen at every k."""
    return cpc.MODE0_SOLID[MORTAR]


def palette_ga():
    """16 gate-array bytes, in pen order -- OUT (&7Fxx) fodder."""
    return [cpc.ink_ga(i) for i in PEN_INK]


def luma(ink):
    r, g, b = cpc.ink_rgb(ink)
    return 0.299 * r + 0.587 * g + 0.114 * b


def check(courses=False):
    """The invariants this palette exists to guarantee.

    `courses` is vpcfg.inc's COURSES.  The mortar invariant is only checked
    when the mortar is DRAWN; gentab.py passes the real flag.
    """
    bad = []
    ceil = max(luma(PEN_INK[CEIL_NEAR]), luma(PEN_INK[CEIL_FAR]))
    for k in range(1, KMAX + 1):
        for door in (0, 1):
            p = wall_pen(k, 0, door)
            if luma(PEN_INK[p]) <= ceil:
                bad.append(f"{'door' if door else 'wall'} k={k} pen {p} "
                           f"ink {PEN_INK[p]} luma {luma(PEN_INK[p]):.0f} "
                           f"<= ceiling luma {ceil:.0f}")
    for ramp, name in ((WALL_RAMP, "wall"), (DOOR_RAMP, "door")):
        seen = []
        for p in ramp:
            if p not in seen:
                seen.append(p)
        for a, b in zip(seen, seen[1:]):
            if luma(PEN_INK[a]) <= luma(PEN_INK[b]):
                bad.append(f"{name} ramp not monotone: pen {a} -> {b}")
        inks = [PEN_INK[p] for p in seen]
        if len(set(inks)) != len(inks):
            bad.append(f"{name} ramp reuses an ink: {inks}")
    # the mortar's own invariant: strictly darker than every ramp step of
    # both ramps, at every depth, so a course joint always RECEDES.
    if courses:
        lm = luma(PEN_INK[MORTAR])
        for k in range(1, KMAX + 1):
            for door in (0, 1):
                p = wall_pen(k, 0, door)
                if lm >= luma(PEN_INK[p]):
                    bad.append(f"mortar pen {MORTAR} luma {lm:.0f} not darker "
                               f"than {'door' if door else 'wall'} k={k} pen "
                               f"{p} luma {luma(PEN_INK[p]):.0f}")
    # ...and the invariant that was MISSING, which only bites if a joint is
    # ever drawn FULL HEIGHT.  The mortar and the ceiling are both firmware
    # ink 1 (pen 4 and pen 11), and that is deliberate and harmless for the
    # HORIZONTAL courses, which sit at v = 1/3 and 2/3 and never reach the
    # top edge of a face.  A VERTICAL line in the same pen runs straight
    # into the ceiling and reads as a slot cut through the wall, serrating
    # the silhouette.  So the rule is scoped to what it protects: if the
    # mortar is ever wanted for a full-height mark, it needs its own ink.
    if courses and MORTAR_FULL_HEIGHT:
        for c in (CEIL_NEAR, CEIL_FAR):
            if PEN_INK[MORTAR] == PEN_INK[c]:
                bad.append(f"mortar pen {MORTAR} and ceiling pen {c} are the "
                           f"same ink ({PEN_INK[MORTAR]}); a full-height mark "
                           f"in it cuts a slot through the wall")
    # the weapon: its four pens must be four DIFFERENT inks, or the
    # silhouette, the slide and the highlight merge into one blob.
    gun = (GUN_DARK, GUN_HAND, GUN_SLIDE, GUN_HL)
    inks = [PEN_INK[p] for p in gun]
    if len(set(inks)) != len(inks):
        bad.append(f"gun pens {gun} share an ink: {inks}")
    # THE TEXTURES ASK FOR INKS; THIS FILE ANSWERS WITH PENS.  walltex.py
    # is the art and names the four firmware inks each texture needs;
    # WALL_TEX_PENS / DOOR_TEX_PENS are where they land here.  Nothing
    # else ties the two together, so if a pen is ever repurposed the
    # texture would silently repaint itself in the new colour -- which is
    # exactly how gunart.PEN drifted (see the note there).  Check it.
    import walltex as _wt
    for name, pens, want in (("wall", WALL_TEX_PENS, _wt.WALL_INKS),
                             ("door", DOOR_TEX_PENS, _wt.DOOR_INKS)):
        got = [PEN_INK[p] for p in pens]
        if got != list(want):
            bad.append(f"{name} texture pens {pens} carry inks {got}, "
                       f"but walltex.py asks for {list(want)}")
        if len(set(pens)) != 4:
            bad.append(f"{name} texture reuses a pen: {pens}")
    return bad


if __name__ == "__main__":
    for b in check():
        print("FAIL:", b)
    print("pen ink  rgb                luma  role")
    roles = ["void / gun outline", "spare (lit edge)", "THE WALL",
             "spare (shaded edge)", "MORTAR", "spare", "HUD frame", "door k=1",
             "door k=2", "door k=3", "door k>=4", "THE CEILING",
             "THE FLOOR", "spare", "gun slide", "HUD text"]
    for p, (ink, role) in enumerate(zip(PEN_INK, roles)):
        print(f"{p:3d} {ink:3d}  {str(cpc.ink_rgb(ink)):18s} "
              f"{luma(ink):5.0f}  {role}")
