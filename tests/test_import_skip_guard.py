"""The conftest guard fails runs on import skips and leaves other skips alone."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_CONFTEST = Path(__file__).with_name("conftest.py")

_TESTS = """
import pytest

def test_import():
    pytest.importorskip("module_that_is_not_installed_xyz")

@pytest.mark.skipif(True, reason="requires another platform")
def test_platform():
    pass
"""


@pytest.fixture
def project(pytester: pytest.Pytester) -> pytest.Pytester:
    shutil.copy(_CONFTEST, pytester.path / "conftest.py")
    pytester.makepyfile(test_sample=_TESTS)
    return pytester


def test_guard_off_by_default(project: pytest.Pytester) -> None:
    project.runpytest_subprocess("-p", "no:cacheprovider").assert_outcomes(
        skipped=2, passed=0
    )


def test_import_skip_fails_the_run(project: pytest.Pytester) -> None:
    result = project.runpytest_subprocess("--fail-on-import-skips")
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(
        ["*unexpected import skips*", "*module_that_is_not_installed_xyz*"]
    )


def test_allow_list_accepts_the_module(project: pytest.Pytester) -> None:
    result = project.runpytest_subprocess(
        "--fail-on-import-skips", "--allow-import-skip=module_that_is_not_installed_xyz"
    )
    assert result.ret == pytest.ExitCode.OK
