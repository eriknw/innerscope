import pytest
import builtins
import innerscope
from pytest import raises
from innerscope import scoped_function

global_x = 1


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


"""
def test_repr():
    @innerscope.call
    def f():
        x = 1

    assert repr(f) == "Scope({'x': 1})"
"""


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
            return
        a = 1
        b = a + 1

    # But we can check the return type
    with raises(ValueError, match="must return at the very end of the function"):
        f(True)
    scope = f(False)
    assert scope == dict(a=1, b=2, boolean=False)

    @scoped_function
    def g(boolean):
        if boolean:
            return (1, 2, 3)
        a = 1
        b = a + 1

    with raises(ValueError, match="must return at the very end of the function"):
        g(True)
    scope = g(False)
    assert scope == dict(a=1, b=2, boolean=False)


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
