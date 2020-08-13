import builtins
import dis
import functools
from collections.abc import Mapping
from types import CellType, FunctionType
from tlz import assoc, concatv, merge


class Scope(Mapping):
    """ A read-only mapping of the inner and outer scope of a function.

    This is the return value when a `ScopedFunction` is called.
    """

    def __init__(self, scoped_function, outer_scope, return_value, inner_scope):
        if type(inner_scope) is not dict:
            raise TypeError("inner_scope argument to Scope must be a dict")
        self.scoped_function = scoped_function
        del outer_scope["__builtins__"]
        self.outer_scope = outer_scope
        for key in scoped_function._code.co_freevars:
            # closures show up in locals, but we want them in outer_scope
            del inner_scope[key]
        self.inner_scope = inner_scope
        self.return_value = return_value

    def __getitem__(self, key):
        if key in self.inner_scope:
            return self.inner_scope[key]
        return self.outer_scope[key]

    def __iter__(self):
        return concatv(self.outer_scope, self.inner_scope)

    def __len__(self):
        return len(self.outer_scope) + len(self.inner_scope)

    def bindto(self, func, *, use_closures=None, use_globals=None):
        """ Bind the variables of this object to a function.

        >>> @call
        ... def haz_cheezburger():
        ...     bun = ...
        ...     patty = ...
        ...     cheez = ...
        ...     cheezburger = [bun, patty, cheez, bun]

        >>> @haz_cheezburger.bindto
        ... def eatz_cheezburger(wantz_piklz):
        ...     my_cheezburger = cheezburger
        ...     if wantz_piklz:
        ...         piklz = ...
        ...         my_cheezburger = cheezburger[:-1] + [piklz] + cheezburger[-1:]
        ...     ...  # Eatz cheezburger!

        >>> yummy = eatz_cheezburger(False)
        >>> ew_piklz = eatz_cheezburger(True)
        >>> 'piklz' in yummy
        False
        >>> 'piklz' in ew_piklz
        True
        >>> len(yummy['my_cheezburger']) < len(ew_piklz['my_cheezburger'])
        True

        ``my_scope.bindsto(func)`` is equivalent to:

         - ``bindwith(my_scope)(func)``
         - ``scoped_function(func, my_scope)``

        See Also
        --------
        bindwith
        scoped_function
        Scope.call
        """
        if use_closures is None:
            use_closures = self.scoped_function.use_closures
        if use_globals is None:
            use_globals = self.scoped_function.use_globals
        return ScopedFunction(func, self, use_closures=use_closures, use_globals=use_globals)

    def call(self, func, *args, **kwargs):
        """ Bind the variables of this object to a function and call the function.

        >>> @call
        ... def haz_cheezburger():
        ...     bun = ...
        ...     patty = ...
        ...     cheez = ...
        ...     cheezburger = [bun, patty, cheez, bun]

        >>> def eatz_cheezburger(wantz_piklz):
        ...     my_cheezburger = cheezburger
        ...     if wantz_piklz:
        ...         piklz = ...
        ...         my_cheezburger = cheezburger[:-1] + [piklz] + cheezburger[-1:]
        ...     ...  # Eatz cheezburger!

        >>> yummy = haz_cheezburger.call(eatz_cheezburger, False)
        >>> ew_piklz = haz_cheezburger.call(eatz_cheezburger, True)
        >>> 'piklz' in yummy
        False
        >>> 'piklz' in ew_piklz
        True
        >>> len(yummy['my_cheezburger']) < len(ew_piklz['my_cheezburger'])
        True

        ``my_scope.call(func, *args, **kwargs)`` is equivalent to:

        - ``my_scope.bind(func)(*args, **kwargs)``
        - ``my_scope.callwith(*args, **kwargs)(func)``
        - ``bindwith(my_scope)(func)(*args, **kwargs)``
        - ``scoped_function(func, my_scope)(*args, **kwargs)``

        See Also
        --------
        call
        Scope.bindto
        Scope.callwith
        """
        return self.bindto(func)(*args, **kwargs)

    def callwith(self, *args, **kwargs):
        """

        >>> @call
        ... def haz_cheezburger():
        ...     bun = ...
        ...     patty = ...
        ...     cheez = ...
        ...     cheezburger = [bun, patty, cheez, bun]

        >>> @haz_cheezburger.callwith(wantz_piklz=True)
        ... def eatz_cheezburger(wantz_piklz=False):
        ...     my_cheezburger = cheezburger
        ...     if wantz_piklz:
        ...         piklz = ...
        ...         my_cheezburger = cheezburger[:-1] + [piklz] + cheezburger[-1:]
        ...     ...  # Eatz cheezburger!

        >>> 'piklz' in eatz_cheezburger
        True

        ``my_scope.callwith(*args, **kwargs)(func)`` is equivalent to:

        - ``my_scope.bind(func)(*args, **kwargs)``
        - ``my_scope.call(func, *args, **kwargs)``
        - ``bindwith(my_scope)(func)(*args, **kwargs)``
        - ``scoped_function(func, my_scope)(*args, **kwargs)``

        See Also
        --------
        callwith
        Scope.bindto
        Scope.call
        """

        def callwith_inner(func, *, use_closures=None, use_globals=None):
            scoped = self.bindto(func, use_closures=use_closures, use_globals=use_globals)
            return scoped(*args, **kwargs)

        return callwith_inner

    def __repr__(self):
        return f"Scope({dict(self)!r})"


class ScopedFunction:
    """ Use to expose the inner scope of a wrapped function after being called.

    The wrapped function should have no return statements.  Instead of a return value,
    a `Scope` object is returned when called, which is a Mapping of the inner scope.

    >>> @scoped_function
    ... def f():
    ...     a = 1
    ...     b = a + 1

    >>> scope = f()
    >>> scope['a']
    1
    >>> scope['b']
    2
    """

    def __init__(self, func, *mappings, use_closures=True, use_globals=True):
        self.use_closures = use_closures
        self.use_globals = use_globals
        if isinstance(func, ScopedFunction):
            self.func = func.func
            code = func.func.__code__
            outer_scope = merge(func.outer_scope, *mappings)
        else:
            self.func = func
            code = func.__code__
            outer_scope = merge(mappings)
        functools.update_wrapper(self, self.func)

        # Modify to end with `return locals()`
        locals_index = len(code.co_names)
        co_names = code.co_names + ("locals",)
        co_code = code.co_code[:-2] + bytes(
            [
                dis.opmap["LOAD_GLOBAL"],
                locals_index,
                dis.opmap["CALL_FUNCTION"],
                0,
                dis.opmap["BUILD_TUPLE"],
                2,
                dis.opmap["RETURN_VALUE"],
                0,
            ]
        )

        # Only keep variables needed by the function
        outer_scope = {
            key: outer_scope[key] for key in code.co_names + code.co_freevars if key in outer_scope
        }
        self.outer_scope = outer_scope
        self.inner_names = set(code.co_varnames + code.co_cellvars)
        if code.co_freevars:
            if use_closures:
                # If this is a closure, move the enclosed variabled to `outer_scope`.
                # Also, use values already in `outer_scope` instead of the original closures.
                for name, cell in zip(code.co_freevars, self.func.__closure__):
                    if name not in outer_scope:
                        outer_scope[name] = cell.cell_contents
            self._closure = tuple(CellType(outer_scope.get(name)) for name in code.co_freevars)
        else:
            self._closure = None
        if use_globals:
            func_globals = self.func.__globals__
            for name in code.co_names:
                if name not in outer_scope and name in func_globals:
                    outer_scope[name] = func_globals[name]
        self.missing = {
            name
            for name in code.co_names
            if name not in outer_scope and not hasattr(builtins, name)
        }
        if not use_closures:
            self.missing.update(name for name in code.co_freevars if name not in outer_scope)
        if self.missing:
            self._code = None
        else:
            # stacksize must be at least 2, because we make a length two tuple
            self._code = code.replace(
                co_code=co_code, co_names=co_names, co_stacksize=max(code.co_stacksize, 2),
            )

    def __call__(self, *args, **kwargs):
        if self.missing:
            raise NameError(
                f"Undefined variables: {', '.join(repr(name) for name in self.missing)}.\n"
                "Use `bind` method to assign values for these names before calling."
            )
        # Should we use builtins, builtins.__dict__, or self.func.__globals__['__builtins__']?
        outer_scope = assoc(self.outer_scope, "__builtins__", builtins)
        func = FunctionType(
            self._code, outer_scope, argdefs=self.func.__defaults__, closure=self._closure
        )
        func.__kwdefaults__ = self.func.__kwdefaults__
        try:
            results = func(*args, **kwargs)
        except UnboundLocalError as exc:
            message = exc.args and exc.args[0] or ""
            if message.startswith("local variable ") and message.endswith(
                " referenced before assignment"
            ):
                name = message[len("local variable ") : -len(" referenced before assignment")]
                raise UnboundLocalError(
                    f"{message}.\n\n"
                    "This probably means you assigned to a local variable with the same name as a "
                    "variable in an outer scope that you meant to use.  This is, unfortunately, "
                    "a current limitation of `innerscope`.  Workarounds include:\n"
                    f"    - Pass {name} in as an argument to the function.\n"
                    f"    - Don't assign to {name}; use a different name for the local variable.\n"
                    "\n"
                    "If it's important to you that this limitation is fixed, then please submit "
                    "an issue (or a pull request!) to https://github.com/eriknw/innerscope"
                )
            else:
                raise
        try:
            return Scope(self, outer_scope, *results)
        except TypeError:
            raise ValueError(
                "Function wrapped by ScopedFunction must return at the very end of the function."
            )

    def bind(self, *mappings, **kwargs):
        """ Bind variables to a function's outer scope.

        This returns a new ScopedFunction object and leaves the original unmodified.

        >>> @scoped_function
        ... def makez_cheezburger():
        ...     bun = ...
        ...     patty = ...
        ...     cheezburger = [bun, patty, cheez, bun]

        >>> makez_cheezburger.missing
        {'cheez'}
        >>> makez_cheezburger_with_cheddar = makez_cheezburger.bind(cheez='cheddar')
        >>> makez_cheezburger_with_cheddar.missing
        set()
        >>> haz_cheezburger = makez_cheezburger_with_cheddar()
        >>> 'cheddar' in haz_cheezburger['cheezburger']
        True
        """
        return ScopedFunction(
            self.func,
            self.outer_scope,
            *mappings,
            kwargs,
            use_closures=self.use_closures,
            use_globals=self.use_globals,
        )


def scoped_function(func=None, *mappings, use_closures=True, use_globals=True):
    """ Use to expose the inner scope of a wrapped function after being called.

    The wrapped function should have no return statements.  Instead of a return value,
    a `Scope` object is returned when called, which is a Mapping of the inner scope.

    >>> @scoped_function
    ... def f():
    ...     a = 1
    ...     b = a + 1

    >>> scope = f()
    >>> scope['a']
    1
    >>> scope['b']
    2

    ``scoped_function`` is flexible when used as a decorator and can bind arguments:

    >>> @scoped_function({'a': 1}, use_globals=False)
    ... def f():
    ...     b = a + 1

    >>> scope = f()
    >>> scope['a']
    1
    >>> scope['b']
    2
    """
    if func is None:

        def inner_scoped_func(func):
            return ScopedFunction(
                func, *mappings, use_closures=use_closures, use_globals=use_globals
            )

        return inner_scoped_func

    if isinstance(func, Mapping):
        return scoped_function(
            None, func, *mappings, use_closures=use_closures, use_globals=use_globals
        )

    return ScopedFunction(func, *mappings, use_closures=use_closures, use_globals=use_globals)


def bindwith(*mappings, **kwargs):
    """ Bind variables to a function's outer scope, but don't yet call the function.

    >>> @bindwith(cheez='cheddar')
    ... def makez_cheezburger():
    ...     bun = ...
    ...     patty = ...
    ...     cheezburger = [bun, patty, cheez, bun]

    >>> makez_cheezburger.outer_scope['cheez']
    'cheddar'
    >>> haz_cheezburger = makez_cheezburger()
    >>> 'cheddar' in haz_cheezburger['cheezburger']
    True

    See Also
    --------
    callwith
    """

    def bindwith_inner(func, *, use_closures=True, use_globals=True):
        return ScopedFunction(
            func, *mappings, kwargs, use_closures=use_closures, use_globals=use_globals
        )

    return bindwith_inner


def call(func, *args, **kwargs):
    """ Useful for making simple pipelines to go from functions to scopes.

    >>> @call
    ... def haz_cheezburger():
    ...     bun = ...
    ...     patty = ...
    ...     cheez = ...
    ...     cheezburger = [bun, patty, cheez, bun]

    >>> len(haz_cheezburger['cheezburger'])
    4
    >>> haz_cheezburger['cheez'] == ...
    True

    >>> def makez_burger(with_cheez):
    ...     bun = ...
    ...     patty = ...
    ...     if with_cheez:
    ...         cheez = ...
    ...         burger = [bun, patty, cheez, bun]
    ...     else:
    ...         burger = [bun, patty, bun]

    >>> haz_burger_no_cheez = call(makez_burger, False)
    >>> haz_burger_with_cheez = call(makez_burger, True)
    >>> 'cheez' in haz_burger_no_cheez
    False
    >>> 'cheez' in haz_burger_with_cheez
    True
    >>> len(haz_burger_no_cheez['burger']) < len(haz_burger_with_cheez['burger'])
    True

    See Also
    --------
    callwith
    """
    scoped = ScopedFunction(func)
    return scoped(*args, **kwargs)


def callwith(*args, **kwargs):
    """ Useful for making simple pipelines to go from functions with arguments to scopes.

    >>> @callwith(extra_cheez_pleez=True)
    ... def haz_cheezburger(extra_cheez_pleez=False):
    ...     bun = ...
    ...     patty = ...
    ...     cheez = ...
    ...     if extra_cheez_pleez:
    ...         cheezburger = [bun, cheez, patty, cheez, cheez, bun]
    ...     else:
    ...         cheezburger = [bun, patty, cheez, bun]

    >>> len(haz_cheezburger['cheezburger'])
    6
    >>> haz_cheezburger['extra_cheez_pleez']
    True

    See Also
    --------
    bindwith
    call
    """

    def callwith_inner(func, *, use_closures=True, use_globals=True):
        scoped = ScopedFunction(func, use_closures=use_closures, use_globals=use_globals)
        return scoped(*args, **kwargs)

    return callwith_inner
