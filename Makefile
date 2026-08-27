# AMazeCPC -- a free-movement, 5-degree-turn first-person maze for the
# Amstrad CPC 6128, filled with horizontal PUSH DE runs.
#
#   engine2/tools/gentab.py   derives every table from engine2/src/vpcfg.inc
#   engine2/tools/genhud.py   derives the HUD furniture from the same file
#   rasm                      assembles the engine
#   iDSK                      wraps it in build/amaze.dsk
#
# Two files reach the disc: TABLES.BIN, which gentab.py derives entirely from
# engine2/src/vpcfg.inc and which is paged in at &4000 as RAM bank 4, and
# GAME3.BIN.  GAME3.BIN loads at &8000 -- the back buffer, which nothing has
# drawn into yet -- because its body has to RUN at &0040, under the engine's
# working RAM at &2400, and a BASIC loader cannot LOAD over &0170 without
# eating the program doing the loading.  The first 28 bytes of the file page
# the machine and copy the rest down.

IDSK    ?= /home/vasilhs/idsk/iDSK
RASM    ?= rasm
PYTHON  ?= python3
BUILD   := build

# EVERY FILE main3.asm INCLUDES, and it has to be every one.  This list
# had drifted four files behind the engine: sound.asm, rastcol.asm,
# pip.asm and menu.asm were all included by main3.asm and named by
# nothing here.
#
# IT IS DOCUMENTATION, NOT A DEPENDENCY, and that is worth saying so
# nobody trusts it for more than it does: `amaze` is .PHONY below, so
# make runs the recipe every time and never consults these prerequisites
# at all.  The list earns its keep by telling a reader what the disc is
# built from -- and by being the thing you check against main3.asm's
# include block when either one changes.  The REAL build bug was in the
# recipe, not here; see GEN.
SRC := engine2/src/main3.asm engine2/src/game.asm engine2/src/frame.asm \
       engine2/src/kernel.asm engine2/src/march.asm engine2/src/project.asm \
       engine2/src/raster.asm engine2/src/rastcol.asm engine2/src/bg.asm \
       engine2/src/hud2.asm engine2/src/gun.asm engine2/src/pip.asm \
       engine2/src/menu.asm engine2/src/sound.asm \
       engine2/src/costcol.inc engine2/src/vpcfg.inc

# The ART is source too.  These files decide what is in TABLES.BIN and what
# engine2/src/tab_equ.inc says the sprites are; a harness that reads them out
# of Python and the pixels off a disc built from an OLDER copy reports
# thousands of wrong bytes and no defect.  See the `gun` target below.
ART := engine2/tools/gunart.py engine2/tools/pal.py engine2/tools/walltex.py

# THE GENERATORS -- AND THIS IS WHERE THE REAL BUILD BUG WAS.  Three of
# them ran in nobody's recipe: gen_march.py, which owns the MAZE out of
# tools/world.py; genmenu.py, which owns the title screen's font and
# words; and gensnd.py, which owns the AY's effect tables.  Their
# outputs are committed .inc files, so `make` happily assembled the
# COMMITTED copy and never asked the generator whether it still agreed.
#
# Editing tools/world.py to move a wall, or gensnd.py's EFFECTS to
# retune a gunshot, therefore changed nothing on the disc -- silently,
# with a successful build and a "done".  That is the expensive kind of
# build bug: it does not fail, and the thing you then test is not the
# thing you changed.
#
# Checked when wiring them up: all three reproduce their committed
# output byte for byte, so no disc that has been built was wrong.  The
# hole had simply never been stepped in.
GEN := engine2/tools/gentab.py engine2/tools/genhud.py \
       engine2/tools/gentex.py engine2/tools/colmodel.py \
       engine2/tools/gen_march.py engine2/tools/genmenu.py \
       engine2/tools/gensnd.py engine2/tools/marchmodel.py \
       tools/world.py

.PHONY: all amaze test verify rast pace gun hud enemy shots clean
all: amaze

amaze: $(SRC) $(ART) $(GEN) engine2/src/disc3.bas
	@mkdir -p $(BUILD)/e3
	@# THE MAZE FIRST.  gen_march.py turns tools/world.py's grid into
	@# gen_maze.inc (packed two bits a cell), the per-heading constants
	@# into gen_slopes.inc, and MARCHTAB into gen_mtab.inc.  It needs
	@# both tool directories on the path and takes its output dir as an
	@# argument -- see the Run: line in its docstring.
	PYTHONPATH=tools:engine2/tools $(PYTHON) engine2/tools/gen_march.py engine2/src
	$(PYTHON) engine2/tools/gentab.py
	@# ...and RAM bank 5: the two wall textures, transposed and page
	@# aligned, plus the column renderer's step table.  Bank 4 has 180
	@# bytes free and the textures alone are 8192, which is why there is
	@# a second bank at all.  See engine2/tools/gentex.py.
	@# It imports genmenu directly for the title screen's blob, so the
	@# two cannot disagree about what is in bank 5.
	$(PYTHON) engine2/tools/gentex.py
	@# the HUD's furniture and needle, derived from the same vpcfg.inc
	$(PYTHON) engine2/tools/genhud.py
	@# the title screen's font and words, and the AY's effect tables
	$(PYTHON) engine2/tools/genmenu.py
	$(PYTHON) engine2/tools/gensnd.py
	cd engine2/src && $(RASM) main3.asm -I ../src \
	    -o ../../$(BUILD)/e3/GAME3 -s -os ../../$(BUILD)/e3/game3.sym
	mv $(BUILD)/e3/GAME3.bin $(BUILD)/e3/GAME3.BIN
	cp engine2/build/TABLES.BIN $(BUILD)/e3/TABLES.BIN
	cp engine2/build/TEX.BIN $(BUILD)/e3/TEX.BIN
	@# AMSDOS reads ASCII BASIC with CR line endings; LF alone reads as one
	@# enormous line and BASIC rejects it.
	sed 's/$$/\r/' engine2/src/disc3.bas > $(BUILD)/e3/DISC.BAS
	@rm -f $(BUILD)/amaze.dsk
	$(IDSK) $(BUILD)/amaze.dsk -n
	$(IDSK) $(BUILD)/amaze.dsk -i $(BUILD)/e3/DISC.BAS   -t 0 -f
	$(IDSK) $(BUILD)/amaze.dsk -i $(BUILD)/e3/GAME3.BIN  -t 1 -c 7000 -e 7000 -f
	$(IDSK) $(BUILD)/amaze.dsk -i $(BUILD)/e3/TABLES.BIN -t 1 -c 7000 -e 7000 -f
	$(IDSK) $(BUILD)/amaze.dsk -i $(BUILD)/e3/TEX.BIN    -t 1 -c 7000 -e 7000 -f
	@$(IDSK) $(BUILD)/amaze.dsk -l

# the game layer's unit tests: collision, sliding, doors, turning
test: amaze
	$(PYTHON) engine2/tools/emu_game.py all

# boot the built disc and check mode, double buffering, turning, walking,
# collision, doors and the measured frame period -- all read out of the
# running machine
verify: amaze
	$(PYTHON) engine2/tools/emu_verify3.py

# the rasteriser, byte for byte against its model.  TWO of them now:
# raster.asm's spans against rastermodel.py, and rastcol.asm's textured
# columns against colmodel.py.  vpcfg.inc's VPCOL picks which one the
# disc carries; both are verified either way, because the one that is not
# shipping is the fallback and has to stay correct.
rast: amaze
	$(PYTHON) engine2/tools/emu_rast.py verify
	$(PYTHON) engine2/tools/emu_rcol.py verify

# the frame PERIOD, sampled on the booted disc over 1400 reachable states,
# plus the walking speed that follows from it, plus the offline replay of
# the cost accumulator over the whole state space
pace: amaze
	@# THE WHOLE STATE SPACE, not a sample.  pacescan.py replays the
	@# accumulator's own rule for all 4055040 states a player can stand
	@# in -- 56320 positions on the 24/256 movement lattice that pass
	@# game.asm's collision box, times 72 headings -- and fails if ANY
	@# of them asks for more vsync waits than PACE_FRAMES has.  It is a
	@# minute on sixteen cores.  The sampled replay below stays because
	@# it prints the distribution; this is what decides the question,
	@# because the states that break a period are three in a million and
	@# a sample does not visit them.
	@# ...it also leaves the 40 most expensive states there ARE in
	@# engine2/build/pacescan_top.json, which is what emu_pacefit.py
	@# below benches.  Benched at the worst 40 a SAMPLE could find, the
	@# same disc reads a worst frame of 90.63 ms; benched at the worst 40
	@# that exist, 98.28.
	$(PYTHON) engine2/tools/pacescan.py
	$(PYTHON) engine2/tools/pacemodel.py 3000
	@# ...and the constants themselves, benched on the booted disc at
	@# those states, each unit checked ON ITS OWN.  A frame total that
	@# over-predicts hides a unit that under-charges: C_BG sat 616 us
	@# under the truth at 44x96 behind a frame total that read "never
	@# under", because the march and the projector covered for it.
	$(PYTHON) engine2/tools/emu_pacefit.py 40 worst
	@# ...and the two units emu_pacefit.py does NOT bench in the shape the
	@# frame runs them: march_setup on the frame the generation counter
	@# wraps, and the TAIL -- flip + game_step + the head of main_loop --
	@# with keys actually HELD and the player pinned so the bench cannot
	@# walk off the state it is measuring.  Both were under-charged.
	$(PYTHON) engine2/tools/emu_holes.py 60
	@# ...and the RASTERISER's own units, which are per CHUNK of scanlines
	@# now and not per quad: emu_atomic.py times raster_quad up to the k'th
	@# hook, differences it into the intervals themselves, and checks every
	@# one of them is charged for.  It also reports the largest atomic unit
	@# before and after the mid-quad yield, which is what sets the period.
	$(PYTHON) engine2/tools/emu_atomic.py 6
	@# ...and the PERIOD on the booted disc.  emu_pace3.py measures the
	@# states the offline replay NAMES as the worst packers as well as a
	@# uniform sample, because a uniform sample cannot find a defect that
	@# lives on three states in a million: built at PACE_FRAMES 5, the
	@# 300 sampled states all read on-pace while 55 of the 60 named ones
	@# sat a whole period late.
	$(PYTHON) engine2/tools/emu_pace3.py 900 150 90 60000
	$(PYTHON) engine2/tools/emu_pace.py 600
	$(PYTHON) engine2/tools/emu_pace.py walk

# the weapon: the blit verified byte for byte at every bob offset on the
# booted disc, then measured, then photographed at rest and at the bob
# extremes so the placement can be checked by eye.
#
# What it COSTS is charged, by main3.asm:gun_paced, and `make pace` is
# what proves the frame period survived it -- emu_pacefit.py benches the
# whole charged block and checks C_GUN clears it, emu_pace.py sweeps the
# disc.  main3.asm's GUN_CHARGED equ 0 rebuilds the disc that does NOT
# charge it, which is the control the fix was measured against.
gun: amaze
	$(PYTHON) engine2/tools/emu_gun.py
	$(PYTHON) engine2/tools/shot_gun.py

# the HUD: verified byte for byte against genhud.py's model, then measured
hud: amaze
	$(PYTHON) engine2/tools/emu_hud.py
	$(PYTHON) engine2/tools/shot_hud.py

# screenshots in build/: corridor, +5 deg, +45 deg, off-centre, doors
shots: amaze
	$(PYTHON) engine2/tools/shot_amaze3.py

clean:
	rm -rf $(BUILD) engine2/build
