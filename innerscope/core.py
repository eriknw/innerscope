import builtins
import dis
import functools
import html
import inspect
import sys
from collections.abc import Mapping
from types import CodeType, FunctionType, MethodType
from tlz import concatv, merge
from . import cfg

try:
    # Added in Python 3.8
    from types import CellType

    def code_replace(code, *, co_code, co_names, co_stacksize):
        return code.replace(
            co_code=co_code,
            co_names=co_names,
            co_stacksize=co_stacksize,
        )


except ImportError:

    def CellType(x):
        def inner():  # pragma: no cover
            return x

        return inner.__closure__[0]

    def code_replace(code, *, co_code, co_names, co_stacksize):
        return CodeType(
            code.co_argcount,
            code.co_kwonlyargcount,
            code.co_nlocals,
            co_stacksize,
            code.co_flags,
            co_code,
            code.co_consts,
            co_names,
            code.co_varnames,
            code.co_filename,
            code.co_name,
            code.co_firstlineno,
            code.co_lnotab,
            code.co_freevars,
            code.co_cellvars,
        )


BUILTINS = set(dir(builtins))


def _get_globals_recursive(func, *, seen=None, isclass=False):
    """ Get all global names used by func and all functions and classes defined within it."""
    if isclass:
        global_names = set()
        local_names = {"__name__"}
        for inst in dis.get_instructions(func):
            if inst.opname == "STORE_NAME":
                local_names.add(inst.argval)
            elif inst.opname == "LOAD_NAME":
                if inst.argval not in local_names:
                    global_names.add(inst.argval)
            elif inst.opname == "LOAD_GLOBAL":  # pragma: no cover
                global_names.add(inst.argval)
    else:
        global_names = {
            inst.argval for inst in dis.get_instructions(func) if inst.opname == "LOAD_GLOBAL"
        }
    if seen is None:
        seen = set()
    num_classes = 0
    for inst in dis.get_instructions(func):
        if inst.opname == "LOAD_CONST" and type(inst.argval) is CodeType:
            if num_classes > 0:
                code_inst = next(dis.get_instructions(inst.argval))
                isclass = code_inst.opname == "LOAD_NAME" and code_inst.argval == "__name__"
                num_classes -= isclass
            if inst.argval in seen:  # pragma: no cover
                # I don't know how to get into a recursive cycle, but let's prevent it anyway.
                continue
            seen.add(inst.argval)
            global_names.update(_get_globals_recursive(inst.argval, seen=seen, isclass=isclass))
        elif inst.opname == "LOAD_BUILD_CLASS":
            num_classes += 1
    return global_names


def _get_repr_table(title, scope, add_break=False):
    if not scope:
        return f'{"<br>" if add_break else ""}<tt>- {title}: {{}}</tt>'
    keys = sorted(scope)
    vals = []
    for key in keys:
        val = scope[key]
        if hasattr(val, "_repr_html_"):
            vals.append(val._repr_html_())
        else:
            vals.append(html.escape(repr(val)))
    contents = "".join(
        f"   <tr><td><tt>{key}</tt></td><td>{val}</td></td>\n" for key, val in zip(keys, vals)
    )
    return (
        "<details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        f"  <tt>{title}</tt>\n"
        " </summary>"
        ' <div style="padding-left:10px;padding-bottom:5px;">'
        '  <table style="max-width:100%; border:1px solid #AAAAAA;">'
        "   <tr><th>Name</th><th>Value</th></tr>"
        f"   {contents}"
        "  </table>\n </div>\n</details>\n"
    )


def _get_repr_set(title, names):
    if not names:
        return ""
    contents = "".join(f"<td><tt>{name}</tt></td>" for name in names)
    contents = (
        '<div style="padding-left:10px;">'
        '<table style="max-width:100%; border:1px solid #AAAAAA; '
        'margin-top:0px; margin-bottom:8px;">'
        f"<tr>{contents}</tr></table></div>"
    )
    return f"<tt>- {title}</tt>{contents}"


class Scope(Mapping):
    """A read-only mapping of the inner and outer scope of a function.

    This is the return value when a `ScopedFunction` is called.
    """

    def __init__(self, scoped_function, outer_scope, return_value, inner_scope):
        self.scoped_function = scoped_function
        self.outer_scope = outer_scope
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
        """Bind the variables of this object to a function.

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
        return scoped_function(func, self, use_closures=use_closures, use_globals=use_globals)

    def call(self, *func_and_args, **kwargs):
        """Bind the variables of this object to a function and call the function.

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
        if not func_and_args:
            raise TypeError("scope.call() missing 1 required positional argument: 'func'")
        func, *args = func_and_args
        return self.bindto(func)(*args, **kwargs)

    def callwith(self, *args, **kwargs):
        """♪ But here's my number, so call me maybe ♪

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
        inner = repr(self.inner_scope)
        if len(inner) < 120:
            inner = f" - inner_scope: {inner}\n"
        else:
            inner = ", ".join(repr(x) for x in sorted(self.inner_scope))
            inner = f" - inner_scope.keys(): {{{inner}}}\n"
        outer = repr(self.outer_scope)
        if len(outer) < 120:
            outer = f" - outer_scope: {outer}\n"
        else:
            outer = ", ".join(repr(x) for x in sorted(self.outer_scope))
            outer = f" - outer_scope.keys(): {{{outer}}}\n"
        return_value = repr(self.return_value)
        if "\\n" in return_value:
            return_value = return_value.replace("\\n", "\n")
            return_value = f" - return_value:\n{return_value}"
        else:
            return_value = f" - return_value: {return_value}"
        return f"Scope\n{outer}{inner}{return_value}"

    def _repr_html_(self):
        outer = _get_repr_table("outer_scope", self.outer_scope, add_break=True)
        inner = _get_repr_table("inner_scope", self.inner_scope, add_break=not self.outer_scope)
        if hasattr(self.return_value, "_repr_html_"):
            return_value = (
                "<details open>\n"
                ' <summary style="display:list-item; outline:none;">\n'
                "  <tt>return_value</tt>\n"
                " </summary>"
                ' <div style="padding-left:10px;padding-bottom:5px;">'
                f"{self.return_value._repr_html_()}"
                "</div>\n</details>\n"
            )
        else:
            return_value = html.escape(repr(self.return_value))
            if "\\n" in return_value:
                if return_value.count("\\n") > 10:
                    return_value = return_value.replace("\\n", "<br>")
                    return_value = (
                        "<details open>\n"
                        ' <summary style="display:list-item; outline:none;">\n'
                        "  <tt>return_value</tt>\n"
                        " </summary>"
                        ' <div style="padding-left:10px;padding-bottom:5px;">'
                        f"{return_value}"
                        "</div>\n</details>\n"
                    )
                else:
                    return_value = return_value.replace("\\n", "<br>")
                    return_value = f"<tt>- return_value:<br>{return_value}</tt>"
            else:
                return_value = f"<tt>- return_value: {return_value}</tt>"
        if not self.inner_scope:
            return_value = f"<br>{return_value}"
        return f'<div style="max-width:100%;">\n<b>Scope</b>\n{outer}{inner}{return_value}</div>'


class ScopedFunction:
    """Use to expose the inner scope of a wrapped function after being called.

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

    def __init__(self, func, *mappings, use_closures=True, use_globals=True, method="default"):
        self.use_closures = use_closures
        self.use_globals = use_globals
        if method == "default":
            method = cfg.default_method
            if method == "default":
                raise ValueError(
                    'Who would set the default method to "default"?  That\'s just silly!\n'
                    'Please set ``innerscope.cfg.default_method`` back to "bytecode", '
                    "and then please continue doing what you're doing, because it's probably "
                    "something awesome :)"
                )
        if method not in {"bytecode", "trace"}:
            raise ValueError(
                f'method= argument to {type(self).__name__} must be "bytecode", "trace", or '
                f'"default".  Got {method!r}.  Using the default method is recommended.'
            )
        self.method = method
        if isinstance(func, ScopedFunction):
            self.func = func.func
            code = func.func.__code__
            outer_scope = merge(func.outer_scope, *mappings)
            self._code = func._code
            global_names = func.missing | func.outer_scope.keys()  # includes globals and closures
            shadowed_globals = func.builtin_names & outer_scope.keys()
            global_names |= shadowed_globals  # outer_scope may override builtins
            global_names -= set(code.co_freevars)  # don't include closures in globals
            self.builtin_names = func.builtin_names - shadowed_globals
        else:
            self.func = func
            code = func.__code__
            outer_scope = merge(mappings)
            self._code = None
            global_names = _get_globals_recursive(self.func)
            self.builtin_names = global_names & BUILTINS
        functools.update_wrapper(self, self.func)
        if inspect.iscoroutinefunction(self.func):
            raise ValueError(
                f"{type(self).__name__} does not yet work on coroutine functions.  "
                "I'm curious what exactly you're trying to do.  Please share :)"
            )
        if inspect.isasyncgenfunction(self.func):
            raise ValueError(
                f"{type(self).__name__} does not yet work on async generator functions.  "
                "I'm curious what exactly you're trying to do.  Please share :)"
            )

        # Only keep variables needed by the function (globals and closures)
        outer_scope = {
            key: outer_scope[key]
            for key in concatv(global_names, code.co_freevars)
            if key in outer_scope
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
            for name in global_names:
                if name not in outer_scope and name in func_globals:
                    outer_scope[name] = func_globals[name]
        self.missing = global_names - outer_scope.keys() - self.builtin_names
        if not use_closures:
            self.missing.update(name for name in code.co_freevars if name not in outer_scope)
        self.builtin_names -= self.outer_scope.keys()

        if self._code is None:
            # Change RETURN_VALUE to JUMP_FORWARD.
            # This way, even long functions can have multiple return statements as long as
            # they are near the end or near each other.  The advantage of this is that we
            # don't need to change the code size, which would require handling other jumps.
            co_code = code.co_code[:-2]  # Remove the RETURN_VALUE that should be at the end
            return_indices = [
                inst.offset
                for inst in dis.get_instructions(self.func)
                if inst.opname == "RETURN_VALUE"
            ]
            jump_target = len(co_code)
            target_index = len(return_indices) - 1
            if len(return_indices) > 1:
                chunks = []
                for i in return_indices[-2::-1]:
                    target = jump_target - i - 2
                    while target_index > 0 and target > 255:
                        target_index -= 1
                        jump_target = return_indices[target_index]
                        target = jump_target - i - 2
                    if target_index == 0 or target > 255 or target < 0:
                        break
                    co_code, chunk = co_code[:i], co_code[i + 2 :]
                    chunks.append(chunk)
                    chunks.append(bytes([dis.opmap["JUMP_FORWARD"], target]))
                chunks.append(co_code)
                co_code = b"".join(reversed(chunks))

            # Modify to end with `return (rv, locals(), secret)`
            co_names = code.co_names + ("_innerscope_locals_", "_innerscope_secret_")
            co_code = co_code + bytes(
                [
                    dis.opmap["LOAD_GLOBAL"],
                    len(code.co_names),
                    dis.opmap["CALL_FUNCTION"],
                    0,
                    dis.opmap["LOAD_GLOBAL"],
                    len(code.co_names) + 1,
                    dis.opmap["BUILD_TUPLE"],
                    3,
                    dis.opmap["RETURN_VALUE"],
                    0,
                ]
            )

            # stacksize must be at least 3, because we make a length three tuple
            self._code = code_replace(
                code,
                co_code=co_code,
                co_names=co_names,
                co_stacksize=max(code.co_stacksize, 3),
            )

    def __call__(self, *args, **kwargs):
        [scope] = self._call(args, kwargs)
        return scope

    def _call(self, args, kwargs):
        if self.missing:
            raise NameError(
                f"Undefined variables: {', '.join(repr(name) for name in self.missing)}.\n"
                "Use `bind` method to assign values for these names before calling."
            )
        # Should we use builtins, builtins.__dict__, or self.func.__globals__['__builtins__']?
        outer_scope = self.outer_scope.copy()
        outer_scope["__builtins__"] = builtins
        outer_scope["_innerscope_locals_"] = locals
        outer_scope["_innerscope_secret_"] = secret = object()
        is_trace = self.method == "trace"
        if is_trace:
            code = self.func.__code__
            prev_trace = sys.gettrace()
            info = {}

            # coverage uses sys.settrace, so I don't know how to cover this function
            def trace_func(frame, event, arg):  # pragma: no cover
                if prev_trace is not None:
                    prev = prev_trace(frame, event, arg)
                    sys.settrace(trace_func)
                else:
                    prev = None
                if event != "call" or frame.f_code is not func.__code__:
                    return prev

                def trace_returns(frame, event, arg):
                    if event == "return":
                        info["locals"] = frame.f_locals
                    if prev is not None:
                        prev(frame, event, arg)

                frame.f_trace = trace_returns
                return trace_returns

        else:
            code = self._code

        func = FunctionType(
            code, outer_scope, argdefs=self.func.__defaults__, closure=self._closure
        )
        func.__kwdefaults__ = self.func.__kwdefaults__
        try:
            if is_trace:
                sys.settrace(trace_func)
            return_value = func(*args, **kwargs)
            if type(self) is ScopedGeneratorFunction:
                return_value = yield from return_value
        except UnboundLocalError as exc:
            message = exc.args and exc.args[0] or ""
            if (
                isinstance(message, str)
                and message.startswith("local variable ")
                and message.endswith(" referenced before assignment")
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
                    "an issue (or a pull request!) to:\nhttps://github.com/eriknw/innerscope"
                ) from exc
            else:
                raise
        finally:
            if is_trace:
                sys.settrace(prev_trace)
        if is_trace:
            inner_scope = info["locals"]
        else:
            try:
                return_value, inner_scope, expect_secret = return_value
            except Exception:
                expect_secret = None
        if is_trace or secret is expect_secret:
            del outer_scope["__builtins__"]
            del outer_scope["_innerscope_locals_"]
            del outer_scope["_innerscope_secret_"]
            # closures show up in locals, but we want them only in outer_scope
            for key in self._code.co_freevars:
                del inner_scope[key]
            rv = Scope(self, outer_scope, return_value, inner_scope)
            if type(self) is ScopedGeneratorFunction:
                return rv
            else:
                yield rv
                return

        return_indices = [
            inst.offset for inst in dis.get_instructions(self.func) if inst.opname == "RETURN_VALUE"
        ]
        jump_target = len(func.__code__.co_code) - 2
        target_index = len(return_indices) - 1
        bad_returns = []
        for i in return_indices[-2::-1]:
            target = jump_target - i - 2
            while target_index > 0 and target > 255:
                target_index -= 1
                jump_target = return_indices[target_index]
                target = jump_target - i - 2
            if target_index == 0 or target > 255 or target < 0:
                target_index = 0
                bad_returns.append(i)
        if len(bad_returns) == 1:
            return_msg = "The first return statement is too far away."
        else:
            return_msg = f"The first {len(bad_returns)} return statements are too far away."
        next_closest = return_indices[len(bad_returns)] - bad_returns[0]
        raise ValueError(
            f"This may sound weird, but functions wrapped by {type(self).__name__} should have "
            "return statements that are close together or near the end of the function.  "
            "By close, I mean that each return statement in the compiled code should be "
            "within 256 bytes of another return statement or the end of the function.  "
            "Worried?  Don't be :).  This limitation is to ensure `innerscope` is rock-solid!"
            f"\n\n{return_msg}  The next closest return statement is {next_closest} bytes away."
            "\n\nA cute workaround is to add code such as `if bool(): return`."
            "\n\nIf it's important to you that this limitation is fixed, then please submit "
            "an issue (or a pull request!) to:\nhttps://github.com/eriknw/innerscope\n\n"
            f'Another workaround is to use `method="trace"` in {type(self).__name__}.  This will '
            "usually work, but it will be slower and may cause havoc if `sys.settrace` is "
            "used by anything else.  The default method is preferred if possible."
        )

    def bind(self, *mappings, **kwargs):
        """Bind variables to a function's outer scope.

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
        return scoped_function(
            self.func,
            self.outer_scope,
            *mappings,
            kwargs,
            use_closures=self.use_closures,
            use_globals=self.use_globals,
        )

    def __repr__(self):
        func = self.func
        sig = inspect.signature(func)
        func = f" - func: {func.__module__}.{func.__name__}{sig}\n"
        inner = ", ".join(repr(x) for x in sorted(self.inner_names))
        inner = f" - inner_scope: {{{inner}}}\n"
        outer = repr(self.outer_scope)
        if len(outer) < 120:
            outer = f" - outer_scope: {outer}"
        else:
            outer = ", ".join(repr(x) for x in sorted(self.outer_scope))
            outer = f" - outer_scope.keys(): {{{outer}}}"
        if self.missing:
            missing = ", ".join(repr(x) for x in sorted(self.missing))
            missing = f"\n - missing: {{{missing}}}"
        else:
            missing = ""
        return f"{type(self).__name__}\n{func}{inner}{outer}{missing}"

    def _repr_html_(self):
        func = self.func
        sig = inspect.signature(func)
        func = f"{func.__module__}.{func.__name__}{sig}"
        func = _get_repr_set("func", [func])
        inner = _get_repr_set("inner_names", self.inner_names)
        missing = _get_repr_set("missing", self.missing)
        outer = _get_repr_table("outer_scope", self.outer_scope)
        return (
            f"<div><b>{type(self).__name__}</b><br>\n"
            f"{func}\n"
            f"{inner}\n"
            f"{missing}\n"
            f"{outer}\n"
            "</div>"
        )

    def __get__(self, instance, owner=None):
        return MethodType(self, instance)


class ScopedGeneratorFunction(ScopedFunction):
    def __call__(self, *args, **kwargs):
        gen = self._call(args, kwargs)
        rv = yield from gen
        return rv


def scoped_function(func=None, *mappings, use_closures=True, use_globals=True, method="default"):
    """Use to expose the inner scope of a wrapped function after being called.

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
            return scoped_function(
                func,
                *mappings,
                use_closures=use_closures,
                use_globals=use_globals,
                method=method,
            )

        return inner_scoped_func

    if isinstance(func, Mapping):
        return scoped_function(
            None,
            func,
            *mappings,
            use_closures=use_closures,
            use_globals=use_globals,
            method=method,
        )
    if type(func) is ScopedGeneratorFunction or inspect.isgeneratorfunction(func):
        klass = ScopedGeneratorFunction
    elif type(func) is ScopedFunction or inspect.isfunction(func):
        klass = ScopedFunction
    else:
        raise TypeError(f"scoped_function expects a Python function.  Got type: {type(func)}")
    return klass(
        func,
        *mappings,
        use_closures=use_closures,
        use_globals=use_globals,
        method=method,
    )


def bindwith(*mappings, **kwargs):
    """Bind variables to a function's outer scope, but don't yet call the function.

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
        return scoped_function(
            func, *mappings, kwargs, use_closures=use_closures, use_globals=use_globals
        )

    return bindwith_inner


def call(*func_and_args, **kwargs):
    """Useful for making simple pipelines to go from functions to scopes.

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
    if not func_and_args:
        raise TypeError("call() missing 1 required positional argument: 'func'")
    func, *args = func_and_args
    scoped = scoped_function(func)
    return scoped(*args, **kwargs)


def callwith(*args, **kwargs):
    """Useful for making simple pipelines to go from functions with arguments to scopes.

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
        scoped = scoped_function(func, use_closures=use_closures, use_globals=use_globals)
        return scoped(*args, **kwargs)

    return callwith_inner
