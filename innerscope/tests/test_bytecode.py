"""Edge cases for the "bytecode" method, checked against the "trace" method.

The "trace" method doesn't modify any code, so it serves as the reference: every function in
`CASES` must give the same scope and return value with both methods.  The tests of the
exception and location tables compare our encoders with CPython's own decoders.
"""

import contextlib
import dis
import gc
import random
import sys
import threading
import warnings
import weakref

import pytest

from innerscope import _bytecode, scoped_function

CAPTURE = _bytecode.STRATEGY == "capture"
# On an interpreter with no bytecode strategy, only the "trace" method is tested
requires_bytecode = pytest.mark.skipif(
    _bytecode.STRATEGY is None, reason='method="bytecode" is not supported here'
)
METHODS = [pytest.param("bytecode", marks=requires_bytecode), "trace"]
# WebAssembly builds may not start threads (as in CPython's test.support.threading_helper)
if sys.platform == "emscripten":
    CAN_START_THREAD = sys._emscripten_info.pthreads
else:
    CAN_START_THREAD = sys.platform != "wasi"
global_x = 1


def _compile(source, name, namespace=None):
    """Make a function from source code (for shapes too long or noisy to write out)."""
    namespace = {} if namespace is None else namespace
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)  # e.g. `return` in `finally` (3.14+)
        exec(compile(source, f"<{name}>", "exec"), namespace)
    return namespace[name]


def plain():
    a = 1
    b = a + 1


def early_return(flag):
    if flag:
        return 42
    a = 1
    return a


def return_in_loop(items):
    total = 0
    for item in items:
        total += item
        if total > 10:
            return "big"
    done = True
    return "small"


def return_in_nested_loops(n):
    for i in range(n):
        for j in range(n):
            if i * j == 4:
                return (i, j)


def ends_with_raise(flag):
    a = 1
    if flag:
        return a
    raise ValueError(a)


def ends_with_loop(n):
    while True:
        n -= 1
        if n < 0:
            return "done"


def try_except(x):
    try:
        y = 1 / x
    except ZeroDivisionError as exc:
        y = None
        caught = str(exc)
        return "caught"
    else:
        z = y * 2
    finally:
        w = "finally"
    return "ok"


def try_finally_return(x):
    try:
        y = x + 1
        return y
    finally:
        z = "finally"


finally_overrides = _compile(
    "def finally_overrides(x):\n"
    "    try:\n"
    "        return x\n"
    "    finally:\n"
    "        y = 'overridden'\n"
    "        return y\n",
    "finally_overrides",
)


def with_statement():
    with contextlib.nullcontext(5) as v:
        w = v + 1
        return w * 2


def nested_with():
    with contextlib.nullcontext(1) as a, contextlib.nullcontext(2) as b:
        with contextlib.suppress(KeyError):
            c = a + b
            {}["missing"]
        d = c + 1


def match_statement(x):
    match x:
        case [a, b]:
            kind = "pair"
        case {"k": a}:
            kind = "map"
        case int() if x > 0:
            kind = "positive"
        case _:
            kind = "other"
    return kind


def closure_and_cells():
    c = 10

    def inner():
        return c + global_x

    d = inner()
    c = 20
    e = inner()


def nonlocal_write():
    count = 0

    def bump():
        nonlocal count
        count += 1

    bump()
    bump()


def comprehensions(n):
    squares = [i * i for i in range(n)]
    evens = {i for i in range(n) if i % 2 == 0}
    lookup = {i: str(i) for i in range(n)}
    total = sum(i for i in range(n))


def comprehension_shadows_local():
    i = "kept"
    squares = [i * i for i in range(3)]


def deleted_local():
    a = 1
    b = 2
    del a


def unbound_local(flag):
    if flag:
        a = 1
    b = 2


def star_args(w, x=1, *args, y=2, z, **kwargs):
    total = w + x + y + z + sum(args) + sum(kwargs.values())


def defines_class():
    base = 10

    class A:
        x = base + global_x

        def method(self):
            return self.x

    instance = A()
    value = instance.method()


def documented():
    """A docstring is not a local."""
    a = 1


def walrus(items):
    if (n := len(items)) > 2:
        big = True
    return n


def exception_variable():
    try:
        raise KeyError("k")
    except KeyError as exc:
        message = str(exc)


many_names = _compile(
    "def many_names():\n"
    + "".join(f"    v{i} = g{i}\n" for i in range(300))
    + "    total = "
    + " + ".join(f"g{i}" for i in range(300))
    + "\n",
    "many_names",
    {f"g{i}": i for i in range(300)},
)

# Returns constant 300 (with EXTENDED_ARG before RETURN_CONST on PyPy 3.12)
many_constants = _compile(
    "def many_constants(flag):\n"
    + "".join(f"    c{i} = {i}.5\n" for i in range(300))
    + "    if flag:\n        return 'early'\n    return 'late'\n",
    "many_constants",
)

many_handlers = _compile(
    "def many_handlers():\n"
    + "".join(
        f"    try:\n        x{i} = {i} // ({i} % 7)\n    except ZeroDivisionError:\n"
        f"        x{i} = -1\n"
        for i in range(300)
    )
    + "    return x299\n",
    "many_handlers",
)

long_early_return = _compile(
    "def long_early_return(flag):\n"
    "    if flag:\n"
    "        return 'early'\n" + "    global_x\n" * 400 + "    late = True\n",
    "long_early_return",
    {"global_x": 1},
)

CASES = [
    (plain, ()),
    (early_return, (True,)),
    (early_return, (False,)),
    (return_in_loop, ([1, 2, 3],)),
    (return_in_loop, ([5, 6, 7],)),
    (return_in_nested_loops, (3,)),
    (return_in_nested_loops, (1,)),
    (ends_with_raise, (True,)),
    (ends_with_loop, (3,)),
    (try_except, (0,)),
    (try_except, (2,)),
    (try_finally_return, (1,)),
    (finally_overrides, (1,)),
    (with_statement, ()),
    (nested_with, ()),
    (match_statement, ([1, 2],)),
    (match_statement, ({"k": 3},)),
    (match_statement, (5,)),
    (match_statement, (-5,)),
    (closure_and_cells, ()),
    (nonlocal_write, ()),
    (comprehensions, (4,)),
    (comprehension_shadows_local, ()),
    (deleted_local, ()),
    (unbound_local, (False,)),
    (unbound_local, (True,)),
    (star_args, (1, 2, 3, 4), {"z": 5, "extra": 6}),
    (defines_class, ()),
    (documented, ()),
    (walrus, ([1, 2, 3],)),
    (walrus, ([],)),
    (exception_variable, ()),
    (many_names, ()),
    (many_constants, (True,)),
    (many_constants, (False,)),
    (many_handlers, ()),
    (long_early_return, (True,)),
    (long_early_return, (False,)),
    (lambda q, r=2: q + r, (1,)),
]


def _normalize(value):
    """Functions, classes, and instances defined in each call differ; compare their names."""
    if isinstance(value, type) or callable(value):
        return ("callable", getattr(value, "__qualname__", repr(value)))
    if type(value).__qualname__.startswith("defines_class."):
        return ("instance", type(value).__qualname__)
    return value


def _call(func, args, kwargs, method):
    scope = scoped_function(func, method=method)(*args, **kwargs)
    inner = {key: _normalize(val) for key, val in scope.inner_scope.items()}
    outer = {key: _normalize(val) for key, val in scope.outer_scope.items()}
    return inner, outer, _normalize(scope.return_value)


def _case_id(case):
    func, args = case[:2]
    return f"{func.__name__}{args!r}"[:60]


@requires_bytecode
@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_methods_agree(case):
    func, args, kwargs = (*case, {}) if len(case) == 2 else case
    expected = _call(func, args, kwargs, "trace")
    if _bytecode.STRATEGY == "returns" and func is long_early_return and args == (True,):
        with pytest.raises(_bytecode.TooFarError, match="too far away"):
            _call(func, args, kwargs, "bytecode")
        return
    assert _call(func, args, kwargs, "bytecode") == expected
    # And this is what the original function returns
    assert expected[2] == _normalize(func(*args, **kwargs))


def test_some_expected_scopes():
    assert scoped_function(plain)() == {"a": 1, "b": 2}
    scope = scoped_function(try_except)(0)
    assert scope == {"x": 0, "y": None, "caught": "division by zero", "w": "finally"}
    assert scope.return_value == "caught"
    scope = scoped_function(closure_and_cells)()
    assert scope.inner_scope.keys() == {"c", "d", "e", "inner"}
    assert (scope["c"], scope["d"], scope["e"]) == (20, 11, 21)
    assert scoped_function(nonlocal_write)()["count"] == 2
    assert scoped_function(comprehension_shadows_local)() == {"i": "kept", "squares": [0, 1, 4]}
    assert scoped_function(deleted_local)() == {"b": 2}
    assert scoped_function(unbound_local)(False) == {"flag": False, "b": 2}
    scope = scoped_function(many_names)()
    assert scope["v299"] == 299
    assert scope["total"] == sum(range(300))
    scope = scoped_function(many_handlers)()
    assert (scope["x6"], scope["x7"], scope["x8"]) == (6 // 6, -1, 8 // 1)
    assert scope.return_value == 299 // (299 % 7)


@pytest.mark.parametrize("method", METHODS)
def test_traceback_line_numbers(method):
    def f(x):
        y = x + 1
        z = y / 0  # line 3 of f
        return z

    with pytest.raises(ZeroDivisionError) as info:
        scoped_function(f, method=method)(1)
    tb = info.value.__traceback__
    while tb.tb_next is not None:
        tb = tb.tb_next
    assert tb.tb_frame.f_code.co_name == "f"
    assert tb.tb_lineno == f.__code__.co_firstlineno + 2


@requires_bytecode
@pytest.mark.parametrize(
    ("func", "args"), [c[:2] for c in CASES[:20]], ids=[_case_id(c) for c in CASES[:20]]
)
def test_line_events_under_a_tracer(func, args):
    """Debuggers and coverage tools must see the same lines as in the original function."""

    def lines_traced(f):
        lines = []

        def tracer(frame, event, arg):
            if frame.f_code.co_name == func.__code__.co_name:
                if event == "line":
                    lines.append(frame.f_lineno)
                return tracer
            return None

        prev = sys.gettrace()
        sys.settrace(tracer)
        try:
            f(*args)
        except ValueError:
            pass
        finally:
            sys.settrace(prev)
        return lines

    expected = lines_traced(func)
    scoped = scoped_function(func, method="bytecode")
    assert lines_traced(scoped) == expected


@pytest.mark.skipif(sys.implementation.name != "cpython", reason="needs reference counting")
@pytest.mark.parametrize("method", METHODS)
def test_no_reference_cycles(method):
    class Canary:
        pass

    def f():
        canary = Canary()
        frame_holder = [sys._getframe()]  # a cycle the function itself creates
        del frame_holder

    refs = []

    def g():
        canary = Canary()
        refs.append(weakref.ref(canary))
        yield 1
        yield 2

    def raises():
        canary = Canary()
        refs.append(weakref.ref(canary))
        raise ValueError("boom")

    gc.disable()
    try:
        scope = scoped_function(f, method=method)()
        ref = weakref.ref(scope["canary"])
        del scope
        assert ref() is None

        # A function that raises
        with pytest.raises(ValueError, match="boom"):
            scoped_function(raises, method=method)()
        assert refs.pop()() is None

        # A generator that is abandoned before it finishes
        gen = scoped_function(g, method=method)()
        assert next(gen) == 1
        ref = refs.pop()
        assert ref() is not None  # the generator is suspended
        del gen
        assert ref() is None
    finally:
        gc.enable()


def test_trace_method_keeps_other_tracers():
    """Interleaved calls with the trace method must leave a debugger or coverage tool working."""
    calls = []

    def other_tracer(frame, event, arg):  # stands in for coverage or a debugger
        if event == "call":
            calls.append(frame.f_code.co_name)

    def g1():
        a = 1
        yield a

    def g2():
        b = 2
        yield b

    def probe():
        pass

    prev = sys.gettrace()
    sys.settrace(other_tracer)
    try:
        it1 = scoped_function(g1, method="trace")()
        it2 = scoped_function(g2, method="trace")()
        next(it1)
        next(it2)  # it2's trace function wraps it1's
        assert list(it1) == []  # it1 finishes first
        assert list(it2) == []
        probe()
        probe_seen = "probe" in calls
        current = sys.gettrace()
    finally:
        sys.settrace(prev)
    assert probe_seen
    assert current is other_tracer


def test_recursion():
    @scoped_function
    def factorial(n):
        if n <= 1:
            return 1
        inner = factorial(n - 1)
        return n * inner.return_value

    scope = factorial(5)
    assert scope.return_value == 120
    assert scope["inner"].return_value == 24
    assert scope["inner"]["inner"]["n"] == 3


@pytest.mark.skipif(not CAN_START_THREAD, reason="cannot start threads")
@pytest.mark.parametrize("method", METHODS)
def test_threads(method):
    sf = scoped_function(match_statement, method=method)
    errors = []

    def worker(k):
        for _ in range(100):
            scope = sf([k, -k])
            if scope["a"] != k or scope["b"] != -k:
                errors.append(dict(scope))

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors


@pytest.mark.skipif(_bytecode.STRATEGY != "returns", reason="only rewriting returns has limits")
def test_return_distance_boundary():
    """A rewritten return can jump at most 255 instructions (510 bytes) forward."""
    for n in range(100, 160):
        f = long_early_return_n(n)
        returns = [i.offset for i in dis.get_instructions(f) if i.opname == "RETURN_VALUE"]
        # The first return jumps to the last one, which jumps to the epilogue right after it
        distance = returns[-1] - returns[0] - 2
        sf = scoped_function(f, method="bytecode")
        if distance <= 510:
            assert sf(True).return_value == "early"
        else:
            with pytest.raises(_bytecode.TooFarError):
                sf(True)
        assert sf(False)["late"] is True


def long_early_return_n(n):
    # Returning variables (not constants) gives RETURN_VALUE everywhere, even on PyPy 3.12
    return _compile(
        "def f(flag):\n    early = 'early'\n    if flag:\n        return early\n"
        + "    global_x\n" * n
        + "    late = True\n    return late\n",
        "f",
        {"global_x": 1},
    )


@pytest.mark.skipif(not CAPTURE, reason="CPython 3.11+")
def test_exception_table_matches_cpython():
    parse = getattr(dis, "_parse_exception_table", None)
    if parse is None:  # pragma: no cover
        pytest.skip("dis._parse_exception_table is not available")
    funcs = [case[0] for case in CASES]
    for func in funcs:
        code = func.__code__
        ours = _bytecode._parse_exception_table(code.co_exceptiontable)
        theirs = [
            (e.start // 2, e.end // 2, e.target // 2, e.depth << 1 | e.lasti) for e in parse(code)
        ]
        assert ours == theirs
        # CPython writes the shortest encoding, and so do we
        assert _bytecode._encode_exception_table(ours) == code.co_exceptiontable
    # Random tables, decoded by CPython
    rng = random.Random(0)
    code = many_handlers.__code__
    for _ in range(200):
        entries = []
        for _ in range(rng.randrange(1, 8)):
            start = rng.choice([0, 1, 63, 64, 4095, 4096, rng.randrange(1 << 20)])
            end = start + rng.choice([1, 63, 64, rng.randrange(1, 1 << 16)])
            target = rng.randrange(1 << 18)
            entries.append((start, end, target, rng.randrange(256)))
        table = _bytecode._encode_exception_table(entries)
        assert _bytecode._parse_exception_table(table) == entries
        new_code = code.replace(co_exceptiontable=table)
        theirs = [
            (e.start // 2, e.end // 2, e.target // 2, e.depth << 1 | e.lasti)
            for e in parse(new_code)
        ]
        assert theirs == entries


@pytest.mark.skipif(not CAPTURE, reason="CPython 3.11+")
def test_location_table_round_trips():
    funcs = [case[0] for case in CASES]
    for func in funcs:
        code = func.__code__
        positions = list(code.co_positions())
        table = _bytecode._encode_location_table(positions, code.co_firstlineno)
        assert list(code.replace(co_linetable=table).co_positions()) == positions
    # Random positions of every kind we encode
    if next(compile("x", "", "eval").co_positions())[2] is None:
        pytest.skip("debug ranges are off (-X no_debug_ranges), so columns are dropped")
    rng = random.Random(0)
    code = many_handlers.__code__
    units = len(code.co_code) // 2
    for _ in range(50):
        positions = []
        line = code.co_firstlineno
        while len(positions) < units:
            kind = rng.randrange(4)
            if kind == 0:
                position = (None, None, None, None)
            else:
                line = max(1, line + rng.randrange(-100, 100))
                if kind == 1:
                    position = (line, line, None, None)
                elif kind == 2:
                    end = line + rng.choice([0, 0, 1, 70])
                    position = (line, end, rng.randrange(300), rng.randrange(300))
                else:
                    position = (line, line + rng.randrange(3), None, None)
            positions.extend([position] * rng.choice([1, 1, 2, 7, 8, 9, 20]))
        positions = positions[:units]
        table = _bytecode._encode_location_table(positions, code.co_firstlineno)
        assert list(code.replace(co_linetable=table).co_positions()) == positions


def test_assemble():
    code = _bytecode.assemble([("LOAD_GLOBAL", 0x12345), ("POP_TOP", 0)])
    instructions = list(dis.get_instructions(_with_code(code)))
    load = next(inst for inst in instructions if inst.opname == "LOAD_GLOBAL")
    assert load.arg == 0x12345


def _with_code(co_code):
    """A code object with the given bytecode and enough names (only for disassembly)."""
    names = tuple(f"n{i}" for i in range(0x12345 + 1))
    return plain.__code__.replace(co_code=co_code, co_names=names, co_linetable=b"")


def test_default_method():
    import importlib

    import innerscope.cfg

    old = innerscope.cfg.default_method
    try:
        importlib.reload(innerscope.cfg)
        if _bytecode.STRATEGY is not None and sys.version_info[:2] <= _bytecode.TESTED_THROUGH:
            assert innerscope.cfg.default_method == "bytecode"
        else:  # pragma: no cover
            assert innerscope.cfg.default_method == "trace"
    finally:
        innerscope.cfg.default_method = old
