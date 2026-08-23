"""Find the largest viewport whose WORST whole frame fits the 80 ms budget.

    python3 engine2/tools/vpfit.py 42x96 40x96 38x96

For each WxH it rewrites engine2/src/vpcfg.inc (the single source of truth),
re-runs gentab, rebuilds and re-sweeps with emu_frame.py, and prints the
measured worst frame.  vpcfg.inc is restored on the way out, whatever
happens.

Legal viewports, from the assertions the code already carries:
    VP_BW  even (MAXPUSH = VP_BW/2), VP_BX + VP_BW <= 80
    VP_H   a multiple of 32 and <= 128 -- bg.asm needs CYH a multiple of 16
           (it counts CHARACTER ROWS and splits the half in two) and
           raster.asm needs VPLINE, VP_H*2 bytes, to be one page.
    so the height ladder is 128 / 96 / 64 and the width is free.
"""

import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_E2 = os.path.dirname(_HERE)
VPCFG = os.path.join(_E2, "src", "vpcfg.inc")


def rewrite(text, bw, h):
    bx = (80 - bw) // 2
    sub = {"VP_BX": bx, "VP_BW": bw, "VP_H": h, "CXH": bw, "CYH": h // 2,
           "FOCAL_V": h, "MAXPUSH": bw // 2}
    out = []
    for line in text.split("\n"):
        m = re.match(r"^(\w+)(\s+equ\s+)(-?\d+)(.*)$", line)
        if m and m.group(1) in sub:
            out.append("%s%s%-14d%s" % (m.group(1), m.group(2),
                                        sub[m.group(1)], m.group(4)))
        else:
            out.append(line)
    return "\n".join(out)


def main(*specs):
    orig = open(VPCFG).read()
    results = []
    try:
        for spec in specs:
            bw, h = (int(v) for v in spec.lower().split("x"))
            assert bw % 2 == 0 and (80 - bw) // 2 + bw <= 80
            assert h % 32 == 0 and h <= 128
            open(VPCFG, "w").write(rewrite(orig, bw, h))
            print("=" * 74)
            print(f"### VIEWPORT {bw}x{h} BYTES = {bw*2}x{h} PIXELS")
            print("=" * 74, flush=True)
            r = subprocess.run(
                [sys.executable, "-u", os.path.join(_HERE, "emu_frame.py"),
                 "sweep", "120", "80"], capture_output=True, text=True)
            print(r.stdout[-6000:])
            if r.returncode:
                print(r.stderr[-3000:])
                results.append((bw, h, None))
                continue
            m = re.search(r"worst frame MEASURED\s+([\d.]+) ms", r.stdout)
            results.append((bw, h, float(m.group(1)) if m else None))
    finally:
        open(VPCFG, "w").write(orig)
        print("\nvpcfg.inc restored")
    print("\n=== SUMMARY " + "=" * 60)
    for bw, h, w in results:
        print("  %2dx%-3d bytes (%3dx%3d px)  worst %s"
              % (bw, h, bw * 2, h,
                 "measurement failed" if w is None else
                 "%6.2f ms  %s" % (w, "FITS" if w <= 80 else "OVER")))


if __name__ == "__main__":
    main(*(sys.argv[1:] or ["42x96", "40x96", "38x96"]))
