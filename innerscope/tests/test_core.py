import pytest
import builtins
import innerscope
from pytest import raises
from innerscope import scoped_function, cfg

global_x = 1
hex = 1  # shadow a builtin


def test_no_args():
    @scoped_function
    def f1():
        a = 1
        b = a + 1

    assert not f1.missing
    scope1 = f1()
    assert len(scope1) == 2
    assert scope1 == dict(a=1, b=2)
    assert scoped_function(f1)() == dict(a=1, b=2)

    def f2():
        c = b + 1

    def check(f2bound):
        assert not f2bound.missing
        assert f2bound.inner_names == {"c"}
        assert f2bound.outer_scope["b"] == 2
        scope2 = f2bound()
        assert scope2 == dict(b=2, c=3)

    check(innerscope.bindwith(b=2)(f2))
    check(innerscope.bindwith({"b": 2})(f2))

    sf2 = scoped_function(f2)
    assert sf2.missing == {"b"}
    with raises(NameError, match="Undefined variables: 'b'"):
        sf2()

    check(sf2.bind(b=2))
    check(sf2.bind({"b": 2}))
    check(sf2.bind(scope1))
    check(scope1.bindto(sf2))
    check(scope1.bindto(sf2.func))
    check(scoped_function(sf2, scope1))
    check(scoped_function(sf2.func, scope1))


def test_no_args_call():
    def f1():
        a = 1
        b = a + 1

    def check(scope1):
        assert scope1 == dict(a=1, b=2)

    scope1 = innerscope.call(f1)
    check(scope1)
    check(innerscope.callwith()(f1))

    def f2():
        c = b + 1

    def check(scope2):
        assert scope2 == dict(b=2, c=3)

    check(scope1.call(f2))
    check(scope1.callwith()(f2))

    with raises(TypeError, match="missing 1 required positional"):
        scope1.call()
    with raises(TypeError, match="missing 1 required positional"):
        innerscope.call()


def test_with_args():
    def f1(a):
        b = a + 1

    def check(scope1):
        assert scope1 == dict(a=1, b=2)

    assert not scoped_function(f1).missing
    scope1 = scoped_function(f1)(1)
    check(scope1)
    check(innerscope.call(f1, 1))
    check(innerscope.callwith(1)(f1))

    def f2(c):
        d = a + 3
        e = b + c

    def check(scope2):
        assert scope2 == dict(a=1, b=2, c=3, d=4, e=5)

    sf2 = scoped_function(f2)
    assert sf2.missing == {"a", "b"}
    check(sf2.bind(a=1, b=2)(3))
    check(sf2.bind({"a": 1}, {"b": 2})(3))
    check(sf2.bind(scope1)(3))
    check(scope1.bindto(sf2)(3))
    check(scope1.bindto(f2)(3))
    check(scope1.call(f2, 3))
    check(scope1.callwith(3)(f2))


def test_scoped_function_decorators():
    @scoped_function
    def f1():
        a = 1

    @scoped_function()
    def f2():
        a = 1

    @scoped_function({"a": 1})
    def f3():
        b = a + 1

    assert f1() == {"a": 1}
    assert f2() == {"a": 1}
    assert f3() == {"a": 1, "b": 2}


def test_bindto_keeps_options():
    @scoped_function(use_closures=True, use_globals=False)
    def f1():
        a = 1

    def f2():
        b = a + 1

    scope1 = f1()
    sf2 = scope1.bindto(f2)
    assert sf2.use_closures is True
    assert sf2.use_globals is False

    sf2 = scope1.bindto(f2, use_closures=False, use_globals=True)
    assert sf2.use_closures is False
    assert sf2.use_globals is True
    assert dict(sf2()) == {"a": 1, "b": 2}


def test_use_closure():
    a = b = c = d = e = x = y = -1

    def f1(a):
        b = a + x + 2

    assert not scoped_function(f1).missing
    assert scoped_function(f1, use_closures=False).missing == {"x"}

    # Overwrite closure
    scope1 = scoped_function(f1, {"x": 10})(1)
    assert scope1 == dict(x=10, a=1, b=13)

    # Default closure
    scope1 = scoped_function(f1)(1)
    assert scope1 == dict(x=-1, a=1, b=2)

    def f2(c):
        d = a + 2 + y
        e = b + c

    assert not scoped_function(f2).missing

    # Overwrite closure
    scope2 = scoped_function(f2).bind(scope1, y=1)(3)
    assert scope2 == dict(y=1, a=1, b=2, c=3, d=4, e=5)

    # Overwrite closure (partially)
    scope2 = scoped_function(f2, scope1)(3)
    assert scope2 == dict(y=-1, a=1, b=2, c=3, d=2, e=5)

    # Default closure
    scope2 = scoped_function(f2)(3)
    assert scope2 == dict(y=-1, a=-1, b=-1, c=3, d=0, e=2)


def test_use_globals():
    def f1():
        x = global_x

    assert not scoped_function(f1, use_globals=True).missing
    assert scoped_function(f1, use_globals=False).missing == {"global_x"}
    assert scoped_function(f1, use_globals=True)() == {"x": 1, "global_x": 1}
    scope = scoped_function(f1, {"global_x": 1}, use_globals=True)()
    assert scope == {"x": 1, "global_x": 1}


def test_closures():
    def f(arg_f):
        nonlocal_y = 2

        def g(arg_g):
            local_z = global_x + nonlocal_y + arg_f + arg_g

        return g

    assert scoped_function(f).inner_names == {"arg_f", "nonlocal_y", "g"}
    g = f(1)
    scoped_g = scoped_function(g)
    assert scoped_g.inner_names == {"arg_g", "local_z"}
    assert scoped_g.outer_scope == {"global_x": 1, "arg_f": 1, "nonlocal_y": 2}
    assert scoped_g(3) == {"arg_f": 1, "nonlocal_y": 2, "global_x": 1, "arg_g": 3, "local_z": 7}


def test_has_builtins():
    @innerscope.call
    def f():
        x = min(1, 2)
        d = dict(a=x, b=3)

    assert f == dict(x=1, d={"a": 1, "b": 3})


def test_raises_error():
    @scoped_function
    def f():
        1 / 0

    with raises(ZeroDivisionError):
        f()


def test_return_values():
    @innerscope.call
    def f1():
        pass

    assert f1.return_value is None
    assert f1 == {}

    @innerscope.call
    def f2():
        return 5

    assert f2.return_value == 5
    assert f2 == {}

    @innerscope.callwith(0)
    def f3(x):
        y = x + 1
        return x + 1 + y

    assert f3.return_value == 2
    assert f3 == {"x": 0, "y": 1}


def test_early_return():
    # We do not yet check for return statements in the function body upon creation
    @scoped_function
    def f(boolean):
        if boolean:
            return 42
        a = 1
        b = a + 1

    # But we can check the return type
    # with raises(ValueError, match="must return at the very end of the function"):
    #     f(True)
    scope = f(True)
    assert scope == {"boolean": True}
    assert scope.return_value == 42

    scope = f(False)
    assert scope == dict(a=1, b=2, boolean=False)

    @scoped_function
    def g(boolean):
        if boolean:
            return (1, 2, 3)
        a = 1
        b = a + 1

    # with raises(ValueError, match="must return at the very end of the function"):
    #     g(True)
    scope = g(True)
    assert scope == {"boolean": True}
    assert scope.return_value == (1, 2, 3)

    scope = g(False)
    assert scope == dict(a=1, b=2, boolean=False)


def test_difficult_return():
    # fmt: off
    x = 1

    @scoped_function
    def f1(arg):
        if arg:
            return 1
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        y = x
        return 2

    if cfg.default_method == 'bytecode':
        with raises(ValueError, match="The first return statement is too far away"):
            f1(True)
    if cfg.default_method == 'trace':
        scope = f1(True)
        assert scope == {'x': 1, 'arg': True}
        assert scope.return_value == 1

    scope = f1(False)
    assert scope == {'arg': False,  'y': 1, 'x': 1}
    assert scope.return_value == 2

    @scoped_function
    def f2(arg):
        if arg == 0:
            return 1
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        if arg == 1:
            return 2
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        y = x
        return 3

    scope = f2(0)
    assert scope == {'arg': 0, 'x': 1}
    assert scope.return_value == 1

    scope = f2(1)
    assert scope == {'arg': 1, 'x': 1}
    assert scope.return_value == 2
    scope = f2(2)
    assert scope == {'arg': 2, 'x': 1, 'y': 1}
    assert scope.return_value == 3

    @scoped_function
    def f3(arg):
        if arg == 0:
            return 1
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        if arg == 1:
            return (1, 2, 3)
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ; x ;
        if arg == 2:
            return 3
        y = x
        return 4

    if cfg.default_method == 'bytecode':
        with raises(ValueError, match="The first 2 return statements are too far away"):
            f3(0)
        with raises(ValueError, match="The first 2 return statements are too far away"):
            f3(1)
    if cfg.default_method == 'trace':
        scope = f3(0)
        assert scope == {'arg': 0, 'x': 1}
        assert scope.return_value == 1
        scope = f3(1)
        assert scope == {'arg': 1, 'x': 1}
        assert scope.return_value == (1, 2, 3)
    scope = f3(2)
    assert scope == {'arg': 2, 'x': 1}
    assert scope.return_value == 3
    scope = f3(3)
    assert scope == {'arg': 3, 'x': 1, 'y': 1}
    assert scope.return_value == 4
    # fmt: on


# @pytest.mark.xfail(reason="Local variable can't yet be the same name as an outer variable")
# This limitation may actually be okay to live with
def test_inner_and_outer_variable():
    def f1():
        x = 1

    scope1 = innerscope.call(f1)
    assert scope1 == {"x": 1}

    @scope1.bindto
    def f2():
        x = x + 1  # pragma: no cover

    with raises(
        UnboundLocalError, match="local variable 'x' referenced before assignment.\n\nThis probably"
    ):
        f2()

    @scoped_function
    def f3():
        raise UnboundLocalError("hahaha")

    with raises(UnboundLocalError, match="hahaha$"):
        f3()


def test_default_args():
    @innerscope.callwith(0, z=3)
    def f(w, x=1, *args, y=2, z, **kwargs):
        pass

    assert f == {"w": 0, "x": 1, "y": 2, "z": 3, "args": (), "kwargs": {}}


def test_list_comprehension():
    closure_val = 2

    def f():
        y = [i for i in range(global_x)]
        z = [j for j in range(closure_val)]

    assert innerscope.call(f) == {"y": [0], "z": [0, 1], "global_x": 1, "closure_val": 2}
    scoped_f = scoped_function(f, use_globals=False, use_closures=False)
    assert scoped_f.missing == {"global_x", "closure_val"}
    scope = scoped_f.bind(global_x=2, closure_val=1)()
    assert scope == {"y": [0, 1], "z": [0], "global_x": 2, "closure_val": 1}


def test_inner_functions():
    def f():
        closure_val = 10

        def g():
            y = global_x + 1
            z = closure_val + 1
            return y, z

    scope = innerscope.call(f)
    assert scope.keys() == {"closure_val", "g", "global_x"}
    assert scope["g"]() == (2, 11)
    scoped_f = scoped_function(f, use_globals=False, use_closures=False)
    assert scoped_f.missing == {"global_x"}
    scope = scoped_f.bind(global_x=2)()
    assert scope.keys() == {"closure_val", "g", "global_x"}
    assert scope["g"]() == (3, 11)


def test_inner_class():
    def f1():
        class A:
            x = global_x + 1

    scope = innerscope.call(f1)
    assert scope.keys() == {"A", "global_x"}
    assert scope["A"].x == 2
    scoped_f = scoped_function(f1, use_globals=False, use_closures=False)
    assert scoped_f.missing == {"global_x"}
    assert scoped_f.bind(global_x=2)()["A"].x == 3

    a = 10

    def f2():
        b = 100

        def g(self):
            pass

        class A:
            x = global_x + 1

            def __init__(self):
                pass

            y = x + 1
            z = a + b
            gm = g

    scope = innerscope.call(f2)
    assert scope.outer_scope.keys() == {"a", "global_x"}
    assert scope.inner_scope.keys() == {"b", "g", "A"}
    assert scope["A"].x == 2
    assert scope["A"].z == 110
    assert scope["A"]().gm() is None
    scoped_f = scoped_function(f2, use_globals=False, use_closures=False)
    assert scoped_f.missing == {"a", "global_x"}
    scope = scoped_f.bind(a=20, global_x=2)()
    assert scope["A"].x == 3
    assert scope["A"].z == 120


def test_bad_method():
    def f():
        x = 1

    with raises(ValueError, match="method= argument to ScopedFunc"):
        scoped_function(f, method="bad_method")
    old_default = cfg.default_method
    try:
        cfg.default_method = "bad_method"
        with raises(ValueError, match="method= argument to ScopedFunc"):
            scoped_function(f)
        cfg.default_method = "default"
        with raises(ValueError, match="silly"):
            scoped_function(f)
    finally:
        cfg.default_method = old_default
    assert innerscope.call(f) == {"x": 1}


def test_generator():
    def f():
        foo = 2
        yield 5
        yield global_x
        return 10

    gf = scoped_function(f)
    [x, y] = gf()
    assert x == 5
    assert y == 1

    gen = gf()
    try:
        while True:
            next(gen)
    except StopIteration as exc:
        scope = exc.value
    assert scope == {"foo": 2, "global_x": 1}
    assert scope.return_value == 10


def test_coroutine():
    async def f():  # pragma: no cover
        await 5

    with raises(ValueError, match="does not yet work on coroutine functions"):
        scoped_function(f)


def test_asyncgen():
    async def f():  # pragma: no cover
        yield 5

    with raises(ValueError, match="does not yet work on async generator functions"):
        scoped_function(f)


def test_classmethod():
    class A:
        @scoped_function
        def f(self):
            x = 1
            y = x + 1
            return y + 1

        @classmethod
        @scoped_function
        def g(cls):
            x = 10
            y = x + 10
            return y + 10

        @scoped_function
        def h(self):
            x = 100
            yield x
            return x + 100

    a = A()
    scope = a.f()
    assert scope == {"self": a, "x": 1, "y": 2}
    assert scope.return_value == 3

    scope = A.g()
    assert scope == {"cls": A, "x": 10, "y": 20}
    assert scope.return_value == 30

    gen = a.h()
    assert next(gen) == 100
    try:
        next(gen)
    except StopIteration as exc:
        scope = exc.value
    assert scope == {"self": a, "x": 100}
    assert scope.return_value == 200


def test_shadow_builtins():
    min = 1

    def f(sum):
        dict = min + sum + max
        return dict + 1

    sf = scoped_function(f)
    assert sf.missing == set()
    assert sf.outer_scope == {"min": 1}
    assert sf.builtin_names == {"max"}

    sf = scoped_function(f, {"max": 100, "bool": 999})

    assert sf.missing == set()
    assert sf.outer_scope == {"min": 1, "max": 100}
    assert sf.builtin_names == set()
    scope = sf(10)
    assert scope == {"min": 1, "sum": 10, "max": 100, "dict": 111}
    assert scope.return_value == 112

    sf = scoped_function(f, use_closures=False)
    assert sf.missing == {"min"}
    assert sf.outer_scope == {}
    assert sf.builtin_names == {"max"}

    sf = scoped_function(f, {"min": 1000, "max": 100, "bool": 999}, use_closures=False)
    assert sf.missing == set()
    assert sf.outer_scope == {"min": 1000, "max": 100}
    assert sf.builtin_names == set()
    scope = sf(10)
    assert scope == {"min": 1000, "sum": 10, "max": 100, "dict": 1110}
    assert scope.return_value == 1111

    def g():
        a = hex + 1

    sg = scoped_function(g)
    assert sg.inner_names == {"a"}
    assert sg.outer_scope == {"hex": 1}
    assert sg.builtin_names == set()
    assert sg.missing == set()
    assert sg() == {"a": 2, "hex": 1}

    sg = scoped_function(g, use_globals=False)
    assert sg.inner_names == {"a"}
    assert sg.outer_scope == {}
    assert sg.missing == set()
    assert sg.builtin_names == {"hex"}

    sg = sg.bind(hex=100)
    assert sg.inner_names == {"a"}
    assert sg.outer_scope == {"hex": 100}
    assert sg.builtin_names == set()
    assert sg.missing == set()
    assert sg() == {"a": 101, "hex": 100}


def test_from_scopedgenerator():
    def gen():
        x = 1

    sgen = scoped_function(gen)
    sgen2 = scoped_function(sgen)
    assert sgen() == {"x": 1}
    assert sgen2() == {"x": 1}


def test_bad_type():
    def f(x):
        y = x + 1
        return y + 1

    cf = classmethod(f)
    with raises(TypeError, match="expects a Python function"):
        scoped_function(cf)
    assert innerscope.call(f, 1) == {"x": 1, "y": 2}
