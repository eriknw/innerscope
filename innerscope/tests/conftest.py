import pytest


def pytest_configure(config):
    from innerscope import cfg

    cfg.default_method = config.getoption("--method", "bytecode")
    print(f'Running tests with "{cfg.default_method}" default method')
