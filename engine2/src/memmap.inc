; =====================================================================
;  memmap.inc -- addresses that more than one build has to agree on.
;
;  QUADS lived in kernel.asm and was COPIED into engine2/test/tst_rast.asm,
;  which does not include the kernel.  When the working RAM moved up a page
;  to make room for raster_joint, the harness went on poking quad records
;  at the old address while the rasteriser read the new one, and reported
;  180 of 180 screens wrong -- on a flat build as well as a coursed one, so
;  it did not even look like a courses bug.  engine2/tools/addrs.py is the
;  same fix on the Python side; between them there is now one number.
;
;  Include this, do not copy out of it.
; =====================================================================

QUADS       equ #3A00           ; 120 x 8 = 960 bytes, #3A00-#3DBF.  The
                                ; geometry kernel's output list; see
                                ; kernel.asm for the record layout and
                                ; main3.asm for the map it sits in.
