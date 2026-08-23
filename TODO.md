# AMazeCPC — handoff

The textured **column renderer** is built, correct and on a disc. The hook
that made it miss its frame period has been **moved**, and offline the
charge now packs into **eight vsync periods** with a fifth of the budget
spare. What has **not** happened is a measurement: this branch was written
on a machine with no cycle-accurate emulator, so nothing here has been run
against a booted 6128. Read §0 before you believe any of it.

Read `engine2/src/vpcfg.inc` and the header of `engine2/src/rastcol.asm`
first; every number here is written down next to the code it constrains.

---

## Where it stands

| | |
|---|---|
| `VPCOL` (`engine2/src/vpcfg.inc`) | **1** — the column renderer ships |
| `PACE_FRAMES` (`engine2/src/main3.asm`) | **8** — 159.74 ms, 6.26 fps |
| `make amaze` | OK, exit status checked, disc fresh (`md5` of `engine2/build/TEX.BIN` == `build/e3/TEX.BIN`) |
| the §1 hook | **moved** — one upper-bound unit per pair, at the top of `rc_column` |
| `colmodel.charge` | **matches it** — one unit per pair, same figure, no edge units |
| `pacescan.py` | **re-run, exhaustive, clean** — 0 of 6,967,296 states ask for an eighth wait |
| `colmodel.render` | **unchanged** — byte-identical over 400 random batches |
| `emu_rcol.py verify` | **NOT RUN** — needs the emulator |
| `emu_rcol.py atomic` | **NOT RUN** — needs the emulator, and it is the check that matters |
| `emu_verify3.py` | **NOT RUN** — needs the emulator |

The span renderer is still the fallback and still locks: set
`VPCOL equ 0` **and** `PACE_FRAMES equ 6` (an `assert` in `main3.asm`
catches you if you change only one) → 119.8 ms, 8.35 fps, `ALL CHECKS PASS`.

---

## 0. THE MEASUREMENT THAT HAS NOT BEEN TAKEN

`engine2/tools/emu_rcol.py`, `emu_verify3.py`, `emu_pace3.py`,
`emu_frame.py` and every other `emu_*` harness open the cycle-accurate
CPC library with `from cpc import CPC`, off `sys.path.insert(0,
os.path.expanduser("~/cpcemu"))`. **`~/cpcemu` is not in this repository
and is not in any repository on the account.** On a machine without it,
the only things that run are the offline models — `pacescan.py`,
`colmodel.py`, `colarea.py`, `pacemodel.py`, `gentab.py`, `gentex.py`.

So the rule this file has held to since the first period was lost still
applies, and it has **not** been satisfied here:

> `pacescan` replays the CHARGE, so it cannot see a wrong charge.
> `emu_verify3.py` is the disc, **or it did not happen**.

`pacescan` saying eight periods is exactly the claim that was made — and
withdrawn — at PACE_FRAMES 8 and again at 9. It is a **packing** check
over the model's charge. What makes the charge trustworthy is
`emu_rcol.py atomic`, which measures the intervals the Z80 actually runs
and cross-checks them against `colmodel.charge` hook for hook. **Run it
first, on a machine that has `~/cpcemu`, before trusting `PACE_FRAMES 8`
or shipping this.**

`rasm` and `iDSK` are not needed from a package: `rasm` builds from
https://github.com/EdouardBERGE/rasm with
`gcc -O2 -DNO_3RD_PARTIES -o rasm rasm.c -lm` (without that define it
fails to link against the bundled compressors), and `iDSK` from
https://github.com/cpcsdk/idsk with `cmake . && make`. `pacescan.py`
imports `emu_frame` for `load()` alone, so on an emulator-less machine it
runs behind a stub `cpc.py` whose `CPC` raises — never behind one that
returns numbers.

---

## 1. THE BLOCKER — DONE IN CODE, NOT YET MEASURED

**What was wrong.** `rc_column` took its `cost_unit` hook **after** its own
setup: the four-bit `u` division, the two Bresenham probes (`rc_hbwd` /
`rc_hfwd`), the `CTABT` lookup and the row range all ran *before* the
charge. Room-then-charge bills the work in front of a hook to that hook,
so all of that setup was billed to the **previous** hook — which is often
a 60 µs `C_CEDGE`.

MEASURED (`python3 engine2/tools/emu_rcol.py atomic 2`), before the fix:

```
hook 33: charged     60   MEASURED  1883   UNDER by 1823 us
hook 47: charged     60   MEASURED  1673   UNDER by 1613 us
hook 22: charged   3362   MEASURED  5101   UNDER by 1739 us
```

An under-charged interval overruns 19968 µs, the yield lands past the
vsync edge, and the frame silently takes another period. That is the whole
of the `[10, 11, 13]`.

**What was done.** `rc_column` now takes **one hook, first**, and the edge
runs take none:

* the two Bresenham probes and the two row ranges (the pair's, from `j`,
  and the taller column's, from `jt`) run at the top, because the charge
  is computed from them;
* then the single `cost_unit`, charging
  `C_COLS + 2*C_CBAND + C_COLR*rows + C_CEDGE*(tall_rows - rows)`;
* then the `u` division and the `CTABT` lookup, which used to precede the
  hook and now follow it;
* then the bands and the edge runs, unhooked.

An interval is therefore exactly one pair. What it has to cover is that
pair's drawing, `rc_pnext`'s step, and the **next** pair's probes and row
ranges — the only work that can precede a hook at all, and a fixed cost
per pair, so the per-pair setup is split across two consecutive pairs and
sums to what `C_COLS` already covered. **No `C_*` constant changed.**

**The charge is an upper bound, and that is what makes it unconditional.**
It bills two bands and the full row range before the occlusion interval
cuts either of them. The exact figure came to *zero* on a pair whose bands
a nearer face had wholly taken — and a pair with no hook is a pair with no
interval boundary, which is the defect being repaired. Over-charging a
pair that draws nothing costs little; leaving it unhooked costs a period.

`colmodel.charge` emits the same single unit per pair, unconditionally,
and no longer emits a unit per edge run. **It has now been fixed twice for
this class of bug** — see item (a) under Traps.

**What that bought, offline.** `pacescan.py`, exhaustive over all
6,967,296 reachable states:

```
   4 waits      12981    0.186%   -> 5 periods
   5 waits    4057365   58.234%   -> 6 periods
   6 waits    2896098   41.567%   -> 7 periods
   7 waits        852    0.012%   -> 8 periods
   worst charged frame 123102 us against a budget of 155648 us
   0 states of 6967296 would take 9 periods
```

so `PACE_FRAMES` is **8**, 159.74 ms, 6.26 fps. (The 4,055,040 this file
used to quote is stale: `tools/world.py` has moved since, and the space is
6,967,296 states now — 96,768 standable positions × 72 headings.)

**What is still open on it, in order.**

1. `emu_rcol.py verify` — 147 screens byte-exact. The renderer's drawing
   was not touched and `colmodel.render` is byte-identical over 400 random
   batches against the previous model, so this should be a formality. It
   is still the thing that proves the reorder did not disturb the picture.
2. `emu_rcol.py atomic 2` — **the one that matters.** Every interval
   inside its charge, and `MODEL/ASM DISAGREE` silent.
3. `pacescan.py` — already clean, but re-run it after any charge change.
4. `emu_verify3.py` — **the disc**, one PERIOD value and not three.
5. `emu_pace3.py 250 50 40 60000`.

**AND ONE THING `atomic` SHOULD BE WATCHED FOR, because it was found by
reading and not by measuring.** `rc_pairloop` skips a pair that a nearer
face has already covered floor to ceiling, and a skipped pair takes **no
hook**: its ~125 µs of `rc_pnext` is charged at the *face* level, as
`C_CSKIP` per pair in range, one `cost_unit` before the pair loop starts.
That reservation is correct only while no yield happens inside the face —
`cost_unit` sets `(cost_acc)` to the new unit when it yields, and the
reservation for the pairs not yet walked goes with it. A face with a
nearer one standing in the middle of it can therefore put a run of up to
twenty unhooked pairs — some 2.5 ms — inside one interval, against
`COST_THI`'s 512 µs of headroom. It predates this change and §1 does not
address it. If `atomic` shows an interval over its charge on a face with
interior skipped pairs, that is where it is, and the fix is the same shape
as this one: hook the skipped pairs too, and drop `C_CSKIP` from the face
unit.

---

## 2. Making it faster, ranked by measured size

Do **nothing** here until §1 is closed **on the disc**: an unlocked frame
cannot show whether a saving materialised, and §1 is not closed until
`atomic` and `emu_verify3` have run.

**a. The per-pair setup — ~1000 µs/pair, 37–41 % of the rasteriser.**
Dominated by 16-bit memory temporaries at 4–5 µs each (`ld hl,(nn)`,
`ld (nn),hl`); the pair loop does about twenty per pair (`rc_num`, `rc_den`,
`rc_h`, `rc_acc`, `rc_t2`, `rc_pup`, `rc_pdn`…). They are in memory because
both register banks are full **inside** the fill — but they are free
*between* pairs. Move the hot state into `IX`/`IY` and the alternate set.
Estimate ~10 ms off the worst frame; two smaller moves of this kind already
bought 11.1 %.

**b. The fill — 10.125 µs/byte against a 5.125 constant-colour floor.**
The alternative is already measured: `colrun` in `engine2/test/tst_byte.asm`
samples once per two scanlines and reads **7.625 µs/byte**, −25 %. A
run-structured loop approaches that on **near** walls, which are exactly the
byte-heavy ones. Cost: the charge must stay one-sided on both paths.

**c. Viewport width.** Everything scales linearly with `VP_BW`. 44 → 40 is
9 % off the fill and off `bg_fill`, and `vpcfg.inc` says it needs only five
constants. Cheapest win available; costs 5 % of the picture.

**d. Do NOT chase `bg_fill`.** It is 9.32 ms and walls overwrite a mean 3609
of 4224 bytes — but background in column order costs 5.125 µs/byte against
`bg_fill`'s 2.2, so it only wins when walls cover nearly everything.

**e. Tighten the charge, not the work.** `C_CFACE + C_CSKIP*np` is billed to
fully occluded faces too. One-sided, so safe, but an over-charge costs
periods exactly as an under-charge does. §1's own charge is now an upper
bound as well: two bands and the full row range on every pair. Both are
worth revisiting once there is a measured frame to compare against, and
neither is worth touching before that.

---

## Traps — do not rediscover these

**A per-FRAME one-sided check cannot see a per-INTERVAL under-charge.** I ran
`charge − measured` over 40 random states, got a minimum margin of +2355 µs,
and called the charge one-sided while the disc was three periods late. Use
`emu_rcol.py atomic`, which sweeps the abort hook `k` and differences
consecutive prefixes, so the numbers it prints **are** the intervals.

**`pacescan` replays the CHARGE, so it cannot see a wrong charge.** It said
nine waits while the disc took twelve. It is a packing check, not a cost
check. It has now said eight, and that number carries exactly as much
weight as the nine did until `atomic` and `emu_verify3` have run.

**(a) The model and the asm must take the same unit SEQUENCE, not just the
same total.** `colmodel.charge` folded the edge rows into the pair unit while
`rc_column` took a separate `C_CEDGE` hook per edge run: 28 model units
against 54 machine hooks on one state. The second version of the same bug
was conditional: the model appended no unit for a pair whose bands were
fully occluded, and neither did the asm — but that left the *pair* without
a boundary. Both sides now emit exactly one unit per pair, always.
`atomic` cross-checks the charge the Z80 is *about to take* at hook `k`
against the model's `k`-th unit and prints `MODEL/ASM DISAGREE` — use it
after any charge change.

**Check `make`'s exit status, not its output.** I grepped for
`"rasm.*error"`, which matches neither `ASSERT ... failed` nor `1 error`.
The build failed for ~40 minutes while I read `0` as success, screenshotted a
**stale disc**, and blamed the renderer for not changing. Use
`if make amaze > log 2>&1; then …` and verify
`md5sum engine2/build/TEX.BIN build/e3/TEX.BIN` matches.

**`jr` has a range and a moved block will tell you.** Lifting the taller
column's row range out of the edge section and up in front of the hook
first went in truncated — `rc_etrows` matched the `jr rc_etrows` inside the
block before it matched the label at the end of it — and rasm caught it as
`relative offset 266 too far [RC_ETSML]`. It is the assembler's job to
catch that, so let it: build after every move, and never on a `-` grep.

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

## Open, lower priority

**Big rooms.** `R_MAX = 6` (L1 cells, `marchmodel.py`) bounds the sight line;
a wall further away is never marched and never drawn, so a big hall reads as
an open field with a sliver of wall on the horizon. Four 6×7 halls put **all
173** standable cells past the limit. The map is now twelve 3×4 rooms joined
by doors, which puts the far corner at L1 7, the last distance the march
files. Raising `R_MAX` is not cheap — the flood's area grows as the square of
the radius, and the oversized rooms alone took the worst march from ~15 cells
to 36 (26.6 ms at `C_CELL`). The alternative is a **far plane**: a
constant-height band beyond the march radius so a hall reads as enclosed.
Cheap to draw, but it is a visual fake and needs its own design.

**The horizontal texture resolution is halved by design.** `rc_column`
samples one texture *byte* per pair and writes it to both screen bytes, so
the two texture pixels come out `P0 P1 P0 P1` instead of a magnified
`P0 P0 P1 P1`. The art now works around it — every joint is snapped to an
even `x` so its byte is solid (`walltex._courses`) — but the underlying
defect is still there. The clean fix is a texture stored with each pixel
doubled (32 columns), which needs 16384 bytes against `CTABT`'s 6148 in the
same 16K bank; bank 6 is entirely unused.

---

## Verify with

```
make amaze                                    # CHECK THE EXIT STATUS
python3 engine2/tools/emu_rcol.py verify      # 147 screens, byte for byte
python3 engine2/tools/emu_rcol.py atomic 2    # every INTERVAL vs its charge
python3 engine2/tools/pacescan.py             # all 6,967,296 states, offline
python3 engine2/tools/emu_verify3.py          # the disc: mode, doors, PERIOD
python3 engine2/tools/emu_pace3.py 250 50 40 60000
python3 engine2/tools/texshot.py              # the art, and the model's output
python3 engine2/tools/shot_amaze3.py          # screenshots into build/
```

Everything but `make`, `pacescan.py`, `texshot.py` and the models needs
`~/cpcemu` on the path — see §0.

Regenerating the world after editing `tools/world.py`:
`PYTHONPATH=$PWD/tools python3 engine2/tools/gen_march.py`
(it is **not** part of the `amaze` target).
