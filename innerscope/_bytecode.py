"""Rewrite a function's bytecode so its locals can be read when it returns.

This module holds everything in innerscope that depends on the bytecode format.  The
``"bytecode"`` method runs a modified copy of the function's code object, made one of two
ways depending on the interpreter (see ``STRATEGY``):

``"capture"`` (CPython 3.11+)
    Insert three instructions right after the first ``RESUME`` that store the running frame
    in the function's globals::

        LOAD_GLOBAL  _innerscope_getframe_ + NULL    # sys._getframe
        CALL         0
        STORE_GLOBAL _innerscope_frame_

    Nothing else changes, so return values, generators, and exceptions behave exactly as in
    the original function.  After the call, the frame still owns its locals (we hold a
    reference to it), and ``frame.f_locals`` is the inner scope.  Since 3.11 every jump is
    relative, so inserting code moves only the absolute offsets in the exception table and
    the source locations in the location table.  Both are re-encoded, and the new code
    object is decoded and checked against what we meant to build before it is used.

``"returns"`` (CPython 3.10, and PyPy with 3.10-style bytecode)
    Replace each ``RETURN_VALUE`` with a ``JUMP_FORWARD`` to an epilogue that returns
    ``(return_value, locals(), secret)``.  A jump reaches 255 instructions, so each return
    must be that close to the next rewritten return or to the end of the function.

The formats used here are documented in CPython's ``InternalDocs/exception_handling.md`` (or
``Objects/exception_handling_notes.txt``) and ``InternalDocs/code_objects.md`` (or
``Objects/locations.md``).  When a new Python is released, the tests (run with
``--method bytecode``) are the check that these assumptions still hold.
"""

import dis
import sys

# Names injected into the globals of the rewritten function
GETFRAME = "_innerscope_getframe_"
FRAME = "_innerscope_frame_"
LOCALS = "_innerscope_locals_"
SECRET = "_innerscope_secret_"  # noqa: S105 (not a password)

# The newest Python version on which the "bytecode" method has been tested.  On newer
# versions it is still available, but "trace" is the default (see `cfg.py`).
TESTED_THROUGH = (3, 15)


def _detect_strategy():
    opmap = dis.opmap
    if (
        sys.implementation.name == "cpython"
        and sys.version_info >= (3, 11)
        and "RESUME" in opmap
        and hasattr(_detect_strategy.__code__, "co_exceptiontable")
        and hasattr(_detect_strategy.__code__, "co_positions")
    ):
        return "capture"
    if (
        sys.version_info >= (3, 10)
        and "CACHE" not in opmap
        and "RESUME" not in opmap
        and all(
            name in opmap
            for name in ["LOAD_GLOBAL", "CALL_FUNCTION", "BUILD_TUPLE", "JUMP_FORWARD"]
        )
    ):
        return "returns"
    return None  # pragma: no cover (unknown bytecode)


STRATEGY = _detect_strategy()


class BytecodeError(ValueError):
    """The bytecode of a function could not be rewritten (use the "trace" method instead)."""


def _cache_entries(opname):
    """The number of inline cache code units that follow an instruction."""
    table = getattr(dis, "_inline_cache_entries", None)
    if table is None:
        return 0  # Python < 3.11
    if hasattr(table, "get"):
        # 3.13+: keyed by name (a `frozendict` in 3.15, which is not a `dict` subclass)
        return table.get(opname, 0)
    return table[dis.opmap[opname]]  # 3.11 and 3.12: a list indexed by opcode


def assemble(instructions):
    """Make bytecode from ``(opname, arg)`` pairs, adding EXTENDED_ARG and cache entries."""
    extended_arg = dis.opmap["EXTENDED_ARG"]
    code = bytearray()
    for opname, arg in instructions:
        for shift in (24, 16, 8):
            if arg >> shift:
                code += bytes([extended_arg, (arg >> shift) & 0xFF])
        code += bytes([dis.opmap[opname], arg & 0xFF])
        code += bytes(2 * _cache_entries(opname))
    return bytes(code)


# Exception table (3.11+): each entry is start, length, target (all in code units), and
# `depth << 1 | lasti`.  Each number is written in big-endian groups of 6 bits, with 0x40 set
# on all but the last group, and 0x80 set on the first byte of an entry.
def _parse_exception_table(table):
    it = iter(table)

    def read(byte):
        value = byte & 0x3F
        while byte & 0x40:
            byte = next(it)
            value = (value << 6) | (byte & 0x3F)
        return value

    entries = []
    for byte in it:
        start = read(byte)
        end = start + read(next(it))
        target = read(next(it))
        depth_lasti = read(next(it))
        entries.append((start, end, target, depth_lasti))
    return entries


def _encode_exception_table(entries):
    table = bytearray()
    for start, end, target, depth_lasti in entries:
        for i, value in enumerate([start, end - start, target, depth_lasti]):
            groups = [value & 0x3F]
            value >>= 6
            while value:
                groups.append(value & 0x3F)
                value >>= 6
            groups.reverse()
            item = bytearray(group | 0x40 for group in groups[:-1])
            item.append(groups[-1])
            if i == 0:
                item[0] |= 0x80
            table += item
    return bytes(table)


# Location table (3.11+): runs of 1 to 8 code units that share a source position.  Each run
# begins with `0x80 | kind << 3 | (length - 1)`.  We write three kinds: 15 has no location;
# 13 has a line and no columns; 14 has a line, end line, and columns.  Lines are deltas from
# the previous run's line (a run without a location does not change it).  Numbers are written
# in little-endian groups of 6 bits, with 0x40 set on all but the last group; signed numbers
# put the sign in the lowest bit.
def _varint(value):
    out = bytearray()
    while value >= 0x40:
        out.append(0x40 | (value & 0x3F))
        value >>= 6
    out.append(value)
    return out


def _signed_varint(value):
    return _varint(((-value) << 1) | 1 if value < 0 else value << 1)


def _encode_location_table(positions, firstlineno):
    table = bytearray()
    line = firstlineno
    i = 0
    while i < len(positions):
        position = positions[i]
        j = i + 1
        while j < len(positions) and j - i < 8 and positions[j] == position:
            j += 1
        size = j - i - 1
        lineno, end_lineno, col, end_col = position
        if lineno is None:
            table.append(0x80 | 15 << 3 | size)
        elif end_lineno == lineno and col is None and end_col is None:
            table.append(0x80 | 13 << 3 | size)
            table += _signed_varint(lineno - line)
            line = lineno
        else:
            table.append(0x80 | 14 << 3 | size)
            table += _signed_varint(lineno - line)
            table += _varint(end_lineno - lineno)
            table += _varint(0 if col is None else col + 1)
            table += _varint(0 if end_col is None else end_col + 1)
            line = lineno
        i = j
    return bytes(table)


def _jump_targets(code):
    """Offsets (in bytes) that the instructions of ``code`` may jump to."""
    jumps = set(dis.hasjrel) | set(getattr(dis, "hasjabs", ()))
    return {inst.argval for inst in dis.get_instructions(code) if inst.opcode in jumps}


def insert_frame_capture(code):
    """Return a copy of ``code`` that stores its own frame in the global FRAME when it starts.

    This is the "capture" strategy for CPython 3.11+.  Raises BytecodeError if the result
    would not be what we expect.
    """
    instructions = list(dis.get_instructions(code))
    resume = next((i for i, inst in enumerate(instructions) if inst.opname == "RESUME"), None)
    if resume is None:  # pragma: no cover (every 3.11+ code object has RESUME)
        raise BytecodeError(f"No RESUME instruction in {code.co_name}")
    if resume + 1 == len(instructions):  # pragma: no cover (code ends in RETURN or RAISE)
        raise BytecodeError(f"Nothing after RESUME in {code.co_name}")
    # Insert after RESUME and its caches, i.e. at the start of the next instruction
    offset = instructions[resume + 1].offset
    if any(target < offset for target in _jump_targets(code)):  # pragma: no cover
        raise BytecodeError(f"{code.co_name} jumps into its prologue")

    getframe_index = len(code.co_names)
    frame_index = getframe_index + 1
    call = [("CALL", 0)]
    if "PRECALL" in dis.opmap:  # 3.11 only
        call.insert(0, ("PRECALL", 0))
    snippet = assemble(
        [
            ("LOAD_GLOBAL", getframe_index << 1 | 1),  # low bit: also push NULL
            *call,
            ("STORE_GLOBAL", frame_index),
        ]
    )
    units = offset // 2  # where the snippet goes, in code units
    size = len(snippet) // 2

    def move(unit, *, is_end=False):
        # An exception range that ends exactly where we insert does not cover the snippet,
        # but a range that starts there does.
        return unit + size if unit > units or (unit == units and not is_end) else unit

    entries = [
        (move(start), move(end, is_end=True), move(target), depth_lasti)
        for start, end, target, depth_lasti in _parse_exception_table(code.co_exceptiontable)
    ]
    positions = list(code.co_positions())
    positions[units:units] = [(None, None, None, None)] * size
    new_code = code.replace(
        co_code=code.co_code[:offset] + snippet + code.co_code[offset:],
        co_names=(*code.co_names, GETFRAME, FRAME),
        co_stacksize=max(code.co_stacksize, 2),
        co_exceptiontable=_encode_exception_table(entries),
        co_linetable=_encode_location_table(positions, code.co_firstlineno),
    )
    _check_frame_capture(
        code, new_code, offset=offset, size=len(snippet), entries=entries, positions=positions
    )
    return new_code


def _check_frame_capture(code, new_code, *, offset, size, entries, positions):
    """Decode ``new_code`` and compare it to what ``insert_frame_capture`` meant to build."""
    name = code.co_name
    old = list(dis.get_instructions(code))
    new = list(dis.get_instructions(new_code))
    inserted = [
        inst
        for inst in new
        if offset <= inst.offset < offset + size and inst.opname != "EXTENDED_ARG"
    ]
    expected = ["LOAD_GLOBAL", "CALL", "STORE_GLOBAL"]
    if "PRECALL" in dis.opmap:  # 3.11 only
        expected.insert(1, "PRECALL")
    if (
        [inst.opname for inst in inserted] != expected
        or inserted[0].argval != GETFRAME
        or "NULL" not in inserted[0].argrepr
        or inserted[-2].arg != 0
        or inserted[-1].argval != FRAME
    ):  # pragma: no cover
        raise BytecodeError(f"Unexpected instructions inserted into {name}: {inserted}")
    rest = [inst for inst in new if not offset <= inst.offset < offset + size]
    if [(inst.opname, inst.argval if inst.opcode not in dis.hasjrel else None) for inst in old] != [
        (inst.opname, inst.argval if inst.opcode not in dis.hasjrel else None) for inst in rest
    ]:  # pragma: no cover
        raise BytecodeError(f"Instructions of {name} changed when rewriting it")
    for before, after in zip(old, rest):
        if before.opcode in dis.hasjrel:
            target = before.argval + size if before.argval >= offset else before.argval
            if after.argval != target:  # pragma: no cover
                raise BytecodeError(f"A jump in {name} changed its target when rewriting it")
    if _parse_exception_table(new_code.co_exceptiontable) != entries:  # pragma: no cover
        raise BytecodeError(f"Could not rewrite the exception table of {name}")
    if list(new_code.co_positions()) != positions:  # pragma: no cover
        raise BytecodeError(f"Could not rewrite the location table of {name}")


class TooFarError(BytecodeError):
    """Some return statements are too far from the end to be rewritten ("returns" strategy)."""


def rewrite_returns(code):
    """Return ``(new_code, error)`` with each RETURN_VALUE jumping to an epilogue.

    This is the "returns" strategy for CPython 3.10 and PyPy.  The epilogue returns
    ``(return_value, locals(), secret)`` using the globals LOCALS and SECRET.  Returns that are
    too far from the end are left as they are, and ``error`` is the TooFarError to raise if
    one of them is used (or None if all were rewritten).
    """
    co_code = code.co_code
    returns = [inst.offset for inst in dis.get_instructions(code) if inst.opname == "RETURN_VALUE"]
    # The epilogue goes after the original code, where the location table has no lines, so
    # jumping to it doesn't look like running another line to debuggers or coverage tools.
    body = bytearray(co_code)
    jump_forward = dis.opmap["JUMP_FORWARD"]
    targets = [len(body)]  # where a return may jump: the epilogue or a rewritten return
    too_far = []
    for offset in reversed(returns):
        # JUMP_FORWARD counts instructions (2 bytes each) from the next instruction
        reachable = [t for t in targets if t - offset - 2 <= 2 * 255]
        if not reachable:
            # Every earlier return is even farther away, so stop here.
            too_far = returns[: returns.index(offset) + 1]
            break
        target = max(reachable)
        body[offset : offset + 2] = bytes([jump_forward, (target - offset - 2) // 2])
        targets.append(offset)
    epilogue = assemble(
        [
            ("LOAD_GLOBAL", len(code.co_names)),
            ("CALL_FUNCTION", 0),
            ("LOAD_GLOBAL", len(code.co_names) + 1),
            ("BUILD_TUPLE", 3),
            ("RETURN_VALUE", 0),
        ]
    )
    new_code = code.replace(
        co_code=bytes(body) + epilogue,
        co_names=(*code.co_names, LOCALS, SECRET),
        co_stacksize=max(code.co_stacksize, 3),
    )
    error = None
    if too_far:
        if len(too_far) == 1:
            which = "The first return statement is too far away."
        else:
            which = f"The first {len(too_far)} return statements are too far away."
        distance = min(targets) - too_far[-1] - 2
        error = TooFarError(
            "This may sound weird, but functions should have return statements that are close "
            "together or near the end of the function.  By close, I mean that each return "
            "statement in the compiled code should be within 512 bytes of another return "
            "statement or the end of the function.  Worried?  Don't be :).  This limitation "
            "is to ensure `innerscope` is rock-solid!"
            f"\n\n{which}  The next closest return statement is {distance} bytes away."
            "\n\nA cute workaround is to add code such as `if bool(): return`."
            "\n\nIf it's important to you that this limitation is fixed, then please submit "
            "an issue (or a pull request!) to:\nhttps://github.com/eriknw/innerscope\n\n"
            'Another workaround is to use `method="trace"`.  This will usually work, but it '
            "will be slower and may cause havoc if `sys.settrace` is used by anything else.  "
            "This limitation only applies to Python 3.10 and PyPy."
        )
    return new_code, error
