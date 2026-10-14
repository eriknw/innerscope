def pytest_addoption(parser):
    parser.addoption(
        "--method",
        action="store",
        default=None,
        choices=["bytecode", "trace"],
        help=(
            "Select the default method for obtaining the inner scope: bytecode or trace "
            "(default: innerscope's default for this Python)"
        ),
    )
