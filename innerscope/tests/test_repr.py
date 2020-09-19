import innerscope
from innerscope import scoped_function


def test_scope_repr():
    @innerscope.call
    def f1():
        x = "hi"

    assert repr(f1) == (
        "Scope\n - outer_scope: {}\n - inner_scope: {'x': 'hi'}\n - return_value: None"
    )

    x = "hello"

    @innerscope.call
    def f2():
        y = "world"
        return f"{x} {y}"

    assert repr(f2) == (
        "Scope\n - outer_scope: {'x': 'hello'}\n - inner_scope: {'y': 'world'}\n - return_value: 'hello world'"
    )


def test_scope_repr_many_keys():
    x = "this name is too long" * 100

    @scoped_function
    def f1():
        y = 2 * x
        return "this\nhas\nnewlines"

    assert repr(f1) == (
        "ScopedFunction\n - func: innerscope.tests.test_repr.f1()\n - inner_scope: {'y'}\n - outer_scope.keys(): {'x'}"
    )

    scope = f1()
    assert repr(scope) == (
        "Scope\n - outer_scope.keys(): {'x'}\n - inner_scope.keys(): {'y'}\n - return_value:\n'this\nhas\nnewlines'"
    )


def test_scope_repr_html():
    @innerscope.call
    def f1():
        x = "hi"

    assert f1._repr_html_() == (
        '<div style="max-width:100%;">\n'
        "<b>Scope</b>\n"
        "<br><tt>- outer_scope: {}</tt><details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        "  <tt>inner_scope</tt>\n"
        ' </summary> <div style="padding-left:10px;padding-bottom:5px;">  <table style="max-width:100%; border:1px solid #AAAAAA;">   <tr><th>Name</th><th>Value</th></tr>      <tr><td><tt>x</tt></td><td>&#x27;hi&#x27;</td></td>\n'
        "  </table>\n"
        " </div>\n"
        "</details>\n"
        "<tt>- return_value: None</tt></div>"
    )

    x = "hello"

    @innerscope.call
    def f2():
        y = "world"
        return f"{x} {y}"

    assert f2._repr_html_() == (
        '<div style="max-width:100%;">\n'
        "<b>Scope</b>\n"
        "<details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        "  <tt>outer_scope</tt>\n"
        ' </summary> <div style="padding-left:10px;padding-bottom:5px;">  <table style="max-width:100%; border:1px solid #AAAAAA;">   <tr><th>Name</th><th>Value</th></tr>      <tr><td><tt>x</tt></td><td>&#x27;hello&#x27;</td></td>\n'
        "  </table>\n"
        " </div>\n"
        "</details>\n"
        "<details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        "  <tt>inner_scope</tt>\n"
        ' </summary> <div style="padding-left:10px;padding-bottom:5px;">  <table style="max-width:100%; border:1px solid #AAAAAA;">   <tr><th>Name</th><th>Value</th></tr>      <tr><td><tt>y</tt></td><td>&#x27;world&#x27;</td></td>\n'
        "  </table>\n"
        " </div>\n"
        "</details>\n"
        "<tt>- return_value: &#x27;hello world&#x27;</tt></div>"
    )

    class A:
        def _repr_html_(self):
            return "in A._repr_html_"

        def __repr__(self):  # pragma: no cover
            return "FAIL"

    a = A()

    @innerscope.call
    def f3():
        b = a
        return a

    assert f3._repr_html_() == (
        '<div style="max-width:100%;">\n'
        "<b>Scope</b>\n"
        "<details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        "  <tt>outer_scope</tt>\n"
        ' </summary> <div style="padding-left:10px;padding-bottom:5px;">  <table style="max-width:100%; border:1px solid #AAAAAA;">   <tr><th>Name</th><th>Value</th></tr>      <tr><td><tt>a</tt></td><td>in A._repr_html_</td></td>\n'
        "  </table>\n"
        " </div>\n"
        "</details>\n"
        "<details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        "  <tt>inner_scope</tt>\n"
        ' </summary> <div style="padding-left:10px;padding-bottom:5px;">  <table style="max-width:100%; border:1px solid #AAAAAA;">   <tr><th>Name</th><th>Value</th></tr>      <tr><td><tt>b</tt></td><td>in A._repr_html_</td></td>\n'
        "  </table>\n"
        " </div>\n"
        "</details>\n"
        "<details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        "  <tt>return_value</tt>\n"
        ' </summary> <div style="padding-left:10px;padding-bottom:5px;">in A._repr_html_</div>\n'
        "</details>\n"
        "</div>"
    )


def test_scope_reprhtml_return_newlines():
    @innerscope.call
    def f1():
        return "hello\nworld\n" * 2

    assert f1._repr_html_() == (
        '<div style="max-width:100%;">\n'
        "<b>Scope</b>\n"
        "<br><tt>- outer_scope: {}</tt><br><tt>- inner_scope: {}</tt><br><tt>- return_value:<br>&#x27;hello<br>world<br>hello<br>world<br>&#x27;</tt></div>"
    )

    @innerscope.call
    def f2():
        return "hello\nworld\n" * 10

    assert f2._repr_html_() == (
        '<div style="max-width:100%;">\n'
        "<b>Scope</b>\n"
        "<br><tt>- outer_scope: {}</tt><br><tt>- inner_scope: {}</tt><br><details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        "  <tt>return_value</tt>\n"
        ' </summary> <div style="padding-left:10px;padding-bottom:5px;">&#x27;hello<br>world<br>hello<br>world<br>hello<br>world<br>hello<br>world<br>hello<br>world<br>hello<br>world<br>hello<br>world<br>hello<br>world<br>hello<br>world<br>hello<br>world<br>&#x27;</div>\n'
        "</details>\n"
        "</div>"
    )


def test_scoped_function_repr():
    @scoped_function
    def f1():
        x = "hi"

    f1()
    assert repr(f1) == (
        "ScopedFunction\n - func: innerscope.tests.test_repr.f1()\n - inner_scope: {'x'}\n - outer_scope: {}"
    )

    x = "hello"

    @innerscope.call
    def f2():
        y = "world"
        return f"{x} {y}"

    assert repr(f2) == (
        "Scope\n - outer_scope: {'x': 'hello'}\n - inner_scope: {'y': 'world'}\n - return_value: 'hello world'"
    )


def test_scoped_function_repr_html():
    @scoped_function
    def f1():
        x = "hi"

    f1()
    assert f1._repr_html_() == (
        "<div><b>ScopedFunction</b><br>\n"
        '<tt>- func</tt><div style="padding-left:10px;"><table style="max-width:100%; border:1px solid #AAAAAA; margin-top:0px; margin-bottom:8px;"><tr><td><tt>innerscope.tests.test_repr.f1()</tt></td></tr></table></div>\n'
        '<tt>- inner_names</tt><div style="padding-left:10px;"><table style="max-width:100%; border:1px solid #AAAAAA; margin-top:0px; margin-bottom:8px;"><tr><td><tt>x</tt></td></tr></table></div>\n'
        "\n"
        "<tt>- outer_scope: {}</tt>\n"
        "</div>"
    )

    x = "hello"

    @innerscope.call
    def f2():
        y = "world"
        return f"{x} {y}"

    assert f2._repr_html_() == (
        '<div style="max-width:100%;">\n'
        "<b>Scope</b>\n"
        "<details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        "  <tt>outer_scope</tt>\n"
        ' </summary> <div style="padding-left:10px;padding-bottom:5px;">  <table style="max-width:100%; border:1px solid #AAAAAA;">   <tr><th>Name</th><th>Value</th></tr>      <tr><td><tt>x</tt></td><td>&#x27;hello&#x27;</td></td>\n'
        "  </table>\n"
        " </div>\n"
        "</details>\n"
        "<details open>\n"
        ' <summary style="display:list-item; outline:none;">\n'
        "  <tt>inner_scope</tt>\n"
        ' </summary> <div style="padding-left:10px;padding-bottom:5px;">  <table style="max-width:100%; border:1px solid #AAAAAA;">   <tr><th>Name</th><th>Value</th></tr>      <tr><td><tt>y</tt></td><td>&#x27;world&#x27;</td></td>\n'
        "  </table>\n"
        " </div>\n"
        "</details>\n"
        "<tt>- return_value: &#x27;hello world&#x27;</tt></div>"
    )


def test_scoped_function_missing():
    @scoped_function
    def f1():  # pragma: no cover
        x = y

    assert repr(f1) == (
        "ScopedFunction\n"
        " - func: innerscope.tests.test_repr.f1()\n"
        " - inner_scope: {'x'}\n"
        " - outer_scope: {}\n"
        " - missing: {'y'}"
    )


def test_scoped_function_missing_html():
    @scoped_function
    def f1():  # pragma: no cover
        x = y

    assert f1._repr_html_() == (
        "<div><b>ScopedFunction</b><br>\n"
        '<tt>- func</tt><div style="padding-left:10px;"><table style="max-width:100%; border:1px solid #AAAAAA; margin-top:0px; margin-bottom:8px;"><tr><td><tt>innerscope.tests.test_repr.f1()</tt></td></tr></table></div>\n'
        '<tt>- inner_names</tt><div style="padding-left:10px;"><table style="max-width:100%; border:1px solid #AAAAAA; margin-top:0px; margin-bottom:8px;"><tr><td><tt>x</tt></td></tr></table></div>\n'
        '<tt>- missing</tt><div style="padding-left:10px;"><table style="max-width:100%; border:1px solid #AAAAAA; margin-top:0px; margin-bottom:8px;"><tr><td><tt>y</tt></td></tr></table></div>\n'
        "<tt>- outer_scope: {}</tt>\n"
        "</div>"
    )
