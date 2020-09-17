def pytest_addoption(parser):
    parser.addoption(
        "--method",
        action="store",
        default="bytecode",
        help="Select the default method for obtaining the inner scope: bytecode or trace",
    )
