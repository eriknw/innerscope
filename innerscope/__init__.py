import importlib.metadata

from .core import bindwith, call, callwith, scoped_function

try:
    __version__ = importlib.metadata.version("innerscope")
except Exception as exc:  # pragma: no cover (safety)
    raise AttributeError(
        "`innerscope.__version__` not available. This may mean "
        "innerscope was incorrectly installed or not installed at all. "
        "For local development, you may want to do an editable install via "
        "`python -m pip install -e path/to/innerscope`"
    ) from exc
del importlib
