"""Select exactly one scheduler implementation for this pytest process."""

from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--backend",
        choices=("python", "python-batch", "rust", "rust-opt", "rust-fast"),
        default="python",
        help="Trio scheduler implementation; use a fresh process for each backend",
    )


def pytest_sessionstart(session):
    from trio_rust_poc import activate

    activate(session.config.getoption("--backend"))


def pytest_report_header(config):
    return f"Trio scheduler compatibility backend: {config.getoption('--backend')}"
