"""Options for the parity harness."""


def pytest_addoption(parser):
    parser.addoption(
        "--regenerate-golden", action="store_true", default=False,
        help="rewrite packs/cars/tests/fixtures/parity_golden.jsonl from the "
             "current engine. Use only for an intended serving change, and read "
             "the diff before committing — this file is the only regression net "
             "the new engine keeps once backend/ is deleted.")
