"""Amstrad CPC hardware constants: Mode 0 pixel encoding, palette, screen addressing.

Mode 0 is 160x200, 2 pixels per byte, 16 pens.  A byte holds a left and a right
pixel, with the pen's 4 bits scattered across the byte:

    left  pixel: bit0->b7  bit1->b3  bit2->b5  bit3->b1
    right pixel: bit0->b6  bit1->b2  bit2->b4  bit3->b0

so pen 0 is &00, pen 15 is &FF, and everything in between is interleaved.
"""

# ---------------------------------------------------------------- screen ----

SCR_W_BYTES = 80           # 160 pixels / 2 pixels per byte
SCR_H = 200
FRONT_BUFFER = 0xC000
BACK_BUFFER = 0x8000


def line_addr(y, base=FRONT_BUFFER):
    """Address of the leftmost byte of scanline `y`.

    The CPC screen is stored in 8 interleaved blocks: consecutive scanlines are
    &800 apart within a character row, and character rows are 80 bytes apart.
    """
    return base + (y & 7) * 0x800 + (y >> 3) * SCR_W_BYTES


def addr_of(x_byte, y, base=FRONT_BUFFER):
    return line_addr(y, base) + x_byte


# ------------------------------------------------------------ mode 0 pen ----

def mode0_byte(left_pen, right_pen):
    """Encode two pens into one Mode 0 byte."""
    b = 0
    for pen, bits in ((left_pen, (7, 3, 5, 1)), (right_pen, (6, 2, 4, 0))):
        for i, bit in enumerate(bits):
            if pen & (1 << i):
                b |= 1 << bit
    return b


def mode0_solid(pen):
    """Byte with both pixels set to `pen` -- what we PUSH for a solid span."""
    return mode0_byte(pen, pen)


MODE0_SOLID = [mode0_solid(p) for p in range(16)]


# ---------------------------------------------------------------- colour ----

# Firmware ink number -> (value to OUT to the gate array, RGB for previews).
# The gate array wants &40 + hardware colour; these are the ready-to-send bytes.
INKS = {
    0:  (0x54, (0x00, 0x00, 0x00)),  # Black
    1:  (0x44, (0x00, 0x00, 0x80)),  # Blue
    2:  (0x55, (0x00, 0x00, 0xFF)),  # Bright Blue
    3:  (0x5C, (0x80, 0x00, 0x00)),  # Red
    4:  (0x58, (0x80, 0x00, 0x80)),  # Magenta
    5:  (0x5D, (0x80, 0x00, 0xFF)),  # Mauve
    6:  (0x4C, (0xFF, 0x00, 0x00)),  # Bright Red
    7:  (0x45, (0xFF, 0x00, 0x80)),  # Purple
    8:  (0x4D, (0xFF, 0x00, 0xFF)),  # Bright Magenta
    9:  (0x56, (0x00, 0x80, 0x00)),  # Green
    10: (0x46, (0x00, 0x80, 0x80)),  # Cyan
    11: (0x57, (0x00, 0x80, 0xFF)),  # Sky Blue
    12: (0x5E, (0x80, 0x80, 0x00)),  # Yellow
    13: (0x40, (0x80, 0x80, 0x80)),  # White
    14: (0x5F, (0x80, 0x80, 0xFF)),  # Pastel Blue
    15: (0x4E, (0xFF, 0x80, 0x00)),  # Orange
    16: (0x47, (0xFF, 0x80, 0x80)),  # Pink
    17: (0x4F, (0xFF, 0x80, 0xFF)),  # Pastel Magenta
    18: (0x52, (0x00, 0xFF, 0x00)),  # Bright Green
    19: (0x42, (0x00, 0xFF, 0x80)),  # Sea Green
    20: (0x53, (0x00, 0xFF, 0xFF)),  # Bright Cyan
    21: (0x5A, (0x80, 0xFF, 0x00)),  # Lime
    22: (0x59, (0x80, 0xFF, 0x80)),  # Pastel Green
    23: (0x5B, (0x80, 0xFF, 0xFF)),  # Pastel Cyan
    24: (0x4A, (0xFF, 0xFF, 0x00)),  # Bright Yellow
    25: (0x43, (0xFF, 0xFF, 0x80)),  # Pastel Yellow
    26: (0x4B, (0xFF, 0xFF, 0xFF)),  # Bright White
}


def ink_ga(ink):
    """Byte to OUT to the gate array to set the currently selected pen."""
    return INKS[ink][0]


def ink_rgb(ink):
    return INKS[ink][1]
