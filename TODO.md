# AMazeCPC — handoff

The textured **column renderer** is built, correct and on a disc. §1's
hook-placement blocker is **closed**: the charge is now one-sided per
interval, measured. The rooms are 4x4 and every door in the map opens.

The disc is **not locked**, and the reason is now known and is not what
this file said for a long time: **a frame with a door OPEN honestly needs
more vsync periods than `PACE_FRAMES` gives it.** The flood pours through
an open doorway into the next room, and the pacing was only ever swept
with every door shut. That is §1, and it is a WORK problem, not a charge
bug — see the two optimisations in §2, which is what closing it needs.

Read `engine2/src/costcol.inc` and the header of `engine2/src/rastcol.asm`
first; every number here is written down next to the code it constrains.

---

## Where it stands

| | |
|---|---|
| `VPCOL` (`engine2/src/vpcfg.inc`) | **1** — the column renderer ships |
| `PACE_FRAMES` (`engine2/src/main3.asm`) | **9** — 179.7 ms, 5.56 fps (was 10) |
| the map (`tools/world.py`) | **nine 4x4 rooms** in a 3x3 grid, 144 floor cells |
| `make amaze` | OK, disc fresh (`md5` of `engine2/build/TEX.BIN` == `build/e3/TEX.BIN`) |
| `emu_rcol.py verify` | **159/159 screens byte-exact** against `colmodel.py` |
| `emu_rcol.py atomic` | **PASS** — every interval inside its charge, 0 model/asm disagreements, 40 states / 2 seeds |
| `emu_march.py` | **PASS** — 516/516 states exact against `marchmodel.py` |
| `roomcost.py` | **PASS** — bucket k <= 7, flood depth <= 8, over all 8,128,512 states |
| `pacescan.py` (doors shut) | **PASS** — 0 of 8,128,512 states over budget |
| `pacescan.py` (doors OPEN) | **FAIL** — 827,181 of 8,792,064 (9.4%) over budget, up to 12 waits |
| `emu_verify3.py` | doors **PASS** (all six, all 12 doors); period **FAIL** — [9, 10, 11], and [9, 10] with every door shut |

The span renderer is still the fallback and still locks: set
`VPCOL equ 0` **and** `PACE_FRAMES equ 6` (an `assert` in `main3.asm`
catches you if you change only one) → 119.8 ms, 8.35 fps, and all six
named views read `[6]`.

---

## What was done (§1, closed)

`rc_column` took its `cost_unit` hook **after** its own setup, and
room-then-charge bills the work in front of a hook to the **previous**
hook — so ~1000 µs of per-pair setup was billed to whatever came before,
often a 60 µs `C_CEDGE`.

**The fix, as shipped.** One hook per pair, taken *before* any setup,
charging an upper bound computed from what is knowable at that point —
the pair's own `rc_up`/`rc_dn` and `h ± (hq+1)`, which bracket both byte
columns' half heights. `rc_charge` in `rastcol.asm`; `C_*` in
`engine2/src/costcol.inc` (**one** file, included by `main3.asm` *and*
`engine2/test/tst_rcol.asm`, parsed by `pacemodel.py` — no second copy).
Skipped pairs and `rc_pnext`'s clamped slow step take their own hooks, so
**every** interval is exactly one pair. `colmodel.charge` emits the same
unit sequence; `colmodel.charge_terms` is the shared source for both the
charge and the fit's regressors, so they cannot drift.

Nothing in the renderer got faster. `C_COLS` went 330 → 1800 because the
setup is finally billed inside its own interval instead of backwards.

**THE OLD MEASUREMENT COULD NOT SEE ANY OF THIS, AND THAT IS THE REAL
LESSON.** `atomic` timed each prefix with `bench()`, which counts whole
iterations in a fixed window: at an 87000 µs prefix in a 2000000 µs
window that is 23 iterations, so each prefix was quantised by up to 4.3%
— ±3500 µs — and the intervals are *differences* of two prefixes about
3000 µs apart. The noise was larger than the quantity. Some of the
under-charges the previous handoff quoted were real and some were noise,
and nothing could tell them apart.

`Rig.bench_exact` (new) runs the prefix an **exact** number of times via
`e_hfixed` in `tst_rcol.asm` and counts ticks to a flag: **repeatable to
4 µs**, and faster. `atomic` and the new `fit` both use it.

**`python3 engine2/tools/emu_rcol.py fit [n]`** (new) times every
interval and solves for the smallest constants that cover all of them —
a covering problem, not a regression, class by class. Re-run it after
**any** change to `rastcol.asm` and paste the answer into `costcol.inc`.
Its `C_COLR` came out 20.0 against the fill's independently measured
20.25 µs/scanline, which is the check that the row bound is really a
bound.

---

## What was done (the rooms and the doors)

**The doors were never broken.** `emu_verify3` hardcoded the door at cell
(5,3) and stood the player on (4,3). When the map became rooms-joined-by-
doors the door moved to (4,3) and (5,3) became plain floor, so `starts
shut` and `shuts it again` both read `SOLID = 0` for a door that opens
and shuts perfectly, and the player was being placed *inside* the
doorway. `a_door()` now finds a door in the map and picks an open
neighbour to stand on, and the walk-through step steps back out of the
doorway before shutting it — a door does not shut on the player. All five
checks pass.

**The rooms are 4x4 in a 3x3 grid**, 16 floor cells against 12, square
rather than oblong. The obvious rule says a W x H room needs
`W + H <= R_MAX + 1 = 7`, so 4x4 should not fit — **and that rule is too
strict**. The only cell at L1 8 in a 4x4 room is the wall corner
diagonally opposite, and both of its room-side neighbours are also wall,
so it has no face pointing into the room. What must be inside the march
is every *visible* face, and those top out at L1 7.

`engine2/tools/roomcost.py` (new) is the measurement, exhaustive over all
8,128,512 reachable states, and it was run at `R_MAX` 6 **and** 7 — the
histograms are identical, so the extra radius files nothing and was not
taken. `R_MAX` stays 6, the bucket pages and flood stack are untouched,
the worst march is 16 cells (was ~15). Re-run it after any map change:
the farthest-bucket line is the one that matters, because `march.asm`
files a face by `|dx| + |dy|` with **no upper bound**, and a key of 8
would write into the page above the last bucket.

The bigger rooms cost 9 states of 8.1 million a tenth period. That was
paid for by making `rc_charge` cheap (below) rather than by a slower
frame: `PACE_FRAMES` stays 9.

**`rc_charge` went from ~500 µs a pair to ~100.** It ran `rc_mul8` — an
eight-iteration loop — twice and counted bands besides, ~11 ms of a frame
of pure charging overhead, and that arithmetic runs *inside* the interval
it charges for, so it was also inflating `C_COLS`. With `C_CBAND == 0`
and `C_CEDGE == 8*C_COLR`, the whole bound is
`C_COLS + C_COLR*(rows + 8*edges)` — one multiply, by shifts, since
`C_COLR == 21 = 16+4+1`. All three relations are `assert`ed in
`rastcol.asm`, so changing a constant fails the build instead of quietly
meaning something else. `C_CSKIP` fell 697 → 560 and `C_COLS` 1980 → 1800.

---

## 1. THE BLOCKER — the frame asks for more periods than it has

`emu_verify3.py` reads `[9, 10, 11]` vsyncs where it must read one value.
Which named views overrun moves with the map — on the 4x4 map it is
`corridor` at 11, `junction` / `worst state` / `(1,5) h12` at 10 — so do
not chase a particular view; chase the unit.

**MOST OF IT IS NOT AN UNDER-CHARGE AT ALL — IT IS AN OPEN DOOR.** An
earlier version of this note concluded "an interval overran, so a unit is
under-charged". That was wrong, and what hid it is that `pacescan` only
ever swept the map's own `SOLID`, in which every door is SHUT. Swept with
the doors OPEN the accumulator asks for up to **12 waits against a budget
of 9**, and **827,181 of 8,792,064 states — 9.4% — are over budget**,
worst charged frame 219,851 µs. The frame is not overrunning an interval;
it is honestly asking for more periods than `PACE_FRAMES` has, and
`pace_wait` then waits without decrementing. That is also why raising
`PACE_FRAMES` 9 → 10 did not help: the demand was 11 and 12.

`emu_verify3` measures the period AFTER its door section, which leaves a
door open — so the `[9, 10, 11]` it reports is largely this.

**WHAT IS LEFT AFTER THAT IS ONE PERIOD, AND IT IS REAL.** With every
door shut, the same build measures the six named views at `[9, 10]` while
the shut-door sweep says every state fits in 9. Three of the six take
exactly one period more than the model predicts. The model is *more*
pessimistic than the disc on the tail — it charges `C_TAIL + C_DOORACT`
on every frame, the disc charges `C_DOORACT` only on a SPACE press edge —
so the disc asking for MORE waits means some unit it charges is missing
from `pacemodel.units()`, or is bigger than its constant.

Count the waits to tell an overrun from a demand — and count them at
**`wait_vsync`**, NOT at `pace_wait`: `pace_drain` calls `wait_vsync`
directly, so a counter on `pace_wait` sees about one wait a frame and
tells you nothing. (Measured: it does exactly that.)

**It is not the column renderer.** `atomic` passes on 40 random states
over two seeds *and* on all six named views, with 0 model/asm
disagreements. And **the span build locks on these very states** —
`VPCOL 0` / `PACE_FRAMES 6` reads `[6]` for all six.

So: some unit is under-charged, it is not in `rastcol.asm`, and it only
bites when the column renderer's heavier frame changes where the interval
boundaries fall. Prime suspects, in order: `cost_face`'s `C_FACE` /
`C_REJ` / `C_CLIP` in the projector (its `FACE_THI` headroom argument
assumes `C_FACE_MAX` bounds a face), `C_BG`, `C_GUN`.

**`(1,5) h12` IS UNREACHABLE** — it fails `game.asm`'s own collision box
(`pacescan.coll_free`), so `pacescan` correctly excludes it and no player
can stand there. `emu_verify3` places it artificially. `nose against a
wall` **is** reachable, so it is the one that matters.

### Do not trust these harnesses as they stand

* **`emu_pacefit.py` is broken against the current `pace_wait`.** Its
  docstring says "(pace_left) is zeroed by the loop so the hooks never
  actually wait" — `pace_wait` was since changed to wait **anyway** when
  the budget is gone. Every yield inside a benched phase therefore costs
  a real 19968 µs vsync, which is exactly the bogus "projector = 20499 /
  42145 µs" readings. It also crashes (`counter unusable: 0`), and its
  `once()` gives up after 400 ms, so `fg_nquad` reads 0 mid-render and
  the "0 quads" rows are an artifact.
* **Reading `QUADS` / `fg_nquad` from a *running* game is racy** —
  `fg_nquad` is zeroed at `project_all`'s head, so an async read returns
  0 or garbage (185 quads, which is past the buffer).
* **Poking `pace_wait` to `RET` in a live game does not measure work** —
  it produced frame "work" times *longer* than the paced period.

Instrument at a **known stopping point** instead — the pattern that does
work is `tst_rcol.asm`'s: an abort hook plus an exact repetition count.

### Then, in order

`emu_rcol.py atomic` (still clean), `pacescan.py`, `emu_verify3.py`
(**the disc**, or it did not happen), `emu_pace3.py`.

---

## 2. Making it faster, ranked by measured size

Do **nothing** here until §1 is closed.

**AND "LESS DETAIL FOR DISTANT WALLS" IS NOT ONE OF THEM — MEASURED.**
The intuition is that far walls could be drawn cheaply. Two measurements
kill it, and they are worth keeping because the reasoning is seductive:

1. `engine2/tools/lodbreak.py` (new) attributes every microsecond of the
   raster charge to the DEPTH of the face that caused it. A far face
   fills almost nothing — 19 scanlines a pair at k=7 against 96 at k=1 —
   so its FILL is only 12% of what it costs. Making its pixels cheaper
   (flat colour instead of texture) is worth 7.2% of the rasteriser at a
   k>=4 cut, because it removes the cheapest part.

2. So the target is the per-pair SETUP, which is 52% of a far face and
   runs identically whether the wall is 96 scanlines tall or 6. A LOD
   path was BUILT — one half height per pair from the Bresenham already
   carried, no `rc_hbwd`/`rc_hfwd`, no second `rc_jof`, no edge runs, no
   second `CTABT` — and benched against the same states with it off:

       RC_LODK 0   65618 us/frame
       RC_LODK 4   63710 us/frame
       saved        1908 us/frame = 2.9%, i.e. 258 us per LOD pair

   **258 of `C_COLS`'s 1800.** The probes, the divide and the CTABT
   lookup are only 14% of a pair; the other ~1540 us is band setup, the
   fill loop's entry and exit, `rc_pnext`'s step and the charge
   arithmetic — none of which any level of detail removes.

The estimate that justified building it said 22.6%. It was wrong by 7x
because it assumed a LOD pair would cost 500 us instead of 1800. The asm
was reverted; `lodbreak.py` is kept, because the breakdown it prints is
the thing that says where to look. **The per-pair fixed cost is the
lever, and (a) below is what attacks it.**

These matter more than they used to. A doors-open frame charges up to
219,851 µs against a 175,104 µs budget, so about **45 ms has to come out
of the frame** before the period locks with doors open — and shrinking
the budget by raising `PACE_FRAMES` to 13 would mean 259.6 ms, 3.85 fps.

**a. The per-pair setup — 44.9 % of the render, AND IT IS DIFFUSE.**
`engine2/tools/pcprof.py` (new) samples the PC through a whole
`raster_colframe` and buckets it by symbol, so this is measured and not
read off the source:

    per-pair / per-face setup   44.9%
    fill (COLBLK/COLTAIL)       42.5%
    band setup                   7.0%
    edge runs                    5.7%

**But there is no hotspot to attack.** The biggest single symbol in the
setup is 3.2%, then 2.2, 2.0, 2.0, 1.9, 1.9 … and 23.5% of the render is
spread over thirty more symbols each under 1%. Two measurements bound
what register allocation can buy here:

* The LOD experiment removed FOUR of the ~twenty setup sites — both
  Bresenham probes, one `rc_jof`, the edge block and a `CTABT` lookup —
  and bought **258 µs of an 1800 µs pair, 14%**.
* The pair loop cannot hold state in registers across `rc_band`, because
  the fill uses BOTH banks (`HL`/`BC`/`D` texture, `HL'`/`BC'` screen).
  Only `IY` and `IXH` survive it — 24 bits. `IY` is enough for the
  occlusion pointer (`rc_dn` is `CNPAIR` bytes past `rc_up`, so one
  index register reaches both and `rc_pup`/`rc_pdn` disappear), and that
  is worth ~33 µs of 1800: **under 1% of the render.**

So the old "~10 ms off the worst frame" was optimism. The setup is real
and it is large, but it is thirty small things, and the register pressure
that put those temporaries in memory has not gone away.

**b. The fill — 10.125 µs/byte against a 5.125 constant-colour floor.**
`colrun` in `engine2/test/tst_byte.asm` samples once per two scanlines and
reads **7.625 µs/byte**, −25 %. A run-structured loop approaches that on
**near** walls, which are exactly the byte-heavy ones. Cost: the charge
must stay one-sided on both paths.

**c. Viewport width.** Everything scales linearly with `VP_BW`. 44 → 40 is
9 % off the fill and off `bg_fill`, and `vpcfg.inc` says it needs only five
constants. Cheapest win available; costs 5 % of the picture.

**d. Do NOT chase `bg_fill`.** It is 9.32 ms and walls overwrite a mean 3609
of 4224 bytes — but background in column order costs 5.125 µs/byte against
`bg_fill`'s 2.2, so it only wins when walls cover nearly everything.

---

## Also open

**Big rooms.** `R_MAX = 6` (L1 cells, `marchmodel.py`) bounds the sight
line; a wall further away is never marched and never drawn, so a big hall
reads as an open field with a sliver of wall on the horizon. Raising
`R_MAX` is not cheap — the flood's area grows as the square of the radius.
The alternative is a **far plane**: a constant-height band beyond the
march radius so a hall reads as enclosed. Cheap to draw, but it is a
visual fake and needs its own design.

**The horizontal texture resolution is halved by design.** `rc_column`
samples one texture *byte* per pair and writes it to both screen bytes, so
the two texture pixels come out `P0 P1 P0 P1` instead of a magnified
`P0 P0 P1 P1`. The art works around it — every joint is snapped to an
even `x` so its byte is solid (`walltex._courses`) — but the underlying
defect is still there. The clean fix is a texture stored with each pixel
doubled (32 columns), which needs 16384 bytes against `CTABT`'s 6148 in
the same 16K bank; bank 6 is entirely unused.

---

## Traps — do not rediscover these

**A MEASUREMENT THAT CANNOT RESOLVE ITS QUANTITY REPORTS CONFIDENT
NONSENSE.** `bench()`'s whole-iteration quantisation was ±3500 µs on
intervals of ~3000 µs; it printed under-charges that were not there and
hid ones that were. Use `bench_exact`. Before believing any number here,
check that repeating it twice gives the same answer.

**A per-FRAME one-sided check cannot see a per-INTERVAL under-charge.**
Use `emu_rcol.py atomic`, which sweeps the abort hook `k` and differences
consecutive prefixes, so the numbers it prints **are** the intervals.

**`pacescan` replays the CHARGE, so it cannot see a wrong charge.** It is
a packing check, not a cost check. It said 0 states over budget while the
disc took an extra period on a reachable state.

**The model and the asm must take the same unit SEQUENCE, not just the
same total.** `atomic` cross-checks the charge the Z80 is *about to take*
at hook `k` against the model's `k`-th unit and prints `MODEL/ASM
DISAGREE`. Use it after any charge change. `colmodel.charge` is built
from `charge_terms` for exactly this reason.

**THE PACING SWEEP ONLY EVER REPLAYED HALF THE GAME.** `pacescan.py`
built `SOLID` straight from the map, in which every door reads 2 — shut
and opaque — so the flood stopped at every doorway in every one of the
8,128,512 states it swept. A door the player has OPENED is transparent:
the flood pours through it and the frame grows. MEASURED exhaustively,
doors-shut → all-doors-open:

    cells popped      16 → 36        quads          8 → 14
    bucket 7 used   4.07% → 44.25%   flood depth    8 → 14

Those are the heaviest frames in the game and none of them had ever been
replayed. `pacescan` now sweeps BOTH configurations (`open_doors()`) and
fails if either misses. Anything that reasons about the worst frame —
`C_CELL`, `QUADS`, the bucket occupancy, `PACE_FRAMES` — was fitted
against the light half until now.

**THE MODEL IS THE ONLY THING THAT COULD HAVE FOUND THE ANGLED-DOOR BUG,
AND IT FOUND IT THE HOUR IT LEARNED THE FEATURE.** `colmodel` did not
know about the overlay pass or the lift, so `emu_rcol verify` ran 159
screens that never once entered the second pass -- it was green and it
was blind. Teaching it (`passes()`, `pair_walk(over=, dlift=)`,
`lift_row()`) and adding 24 batches with a door IN MOTION turned up 4
mismatches immediately, every one of them on a RAKED door.

The cause: `rc_etbig` -- the path taken when the taller byte column is
TALLER THAN THE VIEWPORT, which is every near door and every angled one
-- jumps straight to `rc_etrows`, so a lift placed on the `rc_etsml`
path alone was skipped by exactly the faces that needed it. The tall
column's edge run then hung below the risen door and painted door over
what should have been the room behind. The pair's own lift was already
after `rc_rows` for this reason; the edge lift is now after `rc_etrows`
too.

**The lesson is the one this file keeps relearning**: a verification that
does not exercise a path says nothing about it, and "159 of 159 exact" is
only as strong as the cases behind it. It is 183 now, and the 24 new ones
are the only ones that touch the overlay.

**`emu_march.py` had `BUCKHI` written down as `0x26`.** It stopped being
true the day the working-RAM block moved up four pages for the
course-joint rasteriser (`march.asm`'s memory map: it is `#2A`). The
harness read pages `0x27..0x2D` while the march filed into `0x2B..0x31`,
so every face record came back as whatever zeros were there — `visited`
and `seen` matched, the FACES did not, and it reported **516 of 516
states broken** with the march perfectly correct. It now reads
`addrs.BUCKHI`. Never copy an address; that is what `addrs.py` is for.

**`pacemodel._equ` does `int()` on the third token and falls back to its
own default when that throws.** So writing `C_CEDGE equ 8*C_COLR` in
`costcol.inc` assembles perfectly and silently models a *different disc*
— the model would have used 60 while the machine charged 168. The
constants are literals; `rastcol.asm` asserts the relations between them.

**`pacemodel.units()` read a global `_rm` that only `pacescan` ever set**
(`pm._rm = rm` in its worker initialiser). So `pacescan` worked and every
other caller died with `NameError` the moment `VPCOL` was 1 — including
`emu_pace3.py`, the one harness that measures the booted disc against the
model. The tool that could have caught the disc disagreeing was the tool
the bug silenced. Fixed (local import), but the shape of the mistake is
worth remembering.

**Check `make`'s exit status, not its output.** Grepping for
`"rasm.*error"` matches neither `ASSERT ... failed` nor `1 error`. Use
`if make amaze > log 2>&1; then …` and verify
`md5sum engine2/build/TEX.BIN build/e3/TEX.BIN` matches.

**`assert game_end <= BUCK0` has now fired four times.** Last time the fix
was moving the march's working RAM up one page (`BUCK0`, `BUCKHI`,
`BUCKETS`, `MSTKBOT`, `MSTKTOP`, `FTAB`, `SOLID`, `MARK` in `march.asm`, and
`QUADS` in `memmap.inc`). `addrs.py` parses them out of the source, so the
harnesses follow — never copy an address.

**The harness stack must live below `#4000`.** `raster_colframe` pages bank 5
into `#4000-#7FFF`; a stack at `#7FF0` gets pushed in one bank and popped in
another. The render came out 99.7 % right and then RET'd into the firmware.

**`cpc.write_ram` only reaches banks 0–3.** Bank 5 has to go through
`cpcemu_ram_ptr(5)` — see `emu_rcol.write_bank`. The disc does it the
ordinary way, `OUT (&7Fxx),&C5` then `LOAD`.

**Diagnose in the right component.** Three renderer fixes went in chasing
"broken walls" and none of them changed the picture, because the damage was
horizontal and they were all vertical. `engine2/tools/texshot.py` draws the
art and the model's own output side by side and answers "art or renderer" in
one picture. Run it first.

---

## Verify with

```
make amaze                                    # CHECK THE EXIT STATUS
python3 engine2/tools/emu_rcol.py verify      # 159 screens, byte for byte
python3 engine2/tools/emu_rcol.py atomic 8    # every INTERVAL vs its charge
python3 engine2/tools/emu_rcol.py fit 14      # re-fit costcol.inc, MEASURED
python3 engine2/tools/emu_march.py            # the march vs marchmodel.py
python3 engine2/tools/roomcost.py             # what the MAP costs the march
python3 engine2/tools/pacescan.py             # all reachable states, offline
python3 engine2/tools/emu_verify3.py          # the disc: mode, doors, PERIOD
python3 engine2/tools/emu_pace3.py 120 40 30
python3 engine2/tools/texshot.py              # the art, and the model's output
python3 engine2/tools/shot_amaze3.py          # screenshots into build/
```

Regenerating the world after editing `tools/world.py`:
`PYTHONPATH=$PWD/tools python3 engine2/tools/gen_march.py`
(it is **not** part of the `amaze` target).
