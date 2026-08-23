"""The two numbers the hybrid-LOD architecture needs out of tst_byte.asm
that emu_byte.py does not print: the PER-SCANLINE constant of the
GENERATED block (ld de,nn : push de), against the flat PUSH block's, and
both slopes re-confirmed in the same session.

    python3 engine2/tools/emu_lod0.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import emu_byte as eb                                       # noqa: E402


def main():
    rig = eb.Rig()
    tnop = rig.time(eb.E["nop"])
    tempty = rig.time(eb.E["empty"])
    print(f"calibration: 100 NOPs = {tnop - tempty:8.3f} us "
          f"(must be 100.000)")
    print()
    for name, idx in (("PUSH DE flat", "push"),
                      ("PUSH DE/PUSH BC", "push2"),
                      ("LD DE,nn : PUSH DE (generated)", "pushimm")):
        # slope in BYTES at a fixed line count
        NL = 32
        t22 = rig.time(eb.E[idx], nbytes=22, nlines=NL)
        t44 = rig.time(eb.E[idx], nbytes=44, nlines=NL)
        byte = (t44 - t22) / (22 * NL)
        # slope in LINES at a fixed byte count
        l16 = rig.time(eb.E[idx], nbytes=44, nlines=16)
        l48 = rig.time(eb.E[idx], nbytes=44, nlines=48)
        line = (l48 - l16) / 32.0
        print(f"{name:32} {byte:7.4f} us/byte   "
              f"{line:8.3f} us/scanline total   "
              f"fixed {line - byte * 44:7.3f} us/scanline")
    print()
    print("  'fixed' is the per-scanline setup that is NOT bytes: the "
          "ld sp,hl,\n  the patched JP, the +&800 step and the character-"
          "row wrap.")


if __name__ == "__main__":
    main()
