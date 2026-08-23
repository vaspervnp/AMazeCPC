; =====================================================================
;  engine2/src/frame.asm -- ONE COMPLETE FRAME.
;
;  This is the whole per-frame draw, and nothing else lives here: the
;  three pieces below are each measured on their own elsewhere, and this
;  file exists so that there is exactly one place that says what order
;  they run in.
;
;      frame_draw = bg_fill  ->  frame_geom  ->  raster_frame
;
;    bg_fill       (bg.asm)      ceiling + floor bands over the whole
;                                viewport.  It is painted FIRST and it
;                                doubles as the buffer clear -- every
;                                byte of the viewport is written here, so
;                                there is no separate cls.
;    frame_geom    (kernel.asm)  march + project.  Leaves (fg_nquad)
;                                14-byte quads at QUADS, BACK TO FRONT.
;    raster_frame  (raster.asm)  every quad, in that order, as horizontal
;                                PUSH DE runs.  Painter's algorithm: the
;                                overdraw is what hides the far walls.
;
;  The CRTC flip is NOT here.  Whoever owns the buffers calls
;  frame_setbuf with the back buffer, calls frame_draw, and then flips
;  (R12 = &30 / &20) when it wants to.
;
;  IN   (plr_x) (plr_y) world position, unsigned 16-bit 8.8
;       (plr_a)         heading 0..71
;       SOLID           16x16 map, 0 open / 1 wall / 2 shut door
;       frame_init      called once, with bank 4 paged at &4000
;       frame_setbuf    called with the buffer to paint
;  OUT  that buffer's viewport rectangle finished.
;
;  Clobbers AF BC DE HL IX and SP.  INTERRUPTS MUST BE OFF: SP is the
;  screen pointer inside both fills and the flood stack inside the march.
;  Every routine restores SP itself, so SP is intact on return.
;
;  ------------------------------------------------------------------
;  MEASURED on a cycle-accurate CPC 6128, 60 deg FOV, by
;  engine2/tools/emu_frame.py: 16-bit counter, interrupts off, empty-loop
;  overhead (14.94 us) subtracted, method calibrated to 100.08 us on 100
;  NOPs, measuring window sized so >= 200 whole frames complete in it.
;
;  METHOD.  The whole reachable state space -- 109 floor cells x 16
;  sub-cell offsets x 72 headings = 125568 states -- is counted with the
;  bit-exact Python models; 120 states drawn UNIFORMLY from it are
;  MEASURED and fitted (R^2 0.997, RMS 595 us); the fit then ranks all
;  125568 and the worst 80 are MEASURED too.  The fit is only used to
;  choose what to measure -- every number below is a real emulator run.
;  In all four sweeps the fit's own #1 turned out to be the measured
;  worst, and the fit OVER-predicts at the top (mean -1.6 ms), so the
;  ranking is conservative.
;
;  THE VIEWPORT LADDER.  vpcfg.inc edited and NOTHING else changed
;  (engine2/tools/vpfit.py drives it; each width re-verified bit-exact
;  first).  All four widths agree the worst frame in the maze is the same
;  state -- (0120,0DE0) heading 68, cell (1,13) pressed into a corner,
;  17 quads out of 22 candidate faces:
;
;      viewport      median   p90     WORST MEASURED    vs 80.00 ms
;      44 x 96 B     36.0    54.9      80.96 ms         OVER by 0.96
;      42 x 96 B     35.5    56.8      80.31 ms         OVER by 0.31
;      40 x 96 B     34.2    56.8      77.81 ms         FITS, 2.19 spare
;      38 x 96 B     33.8    56.4      76.61 ms         FITS, 3.39 spare
;
;    -> 40 x 96 BYTES (80x96 pixels) IS THE LARGEST THAT FITS, and that
;    is what vpcfg.inc is set to.  44x96, the size this build was aimed
;    at, misses by 1.2%.  Two bytes of width are worth 0.4-1.3 ms on a
;    worst frame (365 us of it background, the rest wall fill).
;
;    The height cannot be traded finely: bg.asm counts CHARACTER ROWS and
;    halves the half, so CYH must be a multiple of 16 and VP_H a multiple
;    of 32; raster.asm's VPLINE is one page, so VP_H <= 128.  The ladder
;    is 128 / 96 / 64 and nothing between -- 88 does not assemble.  Trade
;    width, which is free for any even VP_BW.
;
;    WITH COLLISION, 44 COMES BACK.  That worst state stands 32/256 =
;    0.125 cells from a wall plane, which is exactly project.asm's ZNEAR:
;    at or inside it the face is rejected and the player sees through the
;    wall, so movement has to keep further out than that anyway.  Re-swept
;    at 44x96 on the 256536 states a 0.25-cell collision radius allows
;    (8x8 sub-cell grid): median 36.8, p90 53.8, WORST 77.21 ms, FITS
;    with 2.79 ms spare.  See vpcfg.inc for how to take it.
;
;  WHERE THE TIME GOES, at 40x96 (measured separately AND together on the
;  same states; the three parts sum to the whole within 150 us, so there
;  is no hidden cost in the wiring):
;
;      background        8.50 ms   FIXED.  10.6% of the budget, and it
;                                  never varies -- same every frame.
;      geometry       3.0-22.3 ms  march + project.  Scales with marched
;                                  cells and candidate faces.
;      rasteriser     0.0-24.4 ms  and ~522 us of every quad is SETUP,
;                                  not fill: 17 quads = 8.9 ms of pure
;                                  Q12.4-undoing before a byte is pushed.
;
;    named scenarios, whole frame, 40x96:
;      nose against a wall       24.4 ms      1 quad
;      tight corner              42.2 ms      4 quads
;      corridor                  42.4 ms      5 quads
;      junction                  51.7 ms      9 quads
;      most open cell, off-axis  55.3 ms      8 quads
;
;  THE NEXT LEVER, if 44x96 or 48x128 is wanted without leaning on
;  collision: kernel.asm already holds (bhi, blo, hhi, hlo) internally and
;  throws them away to emit Q12.4 x and y.  Handing them over instead
;  would delete about half of raster.asm's 522 us per quad -- ~4.4 ms off
;  the worst frame, more than the whole 44-vs-40 difference.  It is a
;  change to the kernel's output contract, so it was not made here.
;  ------------------------------------------------------------------
; =====================================================================

; Needs: bg.asm (bg_init bg_fill bg_bufh), kernel.asm (frame_geom),
;        raster.asm (raster_init raster_setbuf raster_frame)


; ---------------------------------------------------------------------
;  frame_init -- once, at startup, with bank 4 paged at &4000.  Both
;  callees read tables (BANDPEN, LINETAB) and copy what they need out,
;  so after this the caller may page bank 4 away.
; ---------------------------------------------------------------------
frame_init
    call bg_init
    call raster_init
    ret


; ---------------------------------------------------------------------
;  frame_setbuf -- A = &C0 or &80, the buffer the next frame_draw paints.
; ---------------------------------------------------------------------
frame_setbuf
    ld   (bg_bufh),a
    jp   raster_setbuf


; ---------------------------------------------------------------------
;  frame_draw -- the frame.
; ---------------------------------------------------------------------
frame_draw
    call bg_fill
    call frame_geom
    if VPCOL
    jp   raster_colframe        ; textured columns (engine2/src/rastcol.asm)
    else
    jp   raster_frame           ; flat spans     (engine2/src/raster.asm)
    endif
