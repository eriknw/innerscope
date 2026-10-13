import builtins
import dis
import functools
import html
import inspect
import itertools
import sys
import warnings
from collections.abc import Mapping
from types import CellType, CodeType, FunctionType, MethodType

from . import _bytecode, cfg

BUILTINS = set(dir(builtins))

if sys.version_info >= (3, 14):
    import annotationlib

    def _signature(func):
        # Annotations are evaluated lazily (PEP 649) and may name something not yet defined
        return inspect.signature(func, annotation_format=annotationlib.Format.FORWARDREF)

else:
    _signature = inspect.signature

try:
    from types import LazyImportType  # 3.15+ (PEP 810)
except ImportError:
    LazyImportType = None


def _resolve_lazy(value):
    """Resolve a lazy import (`lazy import json`), as looking up the global name would.

    Then `outer_scope` holds the module, which (unlike the proxy) can be pickled.  If it can't
    be imported, leave it for the function to raise, as it would without innerscope.
    """
    if LazyImportType is not None and type(value) is LazyImportType:
        try:
            return value.resolve()
        except Exception:
            return value
    return value


def _merge(*mappings):
    """Merge mappings into a new dict; later mappings take precedence."""
    rv = {}
    for mapping in mappings:
        rv.update(mapping)
    return rv


# In class bodies, these look in the class namespace and then in globals.
# LOAD_FROM_DICT_OR_GLOBALS (3.12+) is also used by the `__annotate__` functions of classes (3.14+).
_LOAD_NAME_OR_GLOBAL = {"LOAD_NAME", "LOAD_FROM_DICT_OR_GLOBALS"}


def _get_globals_recursive(func, *, seen=None, isclass=False, class_names=frozenset()):
    """Get all global names used by func and all functions and classes defined within it.

    ``class_names`` are the names assigned in the nearest enclosing class body.
    """
    instructions = list(dis.get_instructions(func))
    if isclass:
        global_names = set()
        local_names = {"__name__"}
        for inst in instructions:
            if inst.opname == "STORE_NAME":
                local_names.add(inst.argval)
            elif inst.opname == "SETUP_ANNOTATIONS":  # Python < 3.14
                local_names.add("__annotations__")
            elif inst.opname in _LOAD_NAME_OR_GLOBAL:
                if inst.argval not in local_names:
                    global_names.add(inst.argval)
            elif inst.opname == "LOAD_GLOBAL":  # pragma: no cover
                global_names.add(inst.argval)
        # Annotation scopes (annotations on 3.14+, and `type` aliases and type parameters on
        # 3.12+) are evaluated after the class body runs, so they see every name it assigns.
        class_names = local_names
    else:
        global_names = {
            inst.argval
            for inst in instructions
            if inst.opname == "LOAD_GLOBAL"
            # Annotation scopes look in their class body first, then in globals
            or (inst.opname == "LOAD_FROM_DICT_OR_GLOBALS" and inst.argval not in class_names)
        }
    if seen is None:
        seen = set()
    for inst in instructions:
        if inst.opname == "LOAD_CONST" and type(inst.argval) is CodeType:
            if inst.argval in seen:  # pragma: no cover
                # I don't know how to get into a recursive cycle, but let's prevent it anyway.
                continue
            seen.add(inst.argval)
            # Of the code nested in a function, only class bodies are not "optimized".  (A class
            # body usually begins with `__module__ = __name__`, but not always on PyPy 3.12.)
            isclass = not inst.argval.co_flags & inspect.CO_OPTIMIZED
            global_names.update(
                _get_globals_recursive(
                    inst.argval, seen=seen, isclass=isclass, class_names=class_names
                )
            )
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
        f"   <tr><td><tt>{key}</tt></td><td>{val}</td></tr>\n"
        for key, val in zip(keys, vals, strict=True)
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
    contents = "".join(f"<td><tt>{html.escape(name)}</tt></td>" for name in names)
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
        return itertools.chain(self.outer_scope, self.inner_scope)

    def __len__(self):
        return len(self.outer_scope) + len(self.inner_scope)

    def bindto(self, func, *, use_closures=None, use_globals=None, method=None):
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

        ``my_scope.bindto(func)`` is equivalent to:

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
        if method is None:
            method = self.scoped_function.method
        return scoped_function(
            func, self, use_closures=use_closures, use_globals=use_globals, method=method
        )

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

        - ``my_scope.bindto(func)(*args, **kwargs)``
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

        - ``my_scope.bindto(func)(*args, **kwargs)``
        - ``my_scope.call(func, *args, **kwargs)``
        - ``bindwith(my_scope)(func)(*args, **kwargs)``
        - ``scoped_function(func, my_scope)(*args, **kwargs)``

        See Also
        --------
        callwith
        Scope.bindto
        Scope.call
        """

        def callwith_inner(func, *, use_closures=None, use_globals=None, method=None):
            scoped = self.bindto(
                func, use_closures=use_closures, use_globals=use_globals, method=method
            )
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

    When called, a `Scope` object is returned, which is a Mapping of the inner scope.
    The return value of the wrapped function is available as ``scope.return_value``.

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
            outer_scope = _merge(func.outer_scope, *mappings)
            self._code = func._code
            self._too_far = func._too_far
            global_names = func.missing | func.outer_scope.keys()  # includes globals and closures
            shadowed_globals = func.builtin_names & outer_scope.keys()
            global_names |= shadowed_globals  # outer_scope may override builtins
            global_names -= set(code.co_freevars)  # don't include closures in globals
            self.builtin_names = func.builtin_names - shadowed_globals
        else:
            self.func = func
            code = func.__code__
            outer_scope = _merge(*mappings)
            self._code = self._too_far = None
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
            key: _resolve_lazy(outer_scope[key])  # such as from `scoped_function(f, globals())`
            for key in itertools.chain(global_names, code.co_freevars)
            if key in outer_scope
        }
        self.inner_names = set(code.co_varnames + code.co_cellvars)
        # Closure variables not assigned yet (such as a function that calls itself)
        self._unassigned_cells = {}
        if code.co_freevars:
            if use_closures:
                # If this is a closure, move the enclosed variables to `outer_scope`.
                # Also, use values already in `outer_scope` instead of the original closures.
                for name, cell in zip(code.co_freevars, self.func.__closure__, strict=True):
                    if name in outer_scope:
                        continue
                    try:
                        outer_scope[name] = cell.cell_contents
                    except ValueError:  # Cell is empty
                        self._unassigned_cells[name] = cell
            # Use the original cell for an unassigned variable, so the function sees it once it
            # is assigned, and an empty cell for a missing one, so using it raises NameError.
            self._closure = tuple(
                (
                    CellType(outer_scope[name])
                    if name in outer_scope
                    else self._unassigned_cells.get(name, CellType())
                )
                for name in code.co_freevars
            )
        else:
            self._closure = None
        if use_globals:
            func_globals = self.func.__globals__
            for name in global_names:
                if name not in outer_scope and name in func_globals:
                    outer_scope[name] = _resolve_lazy(func_globals[name])
        # Sorted, so reprs don't depend on the order of a set (which changes from run to run)
        self.outer_scope = outer_scope = dict(sorted(outer_scope.items()))
        self.missing = global_names - outer_scope.keys() - self.builtin_names
        if not use_closures:
            self.missing.update(name for name in code.co_freevars if name not in outer_scope)
        self.builtin_names -= self.outer_scope.keys()

        if self._code is None and method == "bytecode":
            self._create_code()

    def _create_code(self):
        # Also reached when unpickling, perhaps on a different interpreter than the pickler's
        code = self.func.__code__
        if _bytecode.STRATEGY == "capture":
            self._code = _bytecode.insert_frame_capture(code)
            self._too_far = None
        elif _bytecode.STRATEGY == "returns":
            self._code, self._too_far = _bytecode.rewrite_returns(code)
        else:  # pragma: no cover
            raise ValueError(
                'method="bytecode" is not supported by this Python interpreter.  '
                'Please use method="trace" instead.'
            )

    def __call__(self, *args, **kwargs):
        [scope] = self._call(args, kwargs)
        return scope

    def _call(self, args, kwargs):
        if self.missing:
            warnings.warn(
                f"Undefined variables: {', '.join(repr(name) for name in sorted(self.missing))}.\n"
                "Perhaps use `bind` method to assign values for these names before calling.",
                stacklevel=2,
            )
        # Should we use builtins, builtins.__dict__, or self.func.__globals__['__builtins__']?
        outer_scope = self.outer_scope.copy()
        for name, cell in self._unassigned_cells.items():
            try:
                outer_scope[name] = cell.cell_contents
            except ValueError:  # Still unassigned
                pass
        outer_scope["__builtins__"] = builtins
        injected = ["__builtins__"]
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
                        # A copy: since Python 3.13 (PEP 667), `f_locals` is a write-through
                        # proxy of the frame, and we delete closure variables from the result.
                        info["locals"] = dict(frame.f_locals)
                    if prev is not None:
                        prev(frame, event, arg)

                frame.f_trace = trace_returns
                return trace_returns

        else:
            code = self._code
            if _bytecode.STRATEGY == "capture":
                # The rewritten code stores its frame in the global FRAME when it starts
                outer_scope[_bytecode.GETFRAME] = sys._getframe
                injected.append(_bytecode.GETFRAME)
            else:
                # The rewritten code returns `(return_value, locals(), secret)`
                outer_scope[_bytecode.LOCALS] = locals
                outer_scope[_bytecode.SECRET] = secret = object()
                injected.extend([_bytecode.LOCALS, _bytecode.SECRET])

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
            # Only keep the frame if the call succeeded: its `f_back` is this frame, so if an
            # exception traceback held both, they would keep each other alive.
            frame = outer_scope.pop(_bytecode.FRAME, None)
        except UnboundLocalError as exc:
            message = exc.args and exc.args[0] or ""
            if isinstance(message, str) and (
                message.startswith("local variable ")
                and message.endswith(" referenced before assignment")
                or message.startswith("cannot access local variable")
                and message.endswith("where it is not associated with a value")
            ):
                if message.startswith("local variable "):
                    name = message[len("local variable ") : -len(" referenced before assignment")]
                else:
                    name = message[
                        len("cannot access local variable ") : -len(
                            " where it is not associated with a value"
                        )
                    ]
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
                # `trace_func` refers to itself; break the cycle so the locals are freed
                # promptly.  If a later call still has this `trace_func` installed (for
                # example, interleaved generators), it hands control back to `prev_trace`.
                trace_func = prev_trace
            # The frame refers to these globals, which refer to the frame
            outer_scope.pop(_bytecode.FRAME, None)
        if is_trace:
            inner_scope = info["locals"]
        elif _bytecode.STRATEGY == "capture":
            if frame is None or frame.f_code is not code:  # pragma: no cover (safety)
                raise _bytecode.BytecodeError(
                    f"Unable to get the inner scope of {self.func.__qualname__}; is "
                    "`sys._getframe` replaced?  Using `method='trace'` may work."
                )
            # The frame took ownership of its locals when the function returned
            inner_scope = dict(frame.f_locals)
            del frame
        else:
            try:
                return_value, inner_scope, expect_secret = return_value
            except Exception:
                expect_secret = None
            if secret is not expect_secret:
                raise self._too_far or _bytecode.BytecodeError(  # pragma: no cover (safety)
                    f"Unable to get the inner scope of {self.func.__qualname__}"
                )
        for key in injected:
            del outer_scope[key]
        # closures show up in locals, but we want them only in outer_scope
        for key in code.co_freevars:
            inner_scope.pop(key, None)
        rv = Scope(self, outer_scope, return_value, inner_scope)
        if type(self) is ScopedGeneratorFunction:
            return rv
        yield rv

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
            method=self.method,
        )

    def __repr__(self):
        func = self.func
        sig = _signature(func)
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
        sig = _signature(func)
        func = f"{func.__module__}.{func.__name__}{sig}"
        func = _get_repr_set("func", [func])
        inner = _get_repr_set("inner_names", sorted(self.inner_names))
        missing = _get_repr_set("missing", sorted(self.missing))
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
        if instance is None:  # accessed on the class, like a plain function
            return self
        return MethodType(self, instance)

    def __getstate__(self):
        rv = dict(self.__dict__)
        rv["_code"] = rv["_too_far"] = None
        return rv

    def __setstate__(self, state):
        # Pickles made by innerscope 0.7.0 and earlier lack these
        state.setdefault("_unassigned_cells", {})
        state.setdefault("_too_far", None)
        self.__dict__.update(state)
        if self.method == "bytecode":
            self._create_code()


class ScopedGeneratorFunction(ScopedFunction):
    def __call__(self, *args, **kwargs):
        gen = self._call(args, kwargs)
        rv = yield from gen
        return rv


def scoped_function(func=None, *mappings, use_closures=True, use_globals=True, method="default"):
    """Use to expose the inner scope of a wrapped function after being called.

    When called, a `Scope` object is returned, which is a Mapping of the inner scope.
    The return value of the wrapped function is available as ``scope.return_value``.

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

    def bindwith_inner(func, *, use_closures=True, use_globals=True, method="default"):
        return scoped_function(
            func,
            *mappings,
            kwargs,
            use_closures=use_closures,
            use_globals=use_globals,
            method=method,
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

    def callwith_inner(func, *, use_closures=True, use_globals=True, method="default"):
        scoped = scoped_function(
            func, use_closures=use_closures, use_globals=use_globals, method=method
        )
        return scoped(*args, **kwargs)

    return callwith_inner
