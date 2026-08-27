; =====================================================================
;  engine2/src/sound.asm -- THE AY, AND A FIFTY-HERTZ TICK WITH NO
;  INTERRUPT TO HANG IT ON.
;
;      snd_init    once, at startup: silence all three channels
;      snd_play    A = an SFX_* index; starts it, replacing whatever
;                  was playing
;      snd_tick    one 50th of a second.  Called from wait_vsync, and
;                  from nowhere else.
;
;  WHY wait_vsync.  The engine runs with interrupts OFF from the first
;  instruction to the last, so there is no 300 Hz tick to drive a sound
;  player from, and the game frame is 9 vsyncs -- 180 ms, which would
;  make a gunshot two steps long.  But every vsync wait in the frame
;  goes through ONE routine.  Hanging the tick there is a real 50 Hz
;  clock for the price of a CALL, and it works everywhere: inside the
;  renderer with bank 5 paged, inside the march, in the tail.  The
;  driver reads its tables out of the code segment, below #4000, so the
;  paging cannot reach them, and AY writes are I/O rather than memory.
;
;  IT SHARES THE PPI WITH THE KEYBOARD AND MUST LEAVE IT AS IT FOUND IT.
;  game.asm's scan_keys reads a key row by selecting AY register 14 and
;  reading it back, which means it turns PPI port A round to INPUT and
;  puts it back to OUTPUT before returning.  This file only ever writes,
;  so it sets port A to output itself rather than trusting whoever ran
;  last -- one OUT, and it removes a whole class of ordering bug.
;
;  AND THE MIXER NEVER SETS BITS 6 OR 7.  R7 bit 6 is the direction of
;  the AY's port A, and on a CPC that port IS the keyboard.  A mixer
;  value with bit 6 set would silence the keyboard, not a channel.
;  engine2/tools/gensnd.py asserts it at generation time; this file
;  never computes a mixer, it only copies one.
;
;  A STEP IS SIX BYTES: ticks, tone lo, tone hi, noise, mixer, volume --
;  in the order the driver writes them.  The common tick is inside a
;  held step and costs a decrement and a return; only a step CHANGE
;  writes the five registers.  That is what keeps nine ticks a frame
;  affordable -- see C_SND in main3.asm for the measurement.
; =====================================================================

SND_PA      equ #F4         ; PPI port A: the AY's data bus
SND_PC      equ #F6         ; PPI port C: bits 7,6 are the AY's control
SND_PCTL    equ #F7         ; PPI control register
SND_AOUT    equ #82         ; ...ports A and C to OUTPUT
SND_SEL     equ #C0         ; port C: %11, latch a register number
SND_WRITE   equ #80         ; port C: %10, write the data bus
SND_IDLE    equ #00         ; port C: %00, inactive

; ---------------------------------------------------------------------
;  snd_init -- silence everything.  Clobbers AF BC HL.
; ---------------------------------------------------------------------
snd_init
    xor  a
    ld   (snd_cur),a                ; nothing playing, nothing held
    ld   (snd_left),a
    ld   a,SND_SILENT
    ld   c,a
    ld   a,R_MIXER
    call snd_wr
    ld   c,0                        ; and all three volumes to zero, so a
    ld   a,R_VOL_A                  ; mixer that opens later cannot let a
    call snd_wr                     ; stale level through
    ld   c,0
    ld   a,R_VOL_B
    call snd_wr
    ld   c,0
    ld   a,R_VOL_C
    jp   snd_wr


; ---------------------------------------------------------------------
;  snd_play -- A = an effect index.  Starts it from the top.
;
;  IT ALWAYS WINS.  There is one channel and no priority: a new sound
;  replaces whatever was playing.  With six effects that are all under
;  600 ms and a game that fires at most five times a second, a queue
;  would cost more than it could ever be heard to be worth.
;
;  Clobbers AF HL DE.
; ---------------------------------------------------------------------
snd_play
    cp   SND_N
    ret  nc                         ; not an effect -- leave the last alone
    add  a,a
    ld   e,a
    ld   d,0
    ld   hl,SNDTAB
    add  hl,de
    ld   a,(hl)
    inc  hl
    ld   h,(hl)
    ld   l,a
    ld   (snd_cur),hl               ; -> the first step
    xor  a
    ld   (snd_left),a               ; ...and no ticks held, so the next
    ret                             ; tick loads it


; ---------------------------------------------------------------------
;  snd_tick -- one 50th of a second.  Clobbers AF BC DE HL.
;
;  Called from wait_vsync, which is called from inside the renderer --
;  so it must not touch IX, must not disturb SP, and must not care what
;  bank is paged.  It does none of those things: the tables are in the
;  code segment and the AY is I/O.
; ---------------------------------------------------------------------
snd_tick
    ld   hl,(snd_cur)
    ld   a,h
    or   l
    ret  z                          ; nothing playing: the common tick

    ld   a,(snd_left)               ; ---- still inside a step?
    or   a
    jr   z,st_step
    dec  a
    ld   (snd_left),a
    ret

st_step
    ld   a,(hl)                     ; ---- the next step: 0 ticks ends it
    or   a
    jr   z,st_stop
    dec  a                          ; this tick is the first of them
    ld   (snd_left),a

    inc  hl                         ; tone period, low then high
    ld   c,(hl)
    ld   a,R_TONE_LO
    push hl
    call snd_wr
    pop  hl
    inc  hl
    ld   c,(hl)
    ld   a,R_TONE_HI
    push hl
    call snd_wr
    pop  hl
    inc  hl                         ; noise period
    ld   c,(hl)
    ld   a,R_NOISE
    push hl
    call snd_wr
    pop  hl
    inc  hl                         ; the mixer -- copied, never computed
    ld   c,(hl)
    ld   a,R_MIXER
    push hl
    call snd_wr
    pop  hl
    inc  hl                         ; and the volume
    ld   c,(hl)
    ld   a,R_VOL_A
    push hl
    call snd_wr
    pop  hl
    inc  hl
    ld   (snd_cur),hl               ; -> the step after this one
    ret

st_stop
    ld   hl,0                       ; the list ran out: silence and stop
    ld   (snd_cur),hl
    ld   c,SND_SILENT
    ld   a,R_MIXER
    call snd_wr
    ld   c,0
    ld   a,R_VOL_A
    jp   snd_wr


; ---------------------------------------------------------------------
;  snd_wr -- A = an AY register, C = the value.
;
;  The same dance scan_keys does to READ a register, with the write
;  pulse on the end instead of an IN.  Port A is set to OUTPUT here
;  rather than assumed, because scan_keys leaves it that way but this
;  routine also runs from inside the renderer, where nothing has been
;  near the PPI for a while.
;
;  Clobbers AF BC.
; ---------------------------------------------------------------------
snd_wr
    ld   b,SND_PCTL                 ; ports A and C to output
    push af
    ld   a,SND_AOUT
    out  (c),a
    pop  af
    ld   b,SND_PA                   ; the register number on the data bus
    out  (c),a
    ld   b,SND_PC
    ld   a,SND_SEL
    out  (c),a                      ; %11: latch it
    xor  a
    out  (c),a                      ; %00: inactive
    ld   b,SND_PA                   ; the value on the data bus
    out  (c),c
    ld   b,SND_PC
    ld   a,SND_WRITE
    out  (c),a                      ; %10: write it
    xor  a
    out  (c),a                      ; %00: inactive
    ret


snd_cur     dw 0                    ; -> the step being held, 0 = silent
snd_left    db 0                    ; ...and how many ticks are left of it
