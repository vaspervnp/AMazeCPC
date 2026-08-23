# AMazeCPC — handoff

The textured **column renderer** is built, correct and on a disc. It is
**not frame-locked**, and closing that is the one blocking task. Everything
below is measured on the booted 6128 unless it says otherwise.

Read `engine2/src/vpcfg.inc` and the header of `engine2/src/rastcol.asm`
first; every number here is written down next to the code it constrains.

---

## Where it stands

| | |
|---|---|
| `VPCOL` (`engine2/src/vpcfg.inc`) | **1** — the column renderer ships |
| `PACE_FRAMES` (`engine2/src/main3.asm`) | **10** — 199.7 ms, 5.01 fps |
| `make amaze` | OK, disc fresh (`md5` of `engine2/build/TEX.BIN` == `build/e3/TEX.BIN`) |
| `emu_rcol.py verify` | **147/147 screens byte-exact** against `colmodel.py` |
| `emu_verify3.py` | **FAIL** — reads `[10, 11, 13]` vsyncs, not one value |
| `pacescan.py` | **stale** — not re-run since `colmodel.charge` was fixed |

The span renderer is still the fallback and still locks: set
`VPCOL equ 0` **and** `PACE_FRAMES equ 6` (an `assert` in `main3.asm`
catches you if you change only one) → 119.8 ms, 8.35 fps, `ALL CHECKS PASS`.

---

## 1. THE BLOCKER — the hook is in the wrong place

`rc_column` takes its `cost_unit` hook **after** its own setup: the four-bit
`u` division, the two Bresenham probes (`rc_hbwd` / `rc_hfwd`) for the pair's
two byte columns, the `CTABT` lookup and the row range all run *before* the
charge. Room-then-charge bills the work in front of a hook to that hook, so
all of that setup is billed to the **previous** hook — which is often a
60 µs `C_CEDGE`.

MEASURED (`python3 engine2/tools/emu_rcol.py atomic 2`):

```
hook 33: charged     60   MEASURED  1883   UNDER by 1823 us
hook 47: charged     60   MEASURED  1673   UNDER by 1613 us
hook 22: charged   3362   MEASURED  5101   UNDER by 1739 us
```

An under-charged interval overruns 19968 µs, the yield lands past the vsync
edge, and the frame silently takes another period. That is the whole of the
`[10, 11, 13]`.

**The fix.** One hook per pair, taken at the **top** of `rc_column` before
any of its setup, charging an upper bound rather than an exact figure —
`C_COLS + 2*C_CBAND + C_COLR*(2j+1) + C_CEDGE*maxedge`. Then an interval is
exactly one pair and the charge covers it by construction. It over-charges
occluded pairs, which is the safe direction, and the atomic unit stays about
5 ms against a 19968 µs period, so there is room to spare.

`colmodel.charge` must emit the same single unit per pair. **It has already
been fixed once for exactly this class of bug** — see item (a) under Traps.

Then, in order: `emu_rcol.py atomic` (every interval inside its charge),
`pacescan.py` (pick `PACE_FRAMES`), `emu_verify3.py` (**the disc**, or it did
not happen), `emu_pace3.py`.

---

## 2. Making it faster, ranked by measured size

Do **nothing** here until §1 is closed: an unlocked frame cannot show whether
a saving materialised.

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
periods exactly as an under-charge does.

---

## Traps — do not rediscover these

**A per-FRAME one-sided check cannot see a per-INTERVAL under-charge.** I ran
`charge − measured` over 40 random states, got a minimum margin of +2355 µs,
and called the charge one-sided while the disc was three periods late. Use
`emu_rcol.py atomic`, which sweeps the abort hook `k` and differences
consecutive prefixes, so the numbers it prints **are** the intervals.

**`pacescan` replays the CHARGE, so it cannot see a wrong charge.** It said
nine waits while the disc took twelve. It is a packing check, not a cost
check.

**(a) The model and the asm must take the same unit SEQUENCE, not just the
same total.** `colmodel.charge` folded the edge rows into the pair unit while
`rc_column` takes a separate `C_CEDGE` hook per edge run: 28 model units
against 54 machine hooks on one state. `atomic` cross-checks the charge the
Z80 is *about to take* at hook `k` against the model's `k`-th unit and prints
`MODEL/ASM DISAGREE` — use it after any charge change.

**Check `make`'s exit status, not its output.** I grepped for
`"rasm.*error"`, which matches neither `ASSERT ... failed` nor `1 error`.
The build failed for ~40 minutes while I read `0` as success, screenshotted a
**stale disc**, and blamed the renderer for not changing. Use
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
python3 engine2/tools/pacescan.py             # all 4,055,040 states, offline
python3 engine2/tools/emu_verify3.py          # the disc: mode, doors, PERIOD
python3 engine2/tools/emu_pace3.py 250 50 40 60000
python3 engine2/tools/texshot.py              # the art, and the model's output
python3 engine2/tools/shot_amaze3.py          # screenshots into build/
```

Regenerating the world after editing `tools/world.py`:
`PYTHONPATH=$PWD/tools python3 engine2/tools/gen_march.py`
(it is **not** part of the `amaze` target).
