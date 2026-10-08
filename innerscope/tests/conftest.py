import pytest


def pytest_configure(config):
    from innerscope import _bytecode, cfg

    method = config.getoption("--method", None)
    if method == "bytecode" and _bytecode.STRATEGY is None:  # pragma: no cover
        raise pytest.UsageError('method="bytecode" is not supported by this Python interpreter')
    if method is not None:
        cfg.default_method = method
    print(f'Running tests with "{cfg.default_method}" default method')


@pytest.fixture(scope="session", autouse=True)
def ic():  # pragma: no cover (debug)
    """Make `ic` available everywhere during testing for easier debugging."""
    try:
        import icecream
    except ImportError:
        return
    icecream.install()
    # icecream.ic.disable()  # This disables icecream; do ic.enable() to re-enable
    return icecream.ic
