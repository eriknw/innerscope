import sys

if sys.version_info < (3, 12):
    default_method = "bytecode"
else:
    default_method = "trace"
del sys
