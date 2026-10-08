import sys

from ._bytecode import STRATEGY, TESTED_THROUGH

# "bytecode" is faster and doesn't interfere with debuggers or coverage tools that use
# `sys.settrace`.  "trace" is the fallback where "bytecode" is unsupported or untested.
if STRATEGY is not None and sys.version_info[:2] <= TESTED_THROUGH:
    default_method = "bytecode"
else:  # pragma: no cover
    default_method = "trace"
del sys, STRATEGY, TESTED_THROUGH
