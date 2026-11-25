"""Tests for readers.validate.validate_session using checked-in fixture sessions.

MSW validate_session() checks only MSW file completeness. Camera/RCE file
validation belongs in rpi_camera_ensemble.validate.
"""

from pathlib import Path

import pytest

from murineshiftwork.readers.validate import ValidationResult, validate_session

try:
    import pyarrow  # noqa: F401

    _PYARROW = True
except ImportError:
    _PYARROW = False

_skip_no_pyarrow = pytest.mark.skipif(not _PYARROW, reason="pyarrow not installed")

FIXTURES_DIR = Path(__file__).parent / "data"


def _session_dir(variant="jsonl"):
    d = FIXTURES_DIR / f"fixture_{variant}"
    if not d.exists():
        pytest.skip(f"Fixture dir absent: {d}")
    return d


# ---------------------------------------------------------------------------
# Return type and structure


def test_validate_returns_validation_result_jsonl():
    result = validate_session(_session_dir("jsonl"), verbose=False)
    assert isinstance(result, ValidationResult)


@_skip_no_pyarrow
def test_validate_returns_validation_result_pkl():
    result = validate_session(_session_dir("pkl"), verbose=False)
    assert isinstance(result, ValidationResult)


# ---------------------------------------------------------------------------
# MSW completeness


def test_validate_jsonl_msw_complete():
    result = validate_session(_session_dir("jsonl"), verbose=False)
    msw_issues = [i for i in result.issues if "MSW" in i or "read_session" in i]
    assert not msw_issues, f"MSW completeness issues: {msw_issues}"


@_skip_no_pyarrow
def test_validate_pkl_msw_complete():
    result = validate_session(_session_dir("pkl"), verbose=False)
    msw_issues = [i for i in result.issues if "MSW" in i or "read_session" in i]
    assert not msw_issues, f"MSW completeness issues: {msw_issues}"


def test_validate_jsonl_passes():
    result = validate_session(_session_dir("jsonl"), verbose=False)
    assert result.passed, f"Validation failed: {result.issues}"


@_skip_no_pyarrow
def test_validate_pkl_passes():
    result = validate_session(_session_dir("pkl"), verbose=False)
    assert result.passed, f"Validation failed: {result.issues}"


# ---------------------------------------------------------------------------
# Version and metadata


def test_validate_jsonl_version_known():
    result = validate_session(_session_dir("jsonl"), verbose=False)
    assert result.msw_version != "unknown"


def _write_cameras(acq_dir, statuses):
    import yaml

    path = acq_dir / "acquisition_manifest.yaml"
    data = (yaml.safe_load(path.read_text()) if path.exists() else None) or {}
    data["cameras"] = {
        "policy": "continue",
        "groups": [{"name": f"g{i}", "status": s} for i, s in enumerate(statuses)],
    }
    path.write_text(yaml.safe_dump(data))


def _fixture_acq(tmp_path):
    import shutil

    container = "_test_subject__20260619_120000_000000"
    acq_name = f"{container}__sequence__v1"
    fixture = Path(__file__).parent / "data" / "fixture_v42"

    dst = tmp_path / acq_name
    shutil.copytree(fixture / container / acq_name, dst)
    return dst


def test_all_cameras_failed_is_a_failure(tmp_path):
    from murineshiftwork.readers.validate import validate_session

    acq = _fixture_acq(tmp_path)
    _write_cameras(acq, ["failed", "failed"])
    r = validate_session(acq, verbose=False)
    assert not r.passed
    assert any("All cameras failed" in m for m in r.issues)


def test_some_cameras_failed_is_a_warning(tmp_path):
    from murineshiftwork.readers.validate import validate_session

    acq = _fixture_acq(tmp_path)
    _write_cameras(acq, ["complete", "failed"])
    r = validate_session(acq, verbose=False)
    assert r.passed
    assert any("g1" in m for m in r.warnings)


def test_cameras_ok_has_no_camera_finding(tmp_path):
    from murineshiftwork.readers.validate import validate_session

    acq = _fixture_acq(tmp_path)
    _write_cameras(acq, ["complete", "partial"])
    r = validate_session(acq, verbose=False)
    assert r.passed
    assert not r.warnings
