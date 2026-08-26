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

QUADS       equ #3C00           ; the geometry kernel's output list; see
NQUAD       equ 56              ; kernel.asm for the record layout and
                                ; main3.asm for the map it sits in.
;
;  IT HELD 120 RECORDS FOR A MEASURED MAXIMUM OF NINE.  Sampling 8000
;  reachable states in each of the three door configurations -- shut,
;  open and in motion -- project_all's largest output was 6, 7 and 9
;  quads respectively.  960 bytes of low RAM were reserved for 72.
;
;  So it is 56 now, which is 448 bytes and still six times the worst
;  seen, and the 512 bytes that came back let march.asm's working RAM
;  move UP two pages -- which is 512 bytes handed to the code segment,
;  whose `assert game_end <= BUCK0` had just fired for the eleventh
;  time.  QUADS still ENDS at #3DBF, so the door tables at #3DC0,
;  pip.asm's scratch at #3DF0 and rastcol.asm's RC_COVER at #3E00 are
;  exactly where they were.
