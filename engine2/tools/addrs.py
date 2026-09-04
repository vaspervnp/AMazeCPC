"""The engine's working-RAM addresses, read out of the assembler source.

WHY THIS FILE EXISTS.  SOLID, MARK, QUADS and the march's buckets are plain
`equ`s in engine2/src/march.asm and engine2/src/kernel.asm, and rasm's .sym
file does not carry equs -- only labels.  So every harness that wanted to
read the live 16x16 map or the quad list had its own copy of the number, and
there were TWELVE of them.

When the whole block moved up one page to make room for raster_joint, the
engine was fine and every one of those harnesses started reading the page
below: emu_verify3 reported "player is in an open cell, SOLID = 12" and
"door (5,3) starts shut: SOLID = 0" -- four failures that looked like game
bugs and were nothing but stale constants.  A harness that reads the wrong
address does not fail loudly, it fails PLAUSIBLY, which is worse.

So the numbers are parsed from the source that defines them.  Move an equ
and every harness follows; delete one and the import fails immediately
instead of silently reading whatever is at the old address.
"""

import os
import re

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src")

# symbol -> the file that defines it
_WHERE = {
    "FTAB": "march.asm",
    "SOLID": "march.asm",
    "MARK": "march.asm",
    "BUCKETS": "march.asm",
    "BUCKHI": "march.asm",
    "BUCKSZ": "march.asm",
    "BUCK0": "march.asm",
    "MSTKBOT": "march.asm",
    "MSTKTOP": "march.asm",
    "QUADS": "memmap.inc",
    # ...and one OFFSET rather than an address, because a harness that wants
    # the bucket write pointers needs both halves and hardcoding either half
    # loses the same way.  emu_pacefit.py had FTAB_BPTR = #33E0 -- FTAB's
    # address from two moves ago, plus this offset -- and so read eight
    # bytes of the flood stack, got zero candidate faces on every state,
    # and made nrej = -nq.  That is a PLAUSIBLE failure, not a loud one:
    # the frame estimate quietly went 8 ms under and the least-squares fit
    # for C_FACE/C_REJ went singular.
    "O_BPTR": "march.asm",
    # The door tables moved out of the code segment and into the free RAM
    # above QUADS when MAXDOORS grew, so they are `equ`s now -- and rasm
    # puts only LABELS in the .sym file, never equs.  emu_verify3 read
    # DOOR_ST out of the symbol table and would simply have stopped
    # finding it.
    "DOORTAB": "game.asm",
    "DOOR_IDX": "game.asm",
    "DOOR_ST": "game.asm",
    "DOOR_TG": "game.asm",
    "MAXDOORS": "game.asm",
    "DOOR_SHUT": "game.asm",
    "DOOR_OPEN": "game.asm",
    # The minimap's bits and the monsters' table.  Both are `equ`s on a
    # base plus an offset rather than literals -- see _read -- because
    # they share one hole in the free RAM and writing four literals is
    # four chances to overlap.
    "MMVARS": "hud2.asm",
    "MMBITS": "hud2.asm",
    "MONTAB": "hud2.asm",
}

_EQU = r"^\s*%s\s+equ\s+(#?[0-9A-Za-z_]+(?:\s*\+\s*\d+)?)\s*(?:;.*)?$"


def _num(tok, path=None):
    """A hex literal, a decimal one, or SYMBOL+offset.

    THE THIRD FORM IS WHY THIS IS A FUNCTION.  MONTAB is `equ MMVARS+50`
    and MMBITS is `equ MMVARS+0`: they share one hole in the free RAM, so
    they are written as offsets from its base and a harness that wanted a
    literal would have to keep its own copy of the arithmetic.  One level
    of indirection is all the sources use and all this resolves.
    """
    tok = tok.strip()
    if "+" in tok:
        base, off = (t.strip() for t in tok.split("+", 1))
        return _num(base, path) + int(off)
    if tok.startswith("#"):
        return int(tok[1:], 16)
    if tok.isdigit():
        return int(tok)
    return _read_in(path, tok)


def _read_in(path, name):
    """The same parse, in a file already chosen -- for the recursion."""
    pat = re.compile(_EQU % re.escape(name), re.MULTILINE | re.IGNORECASE)
    with open(path) as f:
        m = pat.search(f.read())
    if not m:
        raise KeyError(f"{name} is not an `equ` in {os.path.basename(path)}")
    return _num(m.group(1), path)


def _read(name):
    # CASE-INSENSITIVE, because the asm is not consistent about it and the
    # caller should not have to know: march.asm writes SOLID and BUCKHI in
    # capitals, game.asm writes door_idx and door_st in lower case, and
    # both are equs of exactly the same kind.  Matching case-sensitively
    # made addrs.DOOR_IDX raise "not an `equ` any more" for a symbol
    # sitting right there in the file.
    path = os.path.join(SRC, _WHERE[name])
    pat = re.compile(_EQU % re.escape(name), re.MULTILINE | re.IGNORECASE)
    with open(path) as f:
        m = pat.search(f.read())
    if not m:
        raise KeyError(f"{name} is not an `equ` in src/{_WHERE[name]} any more")
    return _num(m.group(1), path)


_CACHE = {}


def __getattr__(name):
    if name not in _WHERE:
        raise AttributeError(name)
    if name not in _CACHE:
        _CACHE[name] = _read(name)
    return _CACHE[name]


def all_():
    return {k: _read(k) for k in _WHERE}


if __name__ == "__main__":
    for k, v in sorted(all_().items(), key=lambda kv: kv[1]):
        print(f"  {k:8s} = #{v:04X}  ({v})")
