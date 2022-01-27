from ._version import get_versions
from .core import bindwith, call, callwith, scoped_function  # noqa

__version__ = get_versions()["version"]
del get_versions
