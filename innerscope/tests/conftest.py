import pytest


def pytest_configure(config):
    from innerscope import cfg

    cfg.default_method = config.getoption("--method", "bytecode")
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
