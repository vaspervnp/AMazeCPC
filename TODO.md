# AMazeCPC — handoff

The textured **column renderer** is built, correct and on a disc. §1's
hook-placement blocker is **closed**: the charge is now one-sided
per interval, measured. The disc is **not fully locked yet** — two of
emu_verify3's six named views still overrun, and the cause is
**outside** the column renderer. That is the one blocking task.

Read `engine2/src/costcol.inc` and the header of `engine2/src/rastcol.asm`
first; every number here is written down next to the code it constrains.

---

## Where it stands

| | |
|---|---|
| `VPCOL` (`engine2/src/vpcfg.inc`) | **1** — the column renderer ships |
| `PACE_FRAMES` (`engine2/src/main3.asm`) | **9** — 179.7 ms, 5.56 fps (was 10) |
| `make amaze` | OK, disc fresh (`md5` of `engine2/build/TEX.BIN` == `build/e3/TEX.BIN`) |
| `emu_rcol.py verify` | **147/147 screens byte-exact** against `colmodel.py` |
| `emu_rcol.py atomic` | **PASS** — every interval inside its charge, 0 model/asm disagreements |
| `pacescan.py` | **PASS** — 0 of 6,967,296 reachable states over budget |
| `emu_verify3.py` | **FAIL** — 4 views lock at 9, `nose against a wall` reads 10, `(1,5) h12` reads 11 |

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

Nothing got faster. `C_COLS` went 330 → 1980 because the setup is finally
billed inside its own interval instead of backwards.

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
Its `C_COLR` came out 20.5 against the fill's independently measured
20.25 µs/scanline, which is the check that the row bound is really a
bound.

---

## 1. THE BLOCKER — an under-charge OUTSIDE rastcol

`emu_verify3.py` reads `nose against a wall` (10,13 h54) at **10** vsyncs
and `(1,5) h12` at **11**, against 9 for the other four.

**It is an interval overrun, not a budget shortfall, and that is
measured, not deduced.** Built at `PACE_FRAMES 10` the *same two* views
read 11 and 12 — the same +1 and +2. More budget does not help, so some
unit's real time exceeds a vsync period while its charge is under
`COST_THI`. (If every unit is one-sided no interval can overrun: an
interval accumulates at most `COST_THI` = 19456 µs of charge, and
charge ≥ work gives work < 19968.)

**It is not the column renderer.** `atomic` passes on 22 random states
(~700 intervals) *and* on all six named views, with 0 model/asm
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

**a. `rc_charge` itself is now ~500 µs a pair** — about 11 ms of a frame
at 22 pairs, pure charging overhead. It calls `rc_mul8` (an 8-iteration
loop) **twice**. Both multiplies are by *constants*: `rows*21` is six
`add hl,*` and `edges*170` is eight, so ~30 µs instead of ~200. Guard the
sequence with `assert C_COLR == 21` so a changed constant fails the build
instead of silently mis-charging. `C_CBAND` is **0**, so the whole band
count can go too. Worth ~4 ms/frame, and it shrinks `C_COLS` with it.

**b. The per-pair setup — ~1000 µs/pair, 37–41 % of the rasteriser.**
Dominated by 16-bit memory temporaries at 4–5 µs each (`ld hl,(nn)`,
`ld (nn),hl`); the pair loop does about twenty per pair (`rc_num`,
`rc_den`, `rc_h`, `rc_acc`, `rc_t2`, `rc_pup`, `rc_pdn`…). They are in
memory because both register banks are full **inside** the fill — but
they are free *between* pairs. Move the hot state into `IX`/`IY` and the
alternate set. Estimate ~10 ms off the worst frame; two smaller moves of
this kind already bought 11.1 %.

**c. The fill — 10.125 µs/byte against a 5.125 constant-colour floor.**
`colrun` in `engine2/test/tst_byte.asm` samples once per two scanlines and
reads **7.625 µs/byte**, −25 %. A run-structured loop approaches that on
**near** walls, which are exactly the byte-heavy ones. Cost: the charge
must stay one-sided on both paths.

**d. Viewport width.** Everything scales linearly with `VP_BW`. 44 → 40 is
9 % off the fill and off `bg_fill`, and `vpcfg.inc` says it needs only five
constants. Cheapest win available; costs 5 % of the picture.

**e. Do NOT chase `bg_fill`.** It is 9.32 ms and walls overwrite a mean 3609
of 4224 bytes — but background in column order costs 5.125 µs/byte against
`bg_fill`'s 2.2, so it only wins when walls cover nearly everything.

---

## Also open

**The door tests fail, and they failed before any of this.** `emu_verify3`
reports `door (5,3) starts shut: SOLID = 0` and `SPACE shuts it again:
SOLID = 0`. **Confirmed pre-existing**: the `VPCOL 0` / `PACE_FRAMES 6`
build fails the same two assertions while passing the period check. It is
a door/`SOLID` bug, not a pacing one, and it is why `emu_verify3` prints
`SOMETHING FAILED` even when the period is locked. Fix it separately.

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
python3 engine2/tools/emu_rcol.py verify      # 147 screens, byte for byte
python3 engine2/tools/emu_rcol.py atomic 8    # every INTERVAL vs its charge
python3 engine2/tools/emu_rcol.py fit 14      # re-fit costcol.inc, MEASURED
python3 engine2/tools/pacescan.py             # all reachable states, offline
python3 engine2/tools/emu_verify3.py          # the disc: mode, doors, PERIOD
python3 engine2/tools/emu_pace3.py 120 40 30
python3 engine2/tools/texshot.py              # the art, and the model's output
python3 engine2/tools/shot_amaze3.py          # screenshots into build/
```

Regenerating the world after editing `tools/world.py`:
`PYTHONPATH=$PWD/tools python3 engine2/tools/gen_march.py`
(it is **not** part of the `amaze` target).
