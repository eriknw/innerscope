# Innerscope

[![Version](https://img.shields.io/pypi/v/innerscope.svg)](https://pypi.org/project/innerscope/)
[![License](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://github.com/eriknw/innerscope/blob/master/LICENSE)
[![Build Status](https://travis-ci.org/eriknw/innerscope.svg?branch=master)](https://travis-ci.org/eriknw/innerscope)
[![Coverage Status](https://coveralls.io/repos/eriknw/innerscope/badge.svg?branch=master)](https://coveralls.io/r/eriknw/innerscope)
[![Code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

`innerscope` exposes the inner scope of functions and offers primitives suitable for creating pipelines.  It explores a design space around functions, dictionaries, and classes.

A function can be made to act like a dictionary:
```python
@innerscope.call
def info():
    first_name = 'Erik'
    last_name = 'Welch'
    full_name = f'{first_name} {last_name}'

>>> info['first_name']
'Erik'
>>> info['full_name']
'Erik Welch'
```
Sometimes we want functions to be more *functional* and accept arguments:
```python
if is_a_good_idea:
    suffix = 'the amazing'
else:
    suffix = 'the bewildering'

@innerscope.callwith(suffix)
def info_with_suffix(suffix=None):
    first_name = 'Erik'
    last_name = 'Welch'
    full_name = f'{first_name} {last_name}'
    if suffix:
        full_name = f'{full_name} {suffix}'

>>> info_with_suffix['full_name']
'Erik Welch the bewildering'
```
Cool!

But, what if we want to reuse the data computed in `info`?  We can control *exactly* what values are within scope inside of a function (including from closures and globals; more on these later).  Let's bind the variables in `info` to a new function:
```python
@info.bindto
def add_suffix(suffix):
    full_name = f'{first_name} {last_name} {suffix}'

>>> scope = add_suffix('the astonishing')
>>> scope['full_name']
'Erik Welch the astonishing'
```
`add_suffix` here is a `ScopedFunction`.  It returns a `Scope`, which is the dict-like object we've already seen.

## `scoped_function` ftw!

Except for the simplest tasks (as with `call` and `callwith` above), using `scoped_function` should usually be preferred.

```python
# step1 becomes a ScopedFunction that we can call
@scoped_function
def step1(a):
    b = a + 1

>>> scope1 = step1(1)
>>> scope1 == {'a': 1, 'b': 2}
True

# Bind any number of mappings to variables (later mappings have precedence)
@scoped_function(scope1, {'c': 3})
def step2(d):
    e = max(a + d, b + c)

>>> step2.outer_scope == {'a': 1, 'b': 2, 'c': 3, '__builtins__': __builtins__}
True
>>> scope2 = step2(4)
>>> scope2 == {'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5}
True
>>> scope2.inner_scope == {'d': 4, 'e': 5}
True
```
Suppose you're paranoid (like me!) and want to control whether a function uses values from closures or globals.  You're in luck!
```python
global_x = 1

def f():
    closure_y = 2
    def g():
        local_z = global_x + closure_y
    return g

# If you're the trusting type...
>>> g = f()
>>> innerscope.call(g) == {'global_x': 1, 'closure_y': 2, 'local_z': 3}
True

# And for the intelligent...
>>> paranoid_g = scoped_function(g, use_closures=False, use_globals=False)
>>> paranoid_g.missing
{'closure_y', 'global_x'}
>>> paranoid_g()
```
```diff
- NameError: Undefined variables: 'global_x', 'closure_y'.
- Use `bind` method to assign values for these names before calling.
```
```python
>>> new_g = paranoid_g.bind({'global_x': 100, 'closure_y': 200})
>>> new_g.missing
set()
>>> new_g() == {'global_x': 100, 'closure_y': 200, 'local_z': 300}
True
```
## How?
This library requires surprisingly little magic.  Perhaps I'll explain it some day.  Here's a hint: the wrapped function shouldn't have any return statements.

## Why?
It's all [@mrocklin's](https://github.com/mrocklin) fault for [asking a question.](https://github.com/dask/distributed/issues/4003)
`innerscope` is exploring a data model that could be convenient for running code remotely with [dask.](https://dask.org)
I bet it would even be useful for building pipelines with dask.

#### *This library is totally awesome and you should use it and tell all your friends* 😉 *!*

