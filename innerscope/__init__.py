from .core import bindwith, call, callwith, scoped_function  # noqa

from ._version import get_versions

__version__ = get_versions()["version"]
del get_versions
