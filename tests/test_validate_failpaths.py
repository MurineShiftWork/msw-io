"""readers.validate fail paths + summary printing (complement to fixture tests)."""

from __future__ import annotations

from murineshiftwork.io import save_trial_data
from murineshiftwork.readers.validate import validate_session


def test_unreadable_dir_fails(tmp_path):
    # no recognised MSW files -> read_session_data raises -> validation fails
    result = validate_session(tmp_path, verbose=False)
    assert result.passed is False
    assert result.issues  # at least one failure recorded


def test_incomplete_session_fails_with_missing_list(tmp_path):
    # a bare df.jsonl with no settings is an incomplete session
    save_trial_data([{"trial": 1}], tmp_path / "s.msw.df.jsonl")
    result = validate_session(tmp_path, verbose=False)
    assert result.passed is False
    assert any("Incomplete" in i or "missing" in i for i in result.issues)


def test_print_summary_runs(tmp_path, capsys):
    # verbose=True path must render without error and mark FAIL
    validate_session(tmp_path, verbose=True)
    out = capsys.readouterr().out
    assert "Session validation: FAIL" in out
