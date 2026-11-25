"""Fail the run when a test is skipped because a module could not be imported.

``importorskip`` and ``skipif(not HAVE_X)`` turn a broken install into a green run.
With ``--fail-on-import-skips`` every skip whose reason says a module is missing or
could not be imported fails the session, unless its reason contains a module named by
``--allow-import-skip``. Platform and fixture skips never match and stay allowed.

The allow-list is per invocation, so each CI job lists the optional packages it does not
install. The block below is self-contained and can be copied to another repo's conftest.
"""

from __future__ import annotations

import re

import pytest

_IMPORT_SKIP = re.compile(
    r"could not import|No module named|ModuleNotFoundError|ImportError|not installed",
    re.IGNORECASE,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("import-skips")
    group.addoption(
        "--fail-on-import-skips",
        action="store_true",
        help="fail when a test is skipped because a module could not be imported",
    )
    group.addoption(
        "--allow-import-skip",
        action="append",
        default=[],
        metavar="MODULE",
        help="module whose import skip is expected in this run (repeatable)",
    )


class _ImportSkipGuard:
    def __init__(self, allowed: list[str]) -> None:
        self.allowed = allowed
        self.unexpected: list[tuple[str, str]] = []

    def _record(self, report: pytest.TestReport | pytest.CollectReport) -> None:
        if not report.skipped:
            return
        longrepr = report.longrepr
        reason = str(longrepr[2]) if isinstance(longrepr, tuple) else str(longrepr)
        if _IMPORT_SKIP.search(reason) and not any(m in reason for m in self.allowed):
            self.unexpected.append((report.nodeid, reason))

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self._record(report)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        self._record(report)

    def pytest_terminal_summary(self, terminalreporter) -> None:
        if not self.unexpected:
            return
        terminalreporter.section("unexpected import skips", red=True)
        for nodeid, reason in self.unexpected:
            terminalreporter.line(f"{nodeid}: {reason}")
        terminalreporter.line(
            "Install the module or pass --allow-import-skip=<module>."
        )

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        if self.unexpected and session.exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--fail-on-import-skips"):
        config.pluginmanager.register(
            _ImportSkipGuard(config.getoption("--allow-import-skip")),
            "import-skip-guard",
        )
